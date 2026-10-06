from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from sigma.artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite
from sigma.economy import Economy
from sigma.economy.io_utils import read_vector
from sigma.execution import ExecutionPlanner
from sigma.places.frame_io import read_geoframe, write_geoframe
from sigma.sources import SourceRef
from sigma.stages import StageSpec
from sigma.transport._sparse_solver import SparseRoadSolver
from sigma.transport.network import RoadNetwork, SnappedPoints
from sigma.transport.roads import FileRoadSource, GeofabrikRoadSource, RoadSource, validate_road_frame
from sigma.workspace import SigmaWorkspace

from .center import cluster_centers
from .clustering import (
    ClusteringConfig,
    cluster_by_type,
    prepare_sparse_context,
    retained_points,
)
from .point_input import Classification, PointInputInfo, prepare_point_input
from .voronoi import all_surface_partitions
from .snap_context import load_sparse_context, save_sparse_context, validate_point_alignment


@dataclass(frozen=True, slots=True)
class SpatialRunConfig:
    """C9 spatial-input and clustering policy, preserving Engine defaults."""

    economy_column: str = "economy_code"
    classification: Classification | None = None
    classification_column: str | None = None
    io80_column: str | None = None
    io16_column: str | None = None
    vertex_digits: int = 11
    max_snap_distance: float | None = None

    min_cluster_size: int = 5
    min_samples: int | None = None
    cluster_selection_method: Literal["eom", "leaf"] = "eom"
    allow_single_cluster: bool = False
    hdbscan_max_distance: float = 5_000.0
    hdbscan_distance_mode: Literal["adaptive", "fixed"] = "adaptive"
    hdbscan_min_distance: float | None = None
    hdbscan_distance_growth: float = 1.5
    hdbscan_distance_steps: int = 4
    hdbscan_core_truncation_tolerance: float = 0.01
    hdbscan_stability_tolerance: float = 1e-12
    hdbscan_max_neighbor_pairs: int = 20_000_000

    # Preserve Engine fallback policy: network Voronoi is primary, coarse network
    # partitions are refined, and planar Euclidean Voronoi is the default recovery path.
    # If both methods fail for one independent type, that type is skipped and recorded.
    voronoi_resolution: float = 500.0
    voronoi_max_cells: int = 1_000_000
    voronoi_refine_factor: float = 0.5
    voronoi_max_refinements: int = 5

    def clustering_config(self) -> ClusteringConfig:
        return ClusteringConfig(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            cluster_selection_method=self.cluster_selection_method,
            allow_single_cluster=self.allow_single_cluster,
            max_distance=self.hdbscan_max_distance,
            distance_mode=self.hdbscan_distance_mode,
            min_distance=self.hdbscan_min_distance,
            distance_growth=self.hdbscan_distance_growth,
            distance_steps=self.hdbscan_distance_steps,
            core_truncation_tolerance=self.hdbscan_core_truncation_tolerance,
            stability_tolerance=self.hdbscan_stability_tolerance,
            max_neighbor_pairs=self.hdbscan_max_neighbor_pairs,
        )


class SpatialPipeline:
    """Managed spatial stages through C11 network-Voronoi partitions."""

    def __init__(
        self,
        workspace: SigmaWorkspace,
        *,
        roads: RoadSource,
        economy: Economy | None = None,
        config: SpatialRunConfig | None = None,
        place_pipeline=None,
        points_path: Path | str | None = None,
        points_layer: str | None = None,
        boundary_path: Path | str | None = None,
        boundary_layer: str | None = None,
        progress=None,
    ):
        if place_pipeline is None and points_path is None:
            raise ValueError("provide place_pipeline and/or points_path")
        if place_pipeline is not None and place_pipeline.workspace.root != workspace.root:
            raise ValueError("place_pipeline and SpatialPipeline must use the same workspace")
        self.workspace = workspace
        self.roads = roads
        place_economy = getattr(place_pipeline, "economy", None) if place_pipeline is not None else None
        self.economy = economy or place_economy
        if economy is not None and place_economy is not None:
            if economy.sector_fingerprint != place_economy.sector_fingerprint:
                raise ValueError(
                    "SpatialPipeline Economy sector identity must match the place-tagging Economy"
                )
        self.config = config or SpatialRunConfig()
        self.place_pipeline = place_pipeline
        self.points_path = Path(points_path).expanduser().resolve() if points_path is not None else None
        self.points_layer = points_layer
        self.boundary_path = (
            Path(boundary_path).expanduser().resolve() if boundary_path is not None else None
        )
        self.boundary_layer = boundary_layer
        self.progress = progress
        self._road_source: SourceRef | None = None
        if isinstance(self.roads, FileRoadSource):
            self._road_source = self.roads.register(workspace.sources)
        elif isinstance(self.roads, GeofabrikRoadSource):
            if place_pipeline is None:
                raise ValueError(
                    "GeofabrikRoadSource requires an area-mode PlacePipeline so it can share "
                    "source.geofabrik_pbf and area.boundary artifacts"
                )
        else:
            raise TypeError(f"unsupported road source: {type(self.roads).__name__}")
        self._point_source: SourceRef | None = None
        if self.points_path is not None:
            self._point_source = workspace.sources.register_user_file(
                self.points_path, name="classified-points", layer=points_layer
            )
        self._boundary_source: SourceRef | None = None
        if self.boundary_path is not None:
            if place_pipeline is not None:
                raise ValueError("boundary_path is only for custom-input spatial workspaces")
            self._boundary_source = workspace.sources.register_user_file(
                self.boundary_path, name="boundary", layer=boundary_layer
            )
        stages = {}
        if place_pipeline is not None:
            stages.update(place_pipeline.planner.stages)
        stages.update(self._build_stages())
        self.planner = ExecutionPlanner(workspace, stages, progress=progress)

    def _build_stages(self) -> dict[str, StageSpec]:
        point_deps = (
            ("transport.roads",)
            if self.points_path is not None
            else ("transport.roads", "places.classified")
        )
        road_deps = (
            ("source.geofabrik_pbf", "area.boundary")
            if isinstance(self.roads, GeofabrikRoadSource)
            else ()
        )
        stages: dict[str, StageSpec] = {
            "transport.roads": StageSpec(
                "transport.roads", road_deps, self._recipe_roads, self._exec_roads
            ),
            "spatial.points": StageSpec(
                "spatial.points", point_deps, self._recipe_points, self._exec_points
            ),
            "spatial.clusters": StageSpec(
                "spatial.clusters",
                ("spatial.points", "transport.roads"),
                self._recipe_clusters,
                self._exec_clusters,
            ),
            "spatial.centers": StageSpec(
                "spatial.centers", ("spatial.clusters",), self._recipe_centers, self._exec_centers
            ),
            "spatial.point_distances": StageSpec(
                "spatial.point_distances",
                ("spatial.clusters", "spatial.centers"),
                self._recipe_point_distances,
                self._exec_point_distances,
            ),
        }
        if self._boundary_source is not None:
            stages["area.boundary"] = StageSpec(
                "area.boundary", (), self._recipe_custom_boundary, self._exec_custom_boundary
            )
        if self.place_pipeline is not None or self._boundary_source is not None:
            stages["spatial.partitions"] = StageSpec(
                "spatial.partitions",
                ("spatial.clusters", "spatial.centers", "area.boundary"),
                self._recipe_partitions,
                self._exec_partitions,
            )
        return stages

    @staticmethod
    def _source_ref_from_artifact(planner: ExecutionPlanner, ref: ArtifactRef) -> SourceRef:
        payload = json.loads((ref.path / "source.json").read_text(encoding="utf-8"))
        return planner.workspace.sources.get(str(payload["source_id"]))

    @staticmethod
    def _boundary_from_artifact(ref: ArtifactRef):
        payload = json.loads((ref.path / "boundary.json").read_text(encoding="utf-8"))
        return shapely.from_wkb(bytes.fromhex(str(payload["geometry_wkb_hex"])))

    def _recipe_roads(self, planner, deps) -> ArtifactRecipe:
        if isinstance(self.roads, FileRoadSource):
            assert self._road_source is not None
            # Preserve the exact C9 recipe for compatibility and explicit file-road overrides.
            return ArtifactRecipe.build(
                "transport.roads",
                implementation_version="file-road-source-v1",
                sources={"roads": self._road_source},
                parameters={"layer": self.roads.layer},
            )

        assert isinstance(self.roads, GeofabrikRoadSource)
        assert self.place_pipeline is not None
        geofabrik = self._source_ref_from_artifact(planner, deps["source.geofabrik_pbf"])
        boundary = self._boundary_from_artifact(deps["area.boundary"])
        return ArtifactRecipe.build(
            "transport.roads",
            implementation_version="geofabrik-road-source-v1",
            dependencies=deps,
            sources={"geofabrik": geofabrik},
            parameters=self.roads.recipe_parameters(self.place_pipeline.area, boundary),
            identities={"area": self.workspace.area_identity or self.place_pipeline.area.slug},
        )

    def _recipe_points(self, planner, deps) -> ArtifactRecipe:
        sources = {"points": self._point_source} if self._point_source is not None else None
        identities = {}
        if self.economy is not None:
            identities["economy_sector_fingerprint"] = self.economy.sector_fingerprint
        return ArtifactRecipe.build(
            "spatial.points",
            implementation_version="point-input-v2-economy-code",
            dependencies=deps,
            sources=sources,
            parameters={
                "economy_column": self.config.economy_column,
                "classification": self.config.classification,
                "classification_column": self.config.classification_column,
                "io80_column": self.config.io80_column,
                "io16_column": self.config.io16_column,
            },
            identities=identities,
        )

    def _recipe_clusters(self, planner, deps) -> ArtifactRecipe:
        cfg = self.config
        return ArtifactRecipe.build(
            "spatial.clusters",
            implementation_version="network-hdbscan-step1-v2-default-euclidean-fallback",
            dependencies=deps,
            parameters={
                "vertex_digits": cfg.vertex_digits,
                "max_snap_distance": cfg.max_snap_distance,
                "min_cluster_size": cfg.min_cluster_size,
                "min_samples": cfg.min_samples,
                "cluster_selection_method": cfg.cluster_selection_method,
                "allow_single_cluster": cfg.allow_single_cluster,
                "hdbscan_max_distance": cfg.hdbscan_max_distance,
                "hdbscan_distance_mode": cfg.hdbscan_distance_mode,
                "hdbscan_min_distance": cfg.hdbscan_min_distance,
                "hdbscan_distance_growth": cfg.hdbscan_distance_growth,
                "hdbscan_distance_steps": cfg.hdbscan_distance_steps,
                "hdbscan_core_truncation_tolerance": cfg.hdbscan_core_truncation_tolerance,
                "hdbscan_stability_tolerance": cfg.hdbscan_stability_tolerance,
                "hdbscan_max_neighbor_pairs": cfg.hdbscan_max_neighbor_pairs,
                "euclidean_fallback": True,
                "continue_on_error": True,
            },
        )


    def _recipe_centers(self, planner, deps) -> ArtifactRecipe:
        return ArtifactRecipe.build(
            "spatial.centers",
            implementation_version="network-1-median-v3-default-euclidean-fallback",
            dependencies=deps,
            parameters={"euclidean_fallback": True, "continue_on_error": True},
        )

    def _recipe_point_distances(self, planner, deps) -> ArtifactRecipe:
        return ArtifactRecipe.build(
            "spatial.point_distances",
            implementation_version="own-center-network-shortest-path-v2-skip-unrecoverable-centers",
            dependencies=deps,
        )

    def _recipe_custom_boundary(self, planner, deps) -> ArtifactRecipe:
        assert self._boundary_source is not None
        return ArtifactRecipe.build(
            "area.boundary",
            implementation_version="file-boundary-source-v1",
            sources={"boundary": self._boundary_source},
            parameters={"layer": self.boundary_layer},
            identities={"workspace_area": self.workspace.area_identity or "custom"},
        )

    def _recipe_partitions(self, planner, deps) -> ArtifactRecipe:
        cfg = self.config
        return ArtifactRecipe.build(
            "spatial.partitions",
            implementation_version="network-voronoi-step4-v3-default-euclidean-fallback",
            dependencies=deps,
            parameters={
                "resolution": cfg.voronoi_resolution,
                "max_cells": cfg.voronoi_max_cells,
                "auto_refine": True,
                "refine_factor": cfg.voronoi_refine_factor,
                "max_refinements": cfg.voronoi_max_refinements,
                "euclidean_fallback": True,
                "continue_on_error": True,
            },
        )

    def _exec_custom_boundary(self, planner, recipe, deps, write: ArtifactWrite):
        assert self._boundary_source is not None
        validation = self.workspace.sources.validate(self._boundary_source)
        if not validation.valid:
            raise RuntimeError(f"boundary source changed after registration: {validation.reason}")
        boundary = read_vector(self._boundary_source.path, self.boundary_layer)
        if boundary.crs is None:
            raise ValueError("study boundary CRS is missing")
        if boundary.empty:
            raise ValueError("study boundary is empty")
        if boundary.geometry.isna().any() or boundary.geometry.is_empty.any():
            raise ValueError("study boundary contains missing or empty geometry")
        invalid = sorted(set(boundary.geometry.geom_type.astype(str)) - {"Polygon", "MultiPolygon"})
        if invalid:
            raise ValueError(f"study boundary must contain only polygon geometry; found {invalid}")
        write_geoframe(boundary, write.output("boundary_frame.json"))
        return {
            "rows": len(boundary),
            "crs": str(boundary.crs),
            "geometry_types": sorted(set(boundary.geometry.geom_type.astype(str))),
            "source_id": self._boundary_source.source_id,
        }, {}

    def _exec_roads(self, planner, recipe, deps, write: ArtifactWrite):
        if isinstance(self.roads, FileRoadSource):
            assert self._road_source is not None
            validation = self.workspace.sources.validate(self._road_source)
            if not validation.valid:
                raise RuntimeError(f"road source changed after registration: {validation.reason}")
            roads = validate_road_frame(read_vector(self._road_source.path, self.roads.layer))
            source_id = self._road_source.source_id
            metadata = {"road_source_mode": "file"}
        else:
            assert isinstance(self.roads, GeofabrikRoadSource)
            assert self.place_pipeline is not None
            geofabrik = self._source_ref_from_artifact(planner, deps["source.geofabrik_pbf"])
            validation = self.workspace.sources.validate(geofabrik)
            if not validation.valid:
                raise RuntimeError(
                    f"shared Geofabrik source changed after registration: {validation.reason}"
                )
            boundary = self._boundary_from_artifact(deps["area.boundary"])
            node_cache = (
                self.workspace.sources.root
                / "geofabrik"
                / "road-node-index"
                / f"{geofabrik.sha256}.nodes.cache"
            )
            roads = self.roads.load(
                geofabrik.path,
                area=self.place_pipeline.area,
                boundary=boundary,
                node_cache=node_cache,
                progress=self.progress,
            )
            source_id = geofabrik.source_id
            metadata = {
                "road_source_mode": "geofabrik",
                **self.roads.recipe_parameters(self.place_pipeline.area, boundary),
            }
        write_geoframe(roads, write.output("roads.json"))
        return {
            "rows": len(roads),
            "crs": str(roads.crs),
            "geometry_types": sorted(set(roads.geometry.geom_type.astype(str))),
            "source_id": source_id,
            **metadata,
        }, {}

    def _load_raw_points(self, deps) -> gpd.GeoDataFrame:
        if self.points_path is not None:
            assert self._point_source is not None
            validation = self.workspace.sources.validate(self._point_source)
            if not validation.valid:
                raise RuntimeError(f"point source changed after registration: {validation.reason}")
            return read_vector(self._point_source.path, self.points_layer)
        if self.place_pipeline is not None:
            frame = read_geoframe(deps["places.classified"].path / "places.json")
            # Siphon's preserved canonical place identifier is ``poi_id`` while Engine's
            # spatial contract is ``canonical_id``.  Adapt only at this boundary so neither
            # proven upstream nor downstream schema has to be rewritten during migration.
            if "canonical_id" not in frame.columns and "poi_id" in frame.columns:
                frame = frame.copy()
                frame["canonical_id"] = frame["poi_id"]
            return frame
        raise AssertionError("SpatialPipeline has no point source")

    def _exec_points(self, planner, recipe, deps, write: ArtifactWrite):
        raw = self._load_raw_points(deps)
        points, info = prepare_point_input(
            raw,
            classification=self.config.classification,
            economy_column=self.config.economy_column,
            classification_column=self.config.classification_column,
            io80_column=self.config.io80_column,
            io16_column=self.config.io16_column,
        )
        if self.economy is not None:
            allowed = set(self.economy.sectors.codes)
            observed = set(points["type"].astype(str))
            unknown = sorted(observed - allowed)
            if unknown:
                raise ValueError(
                    "point economic classifications are outside the selected Economy sector catalog: "
                    f"{unknown[:10]}"
                )
        # New road artifacts record CRS in metadata. Older compatible artifacts may not,
        # so keep a one-time fallback to the managed road frame for backward compatibility.
        road_manifest = self.workspace.artifacts.manifest(deps["transport.roads"])
        road_crs = road_manifest.metadata.get("crs")
        if not road_crs:
            road_crs = read_geoframe(deps["transport.roads"].path / "roads.json").crs
        points = points.to_crs(road_crs)
        write_geoframe(points, write.output("points.json"))
        return {
            "rows": len(points),
            "crs": str(points.crs),
            "classification_column": info.classification_column,
            "canonical_name_source": info.canonical_name_source,
            "type_count": int(points["type"].nunique()),
        }, {}

    def _exec_clusters(self, planner, recipe, deps, write: ArtifactWrite):
        roads = read_geoframe(deps["transport.roads"].path / "roads.json")
        points = read_geoframe(deps["spatial.points"].path / "points.json")
        context = prepare_sparse_context(
            roads,
            points,
            vertex_digits=self.config.vertex_digits,
            progress=self.progress,
        )
        if self.config.max_snap_distance is not None:
            too_far = context.snaps.snap_distance > float(self.config.max_snap_distance)
            if bool(too_far.any()):
                raise ValueError(
                    f"{int(too_far.sum())} classified points exceed max_snap_distance="
                    f"{self.config.max_snap_distance:g}"
                )
        events: list[dict[str, object]] = []
        clustered = cluster_by_type(
            points,
            context,
            self.config.clustering_config(),
            progress=self.progress,
            continue_on_error=True,
            events=events,
        )
        write_geoframe(clustered, write.output("clustered.json"))
        save_sparse_context(
            context,
            write.output("snap_context"),
            crs=roads.crs,
            vertex_digits=self.config.vertex_digits,
            point_ids=points["canonical_id"].astype(str).tolist(),
        )
        def stable_audit(rows):
            return [
                {str(key): value for key, value in dict(row).items() if str(key) != "seconds"}
                for row in rows
            ]

        # Wall-clock timings are useful console diagnostics but are intentionally not part
        # of an immutable artifact: otherwise forcing the same recipe could create different
        # bytes solely because the machine ran faster or slower.
        audit = {
            "clustering_summary": stable_audit(clustered.attrs.get("clustering_summary", [])),
            "clustering_trace": stable_audit(clustered.attrs.get("clustering_trace", [])),
            "events": stable_audit(events),
        }
        write.output("clustering_audit.json").write_text(
            json.dumps(audit, sort_keys=True, separators=(",", ":"), default=str) + "\n",
            encoding="utf-8",
        )
        retained = int((clustered["cluster"] >= 0).sum())
        cluster_count = int(clustered.loc[clustered["cluster"] >= 0, ["type", "cluster"]].drop_duplicates().shape[0])
        summaries = clustered.attrs.get("clustering_summary", [])
        methods = sorted({str(row.get("clustering_method", "unknown")) for row in summaries})
        return {
            "rows": len(clustered),
            "retained_rows": retained,
            "cluster_count": cluster_count,
            "crs": str(clustered.crs),
            "clustering_methods": methods,
            "fallback_type_count": sum(
                str(row.get("clustering_method")) == "euclidean_hdbscan_fallback"
                for row in summaries
            ),
            "skipped_type_count": sum(
                str(row.get("distance_status")) == "failed_skipped" for row in summaries
            ),
            "max_snap_distance_observed": float(context.snaps.snap_distance.max(initial=0.0)),
        }, {"events": stable_audit(events)}

    @staticmethod
    def _normalize_type_value(value: object) -> str:
        """Preserve the canonical economy code established by the point-input stage."""
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            raise ValueError("economic type identifiers must be non-blank")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("economic type identifiers must be non-blank")
        return normalized

    @classmethod
    def _clean_center_output(cls, centers: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        required = ["type", "cluster", "center_network_node", "geometry"]
        missing = set(required) - set(centers.columns)
        if missing:
            raise RuntimeError(f"center output is missing columns: {sorted(missing)}")
        if centers.crs is None:
            raise RuntimeError("center output is missing its CRS")
        out = centers[required].copy()
        out["type"] = [cls._normalize_type_value(value) for value in out["type"]]
        out["cluster"] = pd.to_numeric(out["cluster"], errors="raise").astype(np.int64)
        if (out["cluster"] < 0).any():
            raise RuntimeError("center output contains a negative/noise cluster identifier")
        for position, geometry in enumerate(out.geometry):
            if geometry is None or geometry.is_empty or geometry.geom_type != "Point":
                raise RuntimeError(f"center row {position} must contain one non-empty Point")
            coordinates = np.asarray(geometry.coords, dtype=float)
            if not np.isfinite(coordinates[:, :2]).all():
                raise RuntimeError(f"center row {position} contains non-finite coordinates")
        keys = set(zip(out["type"], out["cluster"].astype(int), strict=True))
        if len(keys) != len(out):
            raise RuntimeError("network centers must have exactly one row per [type, cluster]")
        return out.sort_values(["type", "cluster"], kind="stable").reset_index(drop=True)

    @staticmethod
    def _clean_distance_output(points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        out = points.copy()
        if "point_id" not in out.columns:
            out["point_id"] = (
                out["canonical_id"] if "canonical_id" in out.columns else out.index.astype(str)
            )
        columns = ["point_id", "type", "cluster", "distance_to_cluster_median"]
        columns += [c for c in ["point_center_distance_method"] if c in out.columns]
        columns += [c for c in ["canonical_id", "canonical_name"] if c in out.columns]
        columns += ["geometry"]
        return out[columns].copy()

    def _retained_with_augmented(self, cluster_ref: ArtifactRef):
        clustered = self.read_clusters(cluster_ref, public=False)
        retained = retained_points(clustered)
        if retained.empty:
            raise RuntimeError("network HDBSCAN retained no clusters")
        context, metadata = load_sparse_context(cluster_ref.path / "snap_context")
        point_ref = self._dependency_ref(cluster_ref, "spatial.points")
        all_points = read_geoframe(point_ref.path / "points.json")
        validate_point_alignment(metadata, all_points["canonical_id"].astype(str).tolist())
        source_pos = retained["_sparse_source_pos"].to_numpy(np.int64, copy=False)
        road = RoadNetwork.from_sparse_graph(
            context.graph,
            clustered.crs,
            vertex_digits=self.config.vertex_digits,
        )
        sparse_snaps = context.snaps.subset(source_pos)
        snapped = SnappedPoints(
            pd.DataFrame(
                {
                    "source_pos": np.arange(len(retained), dtype=np.int64),
                    "edge_pos": context.edge_id[source_pos],
                    "edge_id": context.edge_id[source_pos],
                    "offset": sparse_snaps.offset,
                    "snap_distance": sparse_snaps.snap_distance,
                    "snapped_geometry": list(shapely.points(sparse_snaps.snapped_xy)),
                }
            ),
            road.crs,
        )
        augmented = road.augment(snapped, progress=self.progress)
        out = retained.copy().reset_index(drop=True)
        out["network_node"] = augmented.point_node
        out["snap_distance"] = snapped.frame["snap_distance"].to_numpy(float)
        out["network_position"] = snapped.frame["snapped_geometry"].to_numpy()
        out = out.drop(columns="_sparse_source_pos")
        return out, augmented

    def _exec_centers(self, planner, recipe, deps, write: ArtifactWrite):
        retained, augmented = self._retained_with_augmented(deps["spatial.clusters"])
        events: list[dict[str, object]] = []
        detailed = cluster_centers(
            retained,
            augmented,
            progress=self.progress,
            continue_on_error=True,
            events=events,
        )
        methods = sorted(set(detailed["center_method"].astype(str))) if len(detailed) else []
        diagnostics = {
            "centers": [
                {
                    "type": self._normalize_type_value(row.type),
                    "cluster": int(row.cluster),
                    "center_method": str(row.center_method),
                }
                for row in detailed.itertuples(index=False)
            ],
            "events": events,
        }
        write.output("center_diagnostics.json").write_text(
            json.dumps(diagnostics, sort_keys=True, separators=(",", ":"), default=str) + "\n",
            encoding="utf-8",
        )
        centers = self._clean_center_output(detailed)
        write_geoframe(centers, write.output("centers.json"))
        requested = int(retained[["type", "cluster"]].drop_duplicates().shape[0])
        return {
            "rows": len(centers),
            "cluster_count": len(centers),
            "requested_cluster_count": requested,
            "skipped_cluster_count": requested - len(centers),
            "crs": str(centers.crs),
            "center_methods": methods,
        }, {"events": events}

    def _exec_point_distances(self, planner, recipe, deps, write: ArtifactWrite):
        retained, augmented = self._retained_with_augmented(deps["spatial.clusters"])
        centers = read_geoframe(deps["spatial.centers"].path / "centers.json")
        center_node = {
            (str(row["type"]), int(row["cluster"])): int(row["center_network_node"])
            for _, row in centers.iterrows()
        }
        keys = [
            (str(type_value), int(cluster))
            for type_value, cluster in zip(retained["type"], retained["cluster"], strict=True)
        ]
        missing = sorted(set(keys) - set(center_node))
        if missing:
            keep = np.asarray([key in center_node for key in keys], dtype=bool)
            skipped_points = int((~keep).sum())
            if self.progress is not None:
                self.progress(
                    f"point distances: WARNING skipping {skipped_points:,} point(s) in "
                    f"{len(missing):,} cluster(s) whose network and Euclidean center methods both failed"
                )
            retained = retained.loc[keep].reset_index(drop=True)
            keys = [key for key, include in zip(keys, keep, strict=True) if include]
            if retained.empty:
                raise RuntimeError(
                    "no retained cluster has a usable center after network and Euclidean fallbacks"
                )
        else:
            skipped_points = 0
        targets = np.asarray([center_node[key] for key in keys], dtype=np.int64)
        solver = SparseRoadSolver.from_augmented(augmented)
        distance = solver.point_distances_from_centers(
            retained["network_node"].to_numpy(np.int64, copy=False),
            targets,
        )
        if not np.isfinite(distance).all() or np.any(distance < 0):
            raise RuntimeError("one or more retained points cannot reach their own cluster median")
        retained = retained.copy()
        retained["distance_to_cluster_median"] = distance.astype(float)
        retained["point_center_distance_method"] = "network_shortest_path"
        public = self._clean_distance_output(retained)
        write_geoframe(public, write.output("point_distances.json"))
        return {
            "rows": len(public),
            "cluster_count": int(public[["type", "cluster"]].drop_duplicates().shape[0]),
            "crs": str(public.crs),
            "point_center_distance_method": "network_shortest_path",
            "skipped_cluster_count": len(missing),
            "skipped_point_count": skipped_points,
        }, {}

    @classmethod
    def _clean_partition_output(
        cls, partitions: gpd.GeoDataFrame, expected_keys: set[tuple[str, int]]
    ) -> gpd.GeoDataFrame:
        required = ["type", "cluster", "geometry"]
        missing = set(required) - set(partitions.columns)
        if missing:
            raise RuntimeError(f"partition output is missing columns: {sorted(missing)}")
        if partitions.crs is None:
            raise RuntimeError("partition output is missing its CRS")
        out = partitions[required].copy()
        out["type"] = [cls._normalize_type_value(value) for value in out["type"]]
        out["cluster"] = pd.to_numeric(out["cluster"], errors="raise").astype(np.int64)
        if (out["cluster"] < 0).any():
            raise RuntimeError("partition output contains a negative/noise cluster identifier")
        for position, geometry in enumerate(out.geometry):
            if geometry is None or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                raise RuntimeError(f"partition row {position} is not one non-empty polygonal geometry")
            area = float(geometry.area)
            if not geometry.is_valid or not np.isfinite(area) or area <= 0:
                raise RuntimeError(f"partition row {position} is invalid or has non-positive area")
        actual_keys = set(zip(out["type"], out["cluster"].astype(int), strict=True))
        if len(actual_keys) != len(out):
            raise RuntimeError("partitions must have exactly one row per [type, cluster]")
        extra = actual_keys - expected_keys
        if extra:
            raise RuntimeError(
                "partition cluster-key invariant failed: partitions contain clusters that are "
                f"not present in retained points; extra={sorted(extra)[:10]}"
            )
        return out.sort_values(["type", "cluster"], kind="stable").reset_index(drop=True)

    def _load_boundary_frame(self, ref: ArtifactRef) -> gpd.GeoDataFrame:
        managed = ref.path / "boundary_frame.json"
        if managed.exists():
            return read_geoframe(managed)
        payload_path = ref.path / "boundary.json"
        if not payload_path.exists():
            raise RuntimeError("area.boundary artifact contains no readable boundary representation")
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        raw = payload.get("geometry_wkb_hex")
        if not raw:
            raise RuntimeError("area.boundary artifact is missing geometry_wkb_hex")
        geometry = shapely.from_wkb(bytes.fromhex(str(raw)))
        return gpd.GeoDataFrame(geometry=[geometry], crs=payload.get("crs") or "EPSG:4326")

    def _exec_partitions(self, planner, recipe, deps, write: ArtifactWrite):
        retained, augmented = self._retained_with_augmented(deps["spatial.clusters"])
        boundary = self._load_boundary_frame(deps["area.boundary"])
        centers = read_geoframe(deps["spatial.centers"].path / "centers.json")
        events: list[dict[str, object]] = []
        detailed = all_surface_partitions(
            augmented,
            retained,
            boundary,
            self.config.voronoi_resolution,
            self.config.voronoi_max_cells,
            progress=self.progress,
            centers=centers,
            auto_refine=True,
            refine_factor=self.config.voronoi_refine_factor,
            max_refinements=self.config.voronoi_max_refinements,
            euclidean_fallback=True,
            continue_on_error=True,
            events=events,
        )
        expected_keys = set(
            zip(
                (self._normalize_type_value(value) for value in retained["type"]),
                retained["cluster"].astype(int),
                strict=True,
            )
        )
        public = self._clean_partition_output(detailed, expected_keys)
        write_geoframe(public, write.output("partitions.json"))

        detail_rows = []
        for row in detailed.itertuples(index=False):
            detail_rows.append({
                "type": self._normalize_type_value(row.type),
                "cluster": int(row.cluster),
                "surface_area": float(row.surface_area),
                "surface_resolution": (
                    None if not np.isfinite(float(row.surface_resolution))
                    else float(row.surface_resolution)
                ),
                "surface_method": str(row.surface_method),
                "surface_seed_method": str(row.surface_seed_method),
            })
        write.output("partition_diagnostics.json").write_text(
            json.dumps(
                {"partitions": detail_rows, "events": events},
                sort_keys=True, separators=(",", ":"), default=str,
            ) + "\n",
            encoding="utf-8",
        )
        actual_keys = set(zip(public["type"], public["cluster"].astype(int), strict=True))
        return {
            "rows": len(public),
            "cluster_count": len(actual_keys),
            "requested_cluster_count": len(expected_keys),
            "skipped_cluster_count": len(expected_keys - actual_keys),
            "crs": str(public.crs),
            "surface_methods": sorted(set(detailed["surface_method"].astype(str))),
            "surface_resolutions": sorted(
                {float(value) for value in detailed["surface_resolution"] if np.isfinite(float(value))}
            ),
            "boundary_artifact_id": deps["area.boundary"].artifact_id,
        }, {"events": events}

    def analysis_x_dependencies(self) -> tuple[str, ...]:
        return ("spatial.clusters", "spatial.centers", "spatial.partitions")

    def analysis_road(self, deps):
        _, road = self._retained_with_augmented(deps["spatial.clusters"])
        return road

    def prepare_clusters(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("spatial.clusters", force=force)

    def prepare_centers(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("spatial.centers", force=force)

    def prepare_point_distances(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("spatial.point_distances", force=force)

    def prepare_partitions(self, *, force: bool = False) -> ArtifactRef:
        if "spatial.partitions" not in self.planner.stages:
            raise RuntimeError(
                "spatial.partitions requires a boundary; provide boundary_path for custom "
                "inputs or use a managed PlacePipeline with area.boundary"
            )
        return self.planner.ensure("spatial.partitions", force=force)

    def read_centers(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.centers")
        if ref is None:
            raise RuntimeError("spatial.centers has not been prepared")
        return read_geoframe(ref.path / "centers.json")

    def read_point_distances(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.point_distances")
        if ref is None:
            raise RuntimeError("spatial.point_distances has not been prepared")
        return read_geoframe(ref.path / "point_distances.json")

    def read_partitions(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.partitions")
        if ref is None:
            raise RuntimeError("spatial.partitions has not been prepared")
        return read_geoframe(ref.path / "partitions.json")

    def read_partition_diagnostics(self, ref: ArtifactRef | None = None) -> dict[str, object]:
        ref = ref or self.workspace.artifact("spatial.partitions")
        if ref is None:
            raise RuntimeError("spatial.partitions has not been prepared")
        return json.loads((ref.path / "partition_diagnostics.json").read_text(encoding="utf-8"))

    def read_points(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.points")
        if ref is None:
            raise RuntimeError("spatial.points has not been prepared")
        return read_geoframe(ref.path / "points.json")

    def _dependency_ref(self, ref: ArtifactRef, name: str) -> ArtifactRef:
        manifest = self.workspace.artifacts.manifest(ref)
        payload = manifest.recipe.dependencies.get(name)
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"artifact {ref.artifact_id} has no {name!r} dependency")
        stage = str(payload.get("stage") or name)
        recipe_fingerprint = str(payload.get("recipe_fingerprint") or "")
        dependency = self.workspace.artifacts.lookup(stage, recipe_fingerprint)
        if dependency is None or dependency.artifact_id != payload.get("artifact_id"):
            raise RuntimeError(f"artifact dependency {name!r} is unavailable or inconsistent")
        return dependency

    def read_snap_context(self, ref: ArtifactRef | None = None):
        ref = ref or self.workspace.artifact("spatial.clusters")
        if ref is None:
            raise RuntimeError("spatial.clusters has not been prepared")
        context, metadata = load_sparse_context(ref.path / "snap_context")
        point_ref = self._dependency_ref(ref, "spatial.points")
        points = read_geoframe(point_ref.path / "points.json")
        validate_point_alignment(metadata, points["canonical_id"].astype(str).tolist())
        return context, metadata

    def read_clusters(self, ref: ArtifactRef | None = None, *, public: bool = True) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.clusters")
        if ref is None:
            raise RuntimeError("spatial.clusters has not been prepared")
        clustered = read_geoframe(ref.path / "clustered.json")
        audit = json.loads((ref.path / "clustering_audit.json").read_text(encoding="utf-8"))
        clustered.attrs["clustering_summary"] = audit.get("clustering_summary", [])
        clustered.attrs["clustering_trace"] = audit.get("clustering_trace", [])
        if not public:
            return clustered
        context, metadata = load_sparse_context(ref.path / "snap_context")
        validate_point_alignment(metadata, clustered["canonical_id"].astype(str).tolist())
        out = clustered.copy()
        if "point_id" not in out.columns:
            out["point_id"] = out["canonical_id"]
        out["network_position"] = gpd.GeoSeries(
            shapely.points(context.snaps.snapped_xy), index=out.index, crs=out.crs
        )
        if "snap_distance" not in out.columns:
            out["snap_distance"] = context.snaps.snap_distance.astype(float)
        return out

"""Explicit compatibility import of public sigma-engine restart artifacts.

This module deliberately treats restart files as external sources with structural
validation, not as provenance-complete managed artifacts.  It preserves the
legacy ``from-partitions`` boundary while feeding the normal C14/C15 analysis
stages.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from sigma.artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite
from sigma.execution import ExecutionPlanner
from sigma.economy.io_utils import normalize_sector_id
from sigma.places.frame_io import read_geoframe, write_geoframe
from sigma.sources import SourceRef
from sigma.stages import StageSpec
from sigma.transport import FileRoadSource
from sigma.transport.network import AugmentedNetwork, RoadNetwork
from sigma.transport.roads import read_vector, validate_road_frame
from sigma.workspace import SigmaWorkspace


def _normalize_type_value(value: object, sector_codes: Collection[str] | None = None) -> str:
    """Return the sector code of one restart row.

    A value that already is a sector code of the selected Economy is kept unchanged.  Any
    other value receives the PSA-style normalization that the restart files of the
    built-in economies rely on (``1`` and ``"1.0"`` become ``"01"``).  Without this order,
    the code ``"1"`` of a custom Economy would be rewritten to ``"01"``.
    """
    if sector_codes is not None:
        text = "" if value is None else str(value).strip()
        if text in sector_codes:
            return text
        # External tabular formats often coerce integer-looking identifiers to
        # floating-point values (for example ``1`` -> ``1.0``).  Recover the selected
        # custom code before falling back to PSA-style zero padding.  A literal code
        # such as ``"1.0"`` still wins above when it exists in the selected Economy.
        if any(marker in text.casefold() for marker in (".", "e")):
            try:
                number = Decimal(text)
            except (InvalidOperation, ValueError):
                pass
            else:
                if number.is_finite() and number == number.to_integral_value():
                    candidate = str(int(number))
                    if candidate in sector_codes:
                        return candidate
    normalized = normalize_sector_id(value)
    if normalized is None:
        raise ValueError("economic type identifiers must be non-blank")
    return normalized


def _normalize_type_column(
    frame: pd.DataFrame, sector_codes: Collection[str] | None = None
) -> pd.DataFrame:
    out = frame.copy()
    if "type" not in out.columns:
        raise ValueError("artifact is missing required type column")
    out["type"] = [_normalize_type_value(value, sector_codes) for value in out["type"]]
    return out


def _node_keys(
    frame: pd.DataFrame, sector_codes: Collection[str] | None = None
) -> set[tuple[str, int]]:
    types = (_normalize_type_value(value, sector_codes) for value in frame["type"])
    return set(zip(types, frame["cluster"].astype(int), strict=True))


def assert_cluster_invariant(
    points: gpd.GeoDataFrame,
    centers: gpd.GeoDataFrame,
    partitions: gpd.GeoDataFrame,
    sector_codes: Collection[str] | None = None,
) -> int:
    point_keys = _node_keys(points, sector_codes)
    center_keys = _node_keys(centers, sector_codes)
    partition_keys = _node_keys(partitions, sector_codes)
    if point_keys != center_keys or center_keys != partition_keys:
        raise RuntimeError(
            "cluster-count/key invariant failed: retained point clusters, network centers, "
            "and partitions must match exactly; "
            f"points-only={sorted(point_keys-center_keys)[:10]}, "
            f"centers-only={sorted(center_keys-point_keys)[:10]}, "
            f"missing-partitions={sorted(center_keys-partition_keys)[:10]}, "
            f"extra-partitions={sorted(partition_keys-center_keys)[:10]}"
        )
    if len(centers) != len(center_keys):
        raise RuntimeError("network centers must have exactly one row per [type, cluster]")
    if len(partitions) != len(partition_keys):
        raise RuntimeError("partitions must have exactly one row per [type, cluster]")
    return len(center_keys)


def normalize_restart_points(
    points: gpd.GeoDataFrame, sector_codes: Collection[str] | None = None
) -> gpd.GeoDataFrame:
    if points.crs is None:
        raise ValueError("point-center-distance artifact is missing its CRS")
    out = _normalize_type_column(points, sector_codes)
    used_legacy_distance_alias = False
    if "distance_to_cluster_median" not in out.columns:
        if "network_distance_to_center" in out.columns:
            used_legacy_distance_alias = True
            out["distance_to_cluster_median"] = pd.to_numeric(
                out["network_distance_to_center"], errors="coerce"
            )
        else:
            raise ValueError(
                "point-center-distance artifact needs distance_to_cluster_median "
                "(or legacy network_distance_to_center)"
            )
    required = {"type", "cluster", "distance_to_cluster_median", "geometry"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"point-center-distance artifact is missing: {sorted(missing)}")
    out["cluster"] = pd.to_numeric(out["cluster"], errors="raise").astype(np.int64)
    if (out["cluster"] < 0).any():
        raise ValueError("point-center-distance artifact contains HDBSCAN noise rows")
    distance = pd.to_numeric(out["distance_to_cluster_median"], errors="coerce").to_numpy(float)
    if not np.isfinite(distance).all() or np.any(distance < 0):
        raise ValueError("saved point-to-median distances must be finite and non-negative")
    out["distance_to_cluster_median"] = distance
    for position, geometry in enumerate(out.geometry):
        if geometry is None or geometry.is_empty or geometry.geom_type != "Point":
            raise ValueError(f"point-center-distance row {position} must contain one non-empty Point")
    id_column = "point_id" if "point_id" in out.columns else "canonical_id"
    if id_column not in out.columns:
        raise ValueError("point-center-distance artifact needs point_id or canonical_id")
    ids = out[id_column].astype(str)
    if ids.str.strip().eq("").any() or ids.duplicated().any():
        raise ValueError(f"{id_column} must be non-blank and unique")
    if used_legacy_distance_alias:
        if "point_center_distance_method" not in out.columns:
            raise ValueError(
                "legacy point-distance input does not identify the distance method; "
                "cannot verify that Step 7 is using road-network distance"
            )
        methods = set(out["point_center_distance_method"].dropna().astype(str))
        if methods != {"network_shortest_path"}:
            raise ValueError(
                "legacy point-distance input contains a non-network distance method: "
                f"{sorted(methods)}"
            )
    return out.reset_index(drop=True)


def align_legacy_restart_points(
    points: gpd.GeoDataFrame,
    centers: gpd.GeoDataFrame,
    partitions: gpd.GeoDataFrame,
    sector_codes: Collection[str] | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    center_keys = _node_keys(centers, sector_codes)
    partition_keys = _node_keys(partitions, sector_codes)
    if center_keys != partition_keys:
        raise RuntimeError(
            "restart requires exact center/partition cluster agreement; "
            f"missing partitions={sorted(center_keys-partition_keys)[:10]}, "
            f"extra partitions={sorted(partition_keys-center_keys)[:10]}"
        )
    point_keys = _node_keys(points, sector_codes)
    missing = sorted(center_keys - point_keys)
    if missing:
        raise RuntimeError(f"restart point-distance artifact is missing required clusters: {missing[:10]}")
    extra = point_keys - center_keys
    if not extra:
        return points.reset_index(drop=True), 0
    keep = np.asarray(
        [(str(t), int(c)) in center_keys for t, c in zip(points["type"], points["cluster"], strict=True)],
        dtype=bool,
    )
    return points.loc[keep].reset_index(drop=True), int((~keep).sum())


def _clean_centers(
    frame: gpd.GeoDataFrame, sector_codes: Collection[str] | None = None
) -> gpd.GeoDataFrame:
    if frame.crs is None:
        raise ValueError("network-center artifact is missing its CRS")
    out = _normalize_type_column(frame, sector_codes)
    required = {"type", "cluster", "geometry"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"network-center artifact is missing: {sorted(missing)}")
    out["cluster"] = pd.to_numeric(out["cluster"], errors="raise").astype(np.int64)
    if (out["cluster"] < 0).any():
        raise ValueError("network-center artifact contains negative cluster IDs")
    for i, geom in enumerate(out.geometry):
        if geom is None or geom.is_empty or geom.geom_type != "Point":
            raise ValueError(f"network-center row {i} must contain one non-empty Point")
    if len(out) != len(_node_keys(out, sector_codes)):
        raise ValueError("network centers must have exactly one row per [type, cluster]")
    return out.reset_index(drop=True)


def _clean_partitions(
    frame: gpd.GeoDataFrame, sector_codes: Collection[str] | None = None
) -> gpd.GeoDataFrame:
    if frame.crs is None:
        raise ValueError("partition artifact is missing its CRS")
    out = _normalize_type_column(frame, sector_codes)
    required = {"type", "cluster", "geometry"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"partition artifact is missing: {sorted(missing)}")
    out["cluster"] = pd.to_numeric(out["cluster"], errors="raise").astype(np.int64)
    if (out["cluster"] < 0).any():
        raise ValueError("partition artifact contains negative cluster IDs")
    bad = sorted(set(out.geometry.geom_type.astype(str)) - {"Polygon", "MultiPolygon"})
    if bad or out.geometry.isna().any() or out.geometry.is_empty.any():
        raise ValueError(f"partition artifact requires non-empty polygon geometry; found {bad}")
    if len(out) != len(_node_keys(out, sector_codes)):
        raise ValueError("partitions must have exactly one row per [type, cluster]")
    return out.reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class RestartRunConfig:
    vertex_digits: int = 11


class RestartSpatialPipeline:
    """Spatial boundary for explicit legacy ``from-partitions`` imports."""

    def __init__(
        self,
        workspace: SigmaWorkspace,
        *,
        roads: FileRoadSource,
        partitions: Path | str,
        centers: Path | str,
        points_with_center_distance: Path | str,
        config: RestartRunConfig | None = None,
        economy=None,
        progress=None,
    ):
        self.workspace = workspace
        self.roads = roads
        self.config = config or RestartRunConfig()
        self.economy = economy
        self.progress = progress
        self._road_source = workspace.sources.register_user_file(roads.path, layer=roads.layer)
        self._partition_source = workspace.sources.register_user_file(partitions)
        self._center_source = workspace.sources.register_user_file(centers)
        self._point_source = workspace.sources.register_user_file(points_with_center_distance)
        self.planner = ExecutionPlanner(workspace, self._build_stages(), progress=progress)

    def _build_stages(self) -> dict[str, StageSpec]:
        return {
            "transport.roads": StageSpec("transport.roads", (), self._recipe_roads, self._exec_roads),
            "spatial.centers": StageSpec(
                "spatial.centers", ("transport.roads",), self._recipe_centers, self._exec_centers
            ),
            "spatial.partitions": StageSpec(
                "spatial.partitions", ("transport.roads",), self._recipe_partitions, self._exec_partitions
            ),
            "spatial.point_distances": StageSpec(
                "spatial.point_distances",
                ("spatial.centers", "spatial.partitions"),
                self._recipe_points,
                self._exec_points,
            ),
        }

    @property
    def _sector_codes(self) -> frozenset[str] | None:
        """Sector codes of the selected Economy; a restart row that carries one keeps it."""
        return frozenset(self.economy.sectors.codes) if self.economy is not None else None

    def _economy_identity(self) -> dict[str, str]:
        """Recipe identity of the sector catalog that type normalization depends on."""
        if self.economy is None:
            return {}
        return {"economy_sector_fingerprint": self.economy.sector_fingerprint}

    def _recipe_roads(self, planner, deps):
        return ArtifactRecipe.build(
            "transport.roads", implementation_version="restart-file-road-source-v1",
            sources={"roads": self._road_source}, parameters={"layer": self.roads.layer},
        )

    def _recipe_centers(self, planner, deps):
        return ArtifactRecipe.build(
            "spatial.centers", implementation_version="legacy-restart-centers-v3-selected-code-coercion",
            dependencies={"transport.roads": deps["transport.roads"]},
            sources={"centers": self._center_source},
            parameters={"vertex_digits": self.config.vertex_digits, "saved_network_node_ids": "ignored"},
            identities=self._economy_identity(),
        )

    def _recipe_partitions(self, planner, deps):
        return ArtifactRecipe.build(
            "spatial.partitions",
            implementation_version="legacy-restart-partitions-v3-road-crs-normalization",
            dependencies={"transport.roads": deps["transport.roads"]},
            sources={"partitions": self._partition_source},
            identities=self._economy_identity(),
        )

    def _recipe_points(self, planner, deps):
        return ArtifactRecipe.build(
            "spatial.point_distances", implementation_version="legacy-restart-point-distances-v2-selected-code-coercion",
            dependencies={"spatial.centers": deps["spatial.centers"], "spatial.partitions": deps["spatial.partitions"]},
            sources={"points": self._point_source},
            identities=self._economy_identity(),
        )

    def _exec_roads(self, planner, recipe, deps, write: ArtifactWrite):
        validation = self.workspace.sources.validate(self._road_source)
        if not validation.valid:
            raise RuntimeError(f"road source changed after registration: {validation.reason}")
        roads = validate_road_frame(read_vector(self._road_source.path, self.roads.layer))
        write_geoframe(roads, write.output("roads.json"))
        return {"rows": len(roads), "crs": str(roads.crs)}, {"legacy_restart": True}

    def _road_network(self, road_ref: ArtifactRef) -> RoadNetwork:
        roads = read_geoframe(road_ref.path / "roads.json")
        return RoadNetwork.from_geodataframe(roads, vertex_digits=self.config.vertex_digits)

    def _resnap_centers(self, frame: gpd.GeoDataFrame, road_ref: ArtifactRef) -> tuple[gpd.GeoDataFrame, AugmentedNetwork, float]:
        base = self._road_network(road_ref)
        projected = frame.to_crs(base.crs) if frame.crs != base.crs else frame.copy()
        snaps = base.snap(projected)
        augmented = base.augment(snaps)
        projected = projected.reset_index(drop=True)
        projected["center_network_node"] = augmented.point_node
        max_resnap = float(snaps.frame["snap_distance"].max()) if len(snaps.frame) else 0.0
        return projected, augmented, max_resnap

    def _exec_centers(self, planner, recipe, deps, write: ArtifactWrite):
        frame = _clean_centers(gpd.read_parquet(self._center_source.path), self._sector_codes)
        projected, _, max_resnap = self._resnap_centers(frame, deps["transport.roads"])
        write_geoframe(projected, write.output("centers.json"))
        return {"rows": len(projected), "crs": str(projected.crs), "max_center_resnap_distance": max_resnap}, {"legacy_restart": True}

    def _exec_partitions(self, planner, recipe, deps, write: ArtifactWrite):
        frame = _clean_partitions(
            gpd.read_parquet(self._partition_source.path), self._sector_codes
        )
        source_crs = str(frame.crs)
        roads = read_geoframe(deps["transport.roads"].path / "roads.json")
        if frame.crs != roads.crs:
            frame = frame.to_crs(roads.crs)
        write_geoframe(frame, write.output("partitions.json"))
        return {
            "rows": len(frame),
            "crs": str(frame.crs),
            "source_crs": source_crs,
        }, {"legacy_restart": True}

    def _exec_points(self, planner, recipe, deps, write: ArtifactWrite):
        codes = self._sector_codes
        points = normalize_restart_points(gpd.read_parquet(self._point_source.path), codes)
        centers = self.read_centers(deps["spatial.centers"])
        partitions = self.read_partitions(deps["spatial.partitions"])
        points, dropped = align_legacy_restart_points(points, centers, partitions, codes)
        assert_cluster_invariant(points, centers, partitions, codes)
        if self.economy is not None:
            allowed = set(self.economy.sectors.codes)
            missing_types = sorted(set(points["type"].astype(str)) - allowed)
            if missing_types:
                raise ValueError(
                    "classified point sectors are absent from the selected Economy: "
                    f"{missing_types[:20]}"
                )
        if points.crs != centers.crs:
            points = points.to_crs(centers.crs)
        write_geoframe(points, write.output("point_distances.json"))
        return {"rows": len(points), "crs": str(points.crs), "legacy_extra_point_rows_dropped": dropped}, {"legacy_restart": True}

    def prepare_imports(self, *, force: bool = False) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef]:
        centers = self.planner.ensure("spatial.centers", force=force)
        partitions = self.planner.ensure("spatial.partitions", force=force)
        points = self.planner.ensure("spatial.point_distances", force=force)
        return centers, partitions, points

    def analysis_x_dependencies(self) -> tuple[str, ...]:
        return ("transport.roads", "spatial.centers", "spatial.partitions")

    def analysis_road(self, deps) -> AugmentedNetwork:
        centers = self.read_centers(deps["spatial.centers"])
        _, road, _ = self._resnap_centers(centers, deps["transport.roads"])
        return road

    def read_centers(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.centers")
        if ref is None:
            raise RuntimeError("spatial.centers has not been imported")
        return read_geoframe(ref.path / "centers.json")

    def read_partitions(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.partitions")
        if ref is None:
            raise RuntimeError("spatial.partitions has not been imported")
        return read_geoframe(ref.path / "partitions.json")

    def read_point_distances(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("spatial.point_distances")
        if ref is None:
            raise RuntimeError("spatial.point_distances has not been imported")
        return read_geoframe(ref.path / "point_distances.json")

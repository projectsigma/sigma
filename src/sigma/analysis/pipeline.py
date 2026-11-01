"""Managed C14-C15 analysis stages joining X, centrality, and point scoring."""
from __future__ import annotations

import json
from dataclasses import dataclass
import math
import shutil
from typing import Mapping

import geopandas as gpd
import networkx as nx
import pandas as pd

from sigma.artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite
from sigma.execution import ExecutionPlanner
from sigma.places.frame_io import read_geoframe, write_geoframe
from sigma.progress_detail import detail_phase  # SIGMA_DETAILED_PROGRESS_V1
from sigma.stages import StageSpec
from sigma.savepoints import StageSavepoints, CheckpointedRoad  # SIGMA_RESUMABLE_SAVEPOINTS_V2
from sigma.workspace import SigmaWorkspace

from .centrality import CentralityResult, compute_centrality
from .graph import make_node_id
from .scoring import tempered_point_scores
from .x_graph import instantiate_network, mean_hub_effective_distance, inverse_mean_hub_x_weight


_X_EDGE_COLUMNS = [
    "source_type",
    "source_cluster",
    "target_type",
    "target_cluster",
    "technical_coefficient",
    "road_distance",
    "effective_road_distance",
    "edge_weight",
]
_DISCONNECTED_COLUMNS = [
    "source_type",
    "source_cluster",
    "target_type",
    "target_cluster",
    "reason",
]


def _clustered_sector_shares(points: pd.DataFrame) -> dict[tuple[str, int], float]:
    """Allocate each exact economic sector's clustered members among its X nodes."""
    required = {"type", "cluster"}
    if not required <= set(points.columns):
        raise ValueError("sector-share X requires type and cluster columns")
    counts = points.groupby(["type", "cluster"], sort=False).size()
    sector_totals = points.groupby("type", sort=False).size()
    result = {
        (str(t), int(c)): float(count) / float(sector_totals.loc[t])
        for (t, c), count in counts.items()
    }
    if any(not math.isfinite(v) or not 0.0 < v <= 1.0 for v in result.values()):
        raise ValueError("sector-share X requires positive finite cluster proportions")
    return result


@dataclass(frozen=True, slots=True)
class XResult:
    graph: nx.DiGraph
    nodes: pd.DataFrame
    edges: pd.DataFrame
    disconnected: pd.DataFrame
    paths: gpd.GeoDataFrame


@dataclass(frozen=True, slots=True)
class AnalysisRunConfig:
    """Analysis execution policy; balanced directed Katz is canonical by default."""

    centrality_method: str = "katz"
    centrality_direction: str = "incoming"
    katz_alpha_factor: float = 0.85
    katz_beta: float = 1.0
    x_distance_decay_lambda: float = 1.0
    distance_tempering: float = 0.15

    def __post_init__(self) -> None:
        method = str(self.centrality_method).strip().casefold()
        if method not in {"katz", "eigenvector"}:
            raise ValueError("centrality_method must be 'katz' or 'eigenvector'")
        direction = str(self.centrality_direction).strip().casefold()
        if direction not in {"incoming", "outgoing"}:
            raise ValueError("centrality_direction must be 'incoming' or 'outgoing'")
        alpha_factor = float(self.katz_alpha_factor)
        if not math.isfinite(alpha_factor) or not 0.0 < alpha_factor < 1.0:
            raise ValueError("katz_alpha_factor must be finite and strictly between 0 and 1")
        beta = float(self.katz_beta)
        if not math.isfinite(beta) or beta <= 0:
            raise ValueError("katz_beta must be finite and strictly positive")
        decay = float(self.x_distance_decay_lambda)
        if not math.isfinite(decay) or decay < 0.0:
            raise ValueError("x_distance_decay_lambda must be finite and non-negative")
        tempering = float(self.distance_tempering)
        if not math.isfinite(tempering) or not 0.0 <= tempering <= 1.0:
            raise ValueError("distance_tempering must be finite and between 0 and 1")
        object.__setattr__(self, "centrality_method", method)
        object.__setattr__(self, "centrality_direction", direction)
        object.__setattr__(self, "katz_alpha_factor", alpha_factor)
        object.__setattr__(self, "katz_beta", beta)
        object.__setattr__(self, "distance_tempering", tempering)
        object.__setattr__(self, "x_distance_decay_lambda", decay)


class AnalysisPipeline:
    """Managed analysis stages through C15 centrality and point scoring."""

    def __init__(
        self,
        workspace: SigmaWorkspace,
        *,
        spatial_pipeline,
        economy_pipeline,
        config: AnalysisRunConfig | None = None,
        progress=None,
    ):
        if spatial_pipeline.workspace.root != workspace.root:
            raise ValueError("spatial_pipeline and AnalysisPipeline must use the same workspace")
        if economy_pipeline.workspace.root != workspace.root:
            raise ValueError("economy_pipeline and AnalysisPipeline must use the same workspace")
        spatial_economy = getattr(spatial_pipeline, "economy", None)
        if spatial_economy is not None:
            if spatial_economy.sector_fingerprint != economy_pipeline.economy.sector_fingerprint:
                raise ValueError("spatial and economic pipelines must use the same sector identity")
        self.workspace = workspace
        self.spatial = spatial_pipeline
        self.economy = economy_pipeline
        self.config = config or AnalysisRunConfig()
        self.progress = progress
        self._economic_graph_stage = economy_pipeline.analysis_graph_stage
        self._spatial_x_dependencies = tuple(
            spatial_pipeline.analysis_x_dependencies()
            if hasattr(spatial_pipeline, "analysis_x_dependencies")
            else ("spatial.clusters", "spatial.centers", "spatial.partitions")
        )
        stages = dict(spatial_pipeline.planner.stages)
        stages.update(economy_pipeline.planner.stages)
        stages["analysis.x"] = StageSpec(
            "analysis.x",
            (*self._spatial_x_dependencies, "spatial.point_distances", self._economic_graph_stage),
            self._recipe_x,
            self._exec_x,
        )
        stages["analysis.centrality"] = StageSpec(
            "analysis.centrality",
            ("analysis.x",),
            self._recipe_centrality,
            self._exec_centrality,
        )
        stages["analysis.scores"] = StageSpec(
            "analysis.scores",
            ("spatial.point_distances", "analysis.centrality"),
            self._recipe_scores,
            self._exec_scores,
        )
        self.planner = ExecutionPlanner(workspace, stages, progress=progress)

    def _recipe_x(self, planner, deps) -> ArtifactRecipe:
        return ArtifactRecipe.build(
            "analysis.x",
            implementation_version="directed-spatial-economic-x-v6-inverse-mean-hub-sector-shares",
            dependencies={
                name: deps[name]
                for name in (*self._spatial_x_dependencies, "spatial.point_distances", self._economic_graph_stage)
            },
            parameters={
                "overlap_rule": "positive_area",
                "road_distance": "shortest_path",
                "edge_weight": "technical_coefficient_times_both_clustered_sector_shares_times_inverse_mean_hub_distance",
                "cluster_share_denominator": "clustered_establishments_per_exact_type",
                "effective_distance": "center_road_plus_both_mean_member_road_radii",
                "x_distance_decay_lambda": self.config.x_distance_decay_lambda,
                "distance_floor_metres": 1.0,
                "zero_distance_self_edges": "omit",
            },
        )

    def _exec_x(self, planner, recipe, deps, write: ArtifactWrite):
        centers = self.spatial.read_centers(deps["spatial.centers"])
        partitions = self.spatial.read_partitions(deps["spatial.partitions"])
        member_distances = self.spatial.read_point_distances(deps["spatial.point_distances"])
        required = {"type", "cluster", "distance_to_cluster_median"}
        if not required <= set(member_distances.columns):
            raise ValueError("mean-hub X requires scored member-to-1-median road distances")
        # Each retained establishment contributes once to its cluster mean.
        radii = member_distances.groupby(["type", "cluster"], sort=False)[
            "distance_to_cluster_median"
        ].mean()
        mean_radii = {(str(t), int(c)): float(value) for (t, c), value in radii.items()}
        center_keys = set(zip(centers["type"].astype(str), centers["cluster"].astype(int)))
        if missing := center_keys - set(mean_radii):
            raise ValueError(f"mean-hub X missing member radius for {len(missing)} centers")
        if any(not math.isfinite(value) or value < 0 for value in mean_radii.values()):
            raise ValueError("mean-hub X has nonfinite or negative member road radius")
        # Count each retained, clustered establishment once. Unclustered records
        # have no X node, so they are excluded from both the numerator and the
        # sector denominator. Hierarchical types are matched *exactly*.
        cluster_sector_shares = _clustered_sector_shares(member_distances)
        if set(cluster_sector_shares) != center_keys:
            raise ValueError("sector-share X cluster counts must match all X centers")
        reused = self._reuse_x_routes_for_weight_only_change(recipe, deps, write, mean_radii, cluster_sector_shares)
        if reused is not None:
            return reused
        if hasattr(self.spatial, "analysis_road"):
            road = self.spatial.analysis_road(deps)
        else:
            _, road = self.spatial._retained_with_augmented(deps["spatial.clusters"])
        economic = self.economy.load_graph(deps[self._economic_graph_stage]).graph
        savepoints = StageSavepoints(self.workspace.root, recipe.stage, recipe.fingerprint)
        graph, disconnected = instantiate_network(
            centers,
            partitions,
            economic,
            road,
            progress=self.progress,
            x_distance_decay_lambda=self.config.x_distance_decay_lambda,
            mean_road_radius_by_cluster=mean_radii,
            cluster_sector_shares=cluster_sector_shares,
            savepoints=savepoints,
        )

        nodes = self._node_table(graph)
        with detail_phase(
            self.progress,
            f"network X: constructing shortest-road-path geometries for {graph.number_of_edges():,} edges",
        ):
            edges, paths = self._edge_outputs(graph, CheckpointedRoad(road, graph, savepoints, progress=self.progress), progress=self.progress)
        disconnected_out = self._disconnected_output(disconnected)
        if self.progress is not None:
            self.progress(
                f"network X: prepared {len(nodes):,} nodes, {len(edges):,} edges, "
                f"{len(paths):,} paths, {len(disconnected_out):,} disconnected overlaps"
            )

        # Capture graph diagnostics before releasing the routing-heavy X graph.
        # `paths` is the independent WGS84 GeoDataFrame needed for publication.
        metadata = {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "disconnected_overlap_pairs": len(disconnected_out),
            "economic_graph_is_dag": nx.is_directed_acyclic_graph(economic),
            "x_is_dag": nx.is_directed_acyclic_graph(graph),
            "zero_distance_self_edges_omitted": int(
                graph.graph.get("zero_distance_self_edges_omitted", 0)
            ),
            "edge_weight": "technical_coefficient * source_cluster_sector_share * target_cluster_sector_share / max(effective_road_distance_metres, 1) ** x_distance_decay_lambda",
            "effective_distance": "center_road_plus_both_mean_member_road_radii",
            "cluster_share_denominator": "clustered_establishments_per_exact_type",
            "x_distance_decay_lambda": self.config.x_distance_decay_lambda,
            "distance_floor_metres": 1.0,
            "road_distance_crs": str(road.crs),
        }
        del graph  # release all embedded road_path arrays before path serialization
        nodes.to_csv(write.output("x_nodes.csv"), index=False, lineterminator="\n")
        edges.to_csv(
            write.output("x_edges.csv"), index=False, float_format="%.17g", lineterminator="\n"
        )
        disconnected_out.to_csv(
            write.output("disconnected_overlap_pairs.csv"), index=False, lineterminator="\n"
        )
        # GeoParquet stores binary geometry efficiently; JSON would materialize
        # ~255k hex-WKB strings plus one enormous in-memory JSON string.
        with detail_phase(self.progress, f"network X: writing {len(paths):,} paths as GeoParquet"):
            paths.to_parquet(write.output("x_paths.parquet"), index=False)
        write.output("x.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return metadata, {
            "economic_weight": "technical_coefficient_times_both_cluster_sector_shares",
            "spatial_weight": "technical_coefficient_times_capped_inverse_mean_hub_distance_power",
        }

    def _reuse_x_routes_for_weight_only_change(
        self,
        recipe: ArtifactRecipe,
        deps,
        write: ArtifactWrite,
        mean_radii: Mapping[tuple[str, int], float],
        cluster_sector_shares: Mapping[tuple[str, int], float],
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        """Reuse an older X artifact's *unchanged* center-to-center road routes.

        This is an incremental algorithm for X, not a sidecar output. An X recipe
        change caused solely by distance weighting / point radii must not cause
        400k path reconstructions. If ANY routing/topology input changed, decline
        reuse and let the established full-routing implementation execute.
        """
        previous = self.workspace.artifact("analysis.x")
        if previous is None:
            return None
        same_recipe_overlay = previous.recipe_fingerprint == recipe.fingerprint
        if same_recipe_overlay and not (previous.path / "x_paths_overlay.json").is_file():
            # A forced rerun of a full-routing artifact still takes the full
            # route-construction path, preserving the existing determinism test.
            return None
        try:
            store = self.workspace.artifacts
            previous_manifest = store.manifest(previous)
            if same_recipe_overlay:
                # Force=True re-executes the numeric kernel from the validated
                # overlay, not an alternative route/artifact representation.
                # Keep the ORIGINAL base-geometry provenance so files and
                # metadata reproduce the exact immutable artifact identity.
                prior_overlay = json.loads(
                    (previous.path / "x_paths_overlay.json").read_text(encoding="utf-8")
                )
                if (not isinstance(prior_overlay, dict) or prior_overlay.get("version") != 1
                        or prior_overlay.get("kind") !=
                        "immutable_parquet_hardlink_plus_current_edge_csv"):
                    raise ValueError("previous X overlay has an unsupported format")
                route_source_artifact_id = prior_overlay.get("source_x_artifact_id")
                if (not isinstance(route_source_artifact_id, str) or not route_source_artifact_id
                        or previous_manifest.metadata.get("x_route_geometry_reused_from") !=
                        route_source_artifact_id):
                    raise ValueError("previous X overlay has inconsistent base-geometry provenance")
            else:
                route_source_artifact_id = previous.artifact_id
            geom_deps = set(self._spatial_x_dependencies) | {self._economic_graph_stage}
            stored_deps = previous_manifest.recipe.dependencies
            # Exact match of every upstream routing/topology dependency,
            # including preserved road-network versions and economy identity.
            if set(stored_deps) - {"spatial.point_distances"} != geom_deps:
                return None
            for name in geom_deps:
                if stored_deps[name]["artifact_id"] != deps[name].artifact_id:
                    return None
            required = (
                "x_nodes.csv", "x_edges.csv", "x_paths.parquet",
                "disconnected_overlap_pairs.csv", "x.json",
            )
            if any(not (previous.path / name).is_file() for name in required):
                return None
            if not store.validate(previous).valid:
                # Do not use truncated/tampered geometry; let the full path run.
                return None

            # Centrality/weights depend only on the edge table, not the road
            # geometry. Recompute using SIGMA's *same* kernel as full routing.
            old_edges = pd.read_csv(
                previous.path / "x_edges.csv", dtype=str, keep_default_na=False,
            )
            required_edges = (
                "source_type", "source_cluster", "target_type", "target_cluster",
                "technical_coefficient", "road_distance",
            )
            if any(name not in old_edges for name in required_edges):
                return None
            edges = old_edges.copy()
            for col in ("source_cluster", "target_cluster"):
                edges[col] = edges[col].map(int)
            for col in ("technical_coefficient", "road_distance"):
                edges[col] = edges[col].map(float)
            source_radii = [mean_radii[(str(t), int(c))] for t, c in zip(
                edges["source_type"], edges["source_cluster"], strict=True,
            )]
            target_radii = [mean_radii[(str(t), int(c))] for t, c in zip(
                edges["target_type"], edges["target_cluster"], strict=True,
            )]
            effective = [
                mean_hub_effective_distance(center, ra, rb)
                for center, ra, rb in zip(
                    edges["road_distance"], source_radii, target_radii, strict=True,
                )
            ]
            edges["effective_road_distance"] = effective
            source_shares = [cluster_sector_shares[(str(t), int(c))]
                             for t, c in zip(edges["source_type"], edges["source_cluster"], strict=True)]
            target_shares = [cluster_sector_shares[(str(t), int(c))]
                             for t, c in zip(edges["target_type"], edges["target_cluster"], strict=True)]
            edges["edge_weight"] = [
                inverse_mean_hub_x_weight(coeff, distance, self.config.x_distance_decay_lambda)
                * float(source_share) * float(target_share)
                for coeff, distance, source_share, target_share in zip(
                    edges["technical_coefficient"], effective, source_shares, target_shares,
                    strict=True,
                )
            ]
            if any(not math.isfinite(value) or value <= 0.0
                   for value in edges["edge_weight"]):
                raise ValueError("sector-share X weight underflow or invalid value")
            # pyarrow updates numeric attributes of the SAME stored WKB rows.
            # It neither calls the shortest-path engine nor decodes geometry.
            import pyarrow as pa
            import pyarrow.parquet as pq

            parquet_source = pq.ParquetFile(previous.path / "x_paths.parquet")
            source_schema = parquet_source.schema_arrow
            if b"geo" not in (source_schema.metadata or {}):
                raise ValueError("saved X paths have no GeoParquet metadata")
            if parquet_source.metadata.num_rows != len(edges):
                raise ValueError("saved X route row count differs from edge table")
            keys = ("source_type", "source_cluster", "target_type", "target_cluster")
            for key in keys:
                if key not in source_schema.names:
                    raise ValueError(f"saved X routes are missing key {key}")

            # Geometry/route topology is immutable and was validated above.
            # Validate row order using ONLY key columns (not enormous WKB blobs).
            # A weight-only change must never allocate another GeoParquet copy.
            offset = 0
            for batch in parquet_source.iter_batches(batch_size=16384, columns=list(keys)):
                route_keys = pa.Table.from_batches([batch])
                end = offset + route_keys.num_rows
                segment = edges.iloc[offset:end]
                for key in keys:
                    if route_keys.column(key).to_pylist() != segment[key].tolist():
                        raise ValueError(f"saved X route row order differs at {key}, row {offset}")
                offset = end
            if offset != len(edges):
                raise ValueError("saved X path stream ended before all edges")
            # The temporary artifact is on the same filesystem as the saved X.
            # NTFS hard links use no additional route-data blocks. Never copy
            # the whole Parquet on hardlink failure: fail before any rerouting.
            import os
            source_parquet = previous.path / "x_paths.parquet"
            target_parquet = write.output("x_paths.parquet")
            try:
                os.link(source_parquet, target_parquet)
            except OSError as exc:
                raise OSError(
                    f"Cannot hardlink saved X route GeoParquet ({exc}). "
                    "Refusing to copy its geometry or reroute while disk is limited."
                ) from exc
            # A raw read of x_paths.parquet shows the BASE artifact's numeric
            # attributes; the current edge values live in x_edges.csv. All
            # supported readers must overlay current values after key checks.
            overlay = {
                "version": 1,
                "kind": "immutable_parquet_hardlink_plus_current_edge_csv",
                "source_x_artifact_id": route_source_artifact_id,
                "current_edge_table": "x_edges.csv",
                "base_geometry_table": "x_paths.parquet",
                "current_numeric_columns": [
                    "technical_coefficient", "road_distance",
                    "effective_road_distance", "edge_weight",
                ],
            }
            write.output("x_paths_overlay.json").write_text(
                json.dumps(overlay, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            )
            for name in ("x_nodes.csv", "disconnected_overlap_pairs.csv"):
                shutil.copyfile(previous.path / name, write.output(name))
            edges = edges.reindex(columns=_X_EDGE_COLUMNS)
            edges.to_csv(
                write.output("x_edges.csv"), index=False,
                float_format="%.17g", lineterminator="\n",
            )
            meta = dict(previous_manifest.metadata)
            meta.update({
                "node_count": int(meta.get("node_count") or
                                  len(pd.read_csv(previous.path / "x_nodes.csv"))),
                "edge_count": len(edges),
                "edge_weight": "technical_coefficient * source_cluster_sector_share * target_cluster_sector_share / max(effective_road_distance_metres, 1) ** x_distance_decay_lambda",
                "effective_distance": "center_road_plus_both_mean_member_road_radii",
                "cluster_share_denominator": "clustered_establishments_per_exact_type",
                "x_distance_decay_lambda": self.config.x_distance_decay_lambda,
                "distance_floor_metres": 1.0,
                "x_route_geometry_reused_from": route_source_artifact_id,
                "x_route_geometry_reuse": "validated-upstream-artifacts-and-parquet-row-keys",
                "x_route_geometry_storage": "ntfs-hardlink-with-current-edge-overlay",
            })
            meta.pop("log_reference_distance_metres", None)
            write.output("x.json").write_text(
                json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8",
            )
            if self.progress is not None:
                self.progress(
                    f"network X: hardlinked {len(edges):,} saved route geometries "
                    f"without rerouting or rewriting route WKB; recalculated edge weights"
                )
            return meta, {
                "economic_weight": "technical_coefficient_times_both_cluster_sector_shares",
                "spatial_weight": "technical_coefficient_times_capped_inverse_mean_hub_distance_power",
                "routing_reused": True,
                "routing_source_artifact": route_source_artifact_id,
            }
        except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
            # A potentially stale or malformed cached routing result must never
            # be published. Do NOT hide the reason or silently fall back after
            # partially writing a new artifact.
            raise RuntimeError(
                "A previous X artifact passed upstream dependency checks but "
                "cannot be reused safely. Refusing an implicit expensive reroute: "
                f"{exc}. Inspect the saved X artifact or run an explicit repair."
            ) from exc

    @staticmethod
    def _node_table(graph: nx.DiGraph) -> pd.DataFrame:
        rows = []
        for node, data in sorted(graph.nodes(data=True), key=lambda item: str(item[0])):
            rows.append(
                {
                    "node_id": str(node),
                    "type": str(data["type"]),
                    "cluster": int(data["cluster"]),
                    "center_network_node": int(data["center_network_node"]),
                    "center_x": float(data["center_x"]),
                    "center_y": float(data["center_y"]),
                    "in_degree": int(graph.in_degree(node)),
                    "out_degree": int(graph.out_degree(node)),
                }
            )
        return pd.DataFrame(
            rows,
            columns=[
                "node_id", "type", "cluster", "center_network_node",
                "center_x", "center_y", "in_degree", "out_degree",
            ],
        )

    @staticmethod
    def _edge_outputs(graph: nx.DiGraph, road, *, progress=None) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
        table_rows: list[dict[str, object]] = []
        path_rows: list[dict[str, object]] = []
        geometries = []
        total_paths = graph.number_of_edges()
        for finished, (source, target, data) in enumerate(
            sorted(graph.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1]))),
            start=1,
        ):
            source_data = graph.nodes[source]
            target_data = graph.nodes[target]
            road_path = data.get("road_path")
            if road_path is None:
                raise RuntimeError(f"X edge {source!r}->{target!r} is missing its road path")
            common = {
                "source_type": str(source_data["type"]),
                "source_cluster": int(source_data["cluster"]),
                "target_type": str(target_data["type"]),
                "target_cluster": int(target_data["cluster"]),
                "technical_coefficient": float(data["technical_coefficient"]),
                "road_distance": float(data["road_distance"]),
                "effective_road_distance": float(data.get("effective_road_distance", data["road_distance"])),
                "edge_weight": float(data["weight"]),
            }
            table_rows.append(common)
            path_rows.append(
                {
                    "from_id": str(source),
                    "from_type": str(source_data["type"]),
                    "from_cluster": int(source_data["cluster"]),
                    "to_id": str(target),
                    "to_type": str(target_data["type"]),
                    "to_cluster": int(target_data["cluster"]),
                    **common,
                }
            )
            geometries.append(road.path_geometry(road_path))
            if progress is not None and (finished % 25000 == 0 or finished == total_paths):
                progress(
                    f"network X: route geometries {finished:,}/{total_paths:,} "
                    f"({100 * finished / total_paths:.1f}%)"
                )
        table = pd.DataFrame(table_rows, columns=_X_EDGE_COLUMNS)
        path_columns = [
            "from_id", "from_type", "from_cluster", "to_id", "to_type", "to_cluster",
            *_X_EDGE_COLUMNS,
        ]
        if path_rows:
            paths = gpd.GeoDataFrame(
                path_rows, geometry=geometries, crs=road.crs
            ).to_crs("EPSG:4326")
            paths = paths[path_columns + ["geometry"]]
        else:
            paths = gpd.GeoDataFrame(
                {column: pd.Series(dtype="object") for column in path_columns},
                geometry=gpd.GeoSeries([], crs="EPSG:4326"),
                crs="EPSG:4326",
            )
        return table, paths

    @staticmethod
    def _disconnected_output(disconnected: pd.DataFrame) -> pd.DataFrame:
        rows = [
            {
                "source_type": str(row["type1"]),
                "source_cluster": int(row["cluster1"]),
                "target_type": str(row["type2"]),
                "target_cluster": int(row["cluster2"]),
                "reason": str(row["status"]),
            }
            for row in disconnected.to_dict("records")
        ]
        return pd.DataFrame(rows, columns=_DISCONNECTED_COLUMNS)

    def _recipe_centrality(self, planner, deps) -> ArtifactRecipe:
        parameters = {"method": self.config.centrality_method}
        if self.config.centrality_method == "katz":
            parameters.update({
                "katz_alpha_factor": self.config.katz_alpha_factor,
                "katz_beta": self.config.katz_beta,
                "combination": "geometric_mean",
                "normalization": "l2_after_combination",
            })
        return ArtifactRecipe.build(
            "analysis.centrality",
            implementation_version="balanced-directed-katz-geomean-v4-scaled-spectrum",
            dependencies={"analysis.x": deps["analysis.x"]},
            parameters=parameters,
        )

    def _exec_centrality(self, planner, recipe, deps, write: ArtifactWrite):
        with detail_phase(self.progress, "centrality: reconstructing directed X graph (without route geometry)"):
            x = self.load_x(deps["analysis.x"], include_paths=False)
        with detail_phase(
            self.progress,
            f"centrality: computing {self.config.centrality_method} for "
            f"{len(x.nodes):,} nodes and {len(x.edges):,} edges",
        ):
            result = compute_centrality(
                x.graph,
                method=self.config.centrality_method,
                direction=self.config.centrality_direction,
                katz_alpha_factor=self.config.katz_alpha_factor,
                katz_beta=self.config.katz_beta,
            )
        rows = []
        for row in x.nodes.itertuples(index=False):
            node_id = str(row.node_id)
            if node_id not in result.values:
                raise RuntimeError(f"centrality is missing X node {node_id!r}")
            rows.append(
                {
                    "node_id": node_id,
                    "type": str(row.type),
                    "cluster": int(row.cluster),
                    "in_degree": int(row.in_degree),
                    "out_degree": int(row.out_degree),
                    "katz_in_raw": (
                        float(result.katz_in_raw[node_id])
                        if result.katz_in_raw is not None else None
                    ),
                    "katz_out_raw": (
                        float(result.katz_out_raw[node_id])
                        if result.katz_out_raw is not None else None
                    ),
                    "centrality": float(result.values[node_id]),
                }
            )
        table = pd.DataFrame(
            rows,
            columns=[
                "node_id", "type", "cluster", "in_degree", "out_degree",
                "katz_in_raw", "katz_out_raw", "centrality",
            ],
        ).sort_values("node_id", kind="stable").reset_index(drop=True)
        table.to_csv(
            write.output("centrality.csv"),
            index=False,
            float_format="%.17g",
            lineterminator="\n",
        )
        payload = {
            "direction": result.direction,
            "degenerate_dag": bool(result.degenerate_dag),
            "note": result.note,
            "node_count": len(table),
            "method": result.method,
            "alpha": result.alpha,
            "beta": result.beta,
            "spectral_radius": result.spectral_radius,
            "spectral_scale_kind": result.spectral_scale_kind,
            "combination": result.combination,
            "normalization": result.normalization,
        }
        write.output("centrality.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return payload, {
            "centrality_method": result.method,
            "direction_removed_for_centrality": result.direction == "undirected",
            "directed_x_preserved": True,
        }

    def _recipe_scores(self, planner, deps) -> ArtifactRecipe:
        return ArtifactRecipe.build(
            "analysis.scores",
            implementation_version="distance-tempered-point-score-v1",
            dependencies={
                "spatial.point_distances": deps["spatial.point_distances"],
                "analysis.centrality": deps["analysis.centrality"],
            },
            parameters={"distance_tempering": self.config.distance_tempering},
        )

    def _exec_scores(self, planner, recipe, deps, write: ArtifactWrite):
        with detail_phase(self.progress, "scoring: reading point distances and cluster centrality"):
            points = self.spatial.read_point_distances(deps["spatial.point_distances"])
            centrality = self.load_centrality(deps["analysis.centrality"])
        with detail_phase(self.progress, f"scoring: computing scores for {len(points):,} establishments"):
            scores = tempered_point_scores(
                points,
                centrality.values,
                distance_tempering=self.config.distance_tempering,
            )
        with detail_phase(self.progress, f"scoring: serializing {len(scores):,} point scores"):
            write_geoframe(scores, write.output("scores.json"))
        return {
            "rows": len(scores),
            "crs": str(scores.crs),
            "distance_tempering": self.config.distance_tempering,
            "score_min": float(scores["sigma_score"].min()),
            "score_max": float(scores["sigma_score"].max()),
        }, {
            "score_formula": "cluster_centrality * (1 - distance_tempering * normalized_cluster_distance)",
            "distance_normalization": "cluster_p90_bounded",
        }

    def x(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("analysis.x", force=force)

    def centrality(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("analysis.centrality", force=force)

    def scores(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("analysis.scores", force=force)

    def load_centrality(self, ref: ArtifactRef | None = None) -> CentralityResult:
        ref = ref or self.workspace.artifact("analysis.centrality")
        if ref is None:
            raise RuntimeError("analysis.centrality has not been prepared")
        if ref.stage != "analysis.centrality":
            raise ValueError("ArtifactRef is not an analysis.centrality artifact")
        table = pd.read_csv(ref.path / "centrality.csv", dtype=str, keep_default_na=False)
        values = {
            str(row.node_id): float(row.centrality)
            for row in table.itertuples(index=False)
        }
        metadata = json.loads((ref.path / "centrality.json").read_text(encoding="utf-8"))
        katz_in_raw = None
        katz_out_raw = None
        if "katz_in_raw" in table.columns and table["katz_in_raw"].str.len().gt(0).any():
            katz_in_raw = {
                str(row.node_id): float(row.katz_in_raw)
                for row in table.itertuples(index=False) if str(row.katz_in_raw)
            }
        if "katz_out_raw" in table.columns and table["katz_out_raw"].str.len().gt(0).any():
            katz_out_raw = {
                str(row.node_id): float(row.katz_out_raw)
                for row in table.itertuples(index=False) if str(row.katz_out_raw)
            }
        return CentralityResult(
            values=values,
            direction=str(metadata["direction"]),
            degenerate_dag=bool(metadata["degenerate_dag"]),
            note=metadata.get("note"),
            method=str(metadata.get("method") or "eigenvector"),
            alpha=metadata.get("alpha"),
            beta=metadata.get("beta"),
            spectral_radius=metadata.get("spectral_radius"),
            spectral_scale_kind=metadata.get("spectral_scale_kind"),
            katz_in_raw=katz_in_raw,
            katz_out_raw=katz_out_raw,
            combination=metadata.get("combination"),
            normalization=metadata.get("normalization"),
        )

    def read_centrality_table(self, ref: ArtifactRef | None = None) -> pd.DataFrame:
        ref = ref or self.workspace.artifact("analysis.centrality")
        if ref is None:
            raise RuntimeError("analysis.centrality has not been prepared")
        table = pd.read_csv(ref.path / "centrality.csv", dtype=str, keep_default_na=False)
        for column in ("cluster", "in_degree", "out_degree"):
            table[column] = table[column].map(int)
        for column in ("katz_in_raw", "katz_out_raw"):
            if column in table.columns:
                table[column] = table[column].map(lambda value: float(value) if value else float("nan"))
        table["centrality"] = table["centrality"].map(float)
        return table

    def read_scores(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("analysis.scores")
        if ref is None:
            raise RuntimeError("analysis.scores has not been prepared")
        if ref.stage != "analysis.scores":
            raise ValueError("ArtifactRef is not an analysis.scores artifact")
        return read_geoframe(ref.path / "scores.json")

    def load_x(self, ref: ArtifactRef | None = None, *, include_paths: bool = True) -> XResult:
        ref = ref or self.workspace.artifact("analysis.x")
        if ref is None:
            raise RuntimeError("analysis.x has not been prepared")
        if ref.stage != "analysis.x":
            raise ValueError("ArtifactRef is not an analysis.x artifact")
        nodes = pd.read_csv(
            ref.path / "x_nodes.csv", dtype=str, keep_default_na=False
        )
        for column in ("cluster", "center_network_node", "in_degree", "out_degree"):
            nodes[column] = nodes[column].map(int)
        for column in ("center_x", "center_y"):
            nodes[column] = nodes[column].map(float)
        edges = pd.read_csv(
            ref.path / "x_edges.csv",
            dtype=str,
            keep_default_na=False,
        )
        for column in ("source_cluster", "target_cluster"):
            edges[column] = edges[column].map(int)
        for column in ("technical_coefficient", "road_distance", "edge_weight", "effective_road_distance"):
            if column not in edges.columns:  # older managed X artifacts remain readable
                continue
            # Python float parsing round-trips our %.17g serialization exactly;
            # pandas' fast numeric parser can select an adjacent IEEE-754 value.
            edges[column] = edges[column].map(float)
        disconnected = pd.read_csv(
            ref.path / "disconnected_overlap_pairs.csv",
            dtype=str,
            keep_default_na=False,
        )
        for column in ("source_cluster", "target_cluster"):
            if column in disconnected.columns:
                disconnected[column] = disconnected[column].map(int)
        if include_paths:
            parquet_path = ref.path / "x_paths.parquet"
            paths = (
                gpd.read_parquet(parquet_path)
                if parquet_path.is_file()
                else read_geoframe(ref.path / "x_paths.json")
            )
            # GeoParquet can restore EPSG:4326 as a verbose PROJJSON CRS.
            # Validate the actual CRS, then use the stable canonical label that
            # SIGMA's public API and pre-GeoParquet artifacts already expose.
            if paths.crs is None or paths.crs.to_epsg() != 4326:
                raise ValueError("analysis X paths must use EPSG:4326")
            paths = paths.set_crs("EPSG:4326", allow_override=True)
            overlay_file = ref.path / "x_paths_overlay.json"
            if overlay_file.is_file():
                overlay = json.loads(overlay_file.read_text(encoding="utf-8"))
                if (overlay.get("version") != 1 or overlay.get("kind") !=
                        "immutable_parquet_hardlink_plus_current_edge_csv"):
                    raise ValueError("unsupported or malformed X geometry-weight overlay")
                if len(paths) != len(edges):
                    raise ValueError("X base route geometry and current edge table have different row counts")
                # Never attach new weights to the wrong geometry.
                for key in ("source_type", "source_cluster", "target_type", "target_cluster"):
                    if key not in paths or key not in edges:
                        raise ValueError(f"X geometry-weight overlay missing key: {key}")
                    if not (paths[key].astype(str).to_numpy() ==
                            edges[key].astype(str).to_numpy()).all():
                        raise ValueError(f"X base geometry row keys differ from current edges: {key}")
                for key in ("technical_coefficient", "road_distance",
                            "effective_road_distance", "edge_weight"):
                    if key in edges:
                        paths[key] = edges[key].to_numpy(dtype=float)
        else:
            # Centrality needs edge weights and topology but no route geometries.
            paths = gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"))
        graph = nx.DiGraph()
        for row in nodes.itertuples(index=False):
            graph.add_node(
                str(row.node_id),
                type=str(row.type),
                cluster=int(row.cluster),
                center_network_node=int(row.center_network_node),
                center_x=float(row.center_x),
                center_y=float(row.center_y),
            )
        for row in edges.itertuples(index=False):
            source = make_node_id(str(row.source_type), int(row.source_cluster))
            target = make_node_id(str(row.target_type), int(row.target_cluster))
            graph.add_edge(
                source,
                target,
                technical_coefficient=float(row.technical_coefficient),
                dag_weight=float(row.technical_coefficient),
                road_distance=float(row.road_distance),
                **({"effective_road_distance": float(row.effective_road_distance)}
                   if "effective_road_distance" in edges.columns else {}),
                weight=float(row.edge_weight),
            )
        return XResult(graph, nodes, edges, disconnected, paths)

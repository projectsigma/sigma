"""Managed C14-C15 analysis stages joining X, centrality, and point scoring."""
from __future__ import annotations

import json
from dataclasses import dataclass
import math
from typing import Mapping

import geopandas as gpd
import networkx as nx
import pandas as pd

from sigma.artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite
from sigma.execution import ExecutionPlanner
from sigma.places.frame_io import read_geoframe, write_geoframe
from sigma.stages import StageSpec
from sigma.workspace import SigmaWorkspace

from .centrality import CentralityResult, compute_centrality
from .graph import make_node_id
from .scoring import tempered_point_scores
from .x_graph import instantiate_network


_X_EDGE_COLUMNS = [
    "source_type",
    "source_cluster",
    "target_type",
    "target_cluster",
    "technical_coefficient",
    "road_distance",
    "edge_weight",
]
_DISCONNECTED_COLUMNS = [
    "source_type",
    "source_cluster",
    "target_type",
    "target_cluster",
    "reason",
]


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
        tempering = float(self.distance_tempering)
        if not math.isfinite(tempering) or not 0.0 <= tempering <= 1.0:
            raise ValueError("distance_tempering must be finite and between 0 and 1")
        object.__setattr__(self, "centrality_method", method)
        object.__setattr__(self, "centrality_direction", direction)
        object.__setattr__(self, "katz_alpha_factor", alpha_factor)
        object.__setattr__(self, "katz_beta", beta)
        object.__setattr__(self, "distance_tempering", tempering)


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
            (*self._spatial_x_dependencies, self._economic_graph_stage),
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
            implementation_version="directed-spatial-economic-x-v1",
            dependencies={
                name: deps[name]
                for name in (*self._spatial_x_dependencies, self._economic_graph_stage)
            },
            parameters={
                "overlap_rule": "positive_area",
                "road_distance": "shortest_path",
                "edge_weight": "technical_coefficient_times_road_distance",
                "zero_distance_self_edges": "omit",
            },
        )

    def _exec_x(self, planner, recipe, deps, write: ArtifactWrite):
        centers = self.spatial.read_centers(deps["spatial.centers"])
        partitions = self.spatial.read_partitions(deps["spatial.partitions"])
        if hasattr(self.spatial, "analysis_road"):
            road = self.spatial.analysis_road(deps)
        else:
            _, road = self.spatial._retained_with_augmented(deps["spatial.clusters"])
        economic = self.economy.load_graph(deps[self._economic_graph_stage]).graph
        graph, disconnected = instantiate_network(
            centers,
            partitions,
            economic,
            road,
            progress=self.progress,
        )

        nodes = self._node_table(graph)
        edges, paths = self._edge_outputs(graph, road)
        disconnected_out = self._disconnected_output(disconnected)

        nodes.to_csv(write.output("x_nodes.csv"), index=False, lineterminator="\n")
        edges.to_csv(
            write.output("x_edges.csv"), index=False, float_format="%.17g", lineterminator="\n"
        )
        disconnected_out.to_csv(
            write.output("disconnected_overlap_pairs.csv"), index=False, lineterminator="\n"
        )
        write_geoframe(paths, write.output("x_paths.json"))
        metadata = {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "disconnected_overlap_pairs": len(disconnected_out),
            "economic_graph_is_dag": nx.is_directed_acyclic_graph(economic),
            "x_is_dag": nx.is_directed_acyclic_graph(graph),
            "zero_distance_self_edges_omitted": int(
                graph.graph.get("zero_distance_self_edges_omitted", 0)
            ),
            "edge_weight": "technical_coefficient * road_distance",
            "road_distance_crs": str(road.crs),
        }
        write.output("x.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return metadata, {
            "economic_weight": "technical_coefficient",
            "spatial_weight": "technical_coefficient_times_road_distance",
        }

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
    def _edge_outputs(graph: nx.DiGraph, road) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
        table_rows: list[dict[str, object]] = []
        path_rows: list[dict[str, object]] = []
        geometries = []
        for source, target, data in sorted(
            graph.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1]))
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
            implementation_version="balanced-directed-katz-geomean-v2",
            dependencies={"analysis.x": deps["analysis.x"]},
            parameters=parameters,
        )

    def _exec_centrality(self, planner, recipe, deps, write: ArtifactWrite):
        x = self.load_x(deps["analysis.x"])
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
        points = self.spatial.read_point_distances(deps["spatial.point_distances"])
        centrality = self.load_centrality(deps["analysis.centrality"])
        scores = tempered_point_scores(
            points,
            centrality.values,
            distance_tempering=self.config.distance_tempering,
        )
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

    def load_x(self, ref: ArtifactRef | None = None) -> XResult:
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
        for column in ("technical_coefficient", "road_distance", "edge_weight"):
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
        paths = read_geoframe(ref.path / "x_paths.json")
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
                weight=float(row.edge_weight),
            )
        return XResult(graph, nodes, edges, disconnected, paths)

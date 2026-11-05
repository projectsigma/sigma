"""User-facing spatial outputs and run description for unified SIGMA."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pyogrio
from shapely.geometry import Point

from sigma.analysis.graph import make_node_id

WGS84 = "EPSG:4326"


def build_x_node_outputs(
    graph: nx.DiGraph,
    centrality: Mapping[str, float],
    crs: object,
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Create tabular and WGS84 point representations of X nodes."""
    rows: list[dict[str, object]] = []
    geometries = []
    for node, data in sorted(graph.nodes(data=True), key=lambda item: str(item[0])):
        node_id = str(node)
        rows.append(
            {
                "node_id": node_id,
                "type": str(data["type"]),
                "cluster": int(data["cluster"]),
                "cluster_no": int(data["cluster"]),
                "in_degree": int(graph.in_degree(node)),
                "out_degree": int(graph.out_degree(node)),
                "centrality": float(centrality[node_id]),
            }
        )
        geometries.append(Point(float(data["center_x"]), float(data["center_y"])))

    geo = gpd.GeoDataFrame(rows, geometry=geometries, crs=crs)
    geo = geo.to_crs(WGS84)
    geo["lon"] = geo.geometry.x.astype(float)
    geo["lat"] = geo.geometry.y.astype(float)
    order = [
        "node_id",
        "type",
        "cluster",
        "cluster_no",
        "lat",
        "lon",
        "in_degree",
        "out_degree",
        "centrality",
        "geometry",
    ]
    geo = geo[order]
    table = pd.DataFrame(geo.drop(columns="geometry"))
    return table, geo


def _cluster_layer(partitions: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    clusters = partitions.copy()
    clusters["cluster_no"] = clusters["cluster"].astype(int)
    clusters["cluster_id"] = [
        make_node_id(str(type_value), int(cluster))
        for type_value, cluster in zip(clusters["type"], clusters["cluster"], strict=True)
    ]
    return clusters.to_crs(WGS84)


def write_spatial_geopackage(
    path: str | Path,
    partitions: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    paths: gpd.GeoDataFrame,
) -> Path:
    """Write the three requested GIS layers into one WGS84 GeoPackage."""
    for name, frame in (("partitions", partitions), ("nodes", nodes), ("paths", paths)):
        if frame.crs is None:
            raise ValueError(f"{name} export layer has no declared CRS")
    partitions = partitions.to_crs(WGS84) if str(partitions.crs).upper() != WGS84 else partitions.copy()
    nodes = nodes.to_crs(WGS84) if str(nodes.crs).upper() != WGS84 else nodes.copy()
    paths = paths.to_crs(WGS84) if str(paths.crs).upper() != WGS84 else paths.copy()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    clusters = _cluster_layer(partitions)
    pyogrio.write_dataframe(
        clusters,
        target,
        layer="clusters",
        driver="GPKG",
        promote_to_multi=True,
    )
    pyogrio.write_dataframe(
        nodes,
        target,
        layer="nodes",
        driver="GPKG",
        append=True,
        geometry_type="Point",
    )
    pyogrio.write_dataframe(
        paths,
        target,
        layer="paths",
        driver="GPKG",
        append=True,
        geometry_type="LineString",
    )
    return target


def spatial_summary(
    *,
    partitions: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    paths: gpd.GeoDataFrame,
) -> dict[str, object]:
    """Return compact run-specific numbers used by metadata and OUTPUTS.txt."""
    type_counts = partitions.groupby("type", sort=True).size() if len(partitions) else pd.Series()
    route_distance = (
        pd.to_numeric(paths["road_distance"], errors="coerce").to_numpy(float)
        if len(paths)
        else np.empty(0, dtype=float)
    )
    return {
        "represented_types": int(partitions["type"].astype(str).nunique()),
        "clusters_min_per_type": int(type_counts.min()) if len(type_counts) else 0,
        "clusters_median_per_type": float(type_counts.median()) if len(type_counts) else 0.0,
        "clusters_max_per_type": int(type_counts.max()) if len(type_counts) else 0,
        "x_in_degree_max": int(nodes["in_degree"].max()) if len(nodes) else 0,
        "x_out_degree_max": int(nodes["out_degree"].max()) if len(nodes) else 0,
        "x_in_degree_mean": float(nodes["in_degree"].mean()) if len(nodes) else 0.0,
        "x_out_degree_mean": float(nodes["out_degree"].mean()) if len(nodes) else 0.0,
        "route_distance_total": float(route_distance.sum()) if len(route_distance) else 0.0,
        "route_distance_min": float(route_distance.min()) if len(route_distance) else None,
        "route_distance_median": float(np.median(route_distance)) if len(route_distance) else None,
        "route_distance_max": float(route_distance.max()) if len(route_distance) else None,
        "spatial_output_crs": WGS84,
        "spatial_layers": ["clusters", "nodes", "paths"],
    }


def write_outputs_description(
    path: str | Path,
    *,
    metadata: Mapping[str, object],
    output_paths: Mapping[str, str],
) -> Path:
    """Write a stable human-readable description plus run-specific diagnostics."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    def number(key: str, default: object = "n/a") -> object:
        value = metadata.get(key, default)
        if isinstance(value, float):
            return f"{value:,.6g}"
        if isinstance(value, int):
            return f"{value:,}"
        return value

    lines = [
        "SIGMA OUTPUTS",
        "====================",
        f"Generated: {metadata.get('created_at') or datetime.now(UTC).isoformat()}",
        f"SIGMA version: {metadata.get('sigma_version', 'unknown')}",
        f"Workflow: {metadata.get('workflow_version', 'unknown')}",
    ]
    if metadata.get("area_slug"):
        lines.append(
            "Area: "
            f"{metadata.get('area_name') or metadata.get('area_slug')} "
            f"({metadata.get('area_slug')})"
        )
    lines += [
        f"Classification: {metadata.get('classification', 'unknown')}",
        "",
        "PRIMARY GIS OUTPUT",
        "------------------",
        "sigma_spatial_outputs.gpkg is one GeoPackage containing all sectors:",
        "  clusters  Polygon/MultiPolygon cluster partitions for every type. Key fields:",
        "            type, cluster, cluster_no, cluster_id.",
        "  nodes     Point representation of network X nodes in EPSG:4326. Key fields:",
        "            type, cluster_no, lat, lon, in_degree, out_degree, centrality.",
        "  paths     Center-to-center road routes only when --route-geometry precomputed",
        "            is selected. The default browser mode leaves this layer empty and",
        "            publishes sigma_routing_graph.bin for on-demand browser routes.",
        "            Numerical X weights and road distances are identical in both modes.",
        "",
        "OTHER OUTPUTS",
        "-------------",
        "sigma_points.parquet: canonical analyzed establishment layer combining cluster "
        "assignment, center distance, directed Katz components, balanced centrality, and sigma_score.",
        "sigma_network_centers.parquet: final network-node 1-median (or labeled recovery) for each [type, cluster].",
        "sigma_partitions.parquet: final WGS84 cluster polygons; also represented "
        "in the GeoPackage.",
        "sigma_economic_graph.csv: canonical effective directed economic edges; legacy equivalent profiles publish sigma_io_dag.csv.",
        "sigma_X_nodes.csv: tabular X nodes and centrality.",
        "sigma_X_edges.csv: tabular X edges and shortest-path distances.",
        "sigma_disconnected_overlap_pairs.csv: candidate overlaps whose centers are "
        "road-disconnected.",
        "sigma_run_metadata.json: machine-readable run metadata and diagnostics.",
        "OUTPUTS.txt: this file.",
        "",
        "CURRENT RUN",
        "-----------",
        f"Scored points: {number('scored_points')}",
        f"Represented economic types: {number('represented_types')}",
        f"Clusters / X nodes: {number('x_nodes')}",
        f"Numerical X edges (route geometry optional): {number('x_edges')}",
        f"Disconnected overlap pairs omitted from X: {number('disconnected_overlap_pairs')}",
        "Clusters per type (min / median / max): "
        f"{number('clusters_min_per_type')} / {number('clusters_median_per_type')} / "
        f"{number('clusters_max_per_type')}",
        "Maximum in-degree / out-degree: "
        f"{number('x_in_degree_max')} / {number('x_out_degree_max')}",
        "Mean in-degree / out-degree: "
        f"{number('x_in_degree_mean')} / {number('x_out_degree_mean')}",
        "Route distance total: "
        f"{number('route_distance_total')} {metadata.get('road_distance_unit', '')}",
        "Route distance min / median / max: "
        f"{number('route_distance_min')} / {number('route_distance_median')} / "
        f"{number('route_distance_max')} {metadata.get('road_distance_unit', '')}",
        f"Road-distance CRS: {metadata.get('road_distance_crs', 'unknown')}",
        f"GIS output CRS: {metadata.get('spatial_output_crs', WGS84)}",
        "",
        "FILES WRITTEN",
        "-------------",
    ]
    for name, value in sorted(output_paths.items()):
        lines.append(f"{name}: {value}")
    lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target

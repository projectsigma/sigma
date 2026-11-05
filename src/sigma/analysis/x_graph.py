"""Spatial instantiation of a directed economic graph as cluster-level network ``X``.

This is the C14 generalization of Engine's proven ``spatial_graph`` kernel.  The
spatial mechanics are intentionally retained: sector relationships instantiate
only where type-specific Voronoi partitions overlap with positive area, road
separation is exact shortest-path distance between network centers, and X edge
weight is the inverse-power road-distance definition
``technical_coefficient / max(road_distance_in_metres, 1) ** x_distance_decay_lambda``.

Unlike the legacy Engine kernel, neither the sector graph nor X is required to
be acyclic.  Reciprocal economic relationships therefore remain reciprocal X
relationships.  Positive economic self-use remains in the Economy; a zero-road-
distance X self-edge is intentionally omitted as a topological policy,
independent of the now-positive capped distance-decay factor.
"""
from __future__ import annotations

import math

from typing import Callable, Mapping
import json

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely

from sigma.transport.network import AugmentedNetwork

from .graph import make_node_id

_DIAGNOSTIC_COLUMNS = ["type1", "cluster1", "type2", "cluster2", "status"]


def mean_hub_effective_distance(
    center_road_distance: float, source_mean_radius: float, target_mean_radius: float,
) -> float:
    """Mean length of routes constrained through both cluster 1-medians, in metres.

    This is an upper bound on the mean direct shortest-road separation on an
    undirected road metric, not an actual pairwise mean or a geometric route.
    """
    d, ra, rb = (float(center_road_distance), float(source_mean_radius), float(target_mean_radius))
    if any(not math.isfinite(value) or value < 0 for value in (d, ra, rb)):
        raise ValueError("mean-hub distance requires finite nonnegative road distances")
    result = d + ra + rb
    if not math.isfinite(result):
        raise ValueError("mean-hub effective road distance overflowed")
    return result


def inverse_mean_hub_x_weight(
    coefficient: float, effective_distance: float, decay_lambda: float = 1.0,
) -> float:
    """Inverse mean-hub weighting a_st / max(D in metres, 1) ** lambda.

    The one-metre floor applies only to the weighting kernel.
    The measured road distances and route geometries remain unaltered.
    Shared by full routing and weight-only artifact updates.
    """
    a, d, lam = float(coefficient), float(effective_distance), float(decay_lambda)
    if not math.isfinite(a) or a <= 0:
        raise ValueError("technical coefficient must be finite and positive")
    if not math.isfinite(d) or d < 0:
        raise ValueError("effective road distance must be finite and nonnegative")
    if not math.isfinite(lam) or lam < 0:
        raise ValueError("X attenuation exponent must be finite and nonnegative")
    result = a * (max(d / 1.0, 1.0) ** -lam)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("X edge weight underflowed or was nonfinite")
    return result


def _positive_area_overlaps(left_geometry, right: gpd.GeoDataFrame) -> np.ndarray:
    """Return right-row positions having positive-area intersection with ``left``.

    Candidates keep the spatial-index order; the intersections are computed in one
    vectorized GEOS call, with the same test as before (non-empty, positive area).
    """
    candidates = np.asarray(
        right.sindex.query(left_geometry, predicate="intersects"),
        dtype=np.int64,
    )
    if candidates.size == 0:
        return candidates
    intersections = shapely.intersection(left_geometry, right.geometry.to_numpy()[candidates])
    keep = ~shapely.is_empty(intersections) & (shapely.area(intersections) > 0)
    return candidates[keep]


def _pack_routes(routes: list[np.ndarray]) -> dict[str, bytes]:
    """Savepoint payload: route lengths and concatenated int32 road-node ids."""
    lengths = np.asarray([len(route) for route in routes], dtype="<i8")
    nodes = (np.concatenate(routes) if routes else np.empty(0, dtype="<i4")).astype("<i4", copy=False)
    return {"route_lengths.bin": lengths.tobytes(), "route_nodes.bin": nodes.tobytes()}


def _unpack_routes(stored: Mapping[str, bytes], count: int) -> list[np.ndarray]:
    lengths = np.frombuffer(stored["route_lengths.bin"], dtype="<i8")
    nodes = np.frombuffer(stored["route_nodes.bin"], dtype="<i4").astype(np.int32)
    if len(lengths) != count or (lengths < 1).any() or int(lengths.sum()) != len(nodes):
        raise ValueError("route savepoint does not match its X edges")
    return np.split(nodes, np.cumsum(lengths)[:-1]) if count else []


def _validate_spatial_inputs(
    centers: gpd.GeoDataFrame,
    partitions: gpd.GeoDataFrame,
    economic_graph: nx.DiGraph,
) -> None:
    """Check join keys and directed-economic-graph invariants before spatial work."""
    if not economic_graph.is_directed():
        raise ValueError("spatial instantiation requires a directed economic graph")

    center_required = {"type", "cluster", "center_network_node", "geometry"}
    partition_required = {"type", "cluster", "geometry"}
    missing_centers = center_required - set(centers.columns)
    missing_partitions = partition_required - set(partitions.columns)
    if missing_centers:
        raise ValueError(f"center table is missing columns: {sorted(missing_centers)}")
    if missing_partitions:
        raise ValueError(f"partition table is missing columns: {sorted(missing_partitions)}")
    if centers.crs is None or partitions.crs is None:
        raise ValueError("centers and partitions must both have a CRS")
    if centers.crs != partitions.crs:
        raise ValueError("centers and partitions must use the same CRS")

    for position, geometry in enumerate(centers.geometry):
        if geometry is None or geometry.is_empty or geometry.geom_type != "Point":
            raise ValueError(f"center row {position} must contain one non-empty Point")
        coordinates = np.asarray(geometry.coords, dtype=float)
        if not np.isfinite(coordinates[:, :2]).all():
            raise ValueError(f"center row {position} contains non-finite coordinates")

    for position, geometry in enumerate(partitions.geometry):
        if geometry is None or geometry.is_empty:
            raise ValueError(f"partition row {position} has empty geometry")
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"partition row {position} must be polygonal")
        if not geometry.is_valid:
            raise ValueError(
                f"partition row {position} is invalid: {shapely.is_valid_reason(geometry)}"
            )
        if not np.isfinite(float(geometry.area)) or float(geometry.area) <= 0:
            raise ValueError(f"partition row {position} must have positive finite area")

    center_keys = list(
        zip(centers["type"].astype(str), centers["cluster"].astype(int), strict=True)
    )
    partition_keys = list(
        zip(partitions["type"].astype(str), partitions["cluster"].astype(int), strict=True)
    )
    if len(center_keys) != len(set(center_keys)):
        raise ValueError("center [type, cluster] keys must be unique")
    if len(partition_keys) != len(set(partition_keys)):
        raise ValueError("partition [type, cluster] keys must be unique")

    unknown_partitions = sorted(set(partition_keys) - set(center_keys))
    if unknown_partitions:
        raise ValueError(
            "partition rows have no matching network center: " f"{unknown_partitions[:10]}"
        )

    economic_types = {str(value) for value in economic_graph.nodes}
    unknown_types = sorted({key[0] for key in center_keys} - economic_types)
    if unknown_types:
        raise ValueError(
            "spatial centers reference types outside the economic graph: "
            f"{unknown_types[:10]}"
        )


def instantiate_network(
    centers: gpd.GeoDataFrame,
    partitions: gpd.GeoDataFrame,
    economic_graph: nx.DiGraph,
    road: AugmentedNetwork,
    progress: Callable[[str], None] | None = None,
    *,
    x_distance_decay_lambda: float = 1.0,
    mean_road_radius_by_cluster: Mapping[tuple[str, int], float] | None = None,
    cluster_sector_shares: Mapping[tuple[str, int], float] | None = None,
    include_paths: bool = True,
    savepoints=None,
) -> tuple[nx.DiGraph, pd.DataFrame]:
    """Instantiate cluster-level directed network ``X`` from overlapping partitions.

    Every center becomes a node before edges are considered, so isolated clusters
    are retained.  For each positive weighted sector edge, only positive-area
    polygon overlaps create candidate X edges.  Exact road distances and routes
    are evaluated one source center at a time and only for the requested target
    centers; each X edge stores its route as int32 road-node ids (``route_nodes``).
    """
    decay_lambda = float(x_distance_decay_lambda)
    if not math.isfinite(decay_lambda) or decay_lambda < 0.0:
        raise ValueError("x_distance_decay_lambda must be finite and non-negative")
    _validate_spatial_inputs(centers, partitions, economic_graph)

    graph = nx.DiGraph()
    center_index: dict[tuple[str, int], pd.Series] = {}
    for _, row in centers.iterrows():
        key = (str(row["type"]), int(row["cluster"]))
        node_id = make_node_id(*key)
        center_index[key] = row
        graph.add_node(
            node_id,
            type=key[0],
            cluster=key[1],
            center_network_node=int(row["center_network_node"]),
            center_x=float(row.geometry.x),
            center_y=float(row.geometry.y),
        )

    # A share is based on the clustered establishments in the *exact* economic
    # type, not on all establishments in a broader IO16/IO80 parent category.
    # None keeps legacy direct callers' weights unchanged. Managed X always
    # supplies a complete, validated share mapping.
    if cluster_sector_shares is not None:
        if set(cluster_sector_shares) != set(center_index):
            raise ValueError("cluster sector shares must cover every X center exactly")
        for key, share in cluster_sector_shares.items():
            value = float(share)
            if not math.isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f"invalid cluster sector share {key}: {share}")

    diagnostics: list[dict[str, object]] = []
    partitions_by_type = {
        str(type_value): group.reset_index(drop=True)
        for type_value, group in partitions.groupby("type", sort=False)
    }
    # Column arrays per type replace per-candidate ``.iloc`` row lookups.
    clusters_by_type = {
        type_value: frame["cluster"].to_numpy(np.int64)
        for type_value, frame in partitions_by_type.items()
    }
    center_nodes_by_type = {
        type_value: np.asarray(
            [int(center_index[(type_value, int(c))]["center_network_node"]) for c in clusters],
            dtype=np.int64,
        )
        for type_value, clusters in clusters_by_type.items()
    }

    outgoing_by_type: dict[str, list[tuple[str, dict[str, object]]]] = {}
    for type1, type2, edge_data in economic_graph.edges(data=True):
        source_type, target_type = str(type1), str(type2)
        if source_type not in partitions_by_type or target_type not in partitions_by_type:
            continue
        outgoing_by_type.setdefault(source_type, []).append((target_type, edge_data))

    active_source_types = list(outgoing_by_type)
    total_source_types = len(active_source_types)
    omitted_zero_self_edges = 0
    for type_number, type1 in enumerate(active_source_types, start=1):
        source_partitions = partitions_by_type[type1]
        outgoing = outgoing_by_type[type1]
        # SIGMA_RESUMABLE_SAVEPOINTS_V2: source-type routing work unit.
        unit = f"source:{type1}"
        if savepoints is not None:
            stored = savepoints.read(unit)
            expected_files = ({"edges.json", "route_lengths.bin", "route_nodes.bin"}
                              if include_paths else {"edges.json"})
            if stored is not None and set(stored) == expected_files:
                try:
                    saved = json.loads(stored["edges.json"])
                    if saved["source_type"] != type1:
                        raise ValueError("source mismatch")
                    routes = (_unpack_routes(stored, len(saved["edges"])) if include_paths
                              else [None] * len(saved["edges"]))
                    recovered = []
                    for row, route in zip(saved["edges"], routes, strict=True):
                        source, target, attributes = row
                        if (source not in graph or target not in graph or
                                str(graph.nodes[source]["type"]) != type1):
                            raise ValueError("cached X edge node mismatch")
                        if include_paths:
                            attributes["route_nodes"] = route
                        recovered.append((source, target, attributes))
                    for source, target, attributes in recovered:
                        graph.add_edge(source, target, **attributes)
                    diagnostics.extend(saved["diagnostics"])
                    omitted_zero_self_edges += int(saved["omitted_zero_self_edges"])
                    if progress is not None:
                        progress(f"network X: resumed source type {type1!r} ({type_number:,}/{total_source_types:,})")
                    continue
                except (ValueError, KeyError, TypeError, OverflowError):
                    pass
        diagnostic_start = len(diagnostics)
        omitted_start = omitted_zero_self_edges
        if progress is not None:
            progress(
                f"network X: source type {type_number:,}/{total_source_types:,} {type1!r}; "
                f"{len(source_partitions):,} source partitions; current X edges={graph.number_of_edges():,}"
            )

        work_by_source_node: dict[int, list[tuple[str, int, int, int, float]]] = {}
        source_geometries = source_partitions.geometry.to_numpy()
        for position, cluster1 in enumerate(clusters_by_type[type1].tolist()):
            source_network_node = int(center_nodes_by_type[type1][position])
            candidates = work_by_source_node.setdefault(source_network_node, [])

            for type2, edge_data in outgoing:
                economic_weight = float(edge_data.get("technical_coefficient", edge_data.get("weight")))
                if not np.isfinite(economic_weight) or economic_weight <= 0:
                    raise ValueError(
                        f"economic edge {type1!r}->{type2!r} has non-positive/non-finite weight"
                    )
                target_positions = _positive_area_overlaps(
                    source_geometries[position], partitions_by_type[type2]
                )
                for cluster2, target_network_node in zip(
                    clusters_by_type[type2][target_positions].tolist(),
                    center_nodes_by_type[type2][target_positions].tolist(),
                    strict=True,
                ):
                    candidates.append(
                        (type2, cluster1, cluster2, target_network_node, economic_weight)
                    )

        source_nodes = [node for node, candidates in work_by_source_node.items() if candidates]
        source_step = max(1, len(source_nodes) // 10)
        for source_number, source_network_node in enumerate(source_nodes, start=1):
            candidates = work_by_source_node[source_network_node]
            if progress is not None and (
                source_number == 1
                or source_number % source_step == 0
                or source_number == len(source_nodes)
            ):
                progress(
                    f"network X: type {type1!r} source center {source_number:,}/"
                    f"{len(source_nodes):,}; current X edges={graph.number_of_edges():,}"
                )

            target_nodes = np.fromiter(
                (candidate[3] for candidate in candidates), dtype=np.int64, count=len(candidates)
            )
            if include_paths:
                road_distances, routes = road.shortest_route_nodes_to_targets(
                    source_network_node, target_nodes)
            else:
                # Numerical X never computes predecessors or materializes road paths.
                road_distances = road.distances_to_targets(source_network_node, target_nodes)
                routes = [None] * len(target_nodes)

            for candidate, road_distance, route in zip(
                candidates, road_distances, routes, strict=True
            ):
                type2, cluster1, cluster2, _, economic_weight = candidate
                road_distance = float(road_distance)
                if not np.isfinite(road_distance):
                    diagnostics.append(
                        {
                            "type1": type1,
                            "cluster1": cluster1,
                            "type2": type2,
                            "cluster2": cluster2,
                            "status": "disconnected_centers",
                        }
                    )
                    continue
                if road_distance < 0:
                    raise RuntimeError("shortest-path engine returned a negative road distance")
                if include_paths and route is None:
                    raise RuntimeError("connected X edge is missing its shortest road route")

                source_id = make_node_id(type1, cluster1)
                target_id = make_node_id(type2, cluster2)
                if source_id == target_id and road_distance == 0.0:
                    omitted_zero_self_edges += 1
                    continue

                # Retain the true center-to-center route distance and geometry.
                # Production passes within-cluster mean road radii; direct legacy
                # callers without that mapping preserve their old behavior.
                if mean_road_radius_by_cluster is None:
                    effective_distance = road_distance
                else:
                    effective_distance = mean_hub_effective_distance(
                        road_distance,
                        mean_road_radius_by_cluster[(type1, cluster1)],
                        mean_road_radius_by_cluster[(type2, cluster2)],
                    )
                # Capped inverse-power attenuation: at lambda=1,
                # the pre-share weight is a / max(D / 1m, 1).
                # The one-metre floor affects the weight only, not stored
                # center-to-center road distances or route geometry.
                combined_weight = inverse_mean_hub_x_weight(economic_weight, effective_distance, decay_lambda)
                if cluster_sector_shares is not None:
                    combined_weight *= (
                        float(cluster_sector_shares[(type1, cluster1)])
                        * float(cluster_sector_shares[(type2, cluster2)])
                    )
                if not math.isfinite(combined_weight) or combined_weight <= 0.0:
                    raise ValueError(
                        "X edge weight underflowed to zero; reduce x_distance_decay_lambda"
                    )
                graph.add_edge(
                    source_id,
                    target_id,
                    technical_coefficient=economic_weight,
                    # Legacy alias retained internally so old checkpoint adapters can still
                    # consume a generalized X graph during the migration period.
                    dag_weight=economic_weight,
                    road_distance=road_distance,
                    effective_road_distance=effective_distance,
                    **({"route_nodes": route} if include_paths else {}),
                    weight=combined_weight,
                )

        if savepoints is not None:
            source_ids = [node for node in graph.nodes
                          if str(graph.nodes[node]["type"]) == type1]
            def checkpoint_value(value):
                if isinstance(value, np.generic):
                    return value.item()
                if isinstance(value, np.ndarray):
                    return value.tolist()
                raise TypeError(f"non-JSON X edge attribute: {type(value).__name__}")
            saved_edges = list(graph.out_edges(source_ids, data=True))
            edge_data = [
                [str(source), str(target), {k: v for k, v in data.items() if k != "route_nodes"}]
                for source, target, data in saved_edges
            ]
            savepoints.save(unit, {
                "edges.json": json.dumps({
                    "source_type": type1,
                    "edges": edge_data,
                    "diagnostics": diagnostics[diagnostic_start:],
                    "omitted_zero_self_edges": omitted_zero_self_edges - omitted_start,
                }, default=checkpoint_value, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                **(_pack_routes([data["route_nodes"] for _, _, data in saved_edges])
                   if include_paths else {}),
            })
            if progress is not None:
                progress(f"network X: saved source type {type1!r} ({type_number:,}/{total_source_types:,})")

    graph.graph["zero_distance_self_edges_omitted"] = omitted_zero_self_edges
    if progress is not None:
        progress(
            f"network X: complete ({graph.number_of_nodes():,} nodes, "
            f"{graph.number_of_edges():,} edges, {len(diagnostics):,} disconnected overlaps)"
        )
    disconnected = pd.DataFrame(diagnostics, columns=_DIAGNOSTIC_COLUMNS)
    return graph, disconnected

# SIGMA_BROWSER_ROUTING_V4_1_20261105

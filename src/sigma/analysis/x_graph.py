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

from typing import Callable
import json

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely

from sigma.transport.network import AugmentedNetwork

from .graph import make_node_id

_DIAGNOSTIC_COLUMNS = ["type1", "cluster1", "type2", "cluster2", "status"]


def _positive_area_overlaps(left_geometry, right: gpd.GeoDataFrame) -> list[int]:
    """Return right-row positions having positive-area intersection with ``left``."""
    candidates = np.asarray(
        right.sindex.query(left_geometry, predicate="intersects"),
        dtype=np.int64,
    )
    overlaps: list[int] = []
    for position in candidates:
        intersection = left_geometry.intersection(right.geometry.iloc[int(position)])
        if not intersection.is_empty and float(intersection.area) > 0:
            overlaps.append(int(position))
    return overlaps


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
    savepoints=None,
) -> tuple[nx.DiGraph, pd.DataFrame]:
    """Instantiate cluster-level directed network ``X`` from overlapping partitions.

    Every center becomes a node before edges are considered, so isolated clusters
    are retained.  For each positive weighted sector edge, only positive-area
    polygon overlaps create candidate X edges.  Exact road distances are evaluated
    one source center at a time and only for the requested target centers.
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

    diagnostics: list[dict[str, object]] = []
    partitions_by_type = {
        str(type_value): group.reset_index(drop=True)
        for type_value, group in partitions.groupby("type", sort=False)
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
            if stored is not None and set(stored) == {"edges.json"}:
                try:
                    saved = json.loads(stored["edges.json"])
                    if saved["source_type"] != type1:
                        raise ValueError("source mismatch")
                    recovered = []
                    for row in saved["edges"]:
                        source, target, attributes = row
                        if (source not in graph or target not in graph or
                                str(graph.nodes[source]["type"]) != type1):
                            raise ValueError("cached X edge node mismatch")
                        if "road_path" not in attributes:
                            raise ValueError("cached X edge lacks road path")
                        attributes["road_path"] = tuple(int(v) for v in attributes["road_path"])
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
        for _, source_partition in source_partitions.iterrows():
            cluster1 = int(source_partition["cluster"])
            source_center = center_index[(type1, cluster1)]
            source_network_node = int(source_center["center_network_node"])
            candidates = work_by_source_node.setdefault(source_network_node, [])

            for type2, edge_data in outgoing:
                economic_weight = float(edge_data.get("technical_coefficient", edge_data.get("weight")))
                if not np.isfinite(economic_weight) or economic_weight <= 0:
                    raise ValueError(
                        f"economic edge {type1!r}->{type2!r} has non-positive/non-finite weight"
                    )
                target_partitions = partitions_by_type[type2]
                target_positions = _positive_area_overlaps(
                    source_partition.geometry, target_partitions
                )
                for target_position in target_positions:
                    target_partition = target_partitions.iloc[target_position]
                    cluster2 = int(target_partition["cluster"])
                    target_center = center_index[(type2, cluster2)]
                    target_network_node = int(target_center["center_network_node"])
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
            if hasattr(road, "shortest_paths_to_targets"):
                road_distances, road_paths = road.shortest_paths_to_targets(
                    source_network_node, target_nodes
                )
            else:
                road_distances = road.distances_to_targets(source_network_node, target_nodes)
                road_paths = [
                    (source_network_node, int(target)) if np.isfinite(distance) else None
                    for target, distance in zip(target_nodes, road_distances, strict=True)
                ]

            for candidate, road_distance, road_path in zip(
                candidates, road_distances, road_paths, strict=True
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
                if road_path is None:
                    raise RuntimeError("connected X edge is missing its shortest road path")

                source_id = make_node_id(type1, cluster1)
                target_id = make_node_id(type2, cluster2)
                if source_id == target_id and road_distance == 0.0:
                    omitted_zero_self_edges += 1
                    continue

                # Treat road distances as metres: a 1 m floor makes the decay
                # dimensionless, finite at d=0, and at most one. The floor
                # affects weight only; retain the exact measured road distance.
                combined_weight = economic_weight * (max(road_distance, 1.0) ** -decay_lambda)
                if combined_weight == 0.0:
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
                    road_path=road_path,
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
            edge_data = [
                [str(source), str(target), dict(data)]
                for source, target, data in graph.out_edges(source_ids, data=True)
            ]
            savepoints.save(unit, {"edges.json": json.dumps({
                "source_type": type1,
                "edges": edge_data,
                "diagnostics": diagnostics[diagnostic_start:],
                "omitted_zero_self_edges": omitted_zero_self_edges - omitted_start,
            }, default=checkpoint_value, sort_keys=True, separators=(",", ":")).encode("utf-8")})
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

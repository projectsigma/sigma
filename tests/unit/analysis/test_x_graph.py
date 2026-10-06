from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from sigma.analysis import AnalysisPipeline, instantiate_network, make_node_id
from sigma.transport.network import RoadNetwork


def _legacy_fixture():
    roads = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (20, 0)])], crs="EPSG:3857")
    seed = gpd.GeoDataFrame(geometry=[Point(2, 0), Point(18, 0)], crs=roads.crs)
    base = RoadNetwork.from_geodataframe(roads)
    augmented = base.augment(base.snap(seed))
    centers = gpd.GeoDataFrame(
        {"type": ["A", "B"], "cluster": [0, 0], "center_network_node": augmented.point_node},
        geometry=[Point(2, 0), Point(18, 0)],
        crs=roads.crs,
    )
    partitions = gpd.GeoDataFrame(
        {"type": ["A", "B"], "cluster": [0, 0]},
        geometry=[box(0, -2, 20, 2), box(0, -2, 20, 2)],
        crs=roads.crs,
    )
    return augmented, centers, partitions


def test_legacy_mwas_dag_input_reproduces_c0_x_edge_fixture():
    road, centers, partitions = _legacy_fixture()
    economic = nx.DiGraph()
    economic.add_edge("A", "B", weight=3.0)

    graph, diagnostics = instantiate_network(centers, partitions, economic, road)
    edges, paths = AnalysisPipeline._edge_outputs(graph, road)
    golden = json.loads(Path("tests/golden/engine/x_score_output_fixture.json").read_text())

    assert edges.to_dict("records") == golden["x_edges"]
    assert list(paths.columns) == [
        "from_id", "from_type", "from_cluster", "to_id", "to_type", "to_cluster",
        "source_type", "source_cluster", "target_type", "target_cluster",
        "technical_coefficient", "road_distance", "edge_weight", "geometry",
    ]
    assert list(edges.columns) == golden["x_edge_columns"]
    assert diagnostics.empty
    assert graph[make_node_id("A", 0)][make_node_id("B", 0)]["weight"] == 48.0


def test_reciprocal_economic_edges_generate_reciprocal_x_edges_and_cycle():
    road, centers, partitions = _legacy_fixture()
    economic = nx.DiGraph()
    economic.add_edge("A", "B", technical_coefficient=3.0, weight=3.0)
    economic.add_edge("B", "A", technical_coefficient=2.0, weight=2.0)

    graph, diagnostics = instantiate_network(centers, partitions, economic, road)
    a = make_node_id("A", 0)
    b = make_node_id("B", 0)
    assert set(graph.edges) == {(a, b), (b, a)}
    assert graph[a][b]["road_distance"] == 16.0
    assert graph[b][a]["road_distance"] == 16.0
    assert graph[a][b]["weight"] == 48.0
    assert graph[b][a]["weight"] == 32.0
    assert not nx.is_directed_acyclic_graph(graph)
    assert diagnostics.empty


def test_positive_economic_self_use_is_retained_upstream_but_zero_distance_x_self_edge_is_omitted():
    road, centers, partitions = _legacy_fixture()
    centers = centers.iloc[[0]].copy()
    partitions = partitions.iloc[[0]].copy()
    economic = nx.DiGraph()
    economic.add_edge("A", "A", technical_coefficient=0.25, weight=0.25)

    graph, diagnostics = instantiate_network(centers, partitions, economic, road)
    assert graph.number_of_nodes() == 1
    assert graph.number_of_edges() == 0
    assert graph.graph["zero_distance_self_edges_omitted"] == 1
    assert diagnostics.empty


def test_targeted_distance_batching_is_preserved_without_full_distance_materialization():
    centers = gpd.GeoDataFrame(
        {
            "type": ["A", "A", "B", "C"],
            "cluster": [0, 1, 0, 0],
            "center_network_node": [10, 10, 20, 30],
        },
        geometry=[Point(1, 0), Point(9, 0), Point(5, 0), Point(5, 0)],
        crs="EPSG:3857",
    )
    partitions = gpd.GeoDataFrame(
        {"type": ["A", "A", "B", "C"], "cluster": [0, 1, 0, 0]},
        geometry=[box(0, 0, 5, 10), box(5, 0, 10, 10), box(0, 0, 10, 10), box(0, 0, 10, 10)],
        crs="EPSG:3857",
    )
    economic = nx.DiGraph()
    economic.add_edge("A", "B", weight=2.0)
    economic.add_edge("A", "C", weight=3.0)

    class TargetOnlyRoad:
        def __init__(self):
            self.calls = []

        def distances_to_targets(self, source, targets):
            targets = list(map(int, targets))
            self.calls.append((int(source), tuple(targets)))
            return np.abs(np.asarray(targets, dtype=float) - float(source))

        def distances_from(self, source):  # pragma: no cover
            raise AssertionError("X must not materialize full distance dictionaries")

    road = TargetOnlyRoad()
    graph, diagnostics = instantiate_network(centers, partitions, economic, road)
    assert len(road.calls) == 1
    assert road.calls[0][0] == 10
    assert sorted(road.calls[0][1]) == [20, 20, 30, 30]
    assert graph.number_of_edges() == 4
    assert diagnostics.empty


def test_disconnected_positive_overlap_is_audited_and_not_instantiated():
    _, centers, partitions = _legacy_fixture()
    economic = nx.DiGraph()
    economic.add_edge("A", "B", weight=1.0)

    class DisconnectedRoad:
        def shortest_paths_to_targets(self, source, targets):
            return np.full(len(targets), np.inf), [None] * len(targets)

    graph, diagnostics = instantiate_network(centers, partitions, economic, DisconnectedRoad())
    assert graph.number_of_edges() == 0
    assert diagnostics.to_dict("records") == [
        {"type1": "A", "cluster1": 0, "type2": "B", "cluster2": 0, "status": "disconnected_centers"}
    ]


def test_spatial_types_must_belong_to_economic_graph():
    road, centers, partitions = _legacy_fixture()
    economic = nx.DiGraph()
    economic.add_node("A")
    with pytest.raises(ValueError, match="outside the economic graph"):
        instantiate_network(centers, partitions, economic, road)

"""X weights must weaken with road distance, and Katz centrality must show it.

A fixture in which every road distance is equal cannot detect the direction of
the distance factor: SIGMA sets alpha = 0.85 / rho(W), so multiplying every X
weight by one number leaves the Katz scores unchanged, and a * d and a / d then
rank clusters identically. This fixture is the four-cluster example of the
Under the Hood tutorial, with three different road distances.
"""
from __future__ import annotations

import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import LineString, Point, box

from sigma.analysis import balanced_katz_centrality, instantiate_network, make_node_id
from sigma.transport.network import RoadNetwork

# Centers on one straight road, in metres. Road distances between clusters whose
# partitions overlap: F1-R1 600 m, F1-R2 1,400 m, F2-R2 500 m. F2 and R1 do not overlap.
POSITIONS = {("F", 1): 0.0, ("R", 1): 600.0, ("R", 2): -1400.0, ("F", 2): -1900.0}
PARTITIONS = {
    ("F", 1): box(-800, -50, 300, 50),
    ("R", 1): box(200, -50, 900, 50),
    ("R", 2): box(-1700, -50, -100, 50),
    ("F", 2): box(-2200, -50, -1600, 50),
}
F1, F2 = make_node_id("F", 1), make_node_id("F", 2)
R1, R2 = make_node_id("R", 1), make_node_id("R", 2)


def _tutorial_x(**kwargs) -> nx.DiGraph:
    keys = list(POSITIONS)
    crs = "EPSG:3857"
    roads = gpd.GeoDataFrame(geometry=[LineString([(-2500, 0), (1000, 0)])], crs=crs)
    points = [Point(POSITIONS[key], 0) for key in keys]
    base = RoadNetwork.from_geodataframe(roads)
    road = base.augment(base.snap(gpd.GeoDataFrame(geometry=points, crs=crs)))
    centers = gpd.GeoDataFrame(
        {
            "type": [kind for kind, _ in keys],
            "cluster": [cluster for _, cluster in keys],
            "center_network_node": road.point_node,
        },
        geometry=points,
        crs=crs,
    )
    partitions = gpd.GeoDataFrame(
        {"type": [kind for kind, _ in keys], "cluster": [cluster for _, cluster in keys]},
        geometry=[PARTITIONS[key] for key in keys],
        crs=crs,
    )
    economic = nx.DiGraph()
    economic.add_edge("F", "R", weight=0.20)  # Food -> Retail
    economic.add_edge("R", "F", weight=0.10)  # Retail -> Food
    graph, diagnostics = instantiate_network(centers, partitions, economic, road, **kwargs)
    assert diagnostics.empty
    return graph


def test_tutorial_fixture_has_three_different_road_distances():
    graph = _tutorial_x()
    distances = {(u, v): data["road_distance"] for u, v, data in graph.edges(data=True)}
    assert distances == pytest.approx(
        {
            (F1, R1): 600.0, (R1, F1): 600.0,
            (F1, R2): 1400.0, (R2, F1): 1400.0,
            (F2, R2): 500.0, (R2, F2): 500.0,
        }
    )


def test_equal_coefficient_shorter_route_has_larger_x_weight():
    graph = _tutorial_x()
    # All three Food -> Retail edges carry a = 0.20; only road distance differs.
    assert graph[F2][R2]["weight"] == pytest.approx(0.20 / 500.0)
    assert graph[F2][R2]["weight"] > graph[F1][R1]["weight"] > graph[F1][R2]["weight"]


def test_larger_decay_exponent_moves_relative_weight_to_shorter_routes():
    for exponent in (0.0, 1.0, 2.0):
        graph = _tutorial_x(x_distance_decay_lambda=exponent)
        ratio = graph[F2][R2]["weight"] / graph[F1][R2]["weight"]
        assert ratio == pytest.approx((1400.0 / 500.0) ** exponent)


def test_katz_ranking_follows_inverse_distance_not_multiplied_distance():
    graph = _tutorial_x()
    new = balanced_katz_centrality(graph).values
    assert sorted(new, key=new.get, reverse=True) == [R2, F2, F1, R1]

    # Control: the same topology with the historical weight a * d ranks F2 last.
    # If this fails, the fixture no longer distinguishes the two kernels.
    historical = nx.DiGraph()
    for u, v, data in graph.edges(data=True):
        historical.add_edge(u, v, weight=data["technical_coefficient"] * data["road_distance"])
    old = balanced_katz_centrality(historical).values
    assert min(old, key=old.get) == F2
    assert old[F2] < old[F1] and new[F2] > new[F1]

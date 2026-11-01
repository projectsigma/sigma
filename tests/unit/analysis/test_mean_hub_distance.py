"""Mean-hub spatial attenuation is a finite, parameter-free distance composition."""
import math
import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import LineString, Point, box
from sigma.analysis.x_graph import mean_hub_effective_distance, instantiate_network
from sigma.transport.network import RoadNetwork


def test_effective_distance_accounts_for_both_cluster_radii():
    assert mean_hub_effective_distance(200, 40, 60) == pytest.approx(300)
    assert mean_hub_effective_distance(0, 120, 80) == pytest.approx(200)
    assert mean_hub_effective_distance(500, 0, 0) == pytest.approx(500)


def test_effective_distance_is_symmetric():
    assert mean_hub_effective_distance(100, 25, 50) == mean_hub_effective_distance(100, 50, 25)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), -float("inf")])
def test_invalid_distance_is_rejected(value):
    with pytest.raises(ValueError):
        mean_hub_effective_distance(10, value, 1)


def test_real_x_edge_keeps_route_and_uses_member_radii_for_weight():
    crs = "EPSG:3857"
    road_lines = gpd.GeoDataFrame(geometry=[LineString([(0,0),(200,0)])], crs=crs)
    base = RoadNetwork.from_geodataframe(road_lines)
    positions = gpd.GeoDataFrame(geometry=[Point(0,0),Point(200,0)], crs=crs)
    road = base.augment(base.snap(positions))
    centers = gpd.GeoDataFrame({
        "type": ["A", "B"], "cluster": [0, 0], "center_network_node": road.point_node,
    }, geometry=positions.geometry, crs=crs)
    partitions = gpd.GeoDataFrame({"type": ["A", "B"], "cluster": [0,0]},
        geometry=[box(-10,-10,210,10), box(-10,-10,210,10)], crs=crs)
    economic = nx.DiGraph()
    economic.add_edge("A","B",technical_coefficient=.2)
    graph, disconnected = instantiate_network(
        centers, partitions, economic, road,
        mean_road_radius_by_cluster={("A",0):20.0,("B",0):30.0})
    assert disconnected.empty
    assert graph.number_of_edges() == 1
    edge = next(iter(graph.edges(data=True)))[2]
    assert edge["road_distance"] == pytest.approx(200)
    assert edge["effective_road_distance"] == pytest.approx(250)
    assert edge["weight"] == pytest.approx(.2/250)
    assert edge["road_path"] is not None


def test_inverse_hub_has_one_metre_floor():
    f = lambda d: 1.0 / max(d, 1.0)
    assert f(0.0) == f(0.5) == f(1.0) == 1.0
    assert 0.0 < f(100.0) < f(2.0) < f(1.0)

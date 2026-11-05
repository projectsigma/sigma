"""V4: numerical X needs distances, not shortest-path predecessor arrays."""

import networkx as nx
import numpy as np
import geopandas as gpd
from shapely.geometry import Point, box

from sigma.analysis.x_graph import instantiate_network
from sigma.analysis.pipeline import AnalysisPipeline


class DistanceOnlyRoad:
    def __init__(self):
        self.calls = []

    def distances_to_targets(self, source, targets):
        self.calls.append((int(source), tuple(int(x) for x in targets)))
        return np.array([10.0 if int(t) != int(source) else 0.0 for t in targets], dtype=float)

    def shortest_route_nodes_to_targets(self, source, targets):
        raise AssertionError("Numerical X must not request predecessor paths")


def test_numeric_x_has_no_route_nodes_and_preserves_edge_fields():
    crs = "EPSG:32651"
    centers = gpd.GeoDataFrame(
        {"type": ["A", "B"], "cluster": [0, 0], "center_network_node": [0, 1]},
        geometry=[Point(0, 0), Point(10, 0)], crs=crs)
    partitions = gpd.GeoDataFrame(
        {"type": ["A", "B"], "cluster": [0, 0]},
        geometry=[box(-1, -1, 11, 2), box(-1, -1, 11, 2)], crs=crs)
    economy = nx.DiGraph()
    economy.add_edge("A", "B", technical_coefficient=0.6)
    road = DistanceOnlyRoad()
    graph, disconnected = instantiate_network(
        centers, partitions, economy, road, include_paths=False,
        mean_road_radius_by_cluster={("A", 0): 2.0, ("B", 0): 3.0},
        cluster_sector_shares={("A", 0): 1.0, ("B", 0): 1.0})
    assert disconnected.empty
    assert graph.number_of_edges() == 1
    source, target, info = next(iter(graph.edges(data=True)))
    assert "route_nodes" not in info
    assert info["road_distance"] == 10
    assert info["effective_road_distance"] == 15
    assert np.isclose(info["weight"], 0.6 / 15.0)
    assert road.calls == [(0, (1,))]
    table, paths = AnalysisPipeline._numeric_edge_outputs(graph)
    assert paths.empty
    assert len(table) == 1
    assert table["road_distance"].iloc[0] == 10
    assert np.isclose(table["edge_weight"].iloc[0], info["weight"])

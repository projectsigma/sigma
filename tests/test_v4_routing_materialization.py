"""V4 optional route materialization: no numeric X recomputation."""
import networkx as nx
import numpy as np
import geopandas as gpd
import pytest
from shapely.geometry import LineString

from sigma.export.routing_geometry import materialize_x_paths


class MockRoad:
    def __init__(self, distance=10.0):
        self.distance = distance
    def shortest_route_nodes_to_targets(self, source, targets):
        assert int(source) == 0
        assert list(targets) == [1]
        return np.array([self.distance]), [np.array([0, 1], dtype=np.int32)]


class MockAnalysis:
    def _edge_outputs(self, graph, road):
        assert graph.edges['a', 'b']['route_nodes'].tolist() == [0, 1]
        assert graph.edges['a', 'b']['weight'] == 0.42
        return None, gpd.GeoDataFrame({'from_id':['a'], 'to_id':['b']},
            geometry=[LineString([(0, 0), (1, 0)])], crs='EPSG:4326')


def _graph():
    graph=nx.DiGraph()
    graph.add_node('a',center_network_node=0)
    graph.add_node('b',center_network_node=1)
    graph.add_edge('a','b',road_distance=10.0,weight=0.42)
    return graph


def test_precomputed_paths_built_downstream_from_numeric_x():
    graph=_graph()
    output=materialize_x_paths(MockAnalysis(), graph, MockRoad())
    assert len(output)==1
    assert graph.edges['a','b']['weight']==0.42


def test_precomputed_path_distance_mismatch_refused():
    with pytest.raises(ValueError, match='distance differs'):
        materialize_x_paths(MockAnalysis(), _graph(), MockRoad(distance=11.0))

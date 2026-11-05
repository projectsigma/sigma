"""Privacy and distance parity for center-only SIGMA browser road graph."""
from types import SimpleNamespace
import struct

import geopandas as gpd
import numpy as np
import pytest
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString, Point

from sigma.web.routing_binary import MAGIC, write_browser_routing_graph


def _sample():
    # Base road: 0---1---2. Snapped establishments 3 and 5 are NOT centers;
    # vertex 4 is a published cluster center, deliberately between the snaps.
    coords = [(500000,1500000), (500100,1500000), (500200,1500000),
              (500025,1500000), (500050,1500000), (500075,1500000)]
    ends = [(0,3), (3,4), (4,5), (5,1), (1,2)]
    lengths = [25.,25.,25.,25.,100.]
    parent = [0,0,0,0,1]
    crs = 'EPSG:32651'
    nodes = gpd.GeoDataFrame({'network_node': list(range(len(coords)))},
                             geometry=[Point(x,y) for x,y in coords], crs=crs)
    edges = gpd.GeoDataFrame({
        'aug_edge_id': list(range(len(ends))),
        'parent_edge_id': parent,
        'u': [a for a,b in ends], 'v': [b for a,b in ends],
        'length': lengths},
        geometry=[LineString([coords[a],coords[b]]) for a,b in ends], crs=crs)
    return SimpleNamespace(nodes=nodes, edges=edges, crs=crs)


def test_center_only_graph_private_and_exact(tmp_path):
    road = _sample()
    mapping = write_browser_routing_graph(road, tmp_path / 'graph.bin', center_nodes=[4,2])
    data = (tmp_path / 'graph.bin').read_bytes()
    assert data[:8] == MAGIC
    n,m = struct.unpack_from('<II',data,8)
    assert (n,m) == (4,3)  # 0,1,2,4; establishment-only 3/5 eliminated
    assert len(data) == 16+16*n+16*m
    assert len(set(mapping.values())) == 2
    assert np.isfinite(np.frombuffer(data, dtype='<f8', count=n*2, offset=16)).all()
    edge_list = [struct.unpack_from('<IId', data, 16+16*n+i*16) for i in range(m)]
    sparse = coo_matrix((np.array([w for _,_,w in edge_list]*2),
       (np.array([a for a,b,w in edge_list]+[b for a,b,w in edge_list]),
        np.array([b for a,b,w in edge_list]+[a for a,b,w in edge_list]))),shape=(n,n)).tocsr()
    assert dijkstra(sparse,directed=False,indices=mapping[4])[mapping[2]] == 150.0
    assert dijkstra(sparse,directed=False,indices=mapping[2])[mapping[4]] == 150.0
    # All surviving internal routing nodes are original street vertices or the center.
    # WGS84 coordinates are unique and there are only four such positions.
    xy = np.frombuffer(data,dtype='<f8',count=n*2,offset=16).reshape(-1,2)
    assert len(np.unique(xy,axis=0)) == 4


def test_reject_bent_split_chain(tmp_path):
    road = _sample()
    road.nodes.at[4,'geometry'] = Point(500050,1500002)
    road.edges.at[1,'geometry'] = LineString([(500025,1500000),(500050,1500002)])
    road.edges.at[2,'geometry'] = LineString([(500050,1500002),(500075,1500000)])
    with pytest.raises(ValueError,match='bent'):
        write_browser_routing_graph(road,tmp_path/'invalid.bin',center_nodes=[4,2])
    assert not (tmp_path/'invalid.bin').exists()


def test_reject_unknown_center(tmp_path):
    with pytest.raises(ValueError,match='invalid X'):
        write_browser_routing_graph(_sample(),tmp_path/'invalid.bin',center_nodes=[9999])

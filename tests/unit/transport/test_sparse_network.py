import numpy as np
from shapely.geometry import LineString

from sigma.transport._sparse_network import (
    build_network_graph,
    distinct_positions,
    neighbor_graph,
    snap_points,
)


def _line_graph():
    return build_network_graph([LineString([(0, 0), (10, 0), (20, 0)])])


def test_sparse_graph_build_and_snap_are_deterministic():
    graph = _line_graph()
    assert graph.n_vertices == 3
    assert graph.n_arcs == 2
    assert graph.n_components == 1
    assert graph.arc_u.tolist() == [0, 1]
    assert graph.arc_v.tolist() == [1, 2]
    assert graph.arc_length.tolist() == [10.0, 10.0]

    xy = np.array([[2.0, 1.0], [8.0, -1.0], [12.0, 2.0], [18.0, 0.0]])
    snaps = snap_points(graph, xy)
    assert snaps.snap_distance.tolist() == [1.0, 1.0, 2.0, 0.0]
    assert snaps.snapped_xy.tolist() == [[2.0, 0.0], [8.0, 0.0], [12.0, 0.0], [18.0, 0.0]]


def test_distinct_positions_and_neighbor_graph_use_network_distance():
    graph = _line_graph()
    xy = np.array([[2.0, 0.0], [8.0, 0.0], [12.0, 0.0], [18.0, 0.0]])
    snaps = snap_points(graph, xy)
    position, representative = distinct_positions(snaps)
    assert position.tolist() == [0, 1, 2, 3]
    assert representative.tolist() == [0, 1, 2, 3]

    unique = snaps.subset(representative)
    neighbors = neighbor_graph(graph, unique, max_distance=6.0)
    dense = neighbors.toarray()
    expected = np.array(
        [
            [0.0, 6.0, 0.0, 0.0],
            [6.0, 0.0, 4.0, 0.0],
            [0.0, 4.0, 0.0, 6.0],
            [0.0, 0.0, 6.0, 0.0],
        ]
    )
    np.testing.assert_allclose(dense, expected)

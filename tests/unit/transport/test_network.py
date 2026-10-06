import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, Point

from sigma.transport._sparse_network import DEFAULT_VERTEX_DIGITS, build_network_graph
from sigma.transport.network import AugmentedNetwork, RoadNetwork


def test_continuous_snap_and_distance():
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
        crs="EPSG:3857",
    )
    points = gpd.GeoDataFrame(geometry=[Point(2, 1), Point(18, -1)], crs=roads.crs)
    base = RoadNetwork.from_geodataframe(roads)
    snapped = base.snap(points)
    aug = base.augment(snapped)
    a, b = aug.point_node
    assert abs(aug.distance(int(a), int(b)) - 16.0) < 1e-9
    assert snapped.frame.snap_distance.tolist() == [1.0, 1.0]


def test_duplicate_reversed_road_arcs_are_collapsed_and_snap_ties_are_stable():
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (0, 0)])],
        crs="EPSG:3857",
    )
    network = RoadNetwork.from_geodataframe(roads)
    assert len(network.segments) == 1
    points = gpd.GeoDataFrame(geometry=[Point(5, 1)], crs=roads.crs)
    snapped = network.snap(points)
    assert int(snapped.frame.iloc[0].edge_id) == 0


def test_reversing_source_line_does_not_change_augmented_network_state():
    points = gpd.GeoDataFrame(
        geometry=[Point(2, 0), Point(8, 0)],
        crs="EPSG:3857",
    )
    forward = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0)])],
        crs=points.crs,
    )
    reverse = gpd.GeoDataFrame(
        geometry=[LineString([(10, 0), (0, 0)])],
        crs=points.crs,
    )

    net1 = RoadNetwork.from_geodataframe(forward)
    aug1 = net1.augment(net1.snap(points))
    net2 = RoadNetwork.from_geodataframe(reverse)
    aug2 = net2.augment(net2.snap(points))

    assert aug1.nodes.geometry.tolist() == aug2.nodes.geometry.tolist()
    assert aug1.point_node.tolist() == aug2.point_node.tolist()
    assert aug1.edges[["u", "v", "length"]].to_records(index=False).tolist() == (
        aug2.edges[["u", "v", "length"]].to_records(index=False).tolist()
    )


def test_augmented_network_checkpoint_frame_round_trip_preserves_distances():
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
        crs="EPSG:3857",
    )
    points = gpd.GeoDataFrame(geometry=[Point(2, 0), Point(18, 0)], crs=roads.crs)
    base = RoadNetwork.from_geodataframe(roads)
    original = base.augment(base.snap(points))

    restored = AugmentedNetwork.from_checkpoint_frames(
        original.nodes.copy(), original.edges.copy(), original.point_node.copy()
    )

    assert restored.graph.number_of_nodes() == original.graph.number_of_nodes()
    assert restored.graph.number_of_edges() == original.graph.number_of_edges()
    assert restored.point_node.tolist() == original.point_node.tolist()
    source, target = map(int, restored.point_node)
    assert restored.distance(source, target) == original.distance(source, target)


def test_distances_to_targets_and_shortest_path_geometry_are_exact():
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0), (20, 0)])],
        crs="EPSG:3857",
    )
    points = gpd.GeoDataFrame(
        geometry=[Point(2, 0), Point(12, 0), Point(18, 0)], crs=roads.crs
    )
    base = RoadNetwork.from_geodataframe(roads)
    aug = base.augment(base.snap(points))
    source = int(aug.point_node[0])
    targets = np.asarray(aug.point_node[1:], dtype=np.int64)

    distances = aug.distances_to_targets(source, targets)
    path_distances, paths = aug.shortest_paths_to_targets(source, targets)

    assert distances.tolist() == [10.0, 16.0]
    assert path_distances.tolist() == distances.tolist()
    for distance, path in zip(path_distances, paths, strict=True):
        assert path is not None
        geometry = aug.path_geometry(path)
        assert abs(float(geometry.length) - float(distance)) < 1e-9


def test_legacy_builder_uses_significant_vertex_digits_like_sparse_builder():
    roads = gpd.GeoDataFrame(
        geometry=[
            LineString([(285000.0, 1600000.0), (285010.0, 1600000.0)]),
            LineString([(285010.0000001, 1600000.0), (285020.0, 1600000.0)]),
        ],
        crs="EPSG:32651",
    )
    base = RoadNetwork.from_geodataframe(roads, vertex_digits=11)
    assert len(base.nodes) == 3
    assert base.graph.number_of_nodes() == 3


def test_vertex_digits_requires_at_least_one_significant_digit():
    roads = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (10, 0)])], crs="EPSG:3857")
    for digits in (0, 16):
        try:
            RoadNetwork.from_geodataframe(roads, vertex_digits=digits)
        except ValueError as exc:
            assert "between 1 and 15 significant digits" in str(exc)
        else:
            raise AssertionError(f"vertex_digits={digits} was accepted")


def test_legacy_builder_rounds_every_vertex_of_a_line_with_the_sparse_rule():
    from sigma.transport._sparse_network import round_significant

    coordinates = [
        (285000.123456789, 1600000.987654321),
        (285040.5, 1600000.25),
        (285080.75, 1600030.125),
    ]
    roads = gpd.GeoDataFrame(geometry=[LineString(coordinates)], crs="EPSG:32651")
    base = RoadNetwork.from_geodataframe(roads, vertex_digits=9)
    expected = {tuple(xy) for xy in round_significant(np.asarray(coordinates), 9).tolist()}
    assert set(zip(base.nodes.geometry.x, base.nodes.geometry.y, strict=True)) == expected
    assert expected != set(coordinates)


def test_network_builders_share_vertex_digit_validation_and_default():
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(285000.0, 1600000.0), (285010.0, 1600000.0)])],
        crs="EPSG:32651",
    )
    base = RoadNetwork.from_geodataframe(roads)
    assert base.vertex_digits == DEFAULT_VERTEX_DIGITS == 11

    for digits in (0, 16):
        with pytest.raises(ValueError, match="between 1 and 15 significant digits"):
            RoadNetwork.from_geodataframe(roads, vertex_digits=digits)
        with pytest.raises(ValueError, match="between 1 and 15 significant digits"):
            build_network_graph(roads.geometry.to_numpy(), vertex_digits=digits)

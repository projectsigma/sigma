import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point

from sigma.transport._sparse_solver import SparseRoadSolver
from sigma.transport.network import RoadNetwork


def _augmented_line():
    roads = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0), (20, 0)])], crs="EPSG:3857"
    )
    points = gpd.GeoDataFrame(
        geometry=[Point(2, 0), Point(8, 0), Point(18, 0)], crs=roads.crs
    )
    base = RoadNetwork.from_geodataframe(roads)
    return base.augment(base.snap(points))


def test_sparse_solver_distance_and_distances_from_match_augmented_network():
    aug = _augmented_line()
    solver = SparseRoadSolver.from_augmented(aug)
    source, middle, target = map(int, aug.point_node)

    assert solver.distance(source, middle) == aug.distance(source, middle) == 6.0
    assert solver.distance(source, target) == aug.distance(source, target) == 16.0
    assert solver.distances_from(source, cutoff=6.0) == aug.distances_from(source, cutoff=6.0)


def test_sparse_solver_one_median_and_point_distances_are_exact():
    aug = _augmented_line()
    solver = SparseRoadSolver.from_augmented(aug)
    demand = np.asarray(aug.point_node, dtype=np.int64)

    median, objective = solver.one_median(demand)
    assert median == int(aug.point_node[1])
    assert objective == 16.0

    centers = np.full(len(demand), median, dtype=np.int64)
    distances = solver.point_distances_from_centers(demand, centers)
    np.testing.assert_allclose(distances, [6.0, 0.0, 10.0])

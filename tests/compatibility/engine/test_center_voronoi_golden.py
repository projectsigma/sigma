"""Selected C0 center/Voronoi golden contracts for the migrated C2c implementation."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point, box

from sigma.spatial.center import cluster_centers
from sigma.spatial.clustering import ClusteringConfig, cluster_by_type, prepare_sparse_context, retained_points
from sigma.spatial.voronoi import all_surface_partitions
from sigma.transport.network import RoadNetwork, SnappedPoints


def _retained_augmented_fixture():
    roads = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (100, 0)])], crs="EPSG:3857")
    xs = [1, 2, 3, 4, 5, 95, 96, 97, 98, 99]
    points = gpd.GeoDataFrame(
        {
            "canonical_id": [f"p{i}" for i in range(len(xs))],
            "canonical_name": [f"P{i}" for i in range(len(xs))],
            "type": ["A"] * len(xs),
        },
        geometry=[Point(x, 0) for x in xs],
        crs=roads.crs,
    )
    context = prepare_sparse_context(roads, points)
    clustered = cluster_by_type(
        points,
        context,
        ClusteringConfig(min_cluster_size=3, min_samples=2),
        continue_on_error=False,
    )
    retained = retained_points(clustered)

    source_pos = retained["_sparse_source_pos"].to_numpy(np.int64, copy=False)
    road = RoadNetwork.from_sparse_graph(context.graph, roads.crs, vertex_digits=11)
    sparse_snaps = context.snaps.subset(source_pos)
    snapped = SnappedPoints(
        pd.DataFrame(
            {
                "source_pos": np.arange(len(retained), dtype=np.int64),
                "edge_pos": context.edge_id[source_pos],
                "edge_id": context.edge_id[source_pos],
                "offset": sparse_snaps.offset,
                "snap_distance": sparse_snaps.snap_distance,
                "snapped_geometry": list(shapely.points(sparse_snaps.snapped_xy)),
            }
        ),
        road.crs,
    )
    augmented = road.augment(snapped)
    retained = retained.copy().reset_index(drop=True)
    retained["network_node"] = augmented.point_node
    retained["snap_distance"] = snapped.frame["snap_distance"].to_numpy(float)
    retained["network_position"] = snapped.frame["snapped_geometry"].to_numpy()
    retained = retained.drop(columns="_sparse_source_pos")
    return retained, augmented, roads.crs


def test_c0_network_centers_match():
    golden_path = Path(__file__).parents[2] / "golden" / "engine" / "spatial_stage_fixture.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    retained, augmented, _ = _retained_augmented_fixture()

    centers = cluster_centers(retained, augmented, continue_on_error=False)
    actual = [
        {
            "type": str(row.type),
            "cluster": int(row.cluster),
            "center_network_node": int(row.center_network_node),
            "geometry_wkt": row.geometry.wkt,
        }
        for row in centers.itertuples(index=False)
    ]
    assert actual == golden["centers"]


def test_c0_network_partitions_match():
    golden_path = Path(__file__).parents[2] / "golden" / "engine" / "spatial_stage_fixture.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    retained, augmented, crs = _retained_augmented_fixture()
    centers = cluster_centers(retained, augmented, continue_on_error=False)
    boundary = gpd.GeoDataFrame(geometry=[box(0, -5, 100, 5)], crs=crs)

    parts = all_surface_partitions(
        augmented,
        retained,
        boundary,
        resolution=1.0,
        max_cells=5000,
        centers=centers,
        euclidean_fallback=False,
        continue_on_error=False,
    )
    actual = [
        {
            "type": str(row.type),
            "cluster": int(row.cluster),
            "surface_method": str(row.surface_method),
            "surface_seed_method": str(row.surface_seed_method),
            "surface_resolution": float(row.surface_resolution),
            "surface_area": float(row.geometry.area),
            "geometry_bounds": list(row.geometry.bounds),
        }
        for row in parts.itertuples(index=False)
    ]
    assert actual == golden["partitions"]
    assert float(parts.geometry.area.sum()) == golden["partition_area_total"]

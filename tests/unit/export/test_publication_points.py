from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from sigma.export.compatibility import _build_published_points


def test_published_points_keep_one_geometry_and_scalar_cluster_diagnostics():
    scores = gpd.GeoDataFrame(
        {
            "canonical_id": ["a", "b"],
            "canonical_name": ["A", "B"],
            "type": ["1", "1"],
            "cluster": [0, 0],
            "distance_to_cluster_median": [10.0, 20.0],
            "cluster_centrality": [0.5, 0.5],
            "sigma_score": [0.49, 0.48],
        },
        geometry=[Point(121.0, 14.5), Point(121.01, 14.51)],
        crs="EPSG:4326",
    )
    centrality = pd.DataFrame(
        {
            "type": ["1"],
            "cluster": [0],
            "node_id": ["1:0"],
            "in_degree": [2],
            "out_degree": [3],
            "katz_in_raw": [1.2],
            "katz_out_raw": [1.3],
            "centrality": [0.5],
        }
    )
    clustered = gpd.GeoDataFrame(
        {
            "canonical_id": ["a", "b"],
            "membership": [0.9, 0.8],
            "network_position": gpd.GeoSeries(
                [Point(121.0001, 14.5001), Point(121.0101, 14.5101)],
                crs="EPSG:4326",
            ),
        },
        geometry=[Point(121.0, 14.5), Point(121.01, 14.51)],
        crs="EPSG:4326",
    )

    published = _build_published_points(scores, centrality, clustered=clustered)

    assert published.geometry.name == "geometry"
    assert published.crs.to_epsg() == 4326
    assert "network_position" not in published.columns
    assert list(published["membership"]) == [0.9, 0.8]
    assert list(published["katz_in_raw"]) == [1.2, 1.2]
    assert list(published["katz_out_raw"]) == [1.3, 1.3]

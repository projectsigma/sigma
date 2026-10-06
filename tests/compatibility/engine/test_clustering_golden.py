"""Selected C0 clustering golden contract for the migrated C2b implementation."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from sigma.spatial.clustering import ClusteringConfig, cluster_by_type, prepare_sparse_context


def test_c0_cluster_labels_membership_and_network_qa_match():
    golden_path = Path(__file__).parents[2] / "golden" / "engine" / "spatial_stage_fixture.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))["clustered_public"]

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
    got = cluster_by_type(
        points,
        context,
        ClusteringConfig(min_cluster_size=3, min_samples=2),
        continue_on_error=False,
    )

    expected = {
        row["canonical_id"]: (
            row["cluster"],
            row["membership"],
            row["network_component"],
            row["snap_distance_to_network"],
            row["snapped_edge_id"],
        )
        for row in golden
    }
    actual = {
        row.canonical_id: (
            int(row.cluster),
            float(row.membership),
            int(row.network_component),
            float(row.snap_distance_to_network),
            int(row.snapped_edge_id),
        )
        for row in got.itertuples(index=False)
    }
    assert actual == expected

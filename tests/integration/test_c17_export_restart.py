from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from sigma import Economy, SigmaConfig, SigmaWorkspace
from sigma.economy import EconomyPipeline, EconomyRunConfig
from sigma.spatial.restart import align_legacy_restart_points, normalize_restart_points


def test_equivalent_profile_is_explicit_and_uses_legacy_fast_mwas():
    cfg = SigmaConfig.equivalent()
    assert cfg.economic.transaction_preprocessing == "none"
    assert cfg.economic.legacy_mwas_method == "fast"
    assert cfg.spatial.classification == "io80"
    assert SigmaConfig.default().economic.legacy_mwas_method is None


def test_legacy_mwas_graph_is_separate_managed_artifact(tmp_path):
    ws = SigmaWorkspace.create(tmp_path / "ws", area_identity="legacy", source_store=tmp_path / "sources")
    economy = Economy.builtin("io16")
    pipeline = EconomyPipeline(ws, economy=economy, config=EconomyRunConfig(legacy_mwas_method="fast"))
    ref = pipeline.graph()
    assert ref.stage == "economy.graph.legacy_mwas"
    rows = pd.read_csv(ref.path / "io_dag.csv")
    assert len(rows) == 120
    assert set(rows.columns) == {"source_type", "target_type", "transaction_value", "technical_coefficient", "mwas_method"}
    assert set(rows["mwas_method"]) == {"fast"}
    assert ws.artifact("economy.graph") is None


def _restart_frames():
    centers = gpd.GeoDataFrame(
        {"type": ["A", "B"], "cluster": [0, 0], "center_network_node": [999, 999]},
        geometry=[Point(0, 0), Point(10, 0)], crs="EPSG:3857",
    )
    partitions = gpd.GeoDataFrame(
        {"type": ["A", "B"], "cluster": [0, 0]},
        geometry=[Point(0, 0).buffer(2), Point(10, 0).buffer(2)], crs="EPSG:3857",
    )
    points = gpd.GeoDataFrame(
        {
            "canonical_id": ["a", "b", "legacy-extra"],
            "type": ["A", "B", "C"],
            "cluster": [0, 0, 0],
            "network_distance_to_center": [12.5, 3.0, 1.0],
            "point_center_distance_method": ["network_shortest_path"] * 3,
        },
        geometry=[Point(0, 0), Point(10, 0), Point(20, 0)], crs="EPSG:3857",
    )
    return points, centers, partitions


def test_restart_alias_and_legacy_extra_cluster_contract():
    points, centers, partitions = _restart_frames()
    normalized = normalize_restart_points(points)
    assert normalized.loc[0, "distance_to_cluster_median"] == 12.5
    aligned, dropped = align_legacy_restart_points(normalized, centers, partitions)
    assert dropped == 1
    assert list(aligned["type"]) == ["A", "B"]


def test_restart_alias_rejects_unverifiable_distance_method():
    points, _, _ = _restart_frames()
    points["point_center_distance_method"] = "euclidean_fallback"
    with pytest.raises(ValueError, match="non-network distance method"):
        normalize_restart_points(points)

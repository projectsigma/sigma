"""Tests for durable, recipe-scoped SIGMA recovery (no networking required)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from sigma.savepoints import StageSavepoints, CheckpointedRoad


def test_savepoint_is_atomic_verified_and_recipe_scoped(tmp_path: Path):
    store = StageSavepoints(tmp_path, "spatial.partitions", "fingerprint-a")
    assert store.read("type:A") is None
    store.save("type:A", {"audit.json": b'{"rows":2}'})
    assert store.read("type:A") == {"audit.json": b'{"rows":2}'}
    assert StageSavepoints(tmp_path, "spatial.partitions", "fingerprint-b").read("type:A") is None
    assert StageSavepoints(tmp_path, "spatial.clusters", "fingerprint-a").read("type:A") is None
    marker = next(store.root.glob("*.json"))
    assert marker.is_file()
    blob = next(store.root.glob("*.blob"))
    blob.write_bytes(b'corrupt')
    assert store.read("type:A") is None  # hash mismatch forces fresh work
    store.save("type:A", {"audit.json": b'{"rows":3}'})
    assert store.read("type:A") == {"audit.json": b'{"rows":3}'}
    store.clear()
    assert not store.root.exists()


def test_large_file_checkpoint_resume_and_corruption(tmp_path: Path):
    store = StageSavepoints(tmp_path, "export.bundle", "fingerprint")
    source = tmp_path / "source.gpkg"
    source.write_bytes(b'large-geometry-output' * 100)
    store.save_file("geopackage", source)
    restored = tmp_path / "restored.gpkg"
    assert store.restore_file("geopackage", restored)
    assert restored.read_bytes() == source.read_bytes()
    blob = next(store.root.glob("*.blob"))
    blob.write_bytes(b'bad')
    restored.unlink()
    assert not store.restore_file("geopackage", restored)
    assert not restored.exists()


def test_route_geometry_batches_reused_without_geometry_recomputation(tmp_path: Path):
    from sigma.analysis.pipeline import AnalysisPipeline

    graph = nx.DiGraph()
    graph.add_node("a", type="A", cluster=0)
    graph.add_node("b", type="B", cluster=1)
    graph.add_edge("a", "b", technical_coefficient=0.5,
                   road_distance=8., weight=4., road_path=(1, 2))
    class Road:
        crs = "EPSG:4326"
        calls = 0
        def path_geometry(self, path):
            self.calls += 1
            return LineString([(0, 0), (1, 1)])
    store = StageSavepoints(tmp_path, "analysis.x", "recipe")
    road = Road()
    first_edges, first_paths = AnalysisPipeline._edge_outputs(
        graph, CheckpointedRoad(road, graph, store, batch_size=1))
    assert road.calls == 1
    second_edges, second_paths = AnalysisPipeline._edge_outputs(
        graph, CheckpointedRoad(road, graph, store, batch_size=1))
    assert road.calls == 1
    pd.testing.assert_frame_equal(first_edges, second_edges)
    assert first_paths.geometry.iloc[0].equals(second_paths.geometry.iloc[0])


def test_clustering_completed_type_reused(tmp_path: Path, monkeypatch):
    from sigma.spatial import clustering as module
    class Snaps:
        u = np.asarray([0, 1])
        snap_distance = np.zeros(2)
        def __len__(self):
            return len(self.u)
        def subset(self, selected):
            return self
    context = SimpleNamespace(
        graph=SimpleNamespace(component=np.asarray([0, 0])),
        snaps=Snaps(), edge_id=np.asarray([1, 2]))
    points = gpd.GeoDataFrame({"type": ["A", "A"],
        "canonical_id": ["id2", "id1"]},
        geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326")
    calls = []
    def compute(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(labels=np.asarray([7, 7]), membership=np.asarray([0.9, 0.8]),
            summary={"clustering_method": "network_hdbscan", "max_distance": 10.,
                "n_pairs": 1, "distance_status": "complete", "share_core_truncated": 0.0},
            trace=[{"step": 1}])
    monkeypatch.setattr(module, "_run_sparse_hdbscan", compute)
    store = StageSavepoints(tmp_path, "spatial.clusters", "recipe")
    first = module.cluster_by_type(points, context, savepoints=store)
    second = module.cluster_by_type(points, context, savepoints=store)
    assert len(calls) == 1
    assert first["cluster"].tolist() == second["cluster"].tolist()
    assert first["membership"].tolist() == second["membership"].tolist()
    assert first.attrs["clustering_summary"] == second.attrs["clustering_summary"]
    assert first.attrs["clustering_trace"] == second.attrs["clustering_trace"]


def test_voronoi_completed_type_reused(tmp_path: Path, monkeypatch):
    from sigma.spatial import voronoi as module
    points = gpd.GeoDataFrame({"type": ["A"], "cluster": [0]},
                                geometry=[Point(0, 0)], crs="EPSG:3857")
    boundary = gpd.GeoDataFrame(geometry=[Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])],
                                crs="EPSG:3857")
    network = SimpleNamespace(crs="EPSG:3857")
    calls = []
    def compute(*args, **kwargs):
        calls.append(1)
        return gpd.GeoDataFrame({"type": ["A"], "cluster": [0],
                                 "surface_method": ["network"],
                                 "surface_resolution": [1.]},
                  geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])], crs=network.crs)
    monkeypatch.setattr(module, "surface_partition_for_type", compute)
    store = StageSavepoints(tmp_path, "spatial.partitions", "recipe")
    first = module.all_surface_partitions(network, points, boundary, 1.,
                     euclidean_fallback=False, savepoints=store)
    second = module.all_surface_partitions(network, points, boundary, 1.,
                     euclidean_fallback=False, savepoints=store)
    assert len(calls) == 1
    assert first.geometry.iloc[0].equals(second.geometry.iloc[0])


def test_network_x_source_type_restored_without_route_solving(tmp_path: Path):
    from sigma.analysis.x_graph import instantiate_network

    centers = gpd.GeoDataFrame({
        "type": ["A", "B"], "cluster": [0, 0], "center_network_node": [2, 3],
    }, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:3857")
    partitions = gpd.GeoDataFrame({
        "type": ["A", "B"], "cluster": [0, 0],
    }, geometry=[
        Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
        Polygon([(1, 1), (3, 1), (3, 3), (1, 3)]),
    ], crs="EPSG:3857")
    economy = nx.DiGraph()
    economy.add_edge("A", "B", technical_coefficient=0.6, weight=0.6)

    class Road:
        calls = 0
        def shortest_paths_to_targets(self, source_node, targets):
            self.calls += 1
            return np.asarray([5.0] * len(targets)), [
                (int(source_node), int(t)) for t in targets
            ]

    road = Road()
    store = StageSavepoints(tmp_path, "analysis.x", "same-recipe")
    first, diag1 = instantiate_network(centers, partitions, economy, road, savepoints=store)
    assert road.calls == 1
    second, diag2 = instantiate_network(centers, partitions, economy, road, savepoints=store)
    assert road.calls == 1
    assert list(first.edges(data=True)) == list(second.edges(data=True))
    pd.testing.assert_frame_equal(diag1, diag2)

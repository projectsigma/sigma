from __future__ import annotations

import json
from pathlib import Path

from tests.integration.test_c9_spatial_branch import _pipeline, _workspace


def _center_rows(frame):
    return [
        {
            "type": row["type"],
            "cluster": int(row["cluster"]),
            "center_network_node": int(row["center_network_node"]),
            "geometry_wkt": row["geometry"].wkt,
        }
        for row in frame.to_dict("records")
    ]


def _distance_rows(frame):
    return [
        {
            "point_id": row["point_id"],
            "type": row["type"],
            "cluster": int(row["cluster"]),
            "distance_to_cluster_median": float(row["distance_to_cluster_median"]),
            "point_center_distance_method": row["point_center_distance_method"],
            "canonical_id": row.get("canonical_id"),
            "canonical_name": row.get("canonical_name"),
            "geometry_wkt": row["geometry"].wkt,
        }
        for row in frame.to_dict("records")
    ]


def test_c10_centers_and_distances_match_c0_golden(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    distance_ref = pipeline.prepare_point_distances()
    centers = pipeline.read_centers()
    distances = pipeline.read_point_distances(distance_ref)
    golden = json.loads(Path("tests/golden/engine/spatial_stage_fixture.json").read_text())
    assert list(centers.columns) == golden["centers_columns"]
    assert _center_rows(centers) == golden["centers"]
    assert list(distances.columns) == golden["point_distance_columns"]
    assert _distance_rows(distances) == golden["point_distances"]
    assert set(distances["point_center_distance_method"]) == {"network_shortest_path"}


def test_centers_and_distances_reuse_saved_snap_context_without_road_source(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    cluster_ref = pipeline.prepare_clusters()
    (tmp_path / "roads.gpkg").unlink()
    centers = pipeline.prepare_centers()
    distances = pipeline.prepare_point_distances()
    assert centers is not None and distances is not None
    assert pipeline._dependency_ref(centers, "spatial.clusters").artifact_id == cluster_ref.artifact_id
    assert len(pipeline.read_centers()) == 2
    assert len(pipeline.read_point_distances()) == 10


def test_managed_pipeline_uses_euclidean_center_fallback_by_default(monkeypatch, tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)

    import sigma.spatial.center as center

    monkeypatch.setattr(
        center,
        "network_1_median",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic network failure")),
    )
    ref = pipeline.prepare_centers()
    manifest = ws.artifacts.manifest(ref)
    diagnostics = json.loads((ref.path / "center_diagnostics.json").read_text(encoding="utf-8"))
    assert tuple(manifest.metadata["center_methods"]) == ("euclidean_centroid_road_snap_fallback",)
    assert any(
        event["action"] == "fallback_euclidean_centroid_road_snap"
        for event in diagnostics["events"]
    )


def test_identical_rerun_reuses_centers_and_point_distances(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    pipeline.prepare_point_distances()
    first = {s: ws.artifact(s).artifact_id for s in ("spatial.clusters", "spatial.centers", "spatial.point_distances")}
    pipeline.prepare_point_distances()
    second = {s: ws.artifact(s).artifact_id for s in first}
    assert second == first
    tail = {step.stage: step.action for step in pipeline.planner.plan("spatial.point_distances")}
    assert tail["spatial.centers"] == "reuse"
    assert tail["spatial.point_distances"] == "reuse"


def test_cluster_recipe_change_invalidates_centers_and_distances(tmp_path):
    from sigma.spatial import SpatialRunConfig
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    first.prepare_point_distances()
    before = {s: ws.artifact(s).artifact_id for s in ("spatial.points", "spatial.clusters", "spatial.centers", "spatial.point_distances")}
    changed = _pipeline(tmp_path, ws, config=SpatialRunConfig(min_cluster_size=3, min_samples=3))
    changed.prepare_point_distances()
    after = {s: ws.artifact(s).artifact_id for s in before}
    assert after["spatial.points"] == before["spatial.points"]
    assert after["spatial.clusters"] != before["spatial.clusters"]
    assert after["spatial.centers"] != before["spatial.centers"]
    assert after["spatial.point_distances"] != before["spatial.point_distances"]


def test_forced_centers_and_distances_are_deterministic(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    c1 = pipeline.prepare_centers()
    c2 = pipeline.prepare_centers(force=True)
    d1 = pipeline.prepare_point_distances()
    d2 = pipeline.prepare_point_distances(force=True)
    assert c1.artifact_id == c2.artifact_id
    assert d1.artifact_id == d2.artifact_id

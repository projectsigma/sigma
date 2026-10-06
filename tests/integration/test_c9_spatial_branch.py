from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point

from sigma import SigmaWorkspace
from sigma.spatial import SpatialPipeline, SpatialRunConfig
from sigma.spatial.clustering import prepare_sparse_context
from sigma.transport import FileRoadSource


def _write_roads(path: Path, *, y: float = 0.0) -> Path:
    roads = gpd.GeoDataFrame(geometry=[LineString([(0, y), (100, y)])], crs="EPSG:3857")
    roads.to_file(path, layer="roads", driver="GPKG")
    return path


def _write_points(path: Path, *, shifted: bool = False, legacy: bool = False) -> Path:
    xs = [1, 2, 3, 4, 5, 95, 96, 97, 98, 99]
    if shifted:
        xs[0] = 1.5
    data = {
        "canonical_id": [f"p{i}" for i in range(len(xs))],
        "canonical_name": [f"P{i}" for i in range(len(xs))],
    }
    if legacy:
        data["io80_code"] = ["A"] * len(xs)
    else:
        data["economy_code"] = ["A"] * len(xs)
    points = gpd.GeoDataFrame(data, geometry=[Point(x, 0) for x in xs], crs="EPSG:3857")
    points.to_file(path, layer="points", driver="GPKG")
    return path


def _workspace(tmp_path: Path):
    return SigmaWorkspace.create(
        tmp_path / "workspace",
        area_identity="custom-spatial-fixture",
        source_store=tmp_path / "sources",
        output_dir=tmp_path / "output",
    )


def _pipeline(tmp_path: Path, ws, *, legacy: bool = False, config: SpatialRunConfig | None = None):
    roads = tmp_path / "roads.gpkg"
    points = tmp_path / "points.gpkg"
    if not roads.exists():
        _write_roads(roads)
    if not points.exists():
        _write_points(points, legacy=legacy)
    cfg = config or SpatialRunConfig(min_cluster_size=3, min_samples=2)
    if legacy and config is None:
        cfg = SpatialRunConfig(classification="io80", min_cluster_size=3, min_samples=2)
    return SpatialPipeline(
        ws,
        roads=FileRoadSource(roads, "roads"),
        points_path=points,
        points_layer="points",
        config=cfg,
    )


def _row_payload(frame):
    rows = []
    for row in frame.to_dict("records"):
        rows.append({
            "canonical_id": row["canonical_id"],
            "canonical_name": row["canonical_name"],
            "type": row["type"],
            "cluster": int(row["cluster"]),
            "membership": float(row["membership"]),
            "network_component": int(row["network_component"]),
            "snap_distance_to_network": float(row["snap_distance_to_network"]),
            "snapped_edge_id": int(row["snapped_edge_id"]),
            "point_id": row["point_id"],
            "snap_distance": float(row["snap_distance"]),
            "geometry_wkt": row["geometry"].wkt,
            "network_position_wkt": row["network_position"].wkt,
        })
    return rows


def test_canonical_spatial_branch_matches_c0_cluster_fixture_and_persists_exact_snap_context(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    ref = pipeline.prepare_clusters()
    public = pipeline.read_clusters(ref)
    golden = json.loads(Path("tests/golden/engine/spatial_stage_fixture.json").read_text())
    assert _row_payload(public) == golden["clustered_public"]

    points = pipeline.read_points()
    assert points["type"].tolist() == ["A"] * 10
    assert ws.manifest("spatial.points").metadata["classification_column"] == "economy_code"

    saved, meta = pipeline.read_snap_context(ref)
    roads = gpd.read_file(tmp_path / "roads.gpkg", layer="roads")
    direct = prepare_sparse_context(roads, points, vertex_digits=11)
    np.testing.assert_array_equal(saved.graph.vertex_xy, direct.graph.vertex_xy)
    np.testing.assert_array_equal(saved.graph.arc_u, direct.graph.arc_u)
    np.testing.assert_array_equal(saved.graph.arc_v, direct.graph.arc_v)
    np.testing.assert_allclose(saved.snaps.snapped_xy, direct.snaps.snapped_xy, rtol=0, atol=0)
    np.testing.assert_allclose(saved.snaps.snap_distance, direct.snaps.snap_distance, rtol=0, atol=0)
    np.testing.assert_array_equal(saved.edge_id, direct.edge_id)
    assert meta["point_ids"] == [f"p{i}" for i in range(10)]


def test_identical_rerun_reuses_roads_points_and_clusters(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    pipeline.prepare_clusters()
    first = {stage: ws.artifact(stage).artifact_id for stage in ("transport.roads", "spatial.points", "spatial.clusters")}
    pipeline.prepare_clusters()
    second = {stage: ws.artifact(stage).artifact_id for stage in first}
    assert second == first
    assert all(step.action == "reuse" for step in pipeline.planner.plan("spatial.clusters")[-3:])


def test_clustering_parameter_change_reuses_roads_and_points_only(tmp_path):
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    first.prepare_clusters()
    before = {stage: ws.artifact(stage).artifact_id for stage in ("transport.roads", "spatial.points", "spatial.clusters")}

    changed = _pipeline(
        tmp_path,
        ws,
        config=SpatialRunConfig(min_cluster_size=3, min_samples=3),
    )
    changed.prepare_clusters()
    after = {stage: ws.artifact(stage).artifact_id for stage in before}
    assert after["transport.roads"] == before["transport.roads"]
    assert after["spatial.points"] == before["spatial.points"]
    assert after["spatial.clusters"] != before["spatial.clusters"]


def test_point_source_change_reuses_roads_but_invalidates_points_and_clusters(tmp_path):
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    first.prepare_clusters()
    before = {stage: ws.artifact(stage).artifact_id for stage in ("transport.roads", "spatial.points", "spatial.clusters")}

    _write_points(tmp_path / "points.gpkg", shifted=True)
    second = _pipeline(tmp_path, ws)
    second.prepare_clusters()
    after = {stage: ws.artifact(stage).artifact_id for stage in before}
    assert after["transport.roads"] == before["transport.roads"]
    assert after["spatial.points"] != before["spatial.points"]
    assert after["spatial.clusters"] != before["spatial.clusters"]


def test_legacy_io80_input_remains_available_as_explicit_compatibility_mode(tmp_path):
    ws = _workspace(tmp_path)
    _write_roads(tmp_path / "roads.gpkg")
    _write_points(tmp_path / "points.gpkg", legacy=True)
    pipeline = _pipeline(tmp_path, ws, legacy=True)
    pipeline.prepare_clusters()
    assert pipeline.read_points()["type"].tolist() == ["A"] * 10
    assert ws.manifest("spatial.points").metadata["classification_column"] == "io80_code"


def test_max_snap_distance_preserves_engine_rejection(tmp_path):
    ws = _workspace(tmp_path)
    _write_roads(tmp_path / "roads.gpkg", y=10.0)
    _write_points(tmp_path / "points.gpkg")
    pipeline = _pipeline(
        tmp_path,
        ws,
        config=SpatialRunConfig(min_cluster_size=3, min_samples=2, max_snap_distance=5.0),
    )
    import pytest
    with pytest.raises(ValueError, match="exceed max_snap_distance=5"):
        pipeline.prepare_clusters()


def test_forced_same_recipe_is_deterministic_and_reuses_identical_artifact(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    first = pipeline.prepare_clusters()
    second = pipeline.prepare_clusters(force=True)
    assert second.artifact_id == first.artifact_id
    assert second.recipe_fingerprint == first.recipe_fingerprint


def test_road_source_change_invalidates_projection_and_clusters(tmp_path):
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    first.prepare_clusters()
    before = {stage: ws.artifact(stage).artifact_id for stage in ("transport.roads", "spatial.points", "spatial.clusters")}

    # Same path/layer, changed bytes and geometry: SourceStore must issue a new source identity.
    _write_roads(tmp_path / "roads.gpkg", y=1.0)
    second = _pipeline(tmp_path, ws)
    second.prepare_clusters()
    after = {stage: ws.artifact(stage).artifact_id for stage in before}
    assert after["transport.roads"] != before["transport.roads"]
    assert after["spatial.points"] != before["spatial.points"]
    assert after["spatial.clusters"] != before["spatial.clusters"]


def test_old_cluster_ref_reads_its_own_snap_dependency_after_new_points_become_active(tmp_path):
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    old_cluster = first.prepare_clusters()
    old_context, old_meta = first.read_snap_context(old_cluster)

    _write_points(tmp_path / "points.gpkg", shifted=True)
    second = _pipeline(tmp_path, ws)
    second.prepare_clusters()

    restored, meta = second.read_snap_context(old_cluster)
    assert meta["point_ids"] == old_meta["point_ids"]
    np.testing.assert_allclose(restored.snaps.snapped_xy, old_context.snaps.snapped_xy, rtol=0, atol=0)


def test_external_source_mutation_after_registration_fails_instead_of_mislabeling_artifact(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    # Mutate the file after SourceStore registration but before execution.
    _write_points(tmp_path / "points.gpkg", shifted=True)
    import pytest
    with pytest.raises(RuntimeError, match="point source changed after registration"):
        pipeline.planner.ensure("spatial.points")


def test_managed_place_branch_adapts_preserved_poi_id_and_uses_economy_code(tmp_path):
    from tests.integration.test_c8_place_branch import (
        _services as c8_services,
        _synthetic_builtin_taxonomy,
        _workspace as c8_workspace,
    )
    from sigma import Economy
    from sigma.places.pipeline import PlacePipeline

    area, ws = c8_workspace(tmp_path)
    place = PlacePipeline(
        ws,
        area=area,
        services=c8_services(tmp_path, taxonomy=_synthetic_builtin_taxonomy()),
    )
    projected = gpd.GeoSeries([Point(121.0, 14.5)], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
    road_path = tmp_path / "managed_roads.gpkg"
    gpd.GeoDataFrame(
        geometry=[LineString([(projected.x - 100, projected.y), (projected.x + 100, projected.y)])],
        crs="EPSG:3857",
    ).to_file(road_path, layer="roads", driver="GPKG")

    spatial = SpatialPipeline(
        ws,
        roads=FileRoadSource(road_path, "roads"),
        place_pipeline=place,
        economy=Economy.default(),
        config=SpatialRunConfig(min_cluster_size=2, min_samples=2),
    )
    point_ref = spatial.planner.ensure("spatial.points")
    points = spatial.read_points(point_ref)
    assert points.loc[0, "canonical_id"] == points.loc[0, "poi_id"]
    assert points.loc[0, "type"] == "66"
    assert ws.manifest("spatial.points").metadata["classification_column"] == "economy_code"
    assert ws.artifact("places.classified") is not None


def test_spatial_recipe_uses_economy_sector_identity_not_transaction_values(tmp_path):
    import pandas as pd
    from sigma.economy import Economy, Sector, SectorCatalog

    ws = _workspace(tmp_path)
    _write_roads(tmp_path / "roads.gpkg")
    _write_points(tmp_path / "points.gpkg")
    sectors = SectorCatalog([Sector("A", "Alpha")])
    e1 = Economy(
        economy_id="e1",
        sectors=sectors,
        raw_transactions=pd.DataFrame([[1.0]], index=["A"], columns=["A"]),
        total_output=pd.Series([2.0], index=["A"]),
    )
    e2 = Economy(
        economy_id="e2",
        sectors=sectors,
        raw_transactions=pd.DataFrame([[9.0]], index=["A"], columns=["A"]),
        total_output=pd.Series([10.0], index=["A"]),
    )
    first = SpatialPipeline(
        ws,
        roads=FileRoadSource(tmp_path / "roads.gpkg", "roads"),
        points_path=tmp_path / "points.gpkg",
        points_layer="points",
        economy=e1,
        config=SpatialRunConfig(min_cluster_size=3, min_samples=2),
    )
    first.prepare_clusters()
    before = {stage: ws.artifact(stage).artifact_id for stage in ("spatial.points", "spatial.clusters")}
    second = SpatialPipeline(
        ws,
        roads=FileRoadSource(tmp_path / "roads.gpkg", "roads"),
        points_path=tmp_path / "points.gpkg",
        points_layer="points",
        economy=e2,
        config=SpatialRunConfig(min_cluster_size=3, min_samples=2),
    )
    second.prepare_clusters()
    after = {stage: ws.artifact(stage).artifact_id for stage in before}
    assert after == before


def test_spatial_points_reject_codes_outside_selected_economy(tmp_path):
    import pandas as pd
    import pytest
    from sigma.economy import Economy, Sector, SectorCatalog

    ws = _workspace(tmp_path)
    _write_roads(tmp_path / "roads.gpkg")
    _write_points(tmp_path / "points.gpkg")
    economy = Economy(
        economy_id="other",
        sectors=SectorCatalog([Sector("B", "Beta")]),
        raw_transactions=pd.DataFrame([[1.0]], index=["B"], columns=["B"]),
        total_output=pd.Series([2.0], index=["B"]),
    )
    pipeline = SpatialPipeline(
        ws,
        roads=FileRoadSource(tmp_path / "roads.gpkg", "roads"),
        points_path=tmp_path / "points.gpkg",
        points_layer="points",
        economy=economy,
    )
    with pytest.raises(ValueError, match="outside the selected Economy sector catalog"):
        pipeline.planner.ensure("spatial.points")


def test_managed_pipeline_uses_euclidean_clustering_fallback_by_default(monkeypatch, tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)

    import sigma.spatial.clustering as clustering

    monkeypatch.setattr(
        clustering,
        "_run_sparse_hdbscan",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic network failure")),
    )
    ref = pipeline.prepare_clusters()
    audit = json.loads((ref.path / "clustering_audit.json").read_text(encoding="utf-8"))
    assert any(
        event["action"] == "fallback_euclidean_hdbscan" for event in audit["events"]
    )
    assert ws.artifacts.manifest(ref).metadata["fallback_type_count"] >= 1

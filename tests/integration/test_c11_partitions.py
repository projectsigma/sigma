from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from sigma.spatial import SpatialPipeline, SpatialRunConfig
from sigma.transport import FileRoadSource
from tests.integration.test_c9_spatial_branch import _write_points, _write_roads, _workspace


def _write_boundary(path: Path, *, xmax: float = 100.0) -> Path:
    boundary = gpd.GeoDataFrame(
        {"name": ["study"]}, geometry=[box(0, -5, xmax, 5)], crs="EPSG:3857"
    )
    boundary.to_file(path, layer="boundary", driver="GPKG")
    return path


def _pipeline(tmp_path: Path, ws, *, config: SpatialRunConfig | None = None):
    roads = tmp_path / "roads.gpkg"
    points = tmp_path / "points.gpkg"
    boundary = tmp_path / "boundary.gpkg"
    if not roads.exists():
        _write_roads(roads)
    if not points.exists():
        _write_points(points)
    if not boundary.exists():
        _write_boundary(boundary)
    cfg = config or SpatialRunConfig(
        min_cluster_size=3,
        min_samples=2,
        voronoi_resolution=1.0,
        voronoi_max_cells=5000,
    )
    return SpatialPipeline(
        ws,
        roads=FileRoadSource(roads, "roads"),
        points_path=points,
        points_layer="points",
        boundary_path=boundary,
        boundary_layer="boundary",
        config=cfg,
    )


def _partition_payload(frame):
    return [
        {
            "type": str(row.type),
            "cluster": int(row.cluster),
            "geometry_bounds": list(row.geometry.bounds),
            "surface_area": float(row.geometry.area),
        }
        for row in frame.itertuples(index=False)
    ]


def test_c11_managed_partitions_match_engine_c0_geometry_and_public_schema(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    ref = pipeline.prepare_partitions()
    public = pipeline.read_partitions(ref)
    diagnostics = pipeline.read_partition_diagnostics(ref)
    golden = json.loads(Path("tests/golden/engine/spatial_stage_fixture.json").read_text())

    assert list(public.columns) == ["type", "cluster", "geometry"]
    expected_public = [
        {
            "type": row["type"],
            "cluster": row["cluster"],
            "geometry_bounds": row["geometry_bounds"],
            "surface_area": row["surface_area"],
        }
        for row in golden["partitions"]
    ]
    assert _partition_payload(public) == expected_public
    assert float(public.geometry.area.sum()) == golden["partition_area_total"]

    expected_diag = [
        {
            "type": row["type"],
            "cluster": row["cluster"],
            "surface_area": row["surface_area"],
            "surface_resolution": row["surface_resolution"],
            "surface_method": row["surface_method"],
            "surface_seed_method": row["surface_seed_method"],
        }
        for row in golden["partitions"]
    ]
    assert diagnostics["partitions"] == expected_diag
    assert diagnostics["events"] == []


def test_partitions_depend_on_centers_for_default_euclidean_fallback(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    ref = pipeline.prepare_partitions()
    manifest = ws.artifacts.manifest(ref)
    assert set(manifest.recipe.dependencies) == {
        "spatial.clusters",
        "spatial.centers",
        "area.boundary",
    }
    assert ws.artifact("spatial.centers") is not None
    assert ws.artifact("spatial.point_distances") is None


def test_partitions_reuse_exact_cluster_checkpoint_without_original_road_file(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    cluster_ref = pipeline.prepare_clusters()
    (tmp_path / "roads.gpkg").unlink()
    partition_ref = pipeline.prepare_partitions()
    assert pipeline._dependency_ref(partition_ref, "spatial.clusters").artifact_id == cluster_ref.artifact_id
    assert len(pipeline.read_partitions(partition_ref)) == 2


def test_boundary_change_invalidates_boundary_and_partitions_only(tmp_path):
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    first.prepare_centers()
    first.prepare_partitions()
    before = {
        stage: ws.artifact(stage).artifact_id
        for stage in ("spatial.clusters", "spatial.centers", "area.boundary", "spatial.partitions")
    }

    _write_boundary(tmp_path / "boundary.gpkg", xmax=90.0)
    second = _pipeline(tmp_path, ws)
    second.prepare_partitions()
    after = {stage: ws.artifact(stage).artifact_id for stage in before}
    assert after["spatial.clusters"] == before["spatial.clusters"]
    assert after["spatial.centers"] == before["spatial.centers"]
    assert after["area.boundary"] != before["area.boundary"]
    assert after["spatial.partitions"] != before["spatial.partitions"]


def test_voronoi_resolution_change_invalidates_only_partitions(tmp_path):
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    first.prepare_centers()
    first.prepare_partitions()
    before = {
        stage: ws.artifact(stage).artifact_id
        for stage in ("spatial.clusters", "spatial.centers", "area.boundary", "spatial.partitions")
    }
    changed = _pipeline(
        tmp_path,
        ws,
        config=SpatialRunConfig(
            min_cluster_size=3,
            min_samples=2,
            voronoi_resolution=2.0,
            voronoi_max_cells=5000,
        ),
    )
    changed.prepare_partitions()
    after = {stage: ws.artifact(stage).artifact_id for stage in before}
    assert after["spatial.clusters"] == before["spatial.clusters"]
    assert after["spatial.centers"] == before["spatial.centers"]
    assert after["area.boundary"] == before["area.boundary"]
    assert after["spatial.partitions"] != before["spatial.partitions"]


def test_cluster_recipe_change_invalidates_partitions(tmp_path):
    ws = _workspace(tmp_path)
    first = _pipeline(tmp_path, ws)
    first.prepare_partitions()
    before = {
        stage: ws.artifact(stage).artifact_id
        for stage in ("spatial.points", "spatial.clusters", "spatial.partitions")
    }
    changed = _pipeline(
        tmp_path,
        ws,
        config=SpatialRunConfig(
            min_cluster_size=3,
            min_samples=3,
            voronoi_resolution=1.0,
            voronoi_max_cells=5000,
        ),
    )
    changed.prepare_partitions()
    after = {stage: ws.artifact(stage).artifact_id for stage in before}
    assert after["spatial.points"] == before["spatial.points"]
    assert after["spatial.clusters"] != before["spatial.clusters"]
    assert after["spatial.partitions"] != before["spatial.partitions"]


def test_forced_partitions_are_deterministic(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    first = pipeline.prepare_partitions()
    second = pipeline.prepare_partitions(force=True)
    assert second.artifact_id == first.artifact_id


def test_partitions_require_boundary_for_custom_input(tmp_path):
    ws = _workspace(tmp_path)
    _write_roads(tmp_path / "roads.gpkg")
    _write_points(tmp_path / "points.gpkg")
    pipeline = SpatialPipeline(
        ws,
        roads=FileRoadSource(tmp_path / "roads.gpkg", "roads"),
        points_path=tmp_path / "points.gpkg",
        points_layer="points",
        config=SpatialRunConfig(min_cluster_size=3, min_samples=2),
    )
    import pytest
    with pytest.raises(RuntimeError, match="requires a boundary"):
        pipeline.prepare_partitions()


def test_partition_stage_can_skip_one_unrecoverable_cluster_and_continue(monkeypatch, tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)

    import sigma.spatial.pipeline as module
    original = module.all_surface_partitions

    def missing_one(*args, **kwargs):
        frame = original(*args, **kwargs)
        return frame.iloc[:1].copy()

    monkeypatch.setattr(module, "all_surface_partitions", missing_one)
    ref = pipeline.prepare_partitions()
    manifest = ws.artifacts.manifest(ref)
    assert len(pipeline.read_partitions(ref)) == 1
    assert manifest.metadata["requested_cluster_count"] == 2
    assert manifest.metadata["skipped_cluster_count"] == 1


def test_managed_pipeline_uses_euclidean_voronoi_fallback_by_default(monkeypatch, tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)

    import sigma.spatial.voronoi as voronoi

    monkeypatch.setattr(
        voronoi,
        "surface_partition_for_type",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic network failure")),
    )
    ref = pipeline.prepare_partitions()
    diagnostics = pipeline.read_partition_diagnostics(ref)
    assert {row["surface_method"] for row in diagnostics["partitions"]} == {
        "euclidean_voronoi_fallback"
    }
    assert any(event["action"] == "fallback_euclidean_voronoi" for event in diagnostics["events"])


def test_boundary_source_mutation_after_registration_fails_before_partition_execution(tmp_path):
    ws = _workspace(tmp_path)
    pipeline = _pipeline(tmp_path, ws)
    _write_boundary(tmp_path / "boundary.gpkg", xmax=90.0)
    import pytest
    with pytest.raises(RuntimeError, match="boundary source changed after registration"):
        pipeline.prepare_partitions()


def test_managed_place_boundary_artifact_is_consumed_without_duplicate_boundary_parser(tmp_path):
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
    boundary_ref = place.planner.ensure("area.boundary")
    _write_roads(tmp_path / "roads.gpkg")
    spatial = SpatialPipeline(
        ws,
        roads=FileRoadSource(tmp_path / "roads.gpkg", "roads"),
        place_pipeline=place,
        economy=Economy.default(),
        config=SpatialRunConfig(min_cluster_size=2, min_samples=2),
    )
    boundary = spatial._load_boundary_frame(boundary_ref)
    assert str(boundary.crs) == "EPSG:4326"
    assert len(boundary) == 1
    assert boundary.geometry.iloc[0].geom_type in {"Polygon", "MultiPolygon"}

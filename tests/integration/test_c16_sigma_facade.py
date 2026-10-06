from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import geopandas as gpd
import pytest
import pandas as pd
from shapely.geometry import LineString, Point, box

import sigma
from sigma import (
    AnalysisConfig,
    EconomicConfig,
    Economy,
    Sector,
    SectorCatalog,
    Sigma,
    SigmaConfig,
    SpatialConfig,
)
from sigma.errors import CompatibilityError, ConfigurationError


def _economy() -> Economy:
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[2.0, 6.0], [4.0, 2.0]], index=["A", "B"], columns=["A", "B"])
    x = pd.Series([10.0, 10.0], index=["A", "B"])
    return Economy(economy_id="c16-two-sector", sectors=sectors, raw_transactions=z, total_output=x)


def _files(tmp_path: Path):
    roads = tmp_path / "roads.gpkg"
    points = tmp_path / "points.gpkg"
    boundary = tmp_path / "boundary.gpkg"
    gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (20, 0)])], crs="EPSG:3857"
    ).to_file(roads, layer="roads", driver="GPKG")
    xs_a = [1, 2, 3, 4, 5]
    xs_b = [15, 16, 17, 18, 19]
    gpd.GeoDataFrame(
        {
            "canonical_id": [f"a{i}" for i in range(5)] + [f"b{i}" for i in range(5)],
            "canonical_name": [f"A{i}" for i in range(5)] + [f"B{i}" for i in range(5)],
            "economy_code": ["A"] * 5 + ["B"] * 5,
        },
        geometry=[Point(x, 0) for x in xs_a + xs_b],
        crs="EPSG:3857",
    ).to_file(points, layer="points", driver="GPKG")
    gpd.GeoDataFrame(
        {"name": ["study"]}, geometry=[box(0, -2, 20, 2)], crs="EPSG:3857"
    ).to_file(boundary, layer="boundary", driver="GPKG")
    return roads, points, boundary


def _config(*, preprocessing="none", tempering=0.15):
    return SigmaConfig(
        spatial=SpatialConfig(
            min_cluster_size=3,
            min_samples=2,
            allow_single_cluster=True,
            voronoi_resolution=0.5,
            voronoi_max_cells=5000,
        ),
        economic=EconomicConfig(transaction_preprocessing=preprocessing),
        analysis=AnalysisConfig(distance_tempering=tempering),
    )


def _job(tmp_path: Path, *, config=None):
    roads, points, boundary = _files(tmp_path)
    return Sigma.from_inputs(
        workspace=tmp_path / "workspace",
        source_store=tmp_path / "sources",
        output_dir=tmp_path / "output",
        points=points,
        points_layer="points",
        roads=roads,
        roads_layer="roads",
        boundary=boundary,
        boundary_layer="boundary",
        economy=_economy(),
        config=config or _config(),
    )


def test_public_facade_and_grouped_config_are_exposed():
    assert sigma.Sigma is Sigma
    config = SigmaConfig.default()
    assert config.economic.transaction_preprocessing == "none"
    assert config.spatial.economy_column == "economy_code"
    assert len(config.fingerprint) == 64


def test_complete_custom_input_fixture_runs_in_one_facade_call(tmp_path):
    pytest.importorskip("pyarrow")
    job = _job(tmp_path)
    result = job.run()
    expected = {
        "transport.roads",
        "spatial.points",
        "spatial.clusters",
        "spatial.centers",
        "spatial.point_distances",
        "area.boundary",
        "spatial.partitions",
        "economy.definition",
        "economy.transactions.raw",
        "economy.transactions.effective",
        "economy.coefficients",
        "economy.graph",
        "analysis.x",
        "analysis.centrality",
        "analysis.scores",
    }
    assert expected <= set(job.workspace.artifacts.active_keys())
    assert result.analysis.scored_points == job.workspace.artifact("analysis.scores")
    assert result.spatial.partitions == job.workspace.artifact("spatial.partitions")
    assert result.economic.graph == job.workspace.artifact("economy.graph")
    assert result.places is None
    assert "sigma_manifest.json" in result.outputs
    assert result.run_manifest == tmp_path / "output" / "sigma_manifest.json"


def test_rerun_reuses_all_artifacts_and_recompute_targets_only_requested_stage(tmp_path):
    job = _job(tmp_path)
    job.run_analysis()
    before = {key: job.workspace.artifact(key).artifact_id for key in job.workspace.artifacts.active_keys()}

    reopened = Sigma.from_inputs(
        workspace=tmp_path / "workspace",
        points=tmp_path / "points.gpkg",
        points_layer="points",
        roads=tmp_path / "roads.gpkg",
        roads_layer="roads",
        boundary=tmp_path / "boundary.gpkg",
        boundary_layer="boundary",
        economy=_economy(),
        config=_config(),
    )
    reopened.run_analysis()
    after = {key: reopened.workspace.artifact(key).artifact_id for key in before}
    assert after == before
    forced = reopened.recompute("analysis.scores")
    assert forced.artifact_id == before["analysis.scores"]
    assert {key: reopened.workspace.artifact(key).artifact_id for key in before} == before


def test_preprocessing_change_reuses_spatial_and_recomputes_economy_analysis_only(tmp_path):
    job = _job(tmp_path)
    job.run_analysis()
    stable = {
        key: job.workspace.artifact(key).artifact_id
        for key in (
            "transport.roads", "spatial.points", "spatial.clusters", "spatial.centers",
            "spatial.point_distances", "spatial.partitions", "economy.transactions.raw"
        )
    }
    changed_ids = {
        key: job.workspace.artifact(key).artifact_id
        for key in ("economy.transactions.effective", "economy.coefficients", "economy.graph", "analysis.x", "analysis.centrality", "analysis.scores")
    }

    changed = Sigma.from_inputs(
        workspace=tmp_path / "workspace",
        points=tmp_path / "points.gpkg",
        points_layer="points",
        roads=tmp_path / "roads.gpkg",
        roads_layer="roads",
        boundary=tmp_path / "boundary.gpkg",
        boundary_layer="boundary",
        economy=_economy(),
        config=_config(preprocessing="mwas_ras_fast"),
    )
    changed.run_analysis()
    assert {key: changed.workspace.artifact(key).artifact_id for key in stable} == stable
    for key, old in changed_ids.items():
        assert changed.workspace.artifact(key).artifact_id != old


def test_tempering_change_recomputes_scores_only_via_facade(tmp_path):
    job = _job(tmp_path)
    job.run_analysis()
    before = {key: job.workspace.artifact(key).artifact_id for key in (
        "analysis.x", "analysis.centrality", "analysis.scores", "spatial.point_distances"
    )}
    changed = Sigma.from_inputs(
        workspace=tmp_path / "workspace",
        points=tmp_path / "points.gpkg",
        points_layer="points",
        roads=tmp_path / "roads.gpkg",
        roads_layer="roads",
        boundary=tmp_path / "boundary.gpkg",
        boundary_layer="boundary",
        economy=_economy(),
        config=_config(tempering=0.30),
    )
    changed.run_analysis()
    assert changed.workspace.artifact("analysis.x").artifact_id == before["analysis.x"]
    assert changed.workspace.artifact("analysis.centrality").artifact_id == before["analysis.centrality"]
    assert changed.workspace.artifact("spatial.point_distances").artifact_id == before["spatial.point_distances"]
    assert changed.workspace.artifact("analysis.scores").artifact_id != before["analysis.scores"]


def test_status_is_inspection_only_and_reports_missing_before_run(tmp_path):
    job = _job(tmp_path)
    status = job.status()
    assert status["analysis.scores"].status == "missing"
    assert job.workspace.artifacts.active_keys() == ()


def test_component_namespace_exposes_domain_wrappers_without_new_orchestration(tmp_path):
    job = _job(tmp_path)
    assert job.components.places is None
    assert job.components.spatial is not None
    assert job.components.economy is not None
    assert job.components.analysis is not None
    assert job.components.exports is not None
    assert job.components.transport.prepare().stage == "transport.roads"


def test_stage_convenience_methods_delegate_to_managed_targets(tmp_path):
    job = _job(tmp_path)
    transport = job.prepare_network()
    assert transport.roads.stage == "transport.roads"
    economic = job.run_economy()
    assert economic.graph.stage == "economy.graph"
    spatial = job.run_spatial()
    assert spatial.partitions.stage == "spatial.partitions"
    analysis = job.run_analysis()
    assert analysis.scored_points.stage == "analysis.scores"


def test_custom_input_facade_keeps_places_unavailable_but_c17_export_is_public(tmp_path):
    job = _job(tmp_path)
    with pytest.raises(ConfigurationError, match="from_inputs"):
        job.load()
    pytest.importorskip("pyarrow")
    bundle = job.export()
    assert bundle.run_manifest.name == "sigma_manifest.json"


def test_legacy_classification_alias_selects_builtin_economy(tmp_path):
    roads, points, boundary = _files(tmp_path)
    job = Sigma.from_inputs(
        workspace=tmp_path / "legacy-ws",
        points=points,
        roads=roads,
        boundary=boundary,
        classification="io16",
    )
    assert job.economy.economy_id == "psa-2018-io16"
    with pytest.raises(ConfigurationError, match="either economy"):
        Sigma.from_inputs(
            workspace=tmp_path / "bad",
            points=points,
            roads=roads,
            boundary=boundary,
            economy=_economy(),
            classification="io80",
        )


def test_existing_workspace_rejects_conflicting_output_directory(tmp_path):
    job = _job(tmp_path)
    assert job.workspace.output_dir == (tmp_path / "output").resolve()
    with pytest.raises(ConfigurationError, match="existing workspace output_dir"):
        Sigma.from_inputs(
            workspace=tmp_path / "workspace",
            points=tmp_path / "points.gpkg",
            points_layer="points",
            roads=tmp_path / "roads.gpkg",
            roads_layer="roads",
            boundary=tmp_path / "boundary.gpkg",
            boundary_layer="boundary",
            economy=_economy(),
            config=_config(),
            output_dir=tmp_path / "different-output",
        )


def test_config_fingerprint_normalizes_source_store_string_and_path(tmp_path):
    from sigma.config import SourceConfig

    store = tmp_path / "sources"
    as_string = SigmaConfig(sources=SourceConfig(source_store=str(store)))
    as_path = SigmaConfig(sources=SourceConfig(source_store=store))
    assert as_string.fingerprint == as_path.fingerprint


def test_public_place_operation_is_named_load():
    assert hasattr(Sigma, "load")
    assert not hasattr(Sigma, "prepare_places")

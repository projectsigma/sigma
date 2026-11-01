from __future__ import annotations

from pathlib import Path
import json
import math

import geopandas as gpd
import networkx as nx
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from sigma import Economy, Sector, SectorCatalog, SigmaWorkspace
from sigma.analysis import AnalysisPipeline, make_node_id
from sigma.economy import EconomyPipeline, EconomyRunConfig
from sigma.spatial import SpatialPipeline, SpatialRunConfig
from sigma.transport import FileRoadSource


def _workspace(tmp_path: Path):
    return SigmaWorkspace.create(
        tmp_path / "workspace",
        area_identity="c14-two-sector",
        source_store=tmp_path / "sources",
        output_dir=tmp_path / "output",
    )


def _economy() -> Economy:
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[2.0, 6.0], [4.0, 2.0]], index=["A", "B"], columns=["A", "B"])
    x = pd.Series([10.0, 10.0], index=["A", "B"])
    return Economy(economy_id="c14-two-sector", sectors=sectors, raw_transactions=z, total_output=x)


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


def _pipelines(tmp_path: Path, *, econ_config: EconomyRunConfig | None = None):
    ws = _workspace(tmp_path)
    roads, points, boundary = _files(tmp_path)
    economy = _economy()
    spatial = SpatialPipeline(
        ws,
        roads=FileRoadSource(roads, "roads"),
        economy=economy,
        points_path=points,
        points_layer="points",
        boundary_path=boundary,
        boundary_layer="boundary",
        config=SpatialRunConfig(
            min_cluster_size=3,
            min_samples=2,
            allow_single_cluster=True,
            voronoi_resolution=0.5,
            voronoi_max_cells=5000,
        ),
    )
    economic = EconomyPipeline(ws, economy=economy, config=econ_config or EconomyRunConfig())
    analysis = AnalysisPipeline(ws, spatial_pipeline=spatial, economy_pipeline=economic)
    return ws, spatial, economic, analysis


def test_managed_analysis_x_accepts_full_directed_economy_and_reciprocal_edges(tmp_path):
    ws, spatial, economic, analysis = _pipelines(tmp_path)
    ref = analysis.x()
    result = analysis.load_x(ref)
    a = make_node_id("A", 0)
    b = make_node_id("B", 0)

    assert set(result.graph.nodes) == {a, b}
    assert set(result.graph.edges) == {(a, b), (b, a)}
    assert not nx.is_directed_acyclic_graph(result.graph)
    assert result.disconnected.empty
    assert set(result.edges["technical_coefficient"]) == {0.4, 0.6}
    expected = result.edges["technical_coefficient"] / result.edges["effective_road_distance"].clip(lower=1.0)
    assert all(abs(actual - wanted) < 1e-12 for actual, wanted in zip(result.edges["edge_weight"], expected, strict=True))
    assert len(result.paths) == 2
    assert str(result.paths.crs) == "EPSG:4326"
    metadata = ws.manifest("analysis.x").metadata
    assert metadata["economic_graph_is_dag"] is False
    assert metadata["x_is_dag"] is False
    assert metadata["zero_distance_self_edges_omitted"] == 2
    assert metadata["x_distance_decay_lambda"] == 1.0
    assert metadata["distance_floor_metres"] == 1.0
    assert metadata["cluster_share_denominator"] == "clustered_establishments_per_exact_type"


def test_x_decay_exponent_invalidates_x_not_upstream_artifacts(tmp_path):
    from sigma.analysis import AnalysisRunConfig

    ws, spatial, economic, analysis = _pipelines(tmp_path)
    first = analysis.x()
    spatial_ids = {
        stage: ws.artifact(stage).artifact_id
        for stage in ("spatial.clusters", "spatial.centers", "spatial.partitions", "economy.graph")
    }
    changed = AnalysisPipeline(
        ws, spatial_pipeline=spatial, economy_pipeline=economic,
        config=AnalysisRunConfig(x_distance_decay_lambda=2.0),
    )
    second = changed.x()
    assert second.artifact_id != first.artifact_id
    assert {stage: ws.artifact(stage).artifact_id for stage in spatial_ids} == spatial_ids
    for row in changed.load_x(second, include_paths=False).edges.itertuples(index=False):
        assert abs(row.edge_weight - row.technical_coefficient / max(row.effective_road_distance, 1.0) ** 2) < 1e-12


def test_analysis_x_depends_on_mean_member_distance_stage(tmp_path):
    ws, spatial, economic, analysis = _pipelines(tmp_path)
    ref = analysis.x()
    manifest = ws.artifacts.manifest(ref)
    assert set(manifest.recipe.dependencies) == {
        "spatial.clusters", "spatial.centers", "spatial.partitions", "spatial.point_distances", "economy.graph"
    }
    assert ws.artifact("spatial.point_distances") is not None


def test_analysis_x_reuses_exact_saved_spatial_network_after_road_source_removed(tmp_path):
    ws, spatial, economic, analysis = _pipelines(tmp_path)
    spatial.prepare_centers()
    spatial.prepare_partitions()
    spatial.prepare_point_distances()
    economic.graph()
    (tmp_path / "roads.gpkg").unlink()
    ref = analysis.x()
    assert len(analysis.load_x(ref).edges) == 2


def test_switching_economic_preprocessing_reuses_spatial_but_invalidates_x(tmp_path):
    ws, spatial, economic, analysis = _pipelines(tmp_path)
    first = analysis.x()
    spatial_ids = {
        stage: ws.artifact(stage).artifact_id
        for stage in ("spatial.clusters", "spatial.centers", "spatial.partitions")
    }

    sparse_economic = EconomyPipeline(
        ws,
        economy=_economy(),
        config=EconomyRunConfig(transaction_preprocessing="mwas_ras_fast"),
    )
    second_analysis = AnalysisPipeline(
        ws, spatial_pipeline=spatial, economy_pipeline=sparse_economic
    )
    second = second_analysis.x()
    assert second.artifact_id != first.artifact_id
    assert {
        stage: ws.artifact(stage).artifact_id for stage in spatial_ids
    } == spatial_ids


def test_forced_x_same_recipe_is_deterministic(tmp_path):
    _, _, _, analysis = _pipelines(tmp_path)
    first = analysis.x()
    second = analysis.x(force=True)
    assert second.artifact_id == first.artifact_id

def test_weight_only_change_reuses_all_saved_routes_without_running_road_engine(tmp_path, monkeypatch):
    from sigma.analysis import AnalysisRunConfig
    import sigma.analysis.pipeline as module

    ws, spatial, economic, first_analysis = _pipelines(tmp_path)
    first = first_analysis.x()
    previous = first_analysis.load_x(first)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("weight-only X update invoked road-routing graph construction")

    monkeypatch.setattr(module, "instantiate_network", forbidden)
    second_analysis = AnalysisPipeline(
        ws, spatial_pipeline=spatial, economy_pipeline=economic,
        config=AnalysisRunConfig(x_distance_decay_lambda=2.0),
    )
    second = second_analysis.x()
    assert second.artifact_id != first.artifact_id
    assert ws.manifest("analysis.x").metadata["x_route_geometry_reused_from"] == first.artifact_id
    # Reused route data occupies only one set of filesystem blocks. The raw
    # GeoParquet is the immutable base, while load_x overlays current numbers.
    assert (second.path / "x_paths_overlay.json").is_file()
    overlay = json.loads((second.path / "x_paths_overlay.json").read_text(encoding="utf-8"))
    assert overlay["source_x_artifact_id"] == first.artifact_id
    assert (second.path / "x_paths.parquet").samefile(first.path / "x_paths.parquet")
    assert ws.manifest("analysis.x").metadata["x_route_geometry_storage"] == "ntfs-hardlink-with-current-edge-overlay"
    assert ws.manifest("analysis.x").metadata["cluster_share_denominator"] == "clustered_establishments_per_exact_type"
    result = second_analysis.load_x(second)
    assert len(result.paths) == len(previous.paths)
    assert result.paths.geometry.geom_equals(previous.paths.geometry).all()
    for row in result.edges.itertuples(index=False):
        expected = row.technical_coefficient / max(row.effective_road_distance, 1.0) ** 2
        assert row.edge_weight == pytest.approx(expected)
    # GeoParquet, not just the CSV or in-memory graph, must contain fresh values.
    for row, pathrow in zip(result.edges.itertuples(index=False), result.paths.itertuples(index=False), strict=True):
        assert pathrow.edge_weight == pytest.approx(row.edge_weight)
        assert pathrow.effective_road_distance == pytest.approx(row.effective_road_distance)


def test_forced_same_recipe_after_route_reuse_is_deterministic(tmp_path, monkeypatch):
    """Force must not switch an immutable overlay recipe to full-route layout."""
    from sigma.analysis import AnalysisRunConfig
    import sigma.analysis.pipeline as module

    ws, spatial, economic, original = _pipelines(tmp_path)
    base = original.x()
    updated = AnalysisPipeline(
        ws, spatial_pipeline=spatial, economy_pipeline=economic,
        config=AnalysisRunConfig(x_distance_decay_lambda=2.0),
    )
    reused = updated.x()
    assert (reused.path / "x_paths_overlay.json").is_file()
    original_csv = (reused.path / "x_edges.csv").read_bytes()
    original_overlay = (reused.path / "x_paths_overlay.json").read_bytes()
    assert json.loads(original_overlay)["source_x_artifact_id"] == base.artifact_id
    assert ws.artifacts.validate(reused).valid

    def forbidden(*_args, **_kwargs):
        pytest.fail("forcing an overlay recipe must not reconstruct road routes")

    monkeypatch.setattr(module, "instantiate_network", forbidden)
    forced = updated.x(force=True)
    assert forced.artifact_id == reused.artifact_id
    assert forced.path == reused.path
    assert ws.artifacts.validate(forced).valid
    assert (forced.path / "x_edges.csv").read_bytes() == original_csv
    assert (forced.path / "x_paths_overlay.json").read_bytes() == original_overlay
    assert (forced.path / "x_paths.parquet").samefile(base.path / "x_paths.parquet")
    assert ws.artifacts.manifest(forced).metadata["x_route_geometry_reused_from"] == base.artifact_id
    assert len(updated.load_x(forced).paths) == len(original.load_x(base).paths)


def test_clustered_sector_share_denominators_use_exact_type_and_clustered_members():
    from sigma.analysis.pipeline import _clustered_sector_shares

    points = pd.DataFrame({
        "type": ["06:55:178"] * 4 + ["06:55:179"] * 2,
        "cluster": [0, 0, 0, 1, 0, 1],
    })
    shares = _clustered_sector_shares(points)
    assert shares[("06:55:178", 0)] == pytest.approx(3 / 4)
    assert shares[("06:55:178", 1)] == pytest.approx(1 / 4)
    assert shares[("06:55:179", 0)] == pytest.approx(1 / 2)
    assert shares[("06:55:179", 1)] == pytest.approx(1 / 2)

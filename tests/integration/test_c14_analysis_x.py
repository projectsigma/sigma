from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
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
    assert (result.edges["edge_weight"] == result.edges["technical_coefficient"] * result.edges["road_distance"]).all()
    assert len(result.paths) == 2
    assert str(result.paths.crs) == "EPSG:4326"
    metadata = ws.manifest("analysis.x").metadata
    assert metadata["economic_graph_is_dag"] is False
    assert metadata["x_is_dag"] is False
    assert metadata["zero_distance_self_edges_omitted"] == 2


def test_analysis_x_is_independent_of_point_distance_stage(tmp_path):
    ws, spatial, economic, analysis = _pipelines(tmp_path)
    ref = analysis.x()
    manifest = ws.artifacts.manifest(ref)
    assert set(manifest.recipe.dependencies) == {
        "spatial.clusters", "spatial.centers", "spatial.partitions", "economy.graph"
    }
    assert ws.artifact("spatial.point_distances") is None


def test_analysis_x_reuses_exact_saved_spatial_network_after_road_source_removed(tmp_path):
    ws, spatial, economic, analysis = _pipelines(tmp_path)
    spatial.prepare_centers()
    spatial.prepare_partitions()
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

"""A custom Economy may use sector codes that look like unpadded PSA codes."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from sigma import Economy, Sector, SectorCatalog, Sigma, SigmaConfig, SpatialConfig
from sigma.spatial.restart import normalize_restart_points

CODES = ("1", "2")


def _economy() -> Economy:
    sectors = SectorCatalog([Sector(CODES[0], "Alpha"), Sector(CODES[1], "Beta")])
    z = pd.DataFrame([[2.0, 6.0], [4.0, 2.0]], index=list(CODES), columns=list(CODES))
    x = pd.Series([10.0, 10.0], index=list(CODES))
    return Economy(economy_id="digit-codes", sectors=sectors, raw_transactions=z, total_output=x)


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    roads = tmp_path / "roads.gpkg"
    points = tmp_path / "points.gpkg"
    boundary = tmp_path / "boundary.gpkg"
    gpd.GeoDataFrame(geometry=[LineString([(0, 0), (20, 0)])], crs="EPSG:3857").to_file(
        roads, layer="roads", driver="GPKG"
    )
    xs = [1, 2, 3, 4, 5, 15, 16, 17, 18, 19]
    gpd.GeoDataFrame(
        {
            "canonical_id": [f"p{i}" for i in range(10)],
            "canonical_name": [f"P{i}" for i in range(10)],
            "economy_code": [CODES[0]] * 5 + [CODES[1]] * 5,
        },
        geometry=[Point(x, 0) for x in xs],
        crs="EPSG:3857",
    ).to_file(points, layer="points", driver="GPKG")
    gpd.GeoDataFrame(geometry=[box(0, -2, 20, 2)], crs="EPSG:3857").to_file(
        boundary, layer="boundary", driver="GPKG"
    )
    return roads, points, boundary


def test_managed_and_restart_runs_keep_custom_codes(tmp_path):
    pytest.importorskip("pyarrow")
    roads, points, boundary = _files(tmp_path)
    config = SigmaConfig(
        spatial=SpatialConfig(
            min_cluster_size=3, min_samples=2, allow_single_cluster=True, voronoi_resolution=0.5
        )
    )
    managed = Sigma.from_inputs(
        workspace=tmp_path / "workspace", source_store=tmp_path / "sources",
        output_dir=tmp_path / "output", roads=roads, roads_layer="roads",
        points=points, points_layer="points", boundary=boundary, boundary_layer="boundary",
        economy=_economy(), config=config,
    ).run()
    exported_partitions = gpd.read_parquet(managed.outputs["sigma_partitions.parquet"])
    exported_centers = gpd.read_parquet(managed.outputs["sigma_network_centers.parquet"])
    exported_points = gpd.read_parquet(managed.outputs["sigma_points.parquet"])
    assert set(exported_partitions["type"]) == set(CODES)
    assert exported_partitions.crs.to_epsg() == 4326
    assert exported_centers.crs.to_epsg() == 4326
    assert exported_points.crs.to_epsg() == 4326
    assert "network_position" not in exported_points.columns

    restart = Sigma.from_partitions(
        workspace=tmp_path / "restart-workspace", source_store=tmp_path / "restart-sources",
        output_dir=tmp_path / "restart-output", roads=roads, roads_layer="roads",
        partitions=managed.outputs["sigma_partitions.parquet"],
        centers=managed.outputs["sigma_network_centers.parquet"],
        points_with_center_distance=managed.outputs["sigma_points.parquet"],
        economy=_economy(),
    ).run()
    restart_partitions = gpd.read_parquet(restart.outputs["sigma_partitions.parquet"])
    restart_centers = gpd.read_parquet(restart.outputs["sigma_network_centers.parquet"])
    restart_points = gpd.read_parquet(restart.outputs["sigma_points.parquet"])
    assert set(restart_partitions["type"]) == set(CODES)
    assert restart_partitions.crs.to_epsg() == 4326
    assert restart_centers.crs.to_epsg() == 4326
    assert restart_points.crs.to_epsg() == 4326


def test_restart_normalization_keeps_selected_codes_and_pads_only_other_values():
    points = gpd.GeoDataFrame(
        {
            "canonical_id": ["a", "b", "c", "d", "e", "f", "g"],
            "type": ["1", "01", 3, 1.0, "1.0", 2.0, "2.0"],
            "cluster": [0] * 7,
            "distance_to_cluster_median": [0.0] * 7,
        },
        geometry=[Point(0, 0)] * 7,
        crs="EPSG:3857",
    )
    assert list(normalize_restart_points(points)["type"]) == [
        "01", "01", "03", "01", "01", "02", "02"
    ]
    assert list(normalize_restart_points(points, {"1", "2"})["type"]) == [
        "1", "01", "03", "1", "1", "2", "2"
    ]

"""Area-mode runs through the Sigma facade, with the provider calls replaced by local data."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

pytest.importorskip("pyarrow")

from sigma import Area, Sigma, SigmaConfig, SourceConfig, SpatialConfig
from sigma.places.pipeline import PlaceServices

LATITUDE = 14.0
LONGITUDES = [120.9984 + 0.0004 * i for i in range(9)]


def _area() -> Area:
    return Area("fixture", "Fixture City", "city", (120.99, 13.99, 121.01, 14.01))


def _places(source: str, category: str, label: str, *, shift: float = 0.0) -> gpd.GeoDataFrame:
    lons = [lon + shift for lon in LONGITUDES]
    frame = pd.DataFrame(
        {
            "source": source,
            "source_id": [f"{source}/{i}" for i in range(len(lons))],
            "name": [f"{label} Bank Branch {i}" for i in range(len(lons))],
            "category": category,
            "lon": lons,
            "lat": LATITUDE,
            "provenance": source,
            "upstream_license": "ODbL-1.0" if source == "osm" else "CDLA-Permissive-2.0",
            "overture_providers": "" if source == "osm" else "meta",
        }
    )
    geometry = [Point(lon, LATITUDE) for lon in lons]
    return gpd.GeoDataFrame(frame, geometry=geometry, crs="EPSG:4326")


def _job(tmp_path: Path, *, prepared, calls: dict[str, int], refresh=False, overture_shift=0.00002):
    """One area-mode job.  ``prepared(attempt)`` supplies the prepared OSM result."""
    pbf = tmp_path / "philippines.osm.pbf"
    pbf.write_bytes(b"fixture-pbf")
    snapshot = tmp_path / "overture.parquet"
    snapshot.write_bytes(b"fixture-overture")
    roads = tmp_path / "roads.gpkg"
    if not roads.exists():
        line = LineString([(120.992, LATITUDE), (121.008, LATITUDE)])
        gpd.GeoDataFrame(geometry=[line], crs="EPSG:4326").to_crs("EPSG:32651").to_file(
            roads, layer="roads", driver="GPKG"
        )

    def geofabrik(store, config, progress):
        calls["geofabrik"] = calls.get("geofabrik", 0) + 1
        return store.register_path(
            pbf, kind="provider-snapshot", provider="geofabrik",
            name="philippines-osm-pbf", version="fixture-v1",
        )

    def overture(store, bbox, config, progress):
        calls["overture"] = calls.get("overture", 0) + 1
        return store.register_path(
            snapshot, kind="query-snapshot", provider="overture", name="places",
            selection={"bbox": list(bbox)}, metadata={"bbox": list(bbox)},
        )

    def load_prepared(cache_base, ref, area_slug, areas_file, progress):
        calls["prepare"] = calls.get("prepare", 0) + 1
        return prepared(calls["prepare"])

    services = PlaceServices(
        geofabrik=geofabrik,
        overture=overture,
        load_overture=lambda ref: _places("overture", "bank", "Sample", shift=overture_shift),
        load_prepared_osm=load_prepared,
    )
    config = SigmaConfig(
        sources=SourceConfig(refresh_geofabrik=refresh, refresh_overture=refresh),
        spatial=SpatialConfig(
            min_cluster_size=3, min_samples=2, allow_single_cluster=True, voronoi_resolution=2000.0
        ),
    )
    return Sigma(
        _area(), workspace=tmp_path / "workspace", source_store=tmp_path / "sources",
        output_dir=tmp_path / "output", roads=roads, roads_layer="roads", config=config,
        place_services=services,
    )


def _current(attempt: int):
    return _places("osm", "amenity=bank", "Sample"), "fixture-v1", False


def _exported_scores(result) -> str:
    manifest = json.loads(Path(result.run_manifest).read_text(encoding="utf-8"))
    return manifest["dependencies"]["analysis.scores"]["artifact_id"]


def test_area_mode_run_reaches_export_and_acquires_each_source_once(tmp_path):
    calls: dict[str, int] = {}
    job = _job(tmp_path, prepared=_current, calls=calls, refresh=False)
    job.load()
    result = job.run()

    assert (calls["geofabrik"], calls["overture"], calls["prepare"]) == (1, 1, 1)
    report = json.loads(Path(result.outputs["run.json"]).read_text(encoding="utf-8"))
    assert set(report["managed_stage_metadata"]) == {"canonical", "psic"}
    assert _exported_scores(result) == result.analysis.scored_points.artifact_id
    outputs_text = Path(result.outputs["OUTPUTS.txt"]).read_text(encoding="utf-8")
    assert "Area: Fixture City (fixture)" in outputs_text


def test_fallback_is_prepared_once_per_run_and_retried_by_the_next_run(tmp_path):
    calls: dict[str, int] = {}

    def fails_once(attempt: int):
        if attempt == 1:
            return _places("osm", "amenity=bank", "Old"), "old-v0", True
        return _places("osm", "amenity=bank", "Sample"), "fixture-v1", False

    first = _job(tmp_path, prepared=fails_once, calls=calls)
    first.load()
    assert calls["prepare"] == 1
    assert first.workspace.manifest("source.osm_national_pois").metadata["fallback"] is True

    second = _job(tmp_path, prepared=fails_once, calls=calls)
    second.load()
    assert calls["prepare"] == 2
    assert second.workspace.manifest("source.osm_national_pois").metadata["fallback"] is False
    result = second.run()
    assert _exported_scores(result) == result.analysis.scored_points.artifact_id


def test_area_without_places_prepares_empty_layers_and_names_the_cause(tmp_path):
    calls: dict[str, int] = {}

    def outside(attempt: int):
        return _places("osm", "amenity=bank", "Far", shift=0.5), "fixture-v1", False

    job = _job(tmp_path, prepared=outside, calls=calls, overture_shift=0.5)
    job.load()
    assert job.workspace.manifest("places.classified").metadata["rows"] == 0
    with pytest.raises(ValueError, match="no points have the selected economic classification"):
        job.run()


def test_same_sigma_object_retries_provisional_on_next_run(tmp_path):
    calls: dict[str, int] = {}

    def fails_once(attempt: int):
        if attempt == 1:
            return _places("osm", "amenity=bank", "Old"), "old-v0", True
        return _places("osm", "amenity=bank", "Sample"), "fixture-v1", False

    job = _job(tmp_path, prepared=fails_once, calls=calls)
    job.load()
    assert calls["prepare"] == 1
    assert job.workspace.manifest("source.osm_national_pois").metadata["fallback"] is True

    job.load()
    assert calls["prepare"] == 2
    assert job.workspace.manifest("source.osm_national_pois").metadata["fallback"] is False


def test_same_sigma_object_refreshes_each_source_once_per_run(tmp_path):
    calls: dict[str, int] = {}
    job = _job(tmp_path, prepared=_current, calls=calls, refresh=True)

    job.load()
    assert (calls["geofabrik"], calls["overture"]) == (1, 1)

    job.load()
    assert (calls["geofabrik"], calls["overture"]) == (2, 2)


def test_run_requires_the_user_visible_places_handoff(tmp_path):
    calls: dict[str, int] = {}
    job = _job(tmp_path, prepared=_current, calls=calls)
    with pytest.raises(Exception, match="analysis requires a loaded places GeoParquet"):
        job.run()


def test_filtered_places_handoff_is_the_analysis_input(tmp_path):
    calls: dict[str, int] = {}
    job = _job(tmp_path, prepared=_current, calls=calls)
    job.load()

    prepared = gpd.read_parquet(job.places_path)
    filtered = prepared.iloc[:6].copy()
    filtered.to_parquet(job.places_path, index=False)

    analysis_job = _job(tmp_path, prepared=_current, calls=calls)
    result = analysis_job.run()
    assert analysis_job.workspace.manifest("spatial.points").metadata["rows"] == 6
    exported = gpd.read_parquet(result.outputs["pois.parquet"])
    assert len(exported) == 6


def test_run_publishes_qgis_project_with_relative_parquet_layers(tmp_path):
    calls: dict[str, int] = {}
    job = _job(tmp_path, prepared=_current, calls=calls)
    job.load()
    result = job.run()

    assert "fixture.qgz" in result.outputs
    assert "sigma_boundary.parquet" in result.outputs
    assert "sigma_roads.parquet" in result.outputs

    boundary = gpd.read_parquet(result.outputs["sigma_boundary.parquet"])
    roads = gpd.read_parquet(result.outputs["sigma_roads.parquet"])
    assert boundary.crs.to_epsg() == 4326
    assert roads.crs.to_epsg() == 4326
    area_geometry = boundary.geometry.iloc[0]
    assert all(area_geometry.covers(geometry) for geometry in roads.geometry)
    metadata = json.loads(Path(result.outputs["sigma_run_metadata.json"]).read_text(encoding="utf-8"))
    assert metadata["published_roads_clipped_to_area"] is True

    points = gpd.read_parquet(result.outputs["sigma_points.parquet"])
    assert {
        "type_label", "type_display", "type_family", "distance_to_cluster_median",
        "cluster_centrality", "sigma_score", "in_degree", "out_degree",
        "katz_in_raw", "katz_out_raw", "centrality",
    } <= set(points.columns)
    assert points.crs.to_epsg() == 4326
    assert "network_position" not in points.columns
    assert "sigma_points_centrality.parquet" not in result.outputs
    assert "sigma_points_with_center_distance.parquet" not in result.outputs
    assert "sigma_clustered_points.parquet" not in result.outputs

    with zipfile.ZipFile(result.outputs["fixture.qgz"]) as archive:
        names = archive.namelist()
        assert "fixture.qgs" in names
        qgs = archive.read("fixture.qgs").decode("utf-8")
    assert "./sigma_points.parquet" in qgs
    assert "./sigma_points.parquet|layername=" not in qgs
    assert "./sigma_roads.parquet" in qgs
    assert "./sigma_roads.parquet|layername=" not in qgs
    assert "sigma_points_centrality" not in qgs
    assert "sigma_points_with_center_distance" not in qgs
    assert "sigma_clustered_points" not in qgs
    assert "./sigma_boundary.parquet" in qgs
    assert "./sigma_boundary.parquet|layername=" not in qgs
    assert 'layer-tree-group name="Partitions"' in qgs
    assert "sigma_score" in qgs

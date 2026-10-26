"""Provincial cache compatibility with pre-existing nationwide OSM preparation."""
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from sigma.area.catalog import Area
from sigma.sources import osm_prepare as prepare


def _points():
    return gpd.GeoDataFrame(
        {"poi_id": ["inside", "edge", "outside_bbox", "inside_bbox_outside_polygon"]},
        geometry=[Point(1, 1), Point(0, 1), Point(5, 5), Point(1.8, 1.8)],
        crs="EPSG:4326",
    )


def test_missing_province_cache_is_derived_and_reused(tmp_path, monkeypatch):
    prepared_dir = tmp_path / "prepared" / "261004"
    prepared_dir.mkdir(parents=True)
    _points().to_parquet(prepared_dir / "national-pois.parquet")
    area = Area("sample_province", "Sample Province", "province", (0, 0, 2, 2))
    monkeypatch.setattr(prepare, "load_areas", lambda path=None: {area.slug: area})
    monkeypatch.setattr(
        prepare,
        "load_boundary",
        lambda selected: box(0, 0, 2, 2).difference(box(1.5, 1.5, 2, 2)),
    )
    monkeypatch.setattr(
        prepare, "prepare_all_area_osm_caches",
        lambda **kwargs: (prepared_dir, "261004"),
    )
    monkeypatch.setattr(prepare, "_read_current_complete_dir", lambda cache_base: None)

    result, version, fallback = prepare.load_prepared_area_osm(
        cache_base=tmp_path,
        pbf_file=tmp_path / "unused.osm.pbf",
        area_slug=area.slug,
    )
    assert version == "261004"
    assert fallback is False
    assert set(result["poi_id"]) == {"inside", "edge"}

    target = prepared_dir / "areas" / f"{area.slug}.parquet"
    assert target.exists()
    unchanged_mtime = target.stat().st_mtime_ns
    result2, _, _ = prepare.load_prepared_area_osm(
        cache_base=tmp_path,
        pbf_file=tmp_path / "unused.osm.pbf",
        area_slug=area.slug,
    )
    assert set(result2["poi_id"]) == {"inside", "edge"}
    assert target.stat().st_mtime_ns == unchanged_mtime


def test_missing_nonprovince_still_raises(tmp_path, monkeypatch):
    prepared_dir = tmp_path / "prepared" / "261004"
    prepared_dir.mkdir(parents=True)
    _points().to_parquet(prepared_dir / "national-pois.parquet")
    area = Area("sample_city", "Sample City", "city", (0, 0, 2, 2))
    monkeypatch.setattr(prepare, "load_areas", lambda path=None: {area.slug: area})
    monkeypatch.setattr(
        prepare,
        "prepare_all_area_osm_caches",
        lambda **kwargs: (prepared_dir, "261004"),
    )
    monkeypatch.setattr(prepare, "_read_current_complete_dir", lambda cache_base: None)
    with pytest.raises(FileNotFoundError, match="Prepared OSM cache is missing"):
        prepare.load_prepared_area_osm(
            cache_base=tmp_path,
            pbf_file=tmp_path / "unused.osm.pbf",
            area_slug=area.slug,
        )


def test_validation_does_not_require_lazily_generated_province_cache(tmp_path):
    prepared_dir = tmp_path / "prepared" / "261004"
    (prepared_dir / "areas").mkdir(parents=True)
    frame = _points()
    for filename in (
        "national-pois.parquet",
        "boundaries.parquet",
        "assignments.parquet",
        "national-pois-assigned.parquet",
        "areas/sample_city.parquet",
    ):
        frame.to_parquet(prepared_dir / filename)

    city = Area("sample_city", "Sample City", "city", (0, 0, 2, 2))
    province = Area("sample_province", "Sample Province", "province", (0, 0, 2, 2))
    state = prepare._new_state("261004")
    manifest = prepare._validate_and_manifest(
        directory=prepared_dir,
        state=state,
        version="261004",
        points=frame,
        all_areas={city.slug: city, province.slug: province},
        ambiguous_count=0,
        unassigned_count=0,
        progress=None,
    )
    assert manifest["status"] == "complete"
    assert manifest["area_counts"] == {"sample_city": 4}
    assert not (prepared_dir / "areas" / "sample_province.parquet").exists()

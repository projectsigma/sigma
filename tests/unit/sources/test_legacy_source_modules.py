from __future__ import annotations

import json

import pytest

from sigma.places.osm import _category, _has_poi
from sigma.places.overture import OVERTURE_NORMALIZATION_VERSION, _policy_cache_matches
from sigma.sources.cache import cache_matches_bbox, write_cache_identity
from sigma.sources.geofabrik import _latest_from_philippines_page
from sigma.sources.osm_prepare import _load_state, _save_state, _stage


def test_latest_dated_philippines_pbf_is_selected():
    html = """
    <a href="philippines-260928.osm.pbf">philippines-260928.osm.pbf</a>
    <a href="philippines-260929.osm.pbf">philippines-260929.osm.pbf</a>
    <a href="philippines-260929.osm.pbf.md5">checksum</a>
    """
    assert _latest_from_philippines_page(html) == "260929"


def test_cache_identity_requires_matching_bbox(tmp_path):
    cache = tmp_path / "source.parquet"
    cache.touch()
    bbox = (120.0, 14.0, 121.0, 15.0)

    assert not cache_matches_bbox(cache, bbox)
    write_cache_identity(cache, bbox)
    assert cache_matches_bbox(cache, bbox)
    assert not cache_matches_bbox(cache, (120.0, 14.0, 121.1, 15.0))


def test_malformed_cache_identity_fails_closed(tmp_path):
    cache = tmp_path / "source.parquet"
    cache.touch()
    metadata = cache.with_suffix(cache.suffix + ".meta.json")
    metadata.write_text("{not-json", encoding="utf-8")
    assert not cache_matches_bbox(cache, (120.0, 14.0, 121.0, 15.0))


def test_old_overture_cache_without_policy_marker_is_invalid(tmp_path, monkeypatch):
    cache = tmp_path / "overture.parquet"
    cache.touch()
    monkeypatch.setattr("sigma.places.overture.cache_matches_bbox", lambda path, bbox: True)
    assert not _policy_cache_matches(cache, (120.0, 14.0, 121.0, 15.0))


def test_current_overture_policy_marker_is_accepted(tmp_path, monkeypatch):
    cache = tmp_path / "overture.parquet"
    cache.touch()
    bbox = (120.0, 14.0, 121.0, 15.0)
    monkeypatch.setattr("sigma.places.overture.cache_matches_bbox", lambda path, value: True)
    marker = cache.with_suffix(cache.suffix + ".overture.json")
    marker.write_text(
        json.dumps(
            {
                "normalization_version": OVERTURE_NORMALIZATION_VERSION,
                "bbox": list(bbox),
                "raw_rows": 10,
                "accepted_rows": 8,
            }
        ),
        encoding="utf-8",
    )
    assert _policy_cache_matches(cache, bbox)


def test_osm_named_shop_is_a_poi():
    assert _has_poi({"name": "Sample Shop", "shop": "convenience"})
    assert not _has_poi({"shop": "convenience"})


def test_osm_selected_railway_value_is_a_poi():
    assert _has_poi({"name": "Sample Station", "railway": "station"})
    assert not _has_poi({"name": "Sample Track", "railway": "rail"})


def test_osm_category_preserves_classification_evidence():
    category = _category(
        {"amenity": "cafe", "cuisine": "coffee_shop", "brand": "Example Coffee"}
    )
    assert "amenity=cafe" in category
    assert "cuisine=coffee_shop" in category
    assert "brand=Example Coffee" in category


def test_osm_prepare_state_survives_restart(tmp_path):
    state = _load_state(tmp_path, "261001")
    _stage(state, "national_extraction")["status"] = "complete"
    _save_state(tmp_path, state)
    restored = _load_state(tmp_path, "261001")
    assert _stage(restored, "national_extraction")["status"] == "complete"


def test_atomic_parquet_checkpoint_when_pyarrow_available(tmp_path):
    pytest.importorskip("pyarrow")
    import pandas as pd

    from sigma.sources.osm_prepare import _atomic_parquet, _parquet_rows

    target = tmp_path / "checkpoint.parquet"
    _atomic_parquet(pd.DataFrame({"x": [1, 2, 3]}), target)
    assert _parquet_rows(target) == 3
    assert not target.with_suffix(target.suffix + ".tmp").exists()

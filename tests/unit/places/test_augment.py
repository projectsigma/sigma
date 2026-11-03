"""Focused regressions for post-load user-source augmentation."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest

from sigma.places import augment


def test_csv_minimum_schema_and_arbitrary_column(tmp_path):
    path = tmp_path / "places.csv"
    path.write_text("source_id,name,lon,lat,employees\n001,Foo Pharmacy,121.02,14.64,7\n", encoding="utf-8")
    out = augment.read_input(path)
    assert out.source_id.iloc[0] == "001"
    assert out.employees.iloc[0] == 7
    assert out.crs.to_epsg() == 4326
    assert all(out[x].iloc[0] == "" for x in ("io16", "io80", "io240"))


@pytest.mark.parametrize("csv", [
    "source_id,name,lon,lat\n1,Foo,NaN,14.64\n",
    "source_id,name,lon,lat\n1,Foo,121,91\n",
    "source_id,name,lon,lat\n1,Foo,121,14\n1,Bar,122,15\n",
    "source_id,name,lon,lat\n1,,121,14\n",
])
def test_bad_input_rejected(tmp_path, csv):
    path = tmp_path / "bad.csv"
    path.write_text(csv, encoding="utf-8")
    if "Bar" in csv:
        # The two rows are valid and have distinct names, so specifically
        # change the second ID to verify duplicate-source rejection.
        path.write_text(csv.replace("1,Bar", "1,Bar"), encoding="utf-8")
    with pytest.raises(ValueError):
        augment.read_input(path)


def test_matched_three_source_centroid_and_provenance(monkeypatch):
    base = gpd.GeoDataFrame(pd.DataFrame([{
        "canonical_id": "orig", "poi_id": "orig", "name": "Sample Cafe",
        "category": "cafe", "lon": 121.0000, "lat": 14.0000,
        "source_count": 2, "sources": "osm|overture", "aliases": [],
        "match_distance_m": 3.0, "match_name_score": .99,
        "io16_code": "", "io80_code": "", "io240_code": "",
    }]), geometry=gpd.points_from_xy([121.0], [14.0]), crs="EPSG:4326")
    more = gpd.GeoDataFrame(pd.DataFrame([{
        "source_id": "Z-001", "name": "Sample Cafe", "category": "cafe",
        "lon": 121.00003, "lat": 14.0, "employees": 16,
        "io16": "", "io80": "", "io240": "", "psic_code": "",
    }]), geometry=gpd.points_from_xy([121.00003], [14.0]), crs="EPSG:4326")
    monkeypatch.setattr(augment, "validate_io_codes", lambda frame: {})
    out, report = augment.build_augmented(base, more, source="test_source")
    assert report == {"matched": 1, "added": 0, "total": 1, "input": 1,
                      "warnings": [], "warning_count": 0}
    assert out.at[0, "canonical_id"] == "orig"
    assert out.at[0, "sources"] == "osm|overture|user:test_source"
    assert out.at[0, "source_count"] == 3
    assert abs(out.at[0, "lon"] - 121.00001) < 1e-10
    assert out.at[0, "match_distance_m"] == 3.0
    assert out.at[0, "aug_test_source__employees"] == 16


def test_duplicate_source_refused(monkeypatch):
    base = gpd.GeoDataFrame({"canonical_id": ["orig"], "name": ["Café"],
        "lon": [121.0], "lat": [14.0], "sources": ["user:registry"]},
        geometry=gpd.points_from_xy([121.0], [14.0]), crs="EPSG:4326")
    supplied = base.rename(columns={"canonical_id": "source_id"}).copy()
    with pytest.raises(ValueError, match="already exists"):
        augment.build_augmented(base, supplied, source="registry")


def test_unmatched_new_place_keeps_arbitrary_columns(monkeypatch):
    base = gpd.GeoDataFrame(pd.DataFrame([{
        "canonical_id": "prior", "name": "Old Cafe", "lon": 121.0, "lat": 14.0,
        "sources": "osm", "source_count": 1,
    }]), geometry=gpd.points_from_xy([121.0], [14.0]), crs="EPSG:4326")
    supplied = gpd.GeoDataFrame(pd.DataFrame([{
        "source_id": "L001", "name": "Remote Bakery", "category": "bakery",
        "lon": 122.0, "lat": 15.0, "employees": 11,
        "io16": "", "io80": "", "io240": "", "psic_code": "",
    }]), geometry=gpd.points_from_xy([122.0], [15.0]), crs="EPSG:4326")
    monkeypatch.setattr(augment, "validate_io_codes", lambda frame: {})
    monkeypatch.setattr(augment, "_classify_new", lambda frame: frame)
    out, counts = augment.build_augmented(base, supplied, source="my_registry")
    assert counts["added"] == 1
    assert out.loc[1, "aug_my_registry__employees"] == 11
    assert out.loc[1, "sources"] == "user:my_registry"
    assert out.loc[1, "canonical_id"].startswith("ss_")
    assert out.loc[0, "canonical_id"] == "prior"


def test_namespaced_input_can_use_sigma_reserved_fields(tmp_path):
    path = tmp_path / "fields.csv"
    path.write_text(
        "source_id,name,lon,lat,canonical_id,economy_code,source_count\n"
        "R01,Example Factory,121.00,14.60,own-key,not-a-sigma-sector,9\n",
        encoding="utf-8",
    )
    frame = augment.read_input(path)
    assert frame.loc[0, "canonical_id"] == "own-key"
    assert frame.loc[0, "economy_code"] == "not-a-sigma-sector"
    assert frame.loc[0, "source_count"] == 9


def test_three_column_io_manual_codes_and_parentage(monkeypatch):
    import sys
    import types

    classification = types.ModuleType("sigma.classification")
    classification.load_builtin_io_reference = lambda: types.SimpleNamespace(
        io240_parent_map={"001": "11", "002": "12"}
    )
    compat = types.ModuleType("sigma.classification.io_mapping_compat")
    compat.load_catalog = lambda: {
        "11": types.SimpleNamespace(io16_code="01"),
        "12": types.SimpleNamespace(io16_code="02"),
    }
    monkeypatch.setitem(sys.modules, "sigma.classification", classification)
    monkeypatch.setitem(sys.modules, "sigma.classification.io_mapping_compat", compat)
    frame = pd.DataFrame({
        "source_id": ["1", "2", "3", "4", "5"],
        "io16": ["01", "", "01", "", ""],
        "io80": ["", "11", "11", "", ""],
        "io240": ["", "", "", "001", ""],
    })
    tags = augment.validate_io_codes(frame)
    assert set(tags) == {0, 1, 2, 3}
    assert tags[0] == {"io16_code": "01", "io80_code": "", "io240_code": "", "augment_io_code": "01"}
    assert tags[1] == {"io16_code": "01", "io80_code": "11", "io240_code": "", "augment_io_code": "01:11"}
    assert tags[3] == {"io16_code": "01", "io80_code": "11", "io240_code": "001", "augment_io_code": "01:11:001"}
    invalid = pd.DataFrame({"source_id": ["a", "b"], "io16": ["02", "01"],
                            "io80": ["11", "12"], "io240": ["001", ""]})
    with pytest.raises(ValueError, match="2 conflicting or unknown IO tag row") as err:
        augment.validate_io_codes(invalid)
    assert "source_id=a" in str(err.value)
    assert "source_id=b" in str(err.value)
    assert "nothing will be written" in str(err.value)


def test_no_child_inference_from_parent(monkeypatch):
    import sys
    import types
    classification = types.ModuleType("sigma.classification")
    classification.load_builtin_io_reference = lambda: types.SimpleNamespace(io240_parent_map={"001": "11"})
    compat = types.ModuleType("sigma.classification.io_mapping_compat")
    compat.load_catalog = lambda: {"11": types.SimpleNamespace(io16_code="01")}
    monkeypatch.setitem(sys.modules, "sigma.classification", classification)
    monkeypatch.setitem(sys.modules, "sigma.classification.io_mapping_compat", compat)
    tags = augment.validate_io_codes(pd.DataFrame({"source_id": ["a"], "io16": ["01"],
                                                      "io80": [""], "io240": [""]}))
    assert tags[0]["io80_code"] == ""
    assert tags[0]["io240_code"] == ""


def test_explicit_matched_conflict_vs_auto_warning():
    previous = pd.Series({"io16_code": "01", "io80_code": "11", "io240_code": "001"})
    manual = {"io16_code": "02", "io80_code": "12", "io240_code": "002"}
    issues = augment._comparison_warnings(previous, manual, "R-1", context="matched")
    assert len(issues) == 3
    assert "source_id=R-1" in issues[0]
    assert augment._explicit_conflicts(previous.to_dict(), manual) == [
        "io16_code: 01 vs 02", "io80_code: 11 vs 12", "io240_code: 001 vs 002"]


def test_coarser_manual_update_preserves_compatible_fine():
    prior = {"io16_code": "01", "io80_code": "11", "io240_code": "001"}
    newer = {"io16_code": "01", "io80_code": "", "io240_code": ""}
    assert augment._explicit_conflicts(prior, newer) == []


def test_manual_io_candidates_parquet_roundtrip(tmp_path):
    frame = gpd.GeoDataFrame(
        {
            "canonical_id": ["a", "b"],
            "io16_codes": ["01; 02", ""],
            "io80_codes": ["11", ""],
            "io240_codes": ["001", ""],
        },
        geometry=gpd.points_from_xy([121, 121.001], [14, 14.001]),
        crs="EPSG:4326",
    )
    tag = {
        "io16_code": "01",
        "io80_code": "11",
        "io240_code": "001",
        "augment_io_code": "01:11:001",
    }
    augment._override_io(frame, {1: tag}, [1])
    output = tmp_path / "places.parquet"
    frame.to_parquet(output, index=False)
    restored = gpd.read_parquet(output)
    assert [
        restored.at[1, f"io{level}_codes"]
        for level in ("16", "80", "240")
    ] == ["01", "11", "001"]

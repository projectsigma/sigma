"""SIGMA v6 read-only audit: never promote name, branch, location or code hints."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "sigma_national_evidence_audit_v6", ROOT / "scripts" / "sigma_national_evidence_audit.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def ref(**kwargs):
    out = {
        "canonical_id": "ss_one", "name": "Example Hospital",
        "registry_name": "Example Hospital", "registry_ownership": "public",
        "registry_status": "NAME_LOCATION_UNVERIFIED", "registered_id_kind": "official_code",
        "registered_city": "Manila", "registered_address": "Manila City",
        "registry_ids": "doh_nhfr:ABC-123", "relationship_hypothesis":
        "CROSS_LOCALITY_BRANCH_OR_AFFILIATE_CANDIDATE",
        "ownership_opportunity": "CURRENT_IO80_UNASSIGNED", "promotion_allowed": "false",
    }
    out.update(kwargs)
    return out


def places(**kwargs):
    row = {"canonical_id": "ss_one", "osm_name": "Example Hospital",
           "overture_name": "Example Hospital", "city": "Quezon City",
           "nhfr_code": "ABC-123", "osm_category": "amenity=hospital | ref:nhfr=ABC-123",
           "osm_ownership": "public", "latitude": "14.650", "longitude": "121.040"}
    row.update(kwargs)
    return pd.DataFrame([row]).set_index("canonical_id", drop=False)


def test_official_id_and_cross_city_never_autoverified():
    got, summary = MODULE.enrich([ref()], places())
    row = got[0]
    assert row["join_status"] == "JOINED_CANONICAL_ID"
    assert row["official_id_relation"] == "OFFICIAL_CODE_EQUALS_REGISTRY_REVIEW"
    assert row["locality_comparison"] == "CROSS_LOCALITY_BRANCH_OR_SITE_REVIEW_NOT_REJECTION"
    assert row["coordinate_basis"].startswith("explicit_WGS84")
    assert row["identity_verified"] == "false"
    assert row["ownership_promotion_allowed"] == "false"
    assert summary["ownership_changes"] == 0


def test_source_facility_code_conflict_cannot_be_ignored():
    got, _ = MODULE.enrich([ref()], places(nhfr_code="ABC-999", osm_category="ref:nhfr=ABC-999"))
    assert got[0]["official_id_relation"] == "OFFICIAL_CODE_CONFLICT_REVIEW"
    assert "official_code_conflict" in got[0]["candidate_review_reasons"]


def test_inconsistent_source_codes_and_ownership_conflict():
    got, _ = MODULE.enrich([ref()], places(nhfr_code="ABC-123", doh_facility_code="ABC-543",
                                           osm_ownership="public", overture_ownership="private"))
    assert got[0]["official_id_relation"] == "SOURCE_OFFICIAL_IDS_DISAGREE"
    assert got[0]["ownership_evidence_relation"] == "SOURCE_OWNERSHIP_CONFLICT_REVIEW"
    assert got[0]["evidence_priority"] == "HIGH_CONFLICT"


def test_philhealth_pdf_row_is_not_external_facility_id():
    row = ref(registry_ids="philhealth_hospitals:2026-09-30:row-17",
              registered_id_kind="publication_row", registry_name="Example Hospital")
    got, _ = MODULE.enrich([row], places(nhfr_code="2026-09-30:row-17"))
    assert got[0]["official_id_relation"] == "NOT_COMPARABLE_PUBLICATION_ROW"
    assert got[0]["official_ids_observed"] == ""
    assert got[0]["identity_verified"] == "false"


def test_branch_or_subunit_and_raw_name_disagreement():
    got, _ = MODULE.enrich([ref(name="Example Hospital - Outpatient Wing")],
                           places(osm_name="Example Hospital - Outpatient Wing",
                                  overture_name="Example Hospital"))
    assert got[0]["source_name_relation"] == "RAW_SOURCE_NAMES_DISAGREE_REVIEW"
    assert "Wing" in got[0]["subunit_or_branch_signal"]


def test_missing_record_is_explicit_not_silently_dropped():
    got, summary = MODULE.enrich([ref(canonical_id="ss_absent")], places())
    assert got[0]["join_status"] == "MISSING_FROM_PLACES"
    assert summary["join:MISSING_FROM_PLACES"] == 1
    assert got[0]["ownership_promotion_allowed"] == "false"


def test_geometry_requires_known_crs():
    from shapely.geometry import Point
    p = {"geometry": Point(121.02, 14.62).wkb}
    assert MODULE._coord(p, "UNKNOWN")[-1] == "GEOMETRY_CRS_UNVERIFIED"
    lon, lat, basis = MODULE._coord(p, "OGC:CRS84")
    assert lon == "121.02000000" and lat == "14.62000000"
    assert basis.startswith("GeoParquet:")


def test_grouping_aggregates_observations_not_different_institutions():
    grouped = MODULE.grouped([
        {"registry_ids": "doh_nhfr:ABC-123", "registry_name": "X", "registry_ownership": "public",
         "canonical_id": "a", "ownership_opportunity": "CURRENT_IO80_UNASSIGNED"},
        {"registry_ids": "doh_nhfr:ABC-123", "registry_name": "X", "registry_ownership": "public",
         "canonical_id": "b", "ownership_opportunity": "CURRENT_IO80_ALREADY_AGREES"},
        {"registry_ids": "", "canonical_id": "c"},
    ])
    assert len(grouped) == 1
    assert grouped[0]["candidate_observations"] == "2"
    assert grouped[0]["unassigned_io80_observations"] == "1"


def test_end_to_end_fixture_and_refuse_overwrite(tmp_path):
    places_dir = tmp_path / "example_workspace" / "places"
    places_dir.mkdir(parents=True)
    places_file = tmp_path / "places_fixture.csv"
    places().reset_index(drop=True).to_csv(places_file, index=False)
    review = tmp_path / "review.csv"
    with review.open("w", newline="", encoding="utf-8") as f:
        fields = list(ref())
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(ref())
    registry = tmp_path / "registry.csv"
    with registry.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "source_id"])
        writer.writeheader()
        writer.writerow({"source": "doh_nhfr", "source_id": "ABC-123"})
    out = tmp_path / "report"
    summary = MODULE.analyze(review_path=review, places_path=places_file, out_dir=out,
                             registry_path=registry, workspace=tmp_path / "example_workspace")
    assert summary["counts"]["candidates"] == 1
    assert summary["distinct_official_registry_records_in_review"] == 1
    assert len(list(out.iterdir())) == 4
    result = json.loads((out / "sigma_qc_institution_evidence_summary_v6.json").read_text())
    assert result["ownership_changes"] == 0
    assert places_file.read_bytes()
    with pytest.raises(FileExistsError):
        MODULE.analyze(review_path=review, places_path=places_file, out_dir=out,
                       registry_path=registry)


def test_duplicate_canonical_ids_fail_closed(tmp_path):
    path = tmp_path / "places.csv"
    duplicated = [{"canonical_id": "duplicate"}, {"canonical_id": "duplicate"}]
    pd.DataFrame(duplicated).to_csv(path, index=False)
    with pytest.raises(ValueError, match="duplicate canonical_id"):
        MODULE.read_places(path)


def test_review_cannot_enable_promotions(tmp_path):
    path = tmp_path / "review.csv"
    r = ref(promotion_allowed="true")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(r))
        w.writeheader()
        w.writerow(r)
    with pytest.raises(ValueError, match="promotion enabled"):
        MODULE.read_review(path)


def test_refuses_workspace_as_output(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    with pytest.raises(ValueError, match="outside SIGMA workspace"):
        MODULE.analyze(review_path=tmp_path / "dummy.csv", places_path=tmp_path / "places.csv",
                       out_dir=ws / "report", workspace=ws)

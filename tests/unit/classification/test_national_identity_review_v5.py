"""Read-only relationship triage must never manufacture verified branch links."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sigma.classification.registry import Institution

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "sigma_national_identity_review_v5", ROOT / "scripts" / "sigma_national_identity_review.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def hospital(name="The Medical City", city="Pasig City", side="private"):
    return Institution("philhealth_hospitals", "2026-09-30:row-1", name,
                       "health", side, city, "Ortigas Avenue", (),
                       "https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_093026.pdf",
                       "2026-09-30", "publication_row", "explicit_sector")


def test_cross_city_can_be_branch_candidate_but_never_verified():
    source = hospital()
    row = {"name": "The Medical City", "io80_code": "",
           "registry_status": "NAME_LOCATION_UNVERIFIED", "registry_ownership": "private",
           "registry_ids": "philhealth_hospitals:2026-09-30:row-1"}
    results, summary = MODULE.review_rows([row], [source], workspace_city="Quezon City")
    got = results[0]
    assert got["relationship_hypothesis"] == "CROSS_LOCALITY_BRANCH_OR_AFFILIATE_CANDIDATE"
    assert got["ownership_opportunity"] == "CURRENT_IO80_UNASSIGNED"
    assert got["promotion_allowed"] == "false"
    assert got["registered_id_kind"] == "publication_row"
    assert summary["total"] == 1


def test_same_city_still_cannot_prove_establishment_identity():
    row = {"name": "The Medical City", "io80_code": "77", "registry_status": "EXACT_NAME_CITY",
           "registry_ownership": "private", "registry_ids": "philhealth_hospitals:2026-09-30:row-1"}
    got, _ = MODULE.review_rows([row], [hospital(city="Quezon City")],
                                workspace_city="Quezon City")
    assert got[0]["relationship_hypothesis"] == "SAME_LOCALITY_SITE_CANDIDATE"
    assert got[0]["promotion_allowed"] == "false"
    assert got[0]["ownership_opportunity"] == "CURRENT_IO80_ALREADY_AGREES"


def test_conflict_does_not_infer_any_official_identity():
    row = {"name": "A College", "io80_code": "", "registry_status": "CANONICAL_NAME_CONFLICT",
           "registry_ownership": "", "registry_ids": ""}
    got, _ = MODULE.review_rows([row], [hospital()], workspace_city="Quezon City")
    assert got[0]["relationship_hypothesis"] == "IDENTITY_CONFLICT_REVIEW"
    assert got[0]["ownership_opportunity"] == "IDENTITY_REVIEW_FIRST"
    assert got[0]["promotion_allowed"] == "false"


def test_same_name_conflicting_registry_ownership_stays_review():
    row = {"name": "The Medical City", "io80_code": "76", "registry_status": "NAME_LOCATION_UNVERIFIED",
           "registry_ownership": "private", "registry_ids": "philhealth_hospitals:2026-09-30:row-1"}
    got, _ = MODULE.review_rows([row], [hospital()], workspace_city="Quezon City")
    assert got[0]["ownership_opportunity"] == "CURRENT_IO80_DISAGREES_REVIEW"
    assert got[0]["promotion_allowed"] == "false"



def test_hospital_without_structured_city_only_provisional():
    source=hospital(city="")
    row={"name":"The Medical City","io80_code":"","registry_status":"NAME_LOCATION_UNVERIFIED",
         "registry_ownership":"private","registry_ids":"philhealth_hospitals:2026-09-30:row-1"}
    got,_=MODULE.review_rows([row],[source],workspace_city="Quezon City")
    assert got[0]["promotion_allowed"]=="false"

"""Bounded load-time ownership promotion: only independently supported evidence."""
from dataclasses import dataclass

import pandas as pd
import pytest

from sigma.classification import ownership_promotion as promotion


@dataclass
class Industry:
    io16_code: str
    io80_label: str


CATALOG = {
    "74": Industry("14", "Public education"),
    "75": Industry("14", "Private education"),
}


def place(**kw):
    x = {
        "psic_code": "852", "psic_status": "SINGLE",
        "io80_codes": "74; 75", "io240_codes": "229; 230",
        "io80_names": "Public education | Private education",
        "io240_names": "Public education | Private education",
        "io16_code": "14", "io80_code": "75", "io240_code": "230",
        "io80_source": "psic+ownership", "io240_source": "psic+ownership",
        "io80_label": "Private education", "io240_label": "Private education",
        "io80_status": "OWNERSHIP_RESOLVED", "io240_status": "OWNERSHIP_RESOLVED",
        "ownership_domain": "education", "ownership_side": "private",
        "ownership_reason": "name:old_private_heuristic",
    }
    x.update(kw)
    return x


def proposal(basis, status="PROPOSED_IO", **kw):
    x = {
        "shadow_status": status, "shadow_basis": basis,
        "shadow_registry_status": "EXACT_EXTERNAL_ID",
        "shadow_registry_ids": "deped_public:136544",
        "shadow_registry_urls": "https://www.depedncr.com.ph/directory-of-public-schools/",
        "shadow_baseline_conflict": "baseline_private_vs_public",
        "shadow_io80": "74", "shadow_io240": "229",
        "shadow_domain": "education", "shadow_side": "public",
    }
    x.update(kw)
    return x


def run(monkeypatch, response, data=None):
    class FakeShadowResolver:
        def __init__(self, *args, **kwargs):
            pass

        def resolve(self, row):
            return dict(response)

    monkeypatch.setattr(promotion, "ShadowResolver", FakeShadowResolver)
    return promotion.promote_institutions(
        pd.DataFrame([data or place()]), taxonomy=object(), io_mapping=object(),
        catalog=CATALOG, area_slug="elsewhere", registry_index=object(), registry_links={},
    ).iloc[0]


@pytest.mark.parametrize("basis", ["official_registry_external_id", "explicit_source_attribute", "verified_canonical_registry_link"])
def test_promoted_evidence_corrects_name_heuristic(monkeypatch, basis):
    got = run(monkeypatch, proposal(basis))
    assert (got["io80_code"], got["io240_code"]) == ("74", "229")
    assert (got["io80_label"], got["io240_label"]) == ("Public education", "Public education")
    assert got["institution_promotion_status"] == "PROMOTED"
    assert got["ownership_side"] == "public"
    assert got["psic_code"] == "852"
    assert got["io80_codes"] == "74; 75"


def test_name_city_registry_match_is_not_promoted(monkeypatch):
    got = run(monkeypatch, proposal("official_registry_name_city_provisional", shadow_registry_status="EXACT_NAME_CITY"))
    assert got["institution_promotion_status"] == "PROVISIONAL_NOT_PROMOTED"
    assert got["io80_code"] == "75"


def test_operator_proxy_is_not_promoted(monkeypatch):
    got = run(monkeypatch, proposal("government_operator_proxy", shadow_registry_status="NO_MATCH"))
    assert got["institution_promotion_status"] == "PROVISIONAL_NOT_PROMOTED"
    assert got["io240_code"] == "230"


def test_explicit_registry_id_must_be_exact(monkeypatch):
    got = run(monkeypatch, proposal("official_registry_external_id", shadow_registry_status="EXACT_NAME_CITY"))
    assert got["institution_promotion_status"] == "UNVERIFIED_ID"
    assert got["io80_code"] == "75"


def test_strong_existing_psic_direct_resolution_never_overridden(monkeypatch):
    got = run(monkeypatch, proposal("explicit_source_attribute"), place(io80_source="psic+direct"))
    assert got["institution_promotion_status"] == "STRONG_BASELINE_CONFLICT"
    assert got["io80_code"] == "75"


def test_io16_mismatch_blocks_refinement(monkeypatch):
    got = run(monkeypatch, proposal("explicit_source_attribute"), place(io16_code="03"))
    assert got["institution_promotion_status"] == "IO_LEVEL_CONFLICT"
    assert got["io80_code"] == "75"


def test_psic_activity_block_not_promoted(monkeypatch):
    got = run(monkeypatch, proposal("", status="BLOCKED_UPSTREAM"))
    assert got["institution_promotion_status"] == "BLOCKED_UPSTREAM"
    assert got["io80_code"] == "75"


def test_noninstitution_record_unchanged(monkeypatch):
    got = run(monkeypatch, proposal("explicit_source_attribute"), place(io80_codes="01", io240_codes="001"))
    assert not got["institution_promotion_status"]
    assert got["io80_code"] == "75"


def test_empty_frame_returns_stable_columns():
    frame = pd.DataFrame(columns=["io80_codes", "io240_codes"])
    got = promotion.promote_institutions(frame, taxonomy=object(), io_mapping=object(), catalog=CATALOG)
    assert list(got.columns)[-len(promotion.AUDIT_COLUMNS):] == list(promotion.AUDIT_COLUMNS)

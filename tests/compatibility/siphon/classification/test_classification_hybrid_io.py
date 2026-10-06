from __future__ import annotations

import pandas as pd

from sigma.classification.hybrid_io import apply_hybrid_io, direct_io_evidence


def _base(**overrides):
    row = {
        "name": "Sample Bank",
        "category": "amenity=bank",
        "osm_name": "Sample Bank",
        "osm_category": "amenity=bank",
        "overture_name": "",
        "overture_category": "",
        "psic_status": "CANDIDATES_ONLY",
        "psic_flags": "",
        "io16_codes": "",
        "io16_map_code": "",
        "io80_codes": "",
        "io80_map_code": "",
        "io240_codes": "",
        "io240_map_code": "",
        "io240_names": "",
    }
    row.update(overrides)
    return row


def test_direct_bank_evidence_is_io80_66():
    decision = direct_io_evidence(_base())
    assert decision.status == "SINGLE"
    assert decision.io80_code == "66"
    assert decision.io16_code == "10"
    assert decision.sources == ("osm",)


def test_direct_evidence_resolves_inside_psic_candidate_set():
    frame = pd.DataFrame(
        [
            _base(
                io16_codes="10",
                io16_map_code="10",
                io80_codes="65; 66",
            )
        ]
    )
    out = apply_hybrid_io(frame)
    assert out.loc[0, "io80_code"] == "66"
    assert out.loc[0, "io80_status"] == "HYBRID_RESOLVED"
    assert out.loc[0, "io80_source"] == "psic+direct"
    assert out.loc[0, "io16_code"] == "10"


def test_direct_evidence_cannot_override_psic_candidate_set():
    frame = pd.DataFrame([_base(io80_codes="55; 56")])
    out = apply_hybrid_io(frame)
    assert out.loc[0, "io80_code"] == ""
    assert out.loc[0, "io80_status"] == "PSIC_DIRECT_CONFLICT"


def test_direct_fallback_is_allowed_when_psic_has_no_io_candidates():
    frame = pd.DataFrame([_base()])
    out = apply_hybrid_io(frame)
    assert out.loc[0, "io80_code"] == "66"
    assert out.loc[0, "io80_status"] == "DIRECT_FALLBACK"
    assert out.loc[0, "io16_code"] == "10"


def test_direct_fallback_is_blocked_for_non_activity():
    frame = pd.DataFrame([_base(psic_status="NOT_PSIC_ACTIVITY")])
    out = apply_hybrid_io(frame)
    assert out.loc[0, "io80_code"] == ""
    assert out.loc[0, "io80_status"] == "DIRECT_BLOCKED_BY_PSIC_POLICY"


def test_psic_singleton_remains_authoritative_on_direct_disagreement():
    frame = pd.DataFrame([_base(io80_codes="65", io80_map_code="65")])
    out = apply_hybrid_io(frame)
    assert out.loc[0, "io80_code"] == "65"
    assert out.loc[0, "io80_status"] == "PSIC_DIRECT_DISAGREE"
    assert out.loc[0, "io80_source"] == "psic"


def test_io240_remains_psic_only():
    frame = pd.DataFrame(
        [
            _base(
                io240_codes="123",
                io240_map_code="123",
                io240_names="Example IO240 industry",
            )
        ]
    )
    out = apply_hybrid_io(frame)
    assert out.loc[0, "io240_code"] == "123"
    assert out.loc[0, "io240_label"] == "Example IO240 industry"
    assert out.loc[0, "io240_source"] == "psic"

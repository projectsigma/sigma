"""Contract for coarse_policy='contain': a coarse place joins a sector only when the
sector contains all of its IO240 candidates; a parent is kept whole when too many of its
places would straddle its split."""
import numpy as np
import pandas as pd
import pytest

from sigma.economy import Economy, Sector, SectorCatalog
from sigma.economy.hierarchical import build_hierarchical_economy
from sigma.errors import EconomyValidationError

LEAVES = ("B", "D", "M", "S", "C", "L", "Q", "V")


def source():
    n = len(LEAVES)
    z = np.arange(1, n * n + 1, dtype=float).reshape((n, n))
    e = Economy(
        economy_id="synthetic-io240",
        sectors=SectorCatalog(Sector(c, f"Sector {c}") for c in LEAVES),
        raw_transactions=pd.DataFrame(z, index=LEAVES, columns=LEAVES),
        total_output=pd.Series(np.arange(101, 101 + n, dtype=float), index=LEAVES),
    )
    h = pd.DataFrame([
        ("B", "F", "MAN"), ("D", "F", "MAN"), ("M", "F", "MAN"),
        ("S", "F", "MAN"), ("C", "T", "MAN"), ("L", "T", "MAN"),
        ("Q", "Q80", "MAN"), ("V", "V80", "SRV"),
    ], columns=["io240_code", "io80_code", "io16_code"])
    return e, h


def places(rows):
    """rows: (io240, io80, io16, io240 candidates)."""
    return pd.DataFrame(rows, columns=["io240_code", "io80_code", "io16_code", "io240_codes"])


def members(result):
    return result.membership.groupby("economy_code").io240_code.apply(list).to_dict()


def test_candidates_inside_one_sector_are_assigned_there():
    e, h = source()
    p = places([("B", "F", "MAN", "B")] * 4 + [("", "F", "MAN", "D; M")])
    r = build_hierarchical_economy(p, e, h, min_places=2)
    # B is its own sector; D, M, S form F-Other, which holds both candidates.
    assert r.places.economy_status.iloc[-1] == "IO80_CANDIDATES"
    assert set(members(r)[r.places.economy_code.iloc[-1]]) == {"D", "M", "S"}


def test_straddling_minority_is_left_unassigned_not_guessed():
    e, h = source()
    p = places([("B", "F", "MAN", "B")] * 9 + [("", "F", "MAN", "B; D")])
    r = build_hierarchical_economy(p, e, h, min_places=2)
    assert r.places.economy_code.iloc[-1] == ""
    assert r.places.economy_status.iloc[-1] == "UNASSIGNED_IO80_STRADDLES"
    assert r.diagnostics["straddling_unassigned_place_count"] == 1
    assert r.diagnostics["kept_whole_parents"] == []


def test_parent_is_kept_whole_when_straddlers_exceed_the_share():
    e, h = source()
    p = places([("B", "F", "MAN", "B")] * 6 + [("", "F", "MAN", "B; D")] * 3)
    r = build_hierarchical_economy(p, e, h, min_places=2, max_straddle_share=0.25)
    assert members(r)["80:F"] == ["B", "D", "M", "S"]
    assert set(r.places.economy_code) == {"80:F"}
    assert set(r.places.economy_status) == {"IO240_FOLDED", "IO80"}
    assert r.places.economy_code.ne("").all()
    assert r.diagnostics["kept_whole_parents"] == [
        {"level": "io80", "code": "F", "straddling_places": 3, "exactly_assigned_places": 6}
    ]
    # With a higher share the split is kept and the straddlers are left unassigned.
    split = build_hierarchical_economy(p, e, h, min_places=2, max_straddle_share=0.5)
    assert split.places.economy_status.tolist().count("UNASSIGNED_IO80_STRADDLES") == 3


def test_no_coarse_place_is_assigned_outside_its_candidates():
    e, h = source()
    rows = ([("B", "F", "MAN", "B")] * 5 + [("D", "F", "MAN", "D")] * 5
            + [("", "F", "MAN", "M; S")] * 2 + [("", "", "MAN", "C; L")] + [("", "T", "MAN", "")])
    for share in (0.0, 0.25, 0.5, 1.0):
        r = build_hierarchical_economy(places(rows), e, h, min_places=2, max_straddle_share=share)
        groups = r.membership.groupby("economy_code").io240_code.apply(set).to_dict()
        for (_, row), (_, src) in zip(r.places.iterrows(), places(rows).iterrows(), strict=True):
            if src.io240_code or not row.economy_code:
                continue
            cand = {c.strip() for c in src.io240_codes.split(";") if c.strip()}
            cand = cand or set(h.loc[h.io80_code.eq(src.io80_code) if src.io80_code
                                     else h.io16_code.eq(src.io16_code), "io240_code"])
            assert cand <= groups[row.economy_code]


def test_missing_candidates_fall_back_to_the_tag_leaves():
    e, h = source()
    p = places([("B", "F", "MAN", "B")] * 3 + [("", "F", "MAN", "")])
    r = build_hierarchical_economy(p, e, h, min_places=2)
    assert r.diagnostics["coarse_candidate_source_counts"]["tag_leaves"] == 1
    assert r.places.economy_status.iloc[-1] == "UNASSIGNED_IO80_STRADDLES"


def test_policy_and_share_are_validated_and_recorded():
    e, h = source()
    p = places([("B", "F", "MAN", "B")])
    with pytest.raises(ValueError, match="coarse_policy"):
        build_hierarchical_economy(p, e, h, coarse_policy="guess")
    with pytest.raises(ValueError, match="max_straddle_share"):
        build_hierarchical_economy(p, e, h, max_straddle_share=1.5)
    r = build_hierarchical_economy(p, e, h)
    assert r.diagnostics["coarse_policy"] == "contain"
    assert r.diagnostics["max_straddle_share"] == 0.25
    legacy = build_hierarchical_economy(p, e, h, coarse_policy="residual")
    assert legacy.diagnostics["max_straddle_share"] is None


def test_strict_coarse_rejects_straddlers():
    e, h = source()
    p = places([("B", "F", "MAN", "B")] * 9 + [("", "F", "MAN", "B; D")])
    with pytest.raises(EconomyValidationError, match="no single sector contains"):
        build_hierarchical_economy(p, e, h, min_places=2, strict_coarse=True)


def test_totals_are_conserved_when_parents_are_kept_whole():
    e, h = source()
    p = places([("B", "F", "MAN", "B")] * 2 + [("", "", "MAN", "")] * 5)
    r = build_hierarchical_economy(p, e, h, min_places=2)
    assert np.isclose(r.economy.Z_raw.to_numpy().sum(), e.Z_raw.to_numpy().sum())
    assert np.isclose(r.economy.x.sum(), e.x.sum())
    assert r.membership.io240_code.is_unique and len(r.membership) == len(LEAVES)


def test_profile_records_policy_and_old_profiles_default(tmp_path, monkeypatch):
    import json

    from sigma.economy import hierarchical_auto

    monkeypatch.setattr(hierarchical_auto, "sigma_home", lambda: tmp_path)
    path = hierarchical_auto.profile_path()
    path.write_text(json.dumps({
        "schema_version": 1, "mode": "area_hierarchical", "io240_dir": "x", "crosswalk": "y",
        "min_places": 5, "check_psa": True,
    }))
    profile = hierarchical_auto.read_profile()
    assert profile["coarse_policy"] == "residual" and profile["max_straddle_share"] == 0.25
    path.write_text(json.dumps({**profile, "coarse_policy": "guess"}))
    with pytest.raises(EconomyValidationError):
        hierarchical_auto.read_profile()


def test_disjoint_candidate_set_is_conflict_even_when_parent_whole():
    e, h = source()
    rows = [("B", "F", "MAN", "B")] * 3 + [("", "F", "MAN", "V")]
    r = build_hierarchical_economy(places(rows), e, h, min_places=2)
    assert r.places.economy_code.iloc[-1] == ""
    assert r.places.economy_status.iloc[-1] == "UNASSIGNED_CANDIDATE_CONFLICT"
    assert r.places.economy_candidate_source.iloc[-1] == "candidate_conflict"
    assert r.places.economy_evidence.iloc[-1] == "candidate_conflict"
    assert bool(r.places.economy_review_required.iloc[-1])
    assert r.diagnostics["candidate_conflict_place_count"] == 1
    assert r.diagnostics["economy_review_required_count"] >= 1
    # Historical residual assignment is not permitted to erase an inconsistency.
    old = build_hierarchical_economy(places(rows), e, h, min_places=2, coarse_policy="residual")
    assert old.places.economy_status.iloc[-1] == "UNASSIGNED_CANDIDATE_CONFLICT"
    with pytest.raises(EconomyValidationError, match="incompatible"):
        build_hierarchical_economy(places(rows), e, h, min_places=2, strict_coarse=True)


def test_provisional_mapping_is_marked_unverified_without_removing_assignment():
    e, h = source()
    p = places([("B", "F", "MAN", "B"), ("D", "F", "MAN", "D")])
    p["io_mapping_provisional"] = ["true", "false"]
    r = build_hierarchical_economy(p, e, h, min_places=1)
    assert r.places.economy_code.ne("").all()
    assert r.places.economy_evidence.tolist() == ["provisional_mapping", "exact_tag_unverified"]
    assert r.places.economy_review_required.tolist() == [True, False]
    assert r.places.economy_evidence_flags.tolist() == ["provisional_mapping", "exact_tag_unverified"]
    assert r.diagnostics["economy_evidence_counts"]["provisional_mapping"] == 1


def test_low_concordance_confidence_is_review_required():
    e, h = source()
    p = places([("B", "F", "MAN", "B")])
    p["io240_confidence"] = "Low"
    r = build_hierarchical_economy(p, e, h)
    assert r.places.economy_evidence.iloc[0] == "low_concordance_confidence"
    assert bool(r.places.economy_review_required.iloc[0])

"""BEIS user-supplied identity data: no automatic ownership promotion."""
from __future__ import annotations

import csv

import pytest

from sigma.classification.beis_registry import (
    BEISIndex, BEISSchool, LayeredInstitutionIndex, load_beis,
    packaged_beis, school_owner_from_id,
)
from sigma.classification.registry import Match


def rec(code="123456", name="San Isidro Elementary School", town="1381300000"):
    return BEISSchool(code, name, town, school_owner_from_id(code))


def test_conventional_six_digit_school_prefix_only():
    for prefix in "12356":
        assert school_owner_from_id(prefix + "12345") == "public"
    assert school_owner_from_id("412345") == "private"
    for code in ("977201", "1403451", "11002", "", "not-an-id"):
        assert school_owner_from_id(code) == ""


def test_identity_by_name_and_psgc_is_not_promotable():
    index = BEISIndex([rec(), rec("223456", town="1380100000")])
    got = index.match({"name": "San Isidro Elementary School",
                       "town_psgc": "1381300000"}, "education")
    assert got.status == "BEIS_NAME_PSGC_PROVISIONAL"
    assert got.side == "public"
    assert got.source_ids == "deped_beis:123456"
    assert got.status != "EXACT_EXTERNAL_ID"
    assert got.source_urls == ""


def test_repeated_names_without_psgc_cannot_choose_school():
    idx = BEISIndex([rec(), rec("223456", town="1380100000")])
    got = idx.match({"name": "San Isidro Elementary School"}, "education")
    assert got.status == "IDENTITY_AMBIGUOUS"


def test_duplicate_name_same_municipality_remains_ambiguous():
    idx = BEISIndex([rec(), rec("223456")])
    got = idx.match({"name": "San Isidro Elementary School",
                     "town_psgc": "1381300000"}, "education")
    assert got.status == "IDENTITY_AMBIGUOUS"


def test_exact_id_with_matching_name_still_provisional_without_provenance():
    idx = BEISIndex([rec("412345")])
    got = idx.match({"name": "San Isidro Elementary School",
                     "deped_school_id": "412345",
                     "town_psgc": "1381300000"}, "education")
    assert got.status == "BEIS_ID_PROVISIONAL"
    assert got.side == "private"
    assert got.status != "EXACT_EXTERNAL_ID"


def test_exact_school_id_with_wrong_name_fails_closed():
    idx = BEISIndex([rec()])
    got = idx.match({"name": "Other School", "deped_school_id": "123456"}, "education")
    assert got.status == "EXTERNAL_ID_NAME_CONFLICT"


def test_contradictory_municipality_blocks_match():
    idx = BEISIndex([rec()])
    got = idx.match({"name": "San Isidro Elementary School",
                     "town_psgc": "1380100000"}, "education")
    assert got.status == "CITY_CONFLICT"


def test_unsupported_prefix_remains_identity_only():
    idx = BEISIndex([rec("1403451")])
    got = idx.match({"name": "San Isidro Elementary School",
                     "town_psgc": "1381300000"}, "education")
    assert got.status == "BEIS_OWNERSHIP_UNKNOWN"
    assert got.side == ""


def test_no_education_evidence_for_health():
    assert BEISIndex([rec()]).match({"name": rec().name}, "health").status == "NO_MATCH"


def test_layer_abstains_on_overlap():
    class Base:
        def match(self, row, domain):
            return Match("EXACT_NAME_CITY", "public", "unique_name_city_provisional",
                         "independent_school_index", "other:321", "San Isidro Elementary School")
    got = LayeredInstitutionIndex(Base(), BEISIndex([rec()])).match(
        {"name": "San Isidro Elementary School"}, "education")
    assert got.status == "IDENTITY_AMBIGUOUS"


def test_packaged_entire_beis_extract_and_no_duplicates():
    schools = packaged_beis()
    assert len(schools) == 30364
    assert len({x.school_id for x in schools}) == len(schools)
    assert len({x.town_psgc for x in schools}) == 1593


def test_loader_rejects_repeated_id(tmp_path):
    f = tmp_path / "schools.csv"
    with f.open('w', encoding='utf-8', newline='') as out:
        w = csv.writer(out)
        w.writerow(("school_id", "school_name", "town_psgc"))
        w.writerow(("123456", "School A", "1381300000"))
        w.writerow(("123456", "School B", "1381300000"))
    with pytest.raises(ValueError, match="duplicate BEIS"):
        load_beis(f)

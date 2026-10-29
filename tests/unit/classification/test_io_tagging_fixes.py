"""Regression tests for the IO tagging review fixes (refinement, retargets, direct rules,
ownership, level consistency, union mapping)."""
from __future__ import annotations

import pandas as pd
import pytest

from sigma.classification import (
    EconomicTagger,
    TaggingReferences,
    classify_psic,
    load_builtin_io_reference,
    load_builtin_psic_taxonomy,
)
from sigma.classification.hybrid_io import apply_hybrid_io, direct_io_evidence
from sigma.classification.io_mapping import IOMapping
from sigma.classification.io_mapping_compat import deterministic_code, deterministic_matches
from sigma.classification.ownership import ownership_evidence
from sigma.classification.reference import (
    IOBridgeRow,
    IOConcordanceRow,
    IOParentRow,
    IOReferenceCatalog,
    IORefinementRow,
    PsicNode,
    PsicTaxonomy,
)
from sigma.economy import Economy


@pytest.fixture(scope="module")
def taxonomy():
    return load_builtin_psic_taxonomy()


@pytest.fixture(scope="module")
def mapping(taxonomy):
    return IOMapping.load_builtin(taxonomy)


def _tag(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["canonical_id"] = [f"t{i}" for i in range(len(frame))]
    tx = load_builtin_psic_taxonomy()
    economy = Economy.builtin("io80")
    psic = classify_psic(frame)
    references = TaggingReferences.builtin(tx, economy)
    return EconomicTagger(taxonomy=tx, economy=economy, references=references).tag(psic)


# ---- reference data --------------------------------------------------------

def test_parent_table_covers_all_240_codes_and_nests_in_catalog():
    from sigma.classification.io_mapping_compat import load_catalog

    ref = load_builtin_io_reference()
    parents = ref.io240_parent_map
    assert sorted(parents) == [f"{i:03d}" for i in range(1, 241)]
    assert set(parents.values()) == set(load_catalog())


def test_every_refinement_row_strictly_narrows_its_unrefined_mapping(taxonomy, mapping):
    ref = load_builtin_io_reference()
    assert ref.refinement and not ref.refinement_issues(taxonomy)
    for row in ref.refinement:
        result = mapping.map_psic(row.rev5_code)
        assert result["io_mapping_refinement_basis"] == row.basis, row.rev5_code
        assert result["io240_codes"] == "; ".join(row.io240_codes)


@pytest.mark.parametrize("code, io240, io80", [
    ("01121", "001", "01"),   # rice in irrigated lowland -> Palay
    ("10711", "060", "27"),   # baking of bread -> bakery products
    ("85101", "229", "74"),   # public pre-school -> public education
    ("86122", "232", "77"),   # private mental hospital -> private health
    ("96212", "237", "80"),   # barber -> beauty treatment and grooming
])
def test_subclass_refinement_reaches_one_io240(mapping, code, io240, io80):
    result = mapping.map_psic(code)
    assert result["io240_map_code"] == io240
    assert result["io80_map_code"] == io80
    assert result["io_mapping_provisional"] == "true"


def test_group_level_code_is_not_refined(mapping):
    result = mapping.map_psic("011")
    assert result["io_mapping_refinement_code"] == ""
    assert result["io240_map_status"] == "AMBIGUOUS_SET"


def test_refinement_that_would_widen_the_set_is_not_applied():
    taxonomy = PsicTaxonomy([
        PsicNode("A", "section", "Agriculture"),
        PsicNode("01", "division", "Crops", "A"),
        PsicNode("011", "group", "Cereals", "01"),
        PsicNode("0111", "class", "Rice", "011"),
    ])
    catalog = IOReferenceCatalog(
        bridge=(IOBridgeRow("group", "011", "Cereals", ("011",), "same", "reviewed"),),
        concordance=(IOConcordanceRow(
            "group", "011", "Cereals", ("01",), ("Agri",), "High",
            ("01", "02"), ("Palay", "Corn"), "High", ("001", "002"), ("Palay", "Corn"), "High"),),
        bridge_sha256="b", concordance_sha256="c",
        refinement=(IORefinementRow("class", "0111", "Rice", ("003",), "draft"),),
        io240_parents=tuple(
            IOParentRow(code, parent, "concordance")
            for code, parent in (("001", "01"), ("002", "02"), ("003", "03"))
        ),
    )
    result = IOMapping(taxonomy, catalog).map_psic("0111")
    assert result["io_mapping_refinement_basis"] == "not_applied"
    assert result["io240_codes"] == "001; 002"


def test_union_mapping_is_the_union_of_member_sets(mapping):
    result = mapping.map_union(["551", "552", "553", "559"])
    assert result["io_mapping_status"] in {"MAPPED_UNION", "PROVISIONAL_UNION"}
    assert result["io240_codes"] == "191; 192"
    assert result["io80_map_code"] == "62"
    assert mapping.map_union(["1071", "47214"])["io80_map_status"] == "AMBIGUOUS_SET"


# ---- category targets, name rules and precedence ----------------------------

@pytest.mark.parametrize("row, psic, io80", [
    ({"osm_name": "Panaderia", "osm_category": "shop=bakery"}, "47214", "55"),
    ({"osm_name": "Nails", "osm_category": "shop=beauty"}, "962", "80"),
    ({"overture_name": "Bank A", "overture_category": "bank"}, "641", "66"),
    ({"overture_name": "Bank B", "overture_category": "bank_or_credit_union"}, "641", "66"),
    ({"osm_name": "Pension", "osm_category": "tourism=guest_house"}, "552", "62"),
    ({"osm_name": "Hotel Sogo", "osm_category": "tourism=hotel | cuisine=filipino"}, "551", "62"),
])
def test_retargeted_categories_reach_one_io80(row, psic, io80):
    out = _tag([row])
    assert out.loc[0, "psic_code"] == psic
    assert out.loc[0, "io80_code"] == io80


def test_overture_lodging_is_a_union_with_one_io80():
    out = _tag([{"overture_name": "Inn", "overture_category": "lodging"}])
    assert out.loc[0, "psic_status"] == "UNION"
    assert out.loc[0, "io240_codes"] == "191; 192"
    assert out.loc[0, "io80_code"] == "62"


def test_category_floor_overrules_a_disjoint_name_rule():
    out = classify_psic(pd.DataFrame([
        {"osm_name": "Grand Restaurant", "osm_category": "tourism=hotel | cuisine=filipino"},
    ]))
    assert out.loc[0, "psic_code"] == "551"
    assert "NAME_RULE_OVERRULED_BY_CATEGORY" in out.loc[0, "psic_flags"]


@pytest.mark.parametrize("name, expected", [
    ("ABC Construction Supply", ""),
    ("Builder's Depot", ""),
    ("JM Construction", "F"),
    ("Builders Hardware", "4752"),
])
def test_construction_name_rule_excludes_supply_stores(name, expected):
    out = classify_psic(pd.DataFrame([{"osm_name": name}]))
    assert out.loc[0, "psic_code"] == expected


# ---- direct IO80 rules -------------------------------------------------------

@pytest.mark.parametrize("category", [
    "shop=carpet", "shop=caravan", "amenity=public_bath", "amenity=public_bookcase",
    "amenity=public_building",
])
def test_direct_rules_do_not_match_substrings(category):
    assert deterministic_matches(category) == []


def test_direct_rules_prefer_primary_tags_and_never_read_names():
    assert deterministic_code("x", "tourism=hotel | cuisine=filipino")[0] == "62"
    assert deterministic_code("x", "amenity=fast_food | cuisine=burger")[0] == "63"
    assert deterministic_code("ABC Shop Cart Grocery", "") is None


def test_direct_rules_with_disagreeing_tags_are_a_conflict():
    assert {code for code, _ in deterministic_matches("shop=mall | amenity=cinema")} == {"55", "79"}
    row = {"osm_name": "Mall", "osm_category": "shop=mall | amenity=cinema"}
    evidence = direct_io_evidence(row)
    assert evidence.status == "CONFLICT"


# ---- ownership --------------------------------------------------------------

@pytest.mark.parametrize("domain, name, side", [
    ("education", "Bagong Silang National High School", "public"),
    ("education", "Holy Spirit Academy", "private"),
    ("education", "St. Joseph Elementary School", "private"),
    ("education", "University of Santo Tomas", ""),
    ("health", "Rural Health Unit I", "public"),
    ("health", "Smile Dental Clinic", "private"),
    ("health", "City Health Office Clinic", "public"),
])
def test_ownership_evidence_abstains_unless_one_sided(domain, name, side):
    assert ownership_evidence({"osm_name": name}, domain).side == side


def test_ownership_resolves_only_inside_the_pair():
    row = {
        "osm_name": "Bagong Silang National High School", "osm_category": "amenity=school",
        "psic_status": "SINGLE", "psic_flags": "",
        "io16_codes": "14", "io16_map_code": "14",
        "io80_codes": "74; 75", "io80_map_code": "",
        "io240_codes": "229; 230", "io240_map_code": "",
        "io240_names": "Public education | Private education",
    }
    out = apply_hybrid_io(pd.DataFrame([row]))
    assert out.loc[0, "io80_code"] == "74"
    assert out.loc[0, "io80_status"] == "OWNERSHIP_RESOLVED"
    assert out.loc[0, "io240_code"] == "229"
    assert out.loc[0, "io240_label"] == "Public education"
    disabled = apply_hybrid_io(pd.DataFrame([row]), ownership=False)
    assert disabled.loc[0, "io80_code"] == ""


@pytest.mark.parametrize("category, side, expected_io80, expected_io240", [
    ("private_school | place_of_learning", "private", "75", "230"),
    ("public_school | place_of_learning", "public", "74", "229"),
])
def test_education_explicit_source_category_resolves_only_with_candidate_pair(
    category, side, expected_io80, expected_io240,
):
    row = {
        "overture_name": "Generic Educational Institution",
        "overture_category": category,
        "psic_status": "SINGLE", "psic_flags": "",
        "io16_codes": "14", "io16_map_code": "14",
        "io80_codes": "74; 75", "io80_map_code": "",
        "io240_codes": "229; 230", "io240_map_code": "",
        "io240_names": "Public education | Private education",
    }
    evidence = ownership_evidence(row, "education")
    assert evidence.side == side
    assert evidence.reason.startswith("category:overture:")
    tagged = apply_hybrid_io(pd.DataFrame([row]))
    assert tagged.loc[0, "io80_code"] == expected_io80
    assert tagged.loc[0, "io240_code"] == expected_io240
    assert tagged.loc[0, "io80_status"] == "OWNERSHIP_RESOLVED"
    assert tagged.loc[0, "io240_status"] == "OWNERSHIP_RESOLVED"

    # Category evidence must not bypass the exact candidate-set guard.
    disallowed = dict(row, io80_codes=expected_io80, io240_codes=expected_io240)
    disallowed_tagged = apply_hybrid_io(pd.DataFrame([disallowed]))
    assert disallowed_tagged.loc[0, "ownership_domain"] == ""
    assert disallowed_tagged.loc[0, "ownership_side"] == ""


@pytest.mark.parametrize("row, expected_reason", [
    ({"overture_name": "Generic School", "overture_category": "school"}, "no_evidence"),
    ({"overture_name": "Generic School", "overture_category": "private_school_supplies"}, "no_evidence"),
    ({"overture_name": "Generic School", "overture_category": "private_school | public_school"}, "contradictory"),
    ({"overture_name": "Bagong Silang National High School", "overture_category": "private_school"}, "contradictory"),
    ({"overture_name": "ABC Private Elementary School", "overture_category": "public_school"}, "contradictory"),
    ({"overture_name": "Private Academy", "overture_category": "public_school"}, "contradictory"),
])
def test_education_category_evidence_abstains_on_ambiguity(row, expected_reason):
    result = ownership_evidence(row, "education")
    assert result.side == ""
    assert result.reason == expected_reason


# ---- level consistency -------------------------------------------------------

def test_level_guard_keeps_psic_tag_and_derives_its_parents():
    row = {
        "osm_name": "Sample Bank", "osm_category": "amenity=bank",
        "psic_status": "SINGLE", "psic_flags": "",
        "io16_codes": "", "io16_map_code": "", "io80_codes": "", "io80_map_code": "",
        "io240_codes": "123", "io240_map_code": "123", "io240_names": "Basic iron and steel",
    }
    out = apply_hybrid_io(pd.DataFrame([row]))
    assert out.loc[0, "io240_code"] == "123"
    assert out.loc[0, "io80_status"] == "DERIVED_FROM_IO240"
    assert out.loc[0, "io16_status"] == "DERIVED_FROM_IO80"
    parents = load_builtin_io_reference().io240_parent_map
    assert out.loc[0, "io80_code"] == parents["123"]


def test_tagger_output_levels_always_nest():
    from sigma.classification.io_mapping_compat import load_catalog

    parents = load_builtin_io_reference().io240_parent_map
    catalog = load_catalog()
    out = _tag([
        {"osm_name": "A", "osm_category": "shop=bakery"},
        {"osm_name": "B", "osm_category": "shop=beauty"},
        {"overture_name": "C", "overture_category": "lodging"},
        {"osm_name": "D National High School", "osm_category": "amenity=school"},
        {"osm_name": "E", "osm_category": "shop=car"},
    ])
    for _, row in out.iterrows():
        if row.io240_code and row.io80_code:
            assert parents[row.io240_code] == row.io80_code
        if row.io80_code and row.io16_code:
            assert catalog[row.io80_code].io16_code == row.io16_code


@pytest.mark.parametrize("domain,name,expected", [
    ("education", "ABC Private Elementary School", "private"),
    ("education", "Philippine Military Academy", "public"),
    ("education", "Generic Elementary School", ""),
    ("education", "National High School Private Academy", ""),
    ("health", "Private Health Center", "private"),
    ("health", "Government Medical Clinic", "public"),
    ("health", "Community Health Center", ""),
    ("health", "General Clinic", ""),
    ("health", "Government Medical Clinic Private", ""),
    ("health", "Private Rural Health Unit", ""),
])
def test_ownership_explicit_and_generic_counterexamples(domain, name, expected):
    assert ownership_evidence({"name": name}, domain).side == expected

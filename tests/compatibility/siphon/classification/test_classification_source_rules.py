from __future__ import annotations

from sigma.classification.reference import PsicNode, PsicTaxonomy
from sigma.classification.source_rules import (
    automatic_mapping,
    category_plan,
    prepare_source_evidence,
)
from sigma.classification.types import MappingKind


class Hit:
    def __init__(self, code: str, score: float):
        self.code = code
        self.score = score


class ScriptedRetriever:
    def __init__(self, hits):
        self.hits = hits

    def search_hierarchical(self, query, *, top_n=5, branch_roots=()):
        return [Hit(code, score) for code, score in self.hits[:top_n]]


def _taxonomy() -> PsicTaxonomy:
    return PsicTaxonomy(
        [
            PsicNode("G", "section", "Wholesale and Retail Trade"),
            PsicNode("47", "division", "Retail Trade", "G"),
            PsicNode("477", "group", "Other retail sale", "47"),
            PsicNode("4776", "class", "Retail sale of pets and pet supplies", "477"),
            PsicNode("Q", "section", "Human Health Activities"),
            PsicNode("86", "division", "Human Health Activities", "Q"),
            PsicNode("862", "group", "Medical and dental practice activities", "86"),
            PsicNode("8622", "class", "Dental practice activities", "862"),
            PsicNode("86222", "subclass", "Private dental and laboratory services", "8622"),
            PsicNode("I", "section", "Accommodation and Food Service"),
            PsicNode("56", "division", "Food and beverage service activities", "I"),
            PsicNode("561", "group", "Restaurants and mobile food service activities", "56"),
            PsicNode("563", "group", "Beverage serving activities", "56"),
            PsicNode("R", "section", "Arts, Entertainment and Recreation"),
            PsicNode("93", "division", "Sports activities", "R"),
            PsicNode("962", "group", "Hairdressing and beauty treatment activities", "R"),
        ]
    )


def test_source_plans_keep_curated_branches():
    assert category_plan("osm", "amenity=dentist").branch_roots == ("862",)
    assert category_plan("osm", "shop=hairdresser").branch_roots == ("962",)
    assert category_plan("overture", "dental_clinic").branch_roots == ("862",)
    assert category_plan("overture", "thai_restaurant").branch_roots == ("561",)
    assert category_plan("overture", "pet_store").branch_roots == ("4776",)


def test_trusted_floor_survives_weak_retrieval():
    result = automatic_mapping(
        _taxonomy(),
        ScriptedRetriever([]),
        "overture",
        "dental_clinic",
        min_score=1.1,
        min_margin=1.1,
    )
    assert result.mapping is not None
    assert result.mapping.codes == ("862",)
    assert result.mapping.mapping_kind == MappingKind.SUBTREE
    assert result.reason == "trusted_source_floor"


def test_strong_retrieval_refines_below_floor():
    result = automatic_mapping(
        _taxonomy(),
        ScriptedRetriever([("86222", 0.95), ("862", 0.20)]),
        "overture",
        "dental_clinic",
    )
    assert result.mapping is not None
    assert result.mapping.codes == ("86222",)
    assert result.mapping.mapping_kind == MappingKind.EXACT
    assert result.reason == "semantic_refinement"


def test_non_activity_and_broad_bucket_are_terminal():
    taxonomy = _taxonomy()
    assert (
        prepare_source_evidence(taxonomy, "overture", "park").terminal_kind
        == MappingKind.NOT_ACTIVITY
    )
    assert (
        prepare_source_evidence(taxonomy, "overture", "community_center").terminal_kind
        == MappingKind.UNCODEABLE
    )


def test_compound_osm_evidence_does_not_get_a_floor():
    prepared = prepare_source_evidence(
        _taxonomy(),
        "osm",
        "amenity=dentist | shop=convenience",
    )
    assert prepared.floor_code is None
    assert prepared.block_reason == "compound_source"


def test_osm_auxiliary_tags_do_not_create_false_compound_evidence():
    prepared = prepare_source_evidence(
        _taxonomy(),
        "osm",
        "amenity=dentist | operator=Smile Group",
    )
    assert prepared.floor_code == "862"
    assert prepared.block_reason is None


def test_cafe_with_compatible_shop_tag_keeps_deterministic_floor():
    prepared = prepare_source_evidence(
        _taxonomy(),
        "osm",
        "amenity=cafe | shop=coffee | takeaway=yes",
    )
    assert prepared.floor_code == "563"
    assert prepared.block_reason is None


def test_cafe_with_unrelated_principal_tag_still_requires_review():
    prepared = prepare_source_evidence(
        _taxonomy(),
        "osm",
        "amenity=cafe | shop=convenience",
    )
    assert prepared.floor_code is None
    assert prepared.block_reason == "compound_source"

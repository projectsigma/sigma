from __future__ import annotations

from sigma.classification.crosswalk import CrosswalkIndex
from sigma.classification.engine import PsicClassifier
from sigma.classification.reference import PsicNode, PsicTaxonomy
from sigma.classification.types import MappingKind, MappingRule, SourceField


def _taxonomy() -> PsicTaxonomy:
    return PsicTaxonomy(
        [
            PsicNode("Q", "section", "Human Health Activities"),
            PsicNode("86", "division", "Human Health Activities", "Q"),
            PsicNode("862", "group", "Medical and dental practice activities", "86"),
            PsicNode("I", "section", "Accommodation and Food Service"),
            PsicNode("56", "division", "Food and beverage service activities", "I"),
            PsicNode("561", "group", "Restaurants and mobile food service activities", "56"),
        ]
    )


def test_compatible_name_rule_refines_category_rule():
    crosswalk = CrosswalkIndex(
        [
            MappingRule("overture", "health_care", MappingKind.SUBTREE, ("86",)),
            MappingRule(
                "overture",
                "Smile Dental",
                MappingKind.SUBTREE,
                ("862",),
                source_field=SourceField.NAME,
            ),
        ]
    )
    classifier = PsicClassifier(_taxonomy(), crosswalk)
    decision = classifier.classify_row(
        {
            "sources": "overture",
            "overture_name": "Smile Dental",
            "overture_category": "health_care",
        }
    )
    assert decision.code == "862"
    assert "CROSSWALK_CATEGORY_RULE_OVERRULED_NAME" not in decision.flags


def test_conflicting_specific_name_rule_does_not_override_category_rule():
    crosswalk = CrosswalkIndex(
        [
            MappingRule("overture", "restaurant", MappingKind.SUBTREE, ("561",)),
            MappingRule(
                "overture",
                "Smile Dental",
                MappingKind.SUBTREE,
                ("862",),
                source_field=SourceField.NAME,
            ),
        ]
    )
    classifier = PsicClassifier(_taxonomy(), crosswalk)
    decision = classifier.classify_row(
        {
            "sources": "overture",
            "overture_name": "Smile Dental",
            "overture_category": "restaurant",
        }
    )
    assert decision.code == "561"
    assert "CROSSWALK_CATEGORY_RULE_OVERRULED_NAME" in decision.flags


def test_builtin_reviewed_rules_cover_frequent_gaps_and_names():
    crosswalk = CrosswalkIndex.load_builtin()

    insurance = crosswalk.matches(
        "overture", category="insurance_agency", name=None
    )
    assert insurance.entries
    assert insurance.entries[0].codes == ("66220",)

    transfer = crosswalk.matches(
        "overture", category="money_transfer_service", name=None
    )
    assert transfer.entries
    assert transfer.entries[0].codes == ("66191",)

    cafe = crosswalk.matches(
        "osm", category=None, name="The Daily Grind Cafe"
    )
    assert cafe.entries
    assert cafe.entries[0].codes == ("563",)
    assert cafe.entries[0].source_field == SourceField.NAME


def test_name_only_reviewed_rule_is_deterministic():
    taxonomy = PsicTaxonomy(
        [
            PsicNode("I", "section", "Accommodation and Food Service"),
            PsicNode("56", "division", "Food and beverage service activities", "I"),
            PsicNode("563", "group", "Beverage serving activities", "56"),
        ]
    )
    crosswalk = CrosswalkIndex(
        [
            MappingRule(
                "overture",
                r"(?<!internet )(?<!cyber )\bcaf[eé]\b",
                MappingKind.SUBTREE,
                ("563",),
                match_type="regex",
                source_field=SourceField.NAME,
            )
        ]
    )
    classifier = PsicClassifier(taxonomy, crosswalk, min_score=1.1, min_margin=1.1)
    decision = classifier.classify_row(
        {
            "sources": "overture",
            "overture_name": "Neighborhood Café",
            "overture_category": None,
        }
    )
    assert decision.code == "563"
    assert decision.method == "crosswalk"

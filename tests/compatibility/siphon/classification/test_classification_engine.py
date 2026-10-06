from __future__ import annotations

import pandas as pd

from sigma.classification.crosswalk import CrosswalkIndex
from sigma.classification.engine import PsicClassifier
from sigma.classification.reference import PsicNode, PsicTaxonomy


def _taxonomy() -> PsicTaxonomy:
    return PsicTaxonomy(
        [
            PsicNode("Q", "section", "Human Health Activities"),
            PsicNode("86", "division", "Human Health Activities", "Q"),
            PsicNode("862", "group", "Medical and dental practice activities", "86"),
            PsicNode("8622", "class", "Dental practice activities", "862"),
            PsicNode("86222", "subclass", "Private dental and laboratory services", "8622"),
            PsicNode("I", "section", "Accommodation and Food Service"),
            PsicNode("56", "division", "Food and beverage service activities", "I"),
            PsicNode("561", "group", "Restaurants and mobile food service activities", "56"),
        ]
    )


def _classifier() -> PsicClassifier:
    return PsicClassifier(_taxonomy(), CrosswalkIndex([]), min_score=1.1, min_margin=1.1)


def test_classifier_uses_independent_source_semantics():
    frame = pd.DataFrame(
        [
            {
                "poi_id": "x",
                "name": "Smile Dental",
                "sources": "osm|overture",
                "osm_name": "Smile Dental",
                "osm_category": "amenity=dentist",
                "overture_name": "Smile Dental",
                "overture_category": "dental_clinic",
            }
        ]
    )
    out = _classifier().classify_frame(frame)
    assert out.loc[0, "psic_code"] == "862"
    assert out.loc[0, "psic_method"] == "fusion"
    assert out.loc[0, "psic_evidence_sources"] == "osm|overture"


def test_legacy_single_source_row_is_inferred_safely():
    frame = pd.DataFrame(
        [{"poi_id": "x", "name": "Smile Dental", "category": "amenity=dentist", "sources": "osm"}]
    )
    out = _classifier().classify_frame(frame)
    assert out.loc[0, "psic_code"] == "862"
    assert "LEGACY_SOURCE_FIELDS_INFERRED" in out.loc[0, "psic_flags"]


def test_non_activity_is_not_given_a_psic_code():
    frame = pd.DataFrame(
        [{
            "poi_id": "x",
            "name": "Central Park",
            "sources": "overture",
            "overture_name": "Central Park",
            "overture_category": "park",
        }]
    )
    out = _classifier().classify_frame(frame)
    assert out.loc[0, "psic_code"] == ""
    assert out.loc[0, "psic_status"] == "NOT_PSIC_ACTIVITY"


def test_overture_primary_and_alternate_categories_are_dependent_evidence():
    frame = pd.DataFrame(
        [{
            "poi_id": "x",
            "name": "Smile Dental",
            "sources": "overture",
            "overture_name": "Smile Dental",
            "overture_category": "dental_clinic | general_dentistry",
        }]
    )
    out = _classifier().classify_frame(frame)
    assert out.loc[0, "psic_code"] == "862"
    assert out.loc[0, "psic_evidence_sources"] == "overture"


def test_uncodeable_evidence_does_not_cancel_non_activity_decision():
    frame = pd.DataFrame(
        [{
            "poi_id": "x",
            "name": "Community Park",
            "sources": "overture",
            "overture_name": "Community Park",
            "overture_category": "park | community_center",
        }]
    )
    out = _classifier().classify_frame(frame)
    assert out.loc[0, "psic_code"] == ""
    assert out.loc[0, "psic_status"] == "NOT_PSIC_ACTIVITY"


def test_semantic_conflict_flags_suspect_entity_match():
    frame = pd.DataFrame(
        [{
            "poi_id": "x",
            "name": "Ambiguous Place",
            "sources": "osm|overture",
            "osm_name": "Ambiguous Place",
            "osm_category": "amenity=dentist",
            "overture_name": "Ambiguous Place",
            "overture_category": "restaurant",
            "match_distance_m": 95.0,
            "match_name_score": 0.80,
        }]
    )
    out = _classifier().classify_frame(frame)
    assert out.loc[0, "psic_code"] == ""
    assert out.loc[0, "psic_status"] == "REVIEW_ENTITY_MATCH"
    assert "ENTITY_MATCH_SUSPECT_DISTANCE" in out.loc[0, "psic_flags"]
    assert "ENTITY_MATCH_SUSPECT_LOW_MATCH_SCORE" in out.loc[0, "psic_flags"]


def test_classify_frame_reports_progress_at_requested_interval():
    frame = pd.DataFrame(
        [
            {
                "poi_id": f"x-{index}",
                "name": "Smile Dental",
                "sources": "osm",
                "osm_name": "Smile Dental",
                "osm_category": "amenity=dentist",
            }
            for index in range(5)
        ]
    )
    calls: list[tuple[int, int]] = []
    out = _classifier().classify_frame(
        frame,
        progress=lambda done, total: calls.append((done, total)),
        progress_every=2,
    )
    assert len(out) == 5
    assert calls == [(0, 5), (2, 5), (4, 5), (5, 5)]


def test_classify_frame_preserves_output_schema_for_zero_rows():
    frame = pd.DataFrame(columns=["poi_id", "name", "sources", "osm_name", "osm_category"])
    out = _classifier().classify_frame(frame)
    assert out.empty
    for column in (
        "psic_code",
        "psic_level",
        "psic_title",
        "psic_status",
        "psic_method",
        "psic_candidate_codes",
        "psic_evidence_sources",
        "psic_flags",
        "psic_retrieval_score",
        "psic_rule",
        "psic_query",
        "psic_traversal_agreement",
        "psic_model",
        "psic_audit",
    ):
        assert column in out.columns

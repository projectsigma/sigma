"""Focused activity-vs-ownership regression cases (no live sources)."""
import pandas as pd
from sigma.classification.administrative_activity import (
    ADMIN_PSIC, apply_administrative_activity, classify_administrative_function)
from sigma.classification.ownership import ownership_evidence

class _Node:
    level = "subclass"
    title = "Public administration of health, education, cultural services and other social services"

class _Taxonomy:
    def get(self, code):
        assert code == ADMIN_PSIC
        return _Node()


def test_role_classifier_distinguishes_offices_from_services():
    values = [
        ("Quezon City Health Department", "hospital", "ADMIN"),
        ("DOH-Regional Office 4b Mimaropa", "hospital", "ADMIN"),
        ("Department of Education NCR Regional Office", "education", "ADMIN"),
        ("BiteMed Animal Bite Center - DOH Accredited", "health_care", "NONE"),
        ("DepEd Nabangka Elementary School", "elementary_school", "NONE"),
        ("DepEd Teachers Union", "labor_union", "NONE"),
        ("Landbank DepEd NCR ATM", "bank_or_credit_union", "NONE"),
        ("DOH Eye Center", "amenity=clinic", "NONE"),
        ("Poveda-Higher Education Department", "school", "NONE"),
        ("Health Education and Promotion Unit - DOH CHD Calabarzon", "hospital", "REVIEW"),
        ("Ateneo School of Government", "college_university", "NONE"),
        ("UP Diliman Department of Computer Science", "college_university", "NONE"),
    ]
    for name, category, expected in values:
        got, _ = classify_administrative_function({"name": name, "overture_category": category})
        assert got == expected, name


def test_source_name_disagreement_is_review():
    d, _ = classify_administrative_function({
        "name": "Quezon City Health Department", "osm_name": "Quezon City Hospital"})
    assert d == "REVIEW"


def test_apply_only_modifies_identified_administration():
    rows = pd.DataFrame([
        {"name": "Quezon City Health Department", "overture_category": "hospital", "psic_code": "861", "psic_method": "crosswalk", "psic_status": "SINGLE", "psic_level": "group", "psic_title": "Hospitals"},
        {"name": "DepEd Nabangka Elementary School", "overture_category": "elementary_school", "psic_code": "852", "psic_method": "crosswalk", "psic_status": "SINGLE"},
        {"name": "Health Education and Promotion Unit - DOH CHD Calabarzon", "overture_category": "hospital", "psic_code": "861", "psic_method": "crosswalk", "psic_status": "SINGLE"},
    ])
    original = rows.copy(deep=True)
    result = apply_administrative_activity(rows, taxonomy=_Taxonomy())
    assert result.loc[0, "psic_code"] == "84120"
    assert result.loc[0, "admin_activity_status"] == "REASSIGNED"
    assert result.loc[1, "psic_code"] == original.loc[1, "psic_code"]
    assert result.loc[2, "psic_code"] == original.loc[2, "psic_code"]
    assert result.loc[2, "admin_activity_status"] == "REVIEW"
    pd.testing.assert_frame_equal(rows, original)


def test_doh_accreditation_not_public_ownership():
    result = ownership_evidence({"name": "BiteMed Animal Bite Center - DOH Accredited", "overture_category": "health_care"}, "health")
    assert result.side == ""


def test_holy_spirit_not_private_merely_by_name():
    result = ownership_evidence({"name": "Holy Spirit Elementary School", "overture_category": "elementary_school"}, "education")
    assert result.side != "private"


def test_explicit_school_remains_public():
    result = ownership_evidence({"name": "Quezon City National High School", "overture_category": "school"}, "education")
    assert result.side == "public"

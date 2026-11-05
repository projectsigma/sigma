"""Conservative PSIC activity correction for unmistakably administrative offices.

Policy: admin-function-v1. Activity is resolved BEFORE ownership/IO tagging.
A government owner or accreditation does not establish an office function.
University/school internal offices and clinical offices are never automatically changed.
"""
from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

ADMIN_ACTIVITY_POLICY = "admin-function-v1"
ADMIN_PSIC = "84120"  # Public administration of health, education, and other social programmes

# Names identify an administrative government function, not merely an operator.
_STRONG_ADMIN = (
    ("regional_doh_office", re.compile(
        r"^(?:doh|department\s+of\s+health)\s*[-–,:]?\s*"
        r"(?:ncr\s+|national\s+capital\s+region\s+)?regional\s+office\b", re.I)),
    ("regional_deped_office", re.compile(
        r"^(?:deped|department\s+of\s+education)\s*[-–,:]?\s*"
        r"(?:ncr\s+|national\s+capital\s+region\s+)?regional\s+office\b", re.I)),
    ("regional_deped_ncr", re.compile(
        r"^(?:deped|department\s+of\s+education)\s+(?:ncr|national\s+capital\s+region)\s+regional\s+office\b", re.I)),
    ("regional_deped_after", re.compile(
        r"^(?:deped|department\s+of\s+education)\s+regional\s+office\b", re.I)),
    ("division_deped_office", re.compile(
        r"^(?:deped|department\s+of\s+education)\b.{0,60}\b"
        r"(?:schools?\s+division|division)\s+office\b", re.I)),
    ("schools_division_office", re.compile(
        r"^(?:department\s+of\s+education\s+)?schools?\s+division\s+office\b", re.I)),
    ("local_health_department", re.compile(
        r"\b(?:city|municipal|municipality|provincial|province)\s+health\s+department\s*$", re.I)),
    ("local_health_department_office", re.compile(
        r"\b(?:city|municipal|provincial)\s+health\s+department\s+(?:office|headquarters)\s*$", re.I)),
)

# Specifically keep frontline service and co-located teaching/medical subunits out.
_FRONTLINE = re.compile(
    r"\b(?:hospital|clinics?|medical\s+cent(?:er|re)|health\s+cent(?:er|re)|"
    r"eye\s+cent(?:er|re)|animal\s+bite|dental|dentists?|laborator(?:y|ies)|"
    r"elementary\s+school|high\s+school|national\s+high\s+school|"
    r"university|college|academy|tutorial|training\s+cent(?:er|re))\b", re.I)
_INTERNAL = re.compile(
    r"\b(?:department\s+of|division\s+of|dean'?s\s+office|registrar|"
    r"faculty|school\s+of|institute\s+of)\b", re.I)
_REVIEW = re.compile(
    r"\b(?:department\s+of\s+(?:health|education)|health\s+department|"
    r"schools?\s+division\s+office|health\s+office|"
    r"(?:city|municipal|municipality|provincial|regional|government)\s+education\s+department|\bdoh\s+chd\b)\b", re.I)
_SERVICE_CATEGORY = re.compile(
    r"(?:^|[|\s])(?:amenity=(?:hospital|clinic|school)|healthcare=(?:hospital|clinic)|"
    r"hospital|health_care|school|elementary_school|high_school|university|"
    r"college_university|education)(?:$|[|\s])", re.I)


def _str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def classify_administrative_function(row: Any) -> tuple[str, str]:
    """Return (decision, reason). Decisions: ADMIN, REVIEW, NONE."""
    get = row.get
    name = _str(get("name")) or _str(get("canonical_name"))
    if not name:
        return "NONE", ""
    all_names = tuple(dict.fromkeys(
        n for key in ("name", "canonical_name", "osm_name", "overture_name")
        if (n := _str(get(key)))
    ))
    frontline = any(_FRONTLINE.search(n) for n in all_names)
    matches = [label for label, pattern in _STRONG_ADMIN if pattern.search(name)]
    if matches:
        if frontline:
            return "REVIEW", "admin_named_but_frontline_name"
        if _str(get("psic_method")).casefold() in {"user_supplied", "manual"}:
            return "REVIEW", "manual_psic_not_overridden"
        # A clearly named government office can be miscoded as a hospital in
        # its SOURCE category; record the contradiction, do not borrow a service label.
        mismatched_names = [n for n in all_names[1:] if
                            _FRONTLINE.search(n) or
                            (n.casefold() != name.casefold() and
                             not any(p.search(n) for _, p in _STRONG_ADMIN))]
        if mismatched_names:
            return "REVIEW", "conflicting_source_names"
        cat = "|".join(_str(get(k)) for k in ("osm_category", "overture_category"))
        reason = matches[0]
        if _SERVICE_CATEGORY.search(cat):
            reason += "+source_service_category_conflict"
        return "ADMIN", reason
    if _REVIEW.search(name) and not frontline:
        return "REVIEW", "admin_name_insufficient_to_override_activity"
    return "NONE", ""


def apply_administrative_activity(frame: pd.DataFrame, *, taxonomy: Any) -> pd.DataFrame:
    """Return classified-place copy with narrowly corrected administrative activities.

    Only an exact, authoritative role-pattern match may change PSIC. Current
    PSIC evidence is kept in additive audit fields. No IO or ownership is set here.
    """
    out = frame.copy()
    for column in ("admin_activity_status", "admin_activity_reason", "admin_original_psic"):
        if column in out.columns:
            raise ValueError(f"administration audit field already present: {column}")
        out[column] = ""
    if "name" not in out or "psic_code" not in out or out.empty:
        return out
    # Preselection avoids scanning the entire workspace row by row.
    candidate = out["name"].astype("string").fillna("").str.contains(
        r"(?i)health\s+department|regional\s+office|division\s+office|"
        r"department\s+of\s+(?:health|education)|\bdoh\b|\bdeped\b|"
        r"health\s+office|education\s+department", regex=True)
    policy_node = None  # Resolve only when a reassignment needs the reference.
    for idx, row in out.loc[candidate].iterrows():
        decision, reason = classify_administrative_function(row)
        if decision == "NONE":
            continue
        out.at[idx, "admin_activity_status"] = "REASSIGNED" if decision == "ADMIN" else "REVIEW"
        out.at[idx, "admin_activity_reason"] = reason
        if decision != "ADMIN":
            continue
        original = {col: _str(row.get(col)) for col in (
            "psic_code", "psic_level", "psic_title", "psic_status", "psic_method", "psic_rule")}
        if original["psic_code"].startswith("84"):
            # Broad public administration is already the right economic activity.
            # Do not pretend the evidence proves a more precise subclass.
            out.at[idx, "admin_activity_status"] = "CONFIRMED"
            continue
        if policy_node is None:
            policy_node = taxonomy.get(ADMIN_PSIC)  # Fail closed for actual reassignments.
        out.at[idx, "admin_original_psic"] = original["psic_code"]
        out.at[idx, "psic_code"] = ADMIN_PSIC
        out.at[idx, "psic_level"] = policy_node.level
        out.at[idx, "psic_title"] = policy_node.title
        out.at[idx, "psic_status"] = "SINGLE"
        out.at[idx, "psic_method"] = "administrative_role"
        out.at[idx, "psic_candidate_codes"] = ADMIN_PSIC
        out.at[idx, "psic_evidence_sources"] = "name"
        out.at[idx, "psic_rule"] = "administrative_activity:" + reason
        out.at[idx, "psic_query"] = _str(row.get("name"))
        prev_flags = _str(row.get("psic_flags"))
        out.at[idx, "psic_flags"] = "|".join(filter(None, (prev_flags, "ADMIN_ACTIVITY_REASSIGNED")))
        if "psic_retrieval_score" in out:
            out.at[idx, "psic_retrieval_score"] = float("nan")
        if "psic_traversal_agreement" in out:
            out.at[idx, "psic_traversal_agreement"] = ""
        if "psic_model" in out:
            out.at[idx, "psic_model"] = ""
        out.at[idx, "psic_audit"] = json.dumps({
            "policy": ADMIN_ACTIVITY_POLICY,
            "reason": reason,
            "original": original,
            "original_psic_audit": _str(row.get("psic_audit")),
        }, ensure_ascii=False, separators=(",", ":"))
    return out

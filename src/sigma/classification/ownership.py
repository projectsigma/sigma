"""Public or private ownership for education and health places, policy ownership-v3.

PSA's IO tables split education (IO80 74 public / 75 private; IO240 229 / 230) and human
health (IO80 76 / 77; IO240 231 / 232) by ownership. Most source categories ("school",
"hospital") do not say which. This module looks for ownership evidence in the place's
names and, for a few clinic categories, in the category itself.

It acts only when the place's PSIC-derived candidate set is exactly one of these pairs.
It abstains when the evidence points both ways or is absent. Patterns are deliberately
narrow (Philippine naming conventions such as "National High School", "Rural Health
Unit", "Provincial Hospital"); a missed place stays ambiguous rather than guessed.
This is name evidence, not a registry match: results carry their own status
(OWNERSHIP_RESOLVED) so they can be filtered or audited.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

OWNERSHIP_POLICY_VERSION = "ownership-v3"

# domain -> side -> (IO80 code, IO240 code)
OWNERSHIP_CODES: dict[str, dict[str, tuple[str, str]]] = {
    "education": {"public": ("74", "229"), "private": ("75", "230")},
    "health": {"public": ("76", "231"), "private": ("77", "232")},
}

_EDUCATION_PUBLIC = (
    r"\b(?:government|public)\s+(?:elementary\s+|high\s+|primary\s+)?school\b",
    r"\bpublic\s+(?:university|college|academy)\b",
    r"\bnational\s+(?:[a-z]+\s+){0,2}high\s+school\b",
    r"\b(?:central|integrated)\s+(?:elementary\s+)?school\b",
    r"\bstate\s+(?:university|college)\b",
    r"\buniversity\s+of\s+the\s+philippines\b",
    r"\b(?:polytechnic|technological)\s+university\s+of\s+the\s+philippines\b",
    r"\bphilippine\s+normal\s+university\b",
    r"\bpamantasan\s+ng\s+lungsod\b",
    r"\b(?:city|municipal)\s+college\b",
    r"\bchild\s+development\s+cent(?:er|re)\b",
    r"\bday\s*care\s+cent(?:er|re)\b",
    r"\bdeped\b",
    r"\bdepartment\s+of\s+education\b",
    r"\bschools?\s+division\s+office\b",
    r"\btesda\b",
    r"\bphilippine\s+(?:military|national\s+police|merchant\s+marine|public\s+safety)\s+"
    r"(?:academy|college)\b",
)
_EDUCATION_PRIVATE = (
    r"\bprivate\s+(?:elementary\s+|high\s+|primary\s+)?school\b",
    r"\bprivate\s+(?:university|college|academy|learning\s+cent(?:er|re))\b",
    r"\bmontessori\b",
    r"\bcolegio\b",
    r"\blearning\s+(?:cent(?:er|re)|school|institute)\b",
    r"\b(?:christian|catholic|baptist|adventist|methodist|lutheran|evangelical|islamic)\s+"
    r"(?:school|academy|college|learning)\b",
    r"\b(?:inc|incorporated)\b",
    r"\b(?:st|saint|holy|sacred|immaculate|blessed)\b\.?\s",
    r"\bour\s+lady\b",
    r"\bdon\s+bosco\b",
    r"\bla\s+salle\b",
    r"\bateneo\b",
    r"\bmaryknoll\b",
    r"\bama\s+computer\b",
    r"\bsti\s+(?:college|education)\b",
    r"\binternational\s+school\b",
    r"\breview\s+cent(?:er|re)\b",
    r"\btutorial\b",
    r"\bkiddie\b",
)
_HEALTH_PUBLIC = (
    r"\b(?:government|public)\s+(?:medical\s+|dental\s+|health\s+)?(?:clinic|hospital|cent(?:er|re))\b",
    r"\brural\s+health\s+(?:unit|cent(?:er|re)|office)\b",
    r"\brhu\b",
    r"\bbarangay\s+health\s+(?:station|cent(?:er|re)|unit|office|post)\b",
    r"\bbhs\b",
    r"\b(?:city|municipal|provincial)\s+health\s+(?:office|cent(?:er|re)|unit|department)\b",
    r"\bsuper\s+health\s+cent(?:er|re)\b",
    r"\b(?:provincial|district|regional|municipal|city)\s+(?:general\s+)?hospital\b",
    r"\bmedicare\s+(?:community\s+)?hospital\b",
    r"\bregional\s+(?:medical|training\s+and\s+teaching)\s+cent(?:er|re)\b",
    r"\bregional\s+training\s+and\s+teaching\s+hospital\b",
    r"\bphilippine\s+general\s+hospital\b",
    r"\bdepartment\s+of\s+health\b",
    r"\bdoh\b",
)
_HEALTH_PRIVATE = (
    r"\bprivate\s+(?:medical\s+|dental\s+|health\s+)?(?:clinic|hospital|cent(?:er|re))\b",
    r"\b(?:inc|incorporated|corp|corporation)\b",
    r"\bdoctors?'?\s+(?:hospital|clinic)\b",
    r"\bdental\b",
    r"\bdentist",
    r"\bdiagnostic",
    r"\bpolyclinic\b",
    r"\blaborator(?:y|ies)\b",
    r"\blying[\s-]?in\b",
    r"\beye\s+(?:cent(?:er|re)|clinic)\b",
    r"\bderma(?:tology)?\b",
    r"\bortho(?:dontic|dontics)?\b",
    r"\b(?:st|saint|holy|sacred|immaculate|blessed)\b\.?\s",
    r"\bour\s+lady\b",
)
# Only explicit education ownership categories qualify. Generic school and
# university categories never establish public/private ownership.
_EDUCATION_PUBLIC_CATEGORIES = frozenset({"overture:public_school"})
_EDUCATION_PRIVATE_CATEGORIES = frozenset({"overture:private_school"})

# Categories whose places are private practices in the Philippine setting.
_HEALTH_PRIVATE_CATEGORIES = frozenset(
    {
        "overture:dental_clinic",
        "overture:general_dentistry",
        "overture:doctors_office",
        "overture:family_practice",
        "overture:pediatric_clinic",
        "overture:obstetrics_and_gynecology",
        "overture:dialysis_clinic",
        "overture:vision_or_eye_care_clinic",
        "osm:amenity=dentist",
        "osm:healthcare=dentist",
    }
)

_PATTERNS = {
    ("education", "public"): tuple(re.compile(p, re.I) for p in _EDUCATION_PUBLIC),
    ("education", "private"): tuple(re.compile(p, re.I) for p in _EDUCATION_PRIVATE),
    ("health", "public"): tuple(re.compile(p, re.I) for p in _HEALTH_PUBLIC),
    ("health", "private"): tuple(re.compile(p, re.I) for p in _HEALTH_PRIVATE),
}

OWNERSHIP_POLICY_FINGERPRINT = hashlib.sha256(
    json.dumps(
        {
            "version": OWNERSHIP_POLICY_VERSION,
            "codes": OWNERSHIP_CODES,
            "patterns": {f"{d}:{s}": [p.pattern for p in v] for (d, s), v in _PATTERNS.items()},
            "education_public_categories": sorted(_EDUCATION_PUBLIC_CATEGORIES),
            "education_private_categories": sorted(_EDUCATION_PRIVATE_CATEGORIES),
            "private_categories": sorted(_HEALTH_PRIVATE_CATEGORIES),
            "rule": "abstain_when_both_or_neither",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


@dataclass(frozen=True, slots=True)
class OwnershipEvidence:
    domain: str = ""
    side: str = ""
    reason: str = ""

    @property
    def io80_code(self) -> str:
        return OWNERSHIP_CODES[self.domain][self.side][0] if self.side else ""

    @property
    def io240_code(self) -> str:
        return OWNERSHIP_CODES[self.domain][self.side][1] if self.side else ""


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def ownership_domain(io80_codes: tuple[str, ...], io240_codes: tuple[str, ...]) -> str:
    """The domain whose ownership pair equals the candidate set, else ''."""
    for domain, sides in OWNERSHIP_CODES.items():
        pair80 = {sides["public"][0], sides["private"][0]}
        pair240 = {sides["public"][1], sides["private"][1]}
        if set(io80_codes) == pair80 or set(io240_codes) == pair240:
            return domain
    return ""


def ownership_evidence(row: pd.Series | dict[str, Any], domain: str) -> OwnershipEvidence:
    """Public/private evidence for one place in ``domain``; empty side means abstain."""
    if domain not in OWNERSHIP_CODES:
        return OwnershipEvidence()
    get = row.get
    names = list(
        dict.fromkeys(
            text
            for text in (
                _text(get("osm_name", "")),
                _text(get("overture_name", "")),
                _text(get("canonical_name", "")),
                _text(get("name", "")),
            )
            if text
        )
    )
    categories = {
        f"{source}:{part.strip().casefold()}"
        for source in ("osm", "overture")
        for part in _text(get(f"{source}_category", "")).split("|")
        if part.strip()
    }
    found: dict[str, str] = {}
    for side in ("public", "private"):
        for pattern in _PATTERNS[(domain, side)]:
            hit = next((name for name in names if pattern.search(name)), None)
            if hit is not None:
                found.setdefault(side, f"name:{pattern.pattern}")
                break
    if domain == "education":
        for side, allowed in (
            ("public", _EDUCATION_PUBLIC_CATEGORIES),
            ("private", _EDUCATION_PRIVATE_CATEGORIES),
        ):
            matched = categories & allowed
            if matched:
                found.setdefault(side, "category:" + sorted(matched)[0])
    if domain == "health" and categories & _HEALTH_PRIVATE_CATEGORIES:
        found.setdefault(
            "private", "category:" + sorted(categories & _HEALTH_PRIVATE_CATEGORIES)[0]
        )
    # A clear opposing ownership descriptor must not be overridden by an
    # institution-type heuristic even if that descriptor did not match a full
    # institution phrase above (e.g. "Private Rural Health Unit").
    if ("public" in found and any(re.search(r"\bprivate\b", name, re.I) for name in names)) or (
        "private" in found and any(re.search(r"\b(?:government|public)\b", name, re.I) for name in names)
    ):
        return OwnershipEvidence(domain, "", "contradictory")
    if len(found) != 1:
        return OwnershipEvidence(domain, "", "contradictory" if found else "no_evidence")
    side, reason = next(iter(found.items()))
    return OwnershipEvidence(domain, side, reason)

"""DepEd BEIS identity index from a user-supplied nationwide, three-field extract.

A school name is never treated as a unique national identifier. School-ID prefixes
provide a provisional public/private signal only for conventional six-digit IDs.
Source provenance for this input is unverified; this index MUST NOT emit a
promotable EXACT_EXTERNAL_ID status until independently sourced and reviewed.
"""
from __future__ import annotations

import csv
import gzip
import re
from collections import defaultdict
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping

from .registry import Match, key

FIELDS = ("school_id", "school_name", "town_psgc")
RESOURCE = "beis_schools_national.csv.gz"
# DepEd documents these conventions for SIX-digit EBEIS IDs. Longer or older
# identifiers are kept for identity research but receive no ownership inference.
PUBLIC_PREFIXES = frozenset("12356")
PRIVATE_PREFIXES = frozenset("4")


def _s(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.casefold() in {"nan", "none", "<na>"} else s


def school_owner_from_id(code: str) -> str:
    value = _s(code)
    if not re.fullmatch(r"[0-9]{6}", value):
        return ""
    if value[0] in PUBLIC_PREFIXES:
        return "public"
    if value[0] in PRIVATE_PREFIXES:
        return "private"
    return ""


@dataclass(frozen=True, slots=True)
class BEISSchool:
    school_id: str
    name: str
    town_psgc: str
    ownership_hint: str


def load_beis(path: Path) -> list[BEISSchool]:
    """Validate a compact BEIS extract; preserve string IDs and leading zeros."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, mode="rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("BEIS extract must have exactly school_id,school_name,town_psgc")
        values = list(reader)
    if not values:
        raise ValueError("empty BEIS extract")
    seen = set()
    records = []
    for number, row in enumerate(values, start=2):
        code = _s(row.get("school_id"))
        name = _s(row.get("school_name"))
        psgc = _s(row.get("town_psgc"))
        if (not re.fullmatch(r"[0-9]{5,7}", code) or not name or
                not re.fullmatch(r"[0-9]{10}", psgc) or not psgc.endswith("000")):
            raise ValueError(f"invalid BEIS identity/location at line {number}")
        if code in seen:
            raise ValueError(f"duplicate BEIS school ID {code} at line {number}")
        seen.add(code)
        records.append(BEISSchool(code, name, psgc, school_owner_from_id(code)))
    return records


def packaged_beis() -> list[BEISSchool]:
    with resources.as_file(resources.files("sigma.resources.classification").joinpath(RESOURCE)) as path:
        return load_beis(path)


class BEISIndex:
    """Exact name / ID candidates; municipality disambiguation only by PSGC."""

    def __init__(self, records: Iterable[BEISSchool]):
        self.by_id = {}
        self.by_name = defaultdict(list)
        for record in records:
            if record.school_id in self.by_id:
                raise ValueError(f"duplicate BEIS school ID: {record.school_id}")
            self.by_id[record.school_id] = record
            self.by_name[key(record.name)].append(record)

    def match(self, row: Mapping[str, Any], domain: str) -> Match:
        if domain != "education":
            return Match()
        names = [key(row.get(c)) for c in ("name", "canonical_name", "osm_name", "overture_name")]
        names = [x for x in names if x]
        main = names[0] if names else ""
        ids = {_s(row.get(c)) for c in ("deped_school_id", "beis_school_id") if _s(row.get(c))}
        tags = " | ".join(_s(row.get(c)) for c in ("osm_category", "overture_category"))
        for label in ("ref:deped", "ref:deped:school"):
            for m in re.finditer(r"(?:^|\|)\s*" + re.escape(label) + r"\s*=\s*([^|]+)", tags, re.I):
                ids.add(m.group(1).strip())
        ids_found = [self.by_id[code] for code in ids if code in self.by_id]
        if len(ids_found) > 1:
            return Match("IDENTITY_AMBIGUOUS", note="conflicting_school_ids")
        explicit_id = bool(ids_found)
        if explicit_id:
            candidates = ids_found
        else:
            candidates = list({rec.school_id: rec for name in names for rec in self.by_name.get(name, ())}.values())
        if not candidates:
            return Match()
        if explicit_id and names and key(candidates[0].name) not in names:
            return Match("EXTERNAL_ID_NAME_CONFLICT", note="beis_id_and_name_disagree")
        if not explicit_id and main and all(key(x.name) != main for x in candidates):
            return Match("CANONICAL_NAME_CONFLICT", note="secondary_name_is_not_canonical")
        known_psgc = {_s(row.get(c)) for c in (
            "town_psgc", "municipality_psgc", "city_psgc", "area_psgc")
            if re.fullmatch(r"\d{10}", _s(row.get(c)))}
        if len(known_psgc) > 1:
            return Match("CITY_CONFLICT", note="inconsistent_place_psgc_fields")
        if known_psgc:
            location = next(iter(known_psgc))
            matches = [x for x in candidates if x.town_psgc == location]
            if not matches:
                return Match("CITY_CONFLICT", note="school_town_psgc_disagrees")
            candidates = matches
        if len(candidates) > 1:
            return Match("IDENTITY_AMBIGUOUS", note="same_school_name_multiple_official_ids",
                         independent_records=len(candidates))
        record = candidates[0]
        # BEIS extract provenance is user-supplied and lacks a verifiable snapshot
        # URL/date; not promotable as verified identity regardless of school ID.
        status = "BEIS_ID_PROVISIONAL" if explicit_id else (
            "BEIS_NAME_PSGC_PROVISIONAL" if known_psgc else "BEIS_NAME_ONLY_PROVISIONAL")
        if not record.ownership_hint:
            status = "BEIS_OWNERSHIP_UNKNOWN"
        return Match(status, record.ownership_hint,
                     "beis_user_extract_unverified", "deped_beis",
                     f"deped_beis:{record.school_id}", record.name, "",
                     f"user_supplied_beis;town_psgc={record.town_psgc};not_verified_link", 1)


class LayeredInstitutionIndex:
    """Refuse a promotion when a primary institution and the school index overlap."""

    def __init__(self, primary, schools: BEISIndex):
        self.primary = primary
        self.schools = schools

    def match(self, row: Mapping[str, Any], domain: str) -> Match:
        base = self.primary.match(row, domain) if self.primary else Match()
        school = self.schools.match(row, domain)
        if base.status == "NO_MATCH":
            return school
        if school.status == "NO_MATCH":
            return base
        if base.status in {"IDENTITY_AMBIGUOUS", "OWNERSHIP_CONFLICT", "CITY_CONFLICT", "EXTERNAL_ID_NAME_CONFLICT", "CANONICAL_NAME_CONFLICT"}:
            return base
        if school.status in {"IDENTITY_AMBIGUOUS", "OWNERSHIP_CONFLICT", "CITY_CONFLICT", "EXTERNAL_ID_NAME_CONFLICT", "CANONICAL_NAME_CONFLICT"}:
            return school
        return Match("IDENTITY_AMBIGUOUS", note="primary_and_school_index_both_match;manual_review")

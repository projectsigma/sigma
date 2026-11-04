"""National hospital evidence index (v10): validated Level 3 hospitals.

Records are local, attributed source snapshots; this module makes no network calls.
Name/location candidate matches are always provisional. Only independently
verified exact official cross-dataset IDs can support automatic IO promotion.
"""
from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .registry import Institution, Match, key, valid_url

REGISTRY_FILENAME = "institution_national_v1.csv"
REGISTRY_VERSION = "national-hospitals-v10"
FIELDS = (
    "source", "source_id", "name", "domain", "ownership", "city", "province",
    "address", "aliases", "source_url", "as_of", "id_kind", "evidence_type",
    "facility_level",
)
HOSPITAL_SOURCES = frozenset({"philhealth_hospitals", "doh_nhfr"})
ALLOWED_HOSTS = {
    "philhealth_hospitals": frozenset({"philhealth.gov.ph", "www.philhealth.gov.ph"}),
    "doh_nhfr": frozenset({"nhfr.doh.gov.ph", "hfsrb.doh.gov.ph"}),
}


def national_registry_path(workspace_root: Path) -> Path:
    """Shared under SIGMA_HOME/references, never copied per workspace."""
    return Path(workspace_root).resolve().parent.parent / "references" / REGISTRY_FILENAME


def _text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.casefold() in {"nan", "none", "<na>"} else s


def _level3(value: Any) -> bool:
    return key(value) in {"level 3", "level iii", "level three"}



def _valid_record(row: Mapping[str, str], line: int) -> Institution:
    src = _text(row.get("source"))
    url = _text(row.get("source_url"))
    host = (urlparse(url).hostname or "").lower()
    if src not in ALLOWED_HOSTS or not valid_url(url) or host not in ALLOWED_HOSTS[src]:
        raise ValueError(f"row {line}: invalid official provenance {src!r} / {url!r}")
    ident, name = _text(row.get("source_id")), _text(row.get("name"))
    domain, side = _text(row.get("domain")), _text(row.get("ownership"))
    as_of = _text(row.get("as_of"))
    kind = _text(row.get("id_kind"))
    evidence = _text(row.get("evidence_type"))
    if not ident or not name or not as_of or side not in {"public", "private"}:
        raise ValueError(f"row {line}: incomplete identity, provenance date or explicit ownership")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise ValueError(f"row {line}: as_of must be YYYY-MM-DD")
    if kind not in {"official_code", "publication_row"} or evidence != "explicit_sector":
        raise ValueError(f"row {line}: unsupported identity or evidence type")
    if src in HOSPITAL_SOURCES:
        if domain != "health" or not _level3(row.get("facility_level")):
            raise ValueError(f"row {line}: hospital snapshot must explicitly be Level 3")
        if src == "doh_nhfr" and kind != "official_code":
            raise ValueError(f"row {line}: NHFR requires a real facility code")
        if src == "philhealth_hospitals" and kind != "publication_row":
            raise ValueError(f"row {line}: PhilHealth PDF row number is not an official facility ID")
    return Institution(src, ident, name, domain, side, _text(row.get("city")),
                       _text(row.get("address")),
                       tuple(p.strip() for p in _text(row.get("aliases")).split("|") if p.strip()),
                       url, as_of, kind, evidence)


def load_national_registry(path: Path) -> list[Institution]:
    """Load a strictly validated national snapshot; never silently skip bad rows."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if set(reader.fieldnames or []) != set(FIELDS):
            raise ValueError(f"national registry columns must be exactly {', '.join(FIELDS)}")
        data = list(reader)
    if not data:
        raise ValueError("national institution registry is empty")
    out, seen = [], set()
    for line, row in enumerate(data, 2):
        rec = _valid_record(row, line)
        identity = (rec.source, rec.source_id.casefold())
        if identity in seen:
            raise ValueError(f"row {line}: duplicate official/publication identifier {identity}")
        seen.add(identity)
        out.append(rec)
    return out


def national_fingerprint(workspace_root: Path) -> str | None:
    path = national_registry_path(workspace_root)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"national registry path is not a file: {path}")
    # Reference data must be validated before use.
    load_national_registry(path)
    return hashlib.sha256(REGISTRY_VERSION.encode() + b"\0" + path.read_bytes()).hexdigest()


class NationalRegistryIndex:
    """Exact indexed candidates; no fuzzy matching or all-pairs comparisons."""

    def __init__(self, records: Iterable[Institution]):
        self.records = tuple(records)
        self.by_name: dict[str, list[Institution]] = defaultdict(list)
        self.by_code: dict[tuple[str, str], list[Institution]] = defaultdict(list)
        for r in self.records:
            for name in dict.fromkeys([r.name, *r.aliases]):
                if key(name):
                    self.by_name[key(name)].append(r)
            if r.id_kind == "official_code":
                self.by_code[(r.source, r.source_id.casefold())].append(r)

    def match(self, row: Mapping[str, Any], domain: str) -> Match:
        if domain != "health":
            return Match()
        names = [key(row.get(k)) for k in ("name", "canonical_name", "osm_name", "overture_name")]
        names = [v for v in names if v]
        main = names[0] if names else ""
        named = {(r.source, r.source_id): r for n in names for r in self.by_name.get(n, ())
                 if r.domain == domain}
        id_matches = []
        id_fields = {"doh_nhfr": ("nhfr_code", "doh_facility_code")}
        for source, fields in id_fields.items():
            for field in fields:
                val = _text(row.get(field))
                if val:
                    id_matches.extend(r for r in self.by_code.get((source, val.casefold()), ())
                                      if r.domain == domain)
        tags = " | ".join(_text(row.get(k)) for k in ("osm_category", "overture_category"))
        for src, field in (("doh_nhfr", "ref:nhfr"),):
            match = re.search(r"(?:^|\|)\s*" + re.escape(field) + r"\s*=\s*([^|]+)", tags, flags=re.I)
            if match:
                id_matches.extend(r for r in self.by_code.get((src, match.group(1).strip().casefold()), ())
                                  if r.domain == domain)
        if id_matches:
            candidates = {(r.source, r.source_id): r for r in id_matches}
            if not main or not any(main in {key(n) for n in (r.name, *r.aliases)} for r in candidates.values()):
                return Match("EXTERNAL_ID_NAME_CONFLICT", note="official_id_but_canonical_name_differs")
        else:
            candidates = named
        if not candidates:
            return Match()
        values = list(candidates.values())
        known_cities = {key(row.get(c)) for c in ("city", "municipality", "osm_city", "overture_city")
                        if _text(row.get(c))}
        # Locality is evidence about the *registered site*, not an exclusion
        # of a branch, campus, or affiliate of the same nationwide institution.
        # It is never sufficient to establish an institutional relationship.
        if not id_matches and main and not any(main in {key(n) for n in (r.name, *r.aliases)} for r in values):
            return Match("CANONICAL_NAME_CONFLICT", note="source_name_does_not_identify_canonical")
        sources = {(r.source, r.source_id) for r in values}
        sides = {r.ownership for r in values}
        if len(sides) > 1:
            return Match("OWNERSHIP_CONFLICT", note="source_ownership_disagreement", independent_records=len(sources))
        if len(values) > 1:
            return Match("IDENTITY_AMBIGUOUS", note="multiple_institutions_or_campuses", independent_records=len(sources))
        rec = values[0]
        registered_city = key(rec.city)
        locality_disagrees = bool(known_cities and registered_city and
                                   registered_city not in known_cities)
        locality_inconsistent = len(known_cities) > 1
        if id_matches and (locality_disagrees or locality_inconsistent):
            # A real official code may identify a registered site/campus, not
            # every branch bearing the same institution name. The name+code
            # pair is therefore NOT automatically promotable in this case.
            return Match(
                "EXTERNAL_ID_LOCALITY_REVIEW", rec.ownership,
                "external_id_locality_provisional", rec.source,
                f"{rec.source}:{rec.source_id}", rec.name, rec.source_url,
                "registered_site_differs_or_place_localities_inconsistent;"
                "independent_branch_or_establishment_evidence_required", 1,
            )
        if id_matches:
            status = "EXACT_EXTERNAL_ID"
            basis, note = "external_official_id", "verified_official_code_and_name"
        elif known_cities and registered_city and not locality_disagrees and not locality_inconsistent:
            status = "EXACT_NAME_CITY" if main == key(rec.name) else "OFFICIAL_ALIAS_CITY"
            basis, note = "unique_name_city_provisional", "name_and_city_not_identity_proof"
        else:
            status = "NAME_LOCATION_UNVERIFIED"
            basis = "unique_name_provisional"
            note = ("registered_locality_differs_possible_branch_or_affiliate" if locality_disagrees
                    else "place_locality_inconsistent" if locality_inconsistent
                    else "registered_locality_missing_or_unverified")
        return Match(status, rec.ownership, basis, rec.source, f"{rec.source}:{rec.source_id}",
                     rec.name, rec.source_url, note, 1)

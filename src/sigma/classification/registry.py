"""Independently sourced public/private institution reference data for *shadow only*.

No network calls; all references are versioned local snapshots. A name/city link is
PROVISIONAL entity evidence (never an official cross-dataset ID). Match precisely,
and abstain on ambiguity. No diagnostics/ground-truth roster is consumed here.
"""
from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

OFFICIAL_HOSTS = frozenset({
    "nhfr.doh.gov.ph", "hfsrb.doh.gov.ph", "ncroffice.doh.gov.ph",
    "deped.gov.ph", "www.deped.gov.ph", "depedncr.com.ph", "www.depedncr.com.ph",
    "ched.gov.ph", "www.ched.gov.ph", "legacy.ched.gov.ph",
    "philhealth.gov.ph", "www.philhealth.gov.ph", "quezoncity.gov.ph",
})
KNOWN_SOURCES = frozenset({"doh_nhfr", "deped_public", "deped_masterlist", "ched_cmo", "philhealth_hospitals", "qc_government"})


def _str(v: object) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.casefold() in {"nan", "none", "nat", "<na>"} else s


def key(s: object) -> str:
    s = unicodedata.normalize("NFKD", _str(s).casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("&", " and ").replace("’", "").replace("'", "")
    s = re.sub(r"[^\w]+", " ", s)
    s = re.sub(r"\b(?:es)\b$", "elementary school", s)
    s = re.sub(r"\b(?:nhs)\b$", "national high school", s)
    s = re.sub(r"\b(?:hs)\b$", "high school", s)
    s = re.sub(r"\b(?:st)\b(?=\s+\w)", "saint", s)
    s = re.sub(r"\b(?:inc|incorporated|corporation|corp)\b$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in OFFICIAL_HOSTS and not parsed.username and not parsed.password


def city_is_qc(city: str) -> bool:
    return key(city) in {"quezon city", "qc", "q c", "city of quezon", "quezon city metro manila", "sdo quezon city", "schools division of quezon city", "quezon city schools division"}


@dataclass(frozen=True, slots=True)
class Institution:
    source: str
    source_id: str
    name: str
    domain: str
    ownership: str
    city: str
    address: str
    aliases: tuple[str, ...]
    source_url: str
    as_of: str
    id_kind: str
    evidence_type: str


@dataclass(frozen=True, slots=True)
class Match:
    status: str = "NO_MATCH"
    side: str = ""
    basis: str = ""
    source: str = ""
    source_ids: str = ""
    name: str = ""
    source_urls: str = ""
    note: str = ""
    independent_records: int = 0


def records_from_csv(path: Path) -> list[Institution]:
    """Validate a self-describing curated official source snapshot; fail closed."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected = {"source", "source_id", "name", "domain", "ownership", "city", "address", "aliases", "source_url", "as_of", "id_kind", "evidence_type"}
        if not expected <= set(reader.fieldnames or ()):
            raise ValueError(f"registry snapshot missing columns: {sorted(expected - set(reader.fieldnames or ()))}")
        raw = list(reader)
    records = []
    seen = set()
    for n, r in enumerate(raw, 2):
        src = _str(r["source"])
        url = _str(r["source_url"])
        rec = Institution(src, _str(r["source_id"]), _str(r["name"]),
                          _str(r["domain"]), _str(r["ownership"]), _str(r["city"]),
                          _str(r["address"]), tuple(a.strip() for a in _str(r["aliases"]).split("|") if a.strip()),
                          url, _str(r["as_of"]), _str(r["id_kind"]), _str(r["evidence_type"]))
        if (src not in KNOWN_SOURCES or not valid_url(url) or
                rec.domain not in {"education", "health"} or rec.ownership not in {"public", "private"} or
                not rec.source_id or not rec.name or not city_is_qc(rec.city) or not rec.as_of or
                rec.id_kind not in {"official_code", "publication_row"} or
                rec.evidence_type not in {"explicit_sector", "official_public_directory", "official_private_list"}):
            raise ValueError(f"registry row {n} invalid provenance, domain, location, or ownership")
        # Stronger source-schema contract; not just any official URL can self-assert a sector.
        host = urlparse(url).hostname.lower()
        if not (
            (src == "doh_nhfr" and host in {"nhfr.doh.gov.ph", "hfsrb.doh.gov.ph"}) or
            (src == "deped_public" and host in {"depedncr.com.ph", "www.depedncr.com.ph"} and rec.ownership == "public") or
            (src == "deped_masterlist" and host in {"deped.gov.ph", "www.deped.gov.ph", "depedncr.com.ph", "www.depedncr.com.ph"}) or
            (src == "ched_cmo" and host in {"ched.gov.ph", "www.ched.gov.ph", "legacy.ched.gov.ph"} and rec.ownership == "private") or
            (src == "philhealth_hospitals" and host in {"philhealth.gov.ph", "www.philhealth.gov.ph"} and rec.domain == "health") or
            (src == "qc_government" and host == "quezoncity.gov.ph" and rec.ownership == "public")
        ):
            raise ValueError(f"registry row {n} source/URL/ownership mismatch")
        if src == "doh_nhfr" and rec.id_kind != "official_code":
            raise ValueError(f"registry row {n} NHFR requires an official facility code")
        if src in {"deped_public", "deped_masterlist"} and rec.id_kind != "official_code":
            raise ValueError(f"registry row {n} requires official school code")
        unique = (rec.source, rec.source_id)
        if unique in seen:
            raise ValueError(f"duplicate registry source/id: {unique}")
        seen.add(unique)
        records.append(rec)
    return records


def _field(row: Mapping[str, Any], *aliases: str) -> str:
    indexed = {re.sub(r"[^a-z0-9]", "", str(k).casefold()): _str(v) for k, v in row.items()}
    for a in aliases:
        v = indexed.get(re.sub(r"[^a-z0-9]", "", a.casefold()), "")
        if v:
            return v
    return ""


def _raw_rows(path: Path) -> list[dict[str, str]]:
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        import pandas as pd
        return pd.read_excel(path, dtype=str).fillna("").to_dict("records")
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    raise ValueError("official export must be CSV or Excel (.xlsx/.xls)")


def import_export(path: Path, source: str, *, as_of: str, source_url: str) -> list[Institution]:
    """Read official exports with *explicit* ownership; unknown types are excluded.

    Supported formats:
      DOH NHFR: Facility Code/Name, Ownership Major Classification, Type, City
      DepEd: School ID, School Name, Sector/Classification, Division/City

    The caller must supply a source URL describing the downloaded official export.
    Generic DepEd entries without an ownership field are NEVER guessed.
    """
    if source not in {"doh_nhfr", "deped_masterlist"}:
        raise ValueError("unsupported official export type")
    if not valid_url(source_url):
        raise ValueError("export source URL must be the official HTTPS registry")
    host = urlparse(source_url).hostname.lower()
    allowed_hosts = {"doh_nhfr": {"nhfr.doh.gov.ph", "hfsrb.doh.gov.ph"},
                     "deped_masterlist": {"deped.gov.ph", "www.deped.gov.ph", "depedncr.com.ph", "www.depedncr.com.ph"},
    }
    if host not in allowed_hosts[source]:
        raise ValueError("the official export URL is not from the selected registry")
    records = []
    ids = set()
    for row in _raw_rows(path):
        if source == "doh_nhfr":
            identifier = _field(row, "Health Facility Code", "Facility Code", "NHFR Code")
            name = _field(row, "Health Facility Name", "Facility Name", "Name of Health Facility")
            label = key(_field(row, "Ownership Major Classification", "Ownership Major", "Ownership"))
            facility_type = key(_field(row, "Health Facility Type", "Type of Health Facility", "Facility Type"))
            city = _field(row, "City/Municipality", "City Municipality", "Municipality", "City")
            address = _field(row, "Street Address", "Address", "Street")
            domain = "health"
            # This first release tests *hospitals*, not all providers.
            if not re.search(r"\bhospital\b", facility_type):
                continue
            ownership = "public" if label in {"government", "public", "government owned"} else "private" if label in {"private", "privately owned"} else ""
        elif source == "deped_masterlist":
            identifier = _field(row, "School ID", "SchoolID")
            name = _field(row, "School Name", "School")
            label = key(_field(row, "Sector", "School Type", "Public/Private Classification", "Ownership", "Classification"))
            city = _field(row, "City/Municipality", "City", "Division", "Schools Division Office")
            address = _field(row, "Address", "School Address")
            domain = "education"
            ownership = "public" if label == "public" else "private" if label == "private" else ""
        if not identifier or not name or not ownership or not city_is_qc(city):
            continue
        if identifier in ids:
            raise ValueError(f"duplicate registry identifier in {path}: {identifier}")
        ids.add(identifier)
        records.append(Institution(source, identifier, name, domain, ownership, "Quezon City", address,
                                   (), source_url, as_of, "official_code", "explicit_sector"))
    return records


class RegistryIndex:
    def __init__(self, records: Iterable[Institution]):
        self.records = tuple(records)
        self.by_name: dict[str, list[tuple[Institution, str]]] = {}
        self.by_code: dict[tuple[str, str], list[Institution]] = {}
        for r in self.records:
            for name, basis in [(r.name, "EXACT_NAME_CITY"), *[(s, "OFFICIAL_ALIAS_CITY") for s in r.aliases]]:
                k = key(name)
                if k:
                    self.by_name.setdefault(k, []).append((r, basis))
            if r.id_kind == "official_code":
                self.by_code.setdefault((r.source, r.source_id.casefold()), []).append(r)

    def match(self, row: Mapping[str, Any], domain: str) -> Match:
        """City-scoped, identity-exact matching. No substring or fuzzy score."""
        if domain not in {"education", "health"}:
            return Match()
        # An explicit non-QC place address overrides the caller's QC workspace scope.
        city_values = [_str(row.get(c)) for c in ("city", "municipality", "osm_city", "overture_city")]
        if any(v and not city_is_qc(v) for v in city_values):
            return Match("CITY_CONFLICT", note="source_city_outside_quezon_city")
        id_fields = {"deped_masterlist": ("deped_school_id",),
                     "deped_public": ("deped_school_id",),
                     "doh_nhfr": ("nhfr_code", "doh_facility_code"),
        }
        id_matches: list[Institution] = []
        # Only a source's *actual external code* can qualify as exact ID.
        for src, cols in id_fields.items():
            for col in cols:
                value = _str(row.get(col))
                if value:
                    id_matches.extend(self.by_code.get((src, value.casefold()), []))
        # OSM refs may be kept in the source category or in a named column.
        tags = " | ".join(_str(row.get(c)) for c in ("osm_category", "overture_category"))
        for src, tag in (("deped_public", "ref:deped"), ("deped_masterlist", "ref:deped"),
                         ("doh_nhfr", "ref:nhfr")):
            m = re.search(r"(?:^|\|)\s*" + re.escape(tag) + r"\s*=\s*([^|]+)", tags, flags=re.I)
            if m:
                id_matches.extend(self.by_code.get((src, m.group(1).strip().casefold()), []))
        if id_matches:
            matches = [(r, "EXACT_EXTERNAL_ID") for r in id_matches if r.domain == domain]
            # A valid-looking external code attached to a clearly different name
            # signals a reconciliation error, not a permission to transfer ownership.
            observed = {key(_str(row.get(k))) for k in ("name", "canonical_name", "osm_name", "overture_name") if _str(row.get(k))}
            registry_names = {key(n) for r, _ in matches for n in (r.name, *r.aliases)}
            if observed and registry_names and not observed & registry_names:
                return Match("EXTERNAL_ID_NAME_CONFLICT", note="external_id_and_name_disagree", independent_records=len(matches))
        else:
            # Collapse OSM and Overture duplicates; never tokenize or contain-match.
            names = {_str(row.get(k)) for k in ("name", "canonical_name", "osm_name", "overture_name") if _str(row.get(k))}
            matches = []
            for n in names:
                matches.extend((r, basis) for r, basis in self.by_name.get(key(n), ()) if r.domain == domain)
        # Collate independent official records; reject opposite sides and address conflict.
        grouped = {(r.source, r.source_id): (r, b) for r, b in matches}
        if not grouped:
            return Match()
        values = list(grouped.values())
        if not id_matches:
            # A secondary OSM/Overture name must not override a different fused
            # canonical identity (e.g. hospital tenant with parent hospital alias).
            primary = key(row.get("name") or row.get("canonical_name"))
            official_keys = {key(n) for r, _ in values for n in (r.name, *r.aliases)}
            if primary and primary not in official_keys:
                return Match("CANONICAL_NAME_CONFLICT", note="main_name_disagrees_with_source_name", independent_records=len(values))
        sides = {r.ownership for r, _ in values}
        if len({key(r.name) for r, _ in values}) > 1:
            return Match("IDENTITY_AMBIGUOUS", note="two_different_registered_names_in_one_place", independent_records=len(values))
        if len(sides) != 1:
            return Match("OWNERSHIP_CONFLICT", note="registry_records_disagree", independent_records=len(values))
        # Same name, different official codes within the same registry can be different campuses.
        src_counts: dict[str, set[str]] = {}
        for r, _ in values:
            src_counts.setdefault(r.source, set()).add(r.source_id)
        if any(len(ids) > 1 for ids in src_counts.values()):
            return Match("IDENTITY_AMBIGUOUS", note="same_source_multiple_facilities", independent_records=len(values))
        # An OSM/Overture explicit address, if supplied, must not contradict a known city.
        addresses = [_str(row.get(c)) for c in ("address", "osm_address", "overture_address")]
        if any(a and re.search(r"\b(?:manila city|caloocan city|pasig city|marikina city|valenzuela city)\b", key(a)) for a in addresses):
            return Match("CITY_CONFLICT", note="address_outside_quezon_city")
        matched = sorted(values, key=lambda x: (x[0].source, x[0].source_id))
        kind = "EXACT_EXTERNAL_ID" if id_matches else ("EXACT_NAME_CITY" if any(b == "EXACT_NAME_CITY" for _, b in values) else "OFFICIAL_ALIAS_CITY")
        return Match(kind, next(iter(sides)), "external_official_id" if id_matches else "unique_name_city_provisional",
                     "|".join(sorted({r.source for r, _ in matched})),
                     "|".join(f"{r.source}:{r.source_id}" for r, _ in matched),
                     matched[0][0].name,
                     "|".join(sorted({r.source_url for r, _ in matched})),
                     "identity_not_proven_by_name_only" if not id_matches else "external_id_match",
                     len(matched))


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

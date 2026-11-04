"""UniFAST RA 10931 participating HEIs: cautious exact-name/region candidate index.

No municipality, PSGC, official HEI ID, or verified canonical identity is inferred.
A UniFAST record_key is a *local* deterministic digest, never an official code.
Candidates may aid review; they must not directly promote IO ownership.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping

from .registry import Match, key

SOURCE = "https://unifast.gov.ph/hei-list.html"
RESOURCE = "unifast_hei_ra10931.csv.gz"
FIELDS = ("region", "hei_name", "hei_type", "ownership", "source_url", "accessed_utc", "record_key")
TYPES = {"Private HEI": "private", "SUC": "public", "LUC": "public", "CHED Supervised Inst.": ""}
REGION = re.compile(r"^(\d{2}[A-Z]?)\s*-\s*(.+)$", re.I)
DIGEST = re.compile(r"[0-9a-f]{20}")


def _s(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.casefold() in {"nan", "none", "<na>"} else re.sub(r"\s+", " ", s)


def _record_key(region: str, name: str) -> str:
    raw = f"{region.casefold()}\0{name.casefold()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def _region_code(v: str) -> str:
    s = _s(v).upper()
    match = REGION.match(s)
    if match:
        return match.group(1)
    # Only a region code is accepted; city/municipality is not inferred.
    if re.fullmatch(r"\d{2}[A-Z]?", s):
        return s
    return ""


@dataclass(frozen=True, slots=True)
class UniFASTHEI:
    region: str
    hei_name: str
    hei_type: str
    ownership: str
    source_url: str
    accessed_utc: str
    record_key: str


def load_unifast(path: Path) -> list[UniFASTHEI]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("UniFAST CSV must have exact capture schema")
        rows = list(reader)
    if not rows:
        raise ValueError("empty UniFAST reference")
    result, seen = [], set()
    for line, row in enumerate(rows, 2):
        values = {column: _s(row.get(column)) for column in FIELDS}
        region, name, typ = values["region"], values["hei_name"], values["hei_type"]
        record_key = values["record_key"]
        if not REGION.match(region) or not name or typ not in TYPES:
            raise ValueError(f"UniFAST invalid region/name/type on line {line}")
        if values["ownership"] != TYPES[typ]:
            raise ValueError(f"UniFAST explicit type/ownership disagreement on line {line}")
        if values["source_url"] != SOURCE or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", values["accessed_utc"]):
            raise ValueError(f"UniFAST provenance is invalid on line {line}")
        if not DIGEST.fullmatch(record_key) or record_key != _record_key(region, name):
            raise ValueError(f"UniFAST local record key invalid on line {line}")
        identity = (region.casefold(), name.casefold())
        if identity in seen:
            raise ValueError(f"duplicate UniFAST name/region on line {line}")
        seen.add(identity)
        result.append(UniFASTHEI(**values))
    return result


def packaged_unifast() -> list[UniFASTHEI]:
    with resources.as_file(resources.files("sigma.resources.classification").joinpath(RESOURCE)) as path:
        return load_unifast(path)


class UniFASTIndex:
    """A region-aware candidate index, never a verified institutional link."""

    def __init__(self, entries: Iterable[UniFASTHEI]):
        self.by_name: dict[str, list[UniFASTHEI]] = defaultdict(list)
        seen = set()
        for entry in entries:
            ident = (entry.region.casefold(), entry.hei_name.casefold())
            if ident in seen:
                raise ValueError("duplicate HEI name/region")
            seen.add(ident)
            self.by_name[key(entry.hei_name)].append(entry)

    def match(self, row: Mapping[str, Any], domain: str) -> Match:
        if domain != "education":
            return Match()
        names = [key(row.get(c)) for c in ("name", "canonical_name", "osm_name", "overture_name")]
        names = [n for n in names if n]
        main = names[0] if names else ""
        entries = {e.record_key: e for name in names for e in self.by_name.get(name, ())}
        if not entries:
            return Match()
        if main and not any(key(e.hei_name) == main for e in entries.values()):
            return Match("CANONICAL_NAME_CONFLICT", note="secondary_source_name_only")
        entries = {k: e for k, e in entries.items() if not main or key(e.hei_name) == main}
        input_regions = {_region_code(row.get(c)) for c in ("region", "region_code", "admin_region")}
        input_regions.discard("")
        if len(input_regions) > 1:
            return Match("CITY_CONFLICT", note="conflicting_region_tags")
        if input_regions:
            found_region = next(iter(input_regions))
            same_region = {k: e for k, e in entries.items() if _region_code(e.region) == found_region}
            if not same_region:
                return Match("CITY_CONFLICT", note="unifast_region_differs_from_place")
            entries = same_region
        if len(entries) > 1:
            sides = {e.ownership for e in entries.values() if e.ownership}
            if len(sides) > 1:
                return Match("OWNERSHIP_CONFLICT", note="same_hei_name_different_ownership", independent_records=len(entries))
            return Match("IDENTITY_AMBIGUOUS", note="same_hei_name_multiple_regions_or_records", independent_records=len(entries))
        entry = next(iter(entries.values()))
        if not entry.ownership:
            return Match("UNIFAST_TYPE_REVIEW", note="type_not_equated_with_public_private")
        status = "UNIFAST_NAME_REGION_PROVISIONAL" if input_regions else "UNIFAST_NAME_ONLY_PROVISIONAL"
        return Match(status, entry.ownership, "unifast_name_provisional", "unifast_ra10931",
                     f"unifast_ra10931:{entry.record_key}", entry.hei_name, entry.source_url,
                     "participating_HEI_only;local_record_key_not_official;name_not_verified_site;"
                     f"region={entry.region};type={entry.hei_type}", 1)

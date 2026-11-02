"""Opt-in ownership / PSIC-candidate shadow resolver (v3).

No active SIGMA classifications are changed. No name-based ownership guesses.
No benchmark ground-truth labels are inputs. External registry matches require
independently verified *canonical_id* links, never approximate name matching.

The caller supplies the installed PSIC taxonomy and IOMapping; the official
PSIC-to-IO relationship is not duplicated here. Unknown, conflicting or
unsupported refinements abstain instead of assigning an economic sector.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from .registry import RegistryIndex, Match

SHADOW_VERSION = "shadow-evidence-v3"
# This is an eligibility guard, matching SIGMA's existing public/private IO pairs.
# PSIC -> IO assignments are still derived and checked against IOMapping.
DOMAINS = {
    "education": {"public": ("74", "229"), "private": ("75", "230")},
    "health": {"public": ("76", "231"), "private": ("77", "232")},
}
ACTIVITY_BLOCKED_STATUSES = frozenset({"NOT_PSIC_ACTIVITY", "UNCODEABLE", "REVIEW_ENTITY_MATCH", "CANDIDATES_ONLY", "CONFLICT"})
NONENTITY_OSM = ("public_transport=platform", "highway=bus_stop", "railway=station")
NONENTITY_OVERTURE = ("bus_stop", "transit_stop", "train_station", "restaurant", "chapel", "pharmacy")
SUBUNIT_RE = re.compile(
    r"(?:\b\d+(?:st|nd|rd|th)\s+floor\b|\b(?:annex|ward|icu|chapel|"
    r"auditorium|department|dept\.?|dialysis\s+unit|division\s+of|"
    r"emergency\s+(?:ward|room)|medical\s+arts|"
    r"internal\s+medicine|outpatient|doctors?\s+offices?)\b|\s@\s)", re.I
)
GOV_OPERATOR_RE = re.compile(
    r"\b(?:department\s+of\s+(?:health|education|science\s+and\s+technology)|"
    r"deped|doh|dost|schools?\s+division|division\s+of\s+(?:city\s+)?schools|"
    r"city\s+schools\s+division|school\s+district|"
    r"quezon\s+city\s+(?:general\s+hospital|government)|"
    r"(?:city|municipal|provincial)\s+government\s+of|"
    r"local\s+government\s+unit)\b", re.I
)
OWNERSHIP_KEYS = frozenset({"ownership", "owner:type", "owner_type", "ownership:type"})
PUBLIC_VALUES = frozenset({"public", "government", "state", "national_government", "local_government"})
PRIVATE_VALUES = frozenset({"private", "privately_owned"})


def clean(value: Any) -> str:
    """Convert a nullable Parquet/CSV scalar to text, without stringifying NaN."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        import pandas as pd
        if bool(pd.isna(value)):
            return ""
    except (ImportError, TypeError, ValueError):
        pass
    return str(value).strip()


def norm(value: Any) -> str:
    s = unicodedata.normalize("NFKD", clean(value).casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def codes(value: Any) -> frozenset[str]:
    return frozenset(x.strip() for x in re.split(r"[;|]", clean(value)) if x.strip())


def parts(row: Mapping[str, Any], column: str) -> list[str]:
    return [p.strip().casefold() for p in clean(row.get(column)).split("|") if p.strip()]


def _sources(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [(src, part) for src in ("osm", "overture") for part in parts(row, src + "_category")]


def domain_of(row: Mapping[str, Any]) -> str:
    p80, p240 = codes(row.get("io80_codes")), codes(row.get("io240_codes"))
    for domain, sides in DOMAINS.items():
        if p80 == {v[0] for v in sides.values()} or p240 == {v[1] for v in sides.values()}:
            return domain
    return ""


def entity_gate(row: Mapping[str, Any], domain: str) -> tuple[str, str]:
    """Conservative gate: this is not a full cross-source identity resolver."""
    categories = _sources(row)
    osm = [cat for src, cat in categories if src == "osm"]
    overture = [cat for src, cat in categories if src == "overture"]
    if any(any(k in c for k in NONENTITY_OSM) for c in osm):
        return "blocked", "transport_or_noninstitution_osm"
    if any(c in NONENTITY_OVERTURE for c in overture):
        return "blocked", "noninstitution_overture"
    hospital_tags = {"amenity=hospital", "healthcare=hospital", "hospital"}
    school_tags = {"amenity=school", "amenity=university", "school", "elementary_school", "high_school", "university", "college"}
    all_categories = {c for _, c in categories}
    if domain == "education" and hospital_tags & all_categories and not school_tags & all_categories:
        return "blocked", "hospital_activity_conflicts_with_education_psic"
    if domain == "health" and school_tags & all_categories and not hospital_tags & all_categories:
        return "blocked", "education_activity_conflicts_with_health_psic"
    name = next((value for col in ("name", "overture_name", "osm_name")
                 if (value := clean(row.get(col)))), "")
    if SUBUNIT_RE.search(name):
        return "review", "possible_hospital_or_school_subunit"
    # Fused canonical names can hide a unit visible in one raw source name.
    # Do not inherit ownership into those records by matching the other name.
    other_names = [clean(row.get(c)) for c in ("osm_name", "overture_name")]
    if any(SUBUNIT_RE.search(value) for value in other_names if value):
        return "review", "possible_subunit_in_source_name"
    if norm(row.get("psic_status")) in (s.casefold() for s in ACTIVITY_BLOCKED_STATUSES):
        return "blocked", "unresolved_or_incompatible_psic"
    if not clean(row.get("psic_code")):
        return "blocked", "no_psic_code"
    if domain not in DOMAINS:
        return "blocked", "no_supported_io_ownership_pair"
    return "main_candidate", "source_activity_and_psic_pair"


def explicit_evidence(row: Mapping[str, Any], domain: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for src, cat in _sources(row):
        if domain == "education" and src == "overture" and cat in {"public_school", "private_school"}:
            out.append(("public" if cat == "public_school" else "private", f"{src}:{cat}"))
        if "=" not in cat:
            continue
        key, value = (p.strip() for p in cat.split("=", 1))
        if key in OWNERSHIP_KEYS:
            if value in PUBLIC_VALUES:
                out.append(("public", f"{src}:{cat}"))
            elif value in PRIVATE_VALUES:
                out.append(("private", f"{src}:{cat}"))
    for key in ("osm_ownership", "overture_ownership", "osm_owner_type", "overture_owner_type"):
        value = norm(row.get(key)).replace(" ", "_")
        if value in PUBLIC_VALUES:
            out.append(("public", f"{key}={value}"))
        if value in PRIVATE_VALUES:
            out.append(("private", f"{key}={value}"))
    return sorted(set(out))


def operator_evidence(row: Mapping[str, Any]) -> list[str]:
    vals = []
    for src, cat in _sources(row):
        if "=" not in cat:
            continue
        k, v = (p.strip() for p in cat.split("=", 1))
        if k == "operator" and GOV_OPERATOR_RE.search(norm(v)):
            vals.append(f"{src}:operator={v}")
    for column in ("osm_operator", "overture_operator"):
        value = clean(row.get(column))
        if value and GOV_OPERATOR_RE.search(norm(value)):
            vals.append(f"{column}={value}")
    return sorted(set(vals))


@dataclass(frozen=True)
class RegistryLink:
    canonical_id: str
    domain: str
    side: str
    source_url: str
    register_id: str
    verified_as_of: str


def load_registry_links(payload: Mapping[str, Any]) -> dict[str, RegistryLink]:
    """Only independently verified record-ID links; no names/aliases are resolved here.

    This intentionally does NOT accept the diagnostic roster schema.
    A registry entry is not accepted without verified=true and a source URL.
    """
    if payload.get("schema") != "sigma-verified-canonical-links-v1":
        raise ValueError("unsupported registry link schema; benchmark rosters are not registry links")
    links = {}
    for row in payload.get("links", []):
        if row.get("verified") is not True:
            raise ValueError("registry links must be independently verified")
        canonical_id = clean(row.get("canonical_id"))
        domain, side = clean(row.get("domain")), clean(row.get("ownership"))
        source_url, register_id = clean(row.get("source_url")), clean(row.get("registry_id"))
        asof = clean(row.get("verified_as_of"))
        if (not canonical_id.startswith("ss_") or domain not in DOMAINS or
                side not in {"public", "private"} or not source_url.startswith("https://") or
                not register_id or not asof):
            raise ValueError(f"invalid verified link: {canonical_id!r}")
        if canonical_id in links:
            raise ValueError(f"duplicate verified canonical ID: {canonical_id}")
        links[canonical_id] = RegistryLink(canonical_id, domain, side, source_url, register_id, asof)
    return links


def compress_tree(taxonomy: Any, root: str, allowed: frozenset[str]) -> tuple[str, ...]:
    """Minimum disjoint subtree cover. Never implies a singleton PSIC when it isn't."""
    def walk(code: str) -> list[str]:
        leaves = taxonomy.leaves(code)
        if leaves <= allowed:
            return [code]
        if not leaves & allowed:
            return []
        return [x for child in taxonomy.children(code) for x in walk(child)]
    return tuple(walk(root))


class ShadowResolver:
    """Purely additive classifier: emits shadow_* data, never edits active columns."""
    def __init__(self, taxonomy: Any, io_mapping: Any, registry_links: Mapping[str, RegistryLink] | None = None, registry_index: RegistryIndex | None = None):
        self.taxonomy = taxonomy
        self.io_mapping = io_mapping
        self.registry_links = registry_links or {}
        self.registry_index = registry_index
        self._cache: dict[tuple[str, str], dict[str, str]] = {}

    def _refinement(self, psic_code: str, side: str, domain: str) -> dict[str, str]:
        key = (psic_code, side)
        if key in self._cache:
            return self._cache[key]
        result = {"status": "", "psic_roots": "", "psic_single": "", "io80": "", "io240": "", "note": ""}
        if psic_code not in self.taxonomy.nodes:
            result["status"] = "UNKNOWN_PSIC"
            self._cache[key] = result
            return result
        leaves = self.taxonomy.leaves(psic_code)
        typed: dict[str, str] = {}
        for leaf in leaves:
            # A typed PSIC leaf must explicitly name its public/private status.
            title = norm(self.taxonomy.get(leaf).title)
            has_public = bool(re.search(r"\bpublic\b", title))
            has_private = bool(re.search(r"\bprivate\b", title))
            typed[leaf] = "public" if has_public and not has_private else "private" if has_private and not has_public else ""
        if any(not value for value in typed.values()):
            result.update(status="PSIC_OWNERSHIP_NOT_EXHAUSTIVE", note=f"untyped_leaves={sum(not x for x in typed.values())}")
        elif not any(value == side for value in typed.values()):
            result.update(status="SIDE_NOT_IN_PSIC_SUBTREE")
        else:
            allowed = frozenset(leaf for leaf, value in typed.items() if value == side)
            roots = compress_tree(self.taxonomy, psic_code, allowed)
            result["psic_roots"] = "|".join(roots)
            result["psic_single"] = roots[0] if len(roots) == 1 else ""
            # Map each permissible subtree and verify the *whole* union resolves.
            maps = [self.io_mapping.map_psic(code) for code in roots]
            io80 = set().union(*(codes(m.get("io80_codes")) for m in maps)) if maps else set()
            io240 = set().union(*(codes(m.get("io240_codes")) for m in maps)) if maps else set()
            expected80, expected240 = DOMAINS[domain][side]
            if io80 == {expected80} and io240 == {expected240}:
                result.update(status="MAPPED_FROM_PSIC", io80=expected80, io240=expected240)
            else:
                result.update(
                    status="PSIC_IO_MAPPING_UNPROVEN",
                    note=f"mapped_io80={','.join(sorted(io80))};mapped_io240={','.join(sorted(io240))}",
                )
        self._cache[key] = result
        return result

    def resolve(self, row: Mapping[str, Any]) -> dict[str, str]:
        domain = domain_of(row)
        entity, entity_reason = entity_gate(row, domain)
        # Independent registry evidence is also recorded when active PSIC is
        # blocked; a registry cannot silently repair a wrong upstream activity.
        match_domain = domain
        if not match_domain:
            categories = {c for _, c in _sources(row)}
            if categories & {"amenity=hospital", "healthcare=hospital", "hospital"}:
                match_domain = "health"
            elif categories & {"amenity=school", "school", "elementary_school", "high_school", "university", "college"}:
                match_domain = "education"
        regmatch = self.registry_index.match(row, match_domain) if self.registry_index else Match()
        out = {
            "shadow_version": SHADOW_VERSION,
            "shadow_domain": domain,
            "shadow_entity_role": entity,
            "shadow_entity_reason": entity_reason,
            "shadow_side": "",
            "shadow_basis": "",
            "shadow_status": "",
            "shadow_evidence": "",
            "shadow_psic_candidates": "",
            "shadow_psic_single": "",
            "shadow_io80": "",
            "shadow_io240": "",
            "shadow_refinement_status": "",
            "shadow_refinement_note": "",
            "shadow_baseline_conflict": "",
            "shadow_registry_status": regmatch.status,
            "shadow_registry_ownership": regmatch.side,
            "shadow_registry_kind": regmatch.basis,
            "shadow_registry_source": regmatch.source,
            "shadow_registry_ids": regmatch.source_ids,
            "shadow_registry_name": regmatch.name,
            "shadow_registry_urls": regmatch.source_urls,
            "shadow_registry_note": regmatch.note,
            "shadow_registry_count": str(regmatch.independent_records),
        }
        if entity != "main_candidate":
            out["shadow_status"] = "ENTITY_REVIEW" if entity == "review" else "BLOCKED_UPSTREAM"
            return out
        explicit = explicit_evidence(row, domain)
        operator = operator_evidence(row)
        registry = self.registry_links.get(clean(row.get("canonical_id")))
        if registry is not None and registry.domain != domain:
            out.update(shadow_status="REGISTRY_DOMAIN_MISMATCH", shadow_evidence="registry_domain_mismatch")
            return out
        sides = {s for s, _ in explicit}
        if regmatch.status in {"IDENTITY_AMBIGUOUS", "OWNERSHIP_CONFLICT", "CITY_CONFLICT", "EXTERNAL_ID_NAME_CONFLICT", "CANONICAL_NAME_CONFLICT"}:
            out.update(shadow_status="REGISTRY_MATCH_REVIEW", shadow_evidence=regmatch.note)
            return out
        # A name/city match is not a verified record-ID link; it remains
        # provisional and never changes active SIGMA output.
        if regmatch.side:
            sides.add(regmatch.side)
        if registry is not None:
            sides.add(registry.side)
        if len(sides) > 1:
            out.update(shadow_status="EXPLICIT_OR_REGISTRY_CONFLICT", shadow_evidence=json.dumps({"explicit": explicit, "verified_link": registry.register_id if registry else "", "official_match": regmatch.source_ids}, ensure_ascii=False))
            return out
        if registry:
            side = registry.side
            basis = "verified_canonical_registry_link"
            evidences = [f"registry:{registry.register_id}"] + [why for _, why in explicit]
        elif regmatch.side and regmatch.status == "EXACT_EXTERNAL_ID":
            side = regmatch.side
            basis = "official_registry_external_id"
            evidences = [f"official_registry:{regmatch.source_ids}"] + [why for _, why in explicit]
        elif explicit:
            side = next(iter(sides))
            basis = "explicit_source_attribute"
            evidences = [why for _, why in explicit] + ([f"official_match:{regmatch.source_ids}"] if regmatch.side else [])
        elif regmatch.side:
            side = regmatch.side
            basis = "official_registry_name_city_provisional"
            evidences = [f"official_registry:{regmatch.source_ids}"]
        elif operator:
            side = "public"
            basis = "government_operator_proxy"
            evidences = operator
        else:
            out["shadow_status"] = "NO_OWNERSHIP_EVIDENCE"
            return out
        # Operation does not establish legal ownership. Conflicts with it are
        # flagged for review rather than silently overriding explicit/private.
        if operator and side == "private":
            out.update(shadow_status="OPERATOR_VS_PRIVATE_CONFLICT", shadow_evidence=json.dumps({"direct": evidences, "operator": operator}, ensure_ascii=False))
            return out
        out.update(shadow_side=side, shadow_basis=basis, shadow_evidence="|".join(evidences))
        old = clean(row.get("ownership_side"))
        if not old:
            oldcode = clean(row.get("io80_code"))
            if oldcode == DOMAINS[domain]["public"][0]:
                old = "public"
            elif oldcode == DOMAINS[domain]["private"][0]:
                old = "private"
        if old in {"public", "private"} and old != side:
            out["shadow_baseline_conflict"] = f"baseline_{old}_vs_{side}"
        psic_code = clean(row.get("psic_code"))
        refined = self._refinement(psic_code, side, domain)
        # A broad PSIC code need not have an exhaustive ownership-typed leaf set.
        # In that case do NOT fabricate a PSIC subclass. However, ownership may
        # still narrow the IO pair when both the row's existing PSIC-derived IO
        # candidate sets AND the installed mapping for its unchanged PSIC code
        # independently contain exactly the same public/private alternatives.
        # This is IO-only refinement: the PSIC code and PSIC proposal stay coarse.
        if refined["status"] == "PSIC_OWNERSHIP_NOT_EXHAUSTIVE":
            expected80 = frozenset(v[0] for v in DOMAINS[domain].values())
            expected240 = frozenset(v[1] for v in DOMAINS[domain].values())
            actual80, actual240 = codes(row.get("io80_codes")), codes(row.get("io240_codes"))
            if actual80 == expected80 and actual240 == expected240:
                mapped = self.io_mapping.map_psic(psic_code)
                if (codes(mapped.get("io80_codes")) == expected80 and
                        codes(mapped.get("io240_codes")) == expected240):
                    selected80, selected240 = DOMAINS[domain][side]
                    refined = {
                        "status": "MAPPED_IO_ONLY_PSIC_COARSE",
                        "psic_roots": "", "psic_single": "",
                        "io80": selected80, "io240": selected240,
                        "note": (f"psic_retained={psic_code};"
                                 f"original_reason={refined['note']};"
                                 "both_io_candidate_pairs_confirmed=true;"
                                 f"mapping_status={clean(mapped.get('io_mapping_status'))};"
                                 f"mapping_provisional={clean(mapped.get('io_mapping_provisional'))}"),
                    }
                else:
                    refined = {
                        **refined,
                        "status": "PARENT_PSIC_IO_PAIR_MISMATCH",
                        "note": (f"psic={psic_code};mapping_io80={mapped.get('io80_codes', '')};"
                                 f"mapping_io240={mapped.get('io240_codes', '')}"),
                    }
            else:
                refined = {
                    **refined, "status": "ROW_IO_PAIR_INCOMPLETE",
                    "note": f"psic={psic_code};row_io80={','.join(sorted(actual80))};row_io240={','.join(sorted(actual240))}",
                }
        out.update(
            shadow_refinement_status=refined["status"],
            shadow_refinement_note=refined["note"],
            shadow_psic_candidates=refined["psic_roots"],
            shadow_psic_single=refined["psic_single"],
            shadow_io80=refined["io80"],
            shadow_io240=refined["io240"],
        )
        out["shadow_status"] = (
            "PROPOSED_IO" if refined["status"] in {
                "MAPPED_FROM_PSIC", "MAPPED_IO_ONLY_PSIC_COARSE"
            } else "OWNERSHIP_ONLY_IO_ABSTAIN"
        )
        return out

    def resolve_frame(self, frame: Any) -> Any:
        """Return a copy with new shadow columns only. No overwrites permitted."""
        import pandas as pd
        output = frame.copy()
        if any(str(c).startswith("shadow_") for c in frame.columns):
            raise ValueError("refusing to overwrite preexisting shadow_* columns")
        rows = [self.resolve(row) for row in frame.to_dict("records")]
        shadow = pd.DataFrame(rows, index=output.index)
        for c in shadow.columns:
            output[c] = shadow[c]
        return output


def summarize(frame: Any) -> dict[str, Any]:
    """Aggregate only; no institutional reference labels involved."""
    out: dict[str, Any] = {"rows": len(frame), "policy": SHADOW_VERSION}
    for key in ("shadow_domain", "shadow_entity_role", "shadow_basis", "shadow_status", "shadow_refinement_status", "shadow_baseline_conflict"):
        out[key] = dict(sorted(Counter(clean(x) or "(blank)" for x in frame[key]).items()))
    return out

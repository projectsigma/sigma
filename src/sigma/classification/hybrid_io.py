"""Conservative hybrid resolver for PSIC-derived and direct I-O evidence.

PSIC remains the canonical economic-activity classification. Direct I-O rules are
used only as independent downstream evidence: to confirm a PSIC-derived singleton,
resolve an ambiguous PSIC-derived I-O set when the direct code lies inside that
set, or provide a fallback when no PSIC-derived I-O candidate set exists.

A direct code never overrides a conflicting PSIC-derived candidate set.

Two further steps run per row:
- ownership (policy ownership-v1): when the PSIC-derived candidates are exactly the
  public/private pair for education or health, name evidence may choose one side;
- level consistency: if a resolved IO240 code is not a child of the resolved IO80 code,
  or an IO80 code is not a child of the IO16 code, the code from the stronger source is
  kept (PSIC outranks direct rules). A stronger finer code replaces the coarser one by its
  parent (DERIVED_FROM_IO240 / DERIVED_FROM_IO80); otherwise the finer code is cleared
  (LEVEL_CONFLICT). Tags are therefore consistent with SIGMA's references by construction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pandas as pd

from .io_mapping_compat import Industry, Rule, deterministic_matches, load_catalog, load_rules
from .ownership import ownership_domain, ownership_evidence

RESOLUTIONS = ("io16", "io80", "io240")
HYBRID_OUTPUT_COLUMNS = (
    "direct_io_status",
    "direct_io80_candidates",
    "direct_io80_code",
    "direct_io16_code",
    "direct_io_sources",
    "direct_io_reason",
    "io16_code",
    "io16_label",
    "io16_status",
    "io16_source",
    "io80_code",
    "io80_label",
    "io80_status",
    "io80_source",
    "io240_code",
    "io240_label",
    "io240_status",
    "io240_source",
    "ownership_domain",
    "ownership_side",
    "ownership_reason",
)
_DIRECT_BLOCKED_PSIC_STATUSES = frozenset(
    {"NOT_PSIC_ACTIVITY", "UNCODEABLE", "REVIEW_ENTITY_MATCH"}
)


@dataclass(frozen=True, slots=True)
class DirectIOEvidence:
    io80_code: str = ""
    io16_code: str = ""
    status: str = "UNRESOLVED"
    sources: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    candidate_codes: tuple[str, ...] = ()


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _codes(value: object) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            part.strip()
            for part in _text(value).replace("|", ";").split(";")
            if part.strip()
        )
    )


def _source_payloads(row: pd.Series | dict[str, Any]) -> list[tuple[str, str, str]]:
    get = row.get
    payloads: list[tuple[str, str, str]] = []
    for source in ("osm", "overture"):
        name = _text(get(f"{source}_name", ""))
        category = _text(get(f"{source}_category", ""))
        if name or category:
            payloads.append((source, name, category))
    if not payloads:
        name = _text(get("name", ""))
        category = _text(get("category", ""))
        if name or category:
            payloads.append(("canonical", name, category))
    return payloads


def direct_io_evidence(
    row: pd.Series | dict[str, Any],
    *,
    catalog: dict[str, Industry] | None = None,
    rules: list[Rule] | None = None,
) -> DirectIOEvidence:
    """Collect conservative direct-IO evidence from independent source semantics."""
    catalog = catalog or load_catalog()
    rules = rules or load_rules()

    hits: list[tuple[str, str, str]] = []
    for source, _name, category in _source_payloads(row):
        # Tags only: names never trigger direct IO rules. Several codes from one
        # source become a CONFLICT below, exactly like disagreeing sources.
        for code, reason in deterministic_matches(category, rules):
            if code in catalog:
                hits.append((source, code, reason))

    if not hits:
        return DirectIOEvidence()

    candidates = tuple(dict.fromkeys(code for _, code, _ in hits))
    sources = tuple(dict.fromkeys(source for source, _, _ in hits))
    reasons = tuple(dict.fromkeys(reason for _, _, reason in hits))

    if len(candidates) != 1:
        return DirectIOEvidence(
            status="CONFLICT",
            sources=sources,
            reasons=reasons,
            candidate_codes=candidates,
        )

    io80_code = candidates[0]
    industry = catalog[io80_code]
    return DirectIOEvidence(
        io80_code=io80_code,
        io16_code=industry.io16_code,
        status="SINGLE",
        sources=sources,
        reasons=reasons,
        candidate_codes=candidates,
    )


def _direct_allowed(row: pd.Series | dict[str, Any]) -> bool:
    status = _text(row.get("psic_status", ""))
    if status in _DIRECT_BLOCKED_PSIC_STATUSES:
        return False
    flags = set(_codes(row.get("psic_flags", "")))
    return "ACTIVITY_NON_ACTIVITY_CONFLICT" not in flags


def _resolve(
    *,
    psic_candidates: tuple[str, ...],
    psic_map_code: str,
    direct_code: str,
    direct_status: str,
    direct_allowed: bool,
) -> tuple[str, str, str]:
    if psic_map_code:
        if direct_status == "SINGLE" and direct_code:
            if direct_code == psic_map_code:
                return psic_map_code, "PSIC_DIRECT_AGREE", "psic+direct"
            return psic_map_code, "PSIC_DIRECT_DISAGREE", "psic"
        return psic_map_code, "PSIC_MAP", "psic"

    if psic_candidates:
        if direct_status == "SINGLE" and direct_code and direct_allowed:
            if direct_code in psic_candidates:
                return direct_code, "HYBRID_RESOLVED", "psic+direct"
            return "", "PSIC_DIRECT_CONFLICT", "conflict"
        if direct_status == "SINGLE" and direct_code and not direct_allowed:
            return "", "DIRECT_BLOCKED_BY_PSIC_POLICY", "psic"
        if direct_status == "CONFLICT":
            return "", "DIRECT_SOURCE_CONFLICT", "conflict"
        return "", "PSIC_AMBIGUOUS", "psic"

    if direct_status == "SINGLE" and direct_code:
        if direct_allowed:
            return direct_code, "DIRECT_FALLBACK", "direct"
        return "", "DIRECT_BLOCKED_BY_PSIC_POLICY", "psic"

    if direct_status == "CONFLICT":
        return "", "DIRECT_SOURCE_CONFLICT", "conflict"
    return "", "UNRESOLVED", ""


def _label_maps(catalog: dict[str, Industry]) -> tuple[dict[str, str], dict[str, str]]:
    io80 = {code: item.io80_label for code, item in catalog.items()}
    io16: dict[str, str] = {}
    for item in catalog.values():
        io16.setdefault(item.io16_code, item.io16_label)
    return io16, io80


def _candidate_label(
    row: pd.Series | dict[str, Any],
    resolution: str,
    code: str,
) -> str:
    codes = _codes(row.get(f"{resolution}_codes", ""))
    names = tuple(
        part.strip()
        for part in _text(row.get(f"{resolution}_names", "")).split(" | ")
        if part.strip()
    )
    return dict(zip(codes, names, strict=False)).get(code, "")


@lru_cache(maxsize=1)
def _builtin_io240_parents() -> dict[str, str]:
    from .reference import load_builtin_io_reference

    return load_builtin_io_reference().io240_parent_map


def _apply_ownership(
    row: pd.Series | dict[str, Any],
    allowed: bool,
    io80: tuple[str, str, str],
    io240: tuple[str, str, str],
) -> tuple[tuple[str, str, str], tuple[str, str, str], tuple[str, str, str]]:
    candidates80 = _codes(row.get("io80_codes", ""))
    candidates240 = _codes(row.get("io240_codes", ""))
    domain = ownership_domain(candidates80, candidates240) if allowed else ""
    if not domain:
        return io80, io240, ("", "", "")
    evidence = ownership_evidence(row, domain)
    if not evidence.side:
        return io80, io240, (domain, "", evidence.reason)
    if not io80[0] and evidence.io80_code in candidates80:
        io80 = (evidence.io80_code, "OWNERSHIP_RESOLVED", "psic+ownership")
    if not io240[0] and evidence.io240_code in candidates240:
        io240 = (evidence.io240_code, "OWNERSHIP_RESOLVED", "psic+ownership")
    return io80, io240, (domain, evidence.side, evidence.reason)


_SOURCE_RANK = {"psic": 2, "psic+direct": 2, "psic+ownership": 2, "direct": 1}


def _level_guard(
    io16: tuple[str, str, str],
    io80: tuple[str, str, str],
    io240: tuple[str, str, str],
    catalog: Mapping[str, Industry],
    parents: Mapping[str, str],
) -> tuple[tuple[str, str, str], tuple[str, str, str], tuple[str, str, str]]:
    """Make the three levels nest. The stronger source wins; PSIC outranks direct rules.

    A finer PSIC-derived code replaces a weaker coarser code by its parent (status
    DERIVED_FROM_IO240 / DERIVED_FROM_IO80). Otherwise the finer code is cleared
    (LEVEL_CONFLICT). With SIGMA's own references neither case occurs for PSIC-only tags.
    """
    conflict = ("", "LEVEL_CONFLICT", "conflict")

    def rank(level: tuple[str, str, str]) -> int:
        return _SOURCE_RANK.get(level[2], 0)

    if io240[0] and io80[0] and io240[0] in parents and parents[io240[0]] != io80[0]:
        if rank(io240) > rank(io80):
            io80 = (parents[io240[0]], "DERIVED_FROM_IO240", io240[2])
        else:
            io240 = conflict
    if io80[0] and io16[0] and io80[0] in catalog and catalog[io80[0]].io16_code != io16[0]:
        if rank(io80) > rank(io16):
            io16 = (catalog[io80[0]].io16_code, "DERIVED_FROM_IO80", io80[2])
        else:
            io80 = conflict
            if io240[0]:
                io240 = conflict
    return io16, io80, io240


def apply_hybrid_io(
    frame: pd.DataFrame,
    *,
    catalog: dict[str, Industry] | None = None,
    rules: list[Rule] | None = None,
    ownership: bool = True,
    io240_parents: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Add authoritative final I-O codes without changing the PSIC decision."""
    result = frame.copy()
    catalog = catalog or load_catalog()
    rules = rules if rules is not None else load_rules()
    parents = io240_parents if io240_parents is not None else _builtin_io240_parents()
    io16_labels, io80_labels = _label_maps(catalog)

    records: list[dict[str, str]] = []
    for _, row in result.iterrows():
        direct = direct_io_evidence(row, catalog=catalog, rules=rules)
        allowed = _direct_allowed(row)

        io16_code, io16_status, io16_source = _resolve(
            psic_candidates=_codes(row.get("io16_codes", "")),
            psic_map_code=_text(row.get("io16_map_code", "")),
            direct_code=direct.io16_code,
            direct_status=direct.status,
            direct_allowed=allowed,
        )
        io80_code, io80_status, io80_source = _resolve(
            psic_candidates=_codes(row.get("io80_codes", "")),
            psic_map_code=_text(row.get("io80_map_code", "")),
            direct_code=direct.io80_code,
            direct_status=direct.status,
            direct_allowed=allowed,
        )
        io240_code, io240_status, io240_source = _resolve(
            psic_candidates=_codes(row.get("io240_codes", "")),
            psic_map_code=_text(row.get("io240_map_code", "")),
            direct_code="",
            direct_status="UNRESOLVED",
            direct_allowed=False,
        )
        owner = ("", "", "")
        if ownership:
            io80_level, io240_level, owner = _apply_ownership(
                row,
                allowed,
                (io80_code, io80_status, io80_source),
                (io240_code, io240_status, io240_source),
            )
            io80_code, io80_status, io80_source = io80_level
            io240_code, io240_status, io240_source = io240_level
        (
            (io16_code, io16_status, io16_source),
            (io80_code, io80_status, io80_source),
            (io240_code, io240_status, io240_source),
        ) = (
            _level_guard(
                (io16_code, io16_status, io16_source),
                (io80_code, io80_status, io80_source),
                (io240_code, io240_status, io240_source),
                catalog,
                parents,
            )
        )

        records.append(
            {
                "direct_io_status": direct.status,
                "direct_io80_candidates": "; ".join(direct.candidate_codes),
                "direct_io80_code": direct.io80_code,
                "direct_io16_code": direct.io16_code,
                "direct_io_sources": "|".join(direct.sources),
                "direct_io_reason": " | ".join(direct.reasons),
                "io16_code": io16_code,
                "io16_label": io16_labels.get(io16_code, ""),
                "io16_status": io16_status,
                "io16_source": io16_source,
                "io80_code": io80_code,
                "io80_label": io80_labels.get(io80_code, ""),
                "io80_status": io80_status,
                "io80_source": io80_source,
                "io240_code": io240_code,
                "io240_label": _candidate_label(row, "io240", io240_code),
                "io240_status": io240_status,
                "io240_source": io240_source,
                "ownership_domain": owner[0],
                "ownership_side": owner[1],
                "ownership_reason": owner[2],
            }
        )

    # Explicit columns keep the output schema when the frame has no rows.
    tagged = pd.DataFrame(records, index=result.index, columns=list(HYBRID_OUTPUT_COLUMNS))
    for column in tagged.columns:
        result[column] = tagged[column]
    return result


def hybrid_io_coverage_summary(frame: pd.DataFrame) -> dict[str, object]:
    """Summarize final hybrid I-O coverage and provenance."""
    resolutions: dict[str, dict[str, object]] = {}
    for resolution in RESOLUTIONS:
        code_col = f"{resolution}_code"
        status_col = f"{resolution}_status"
        source_col = f"{resolution}_source"
        if code_col not in frame:
            coded_rows = 0
        else:
            coded_rows = int(
                frame[code_col].astype("string").fillna("").str.strip().ne("").sum()
            )
        resolutions[resolution] = {
            "coded_rows": coded_rows,
            "status_counts": (
                frame[status_col].fillna("").value_counts().to_dict()
                if status_col in frame
                else {}
            ),
            "source_counts": (
                frame[source_col].fillna("").value_counts().to_dict()
                if source_col in frame
                else {}
            ),
        }
    return {
        "rows": len(frame),
        "direct_status_counts": (
            frame["direct_io_status"].fillna("").value_counts().to_dict()
            if "direct_io_status" in frame
            else {}
        ),
        "resolutions": resolutions,
    }

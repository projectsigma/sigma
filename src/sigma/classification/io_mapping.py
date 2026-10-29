"""Map PSIC Revision 5 classifications to PSA 2018 I-O industry sets.

The bundled concordance was defined on PSIC 2019, so mapping follows:
PSIC Rev. 5 -> PSIC 2019 -> PSA 2018 IO16/IO80/IO240.

One PSIC category may map to several I-O industries. Candidate sets are therefore
preserved and a single map code is exposed only when the candidate set is a singleton,
or when the audited IO80 same-name resolver can resolve one of its supported pairs.

The bridge and the concordance stop at PSIC groups. A bundled refinement table narrows
the IO240 set of a Rev. 5 class or subclass inside its group's set (never outside it);
IO80 and IO16 sets are then narrowed to the parents of the remaining IO240 codes.
A PSIC decision that is a union of subtrees (status UNION) is mapped as the union of
the IO sets of its member codes, so it is never wider than the members justify.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pandas as pd

from .io80_resolver import (
    IO80_RESOLUTION_COLUMNS,
    IO80_RESOLVED_STATUSES,
    parse_candidate_codes,
    resolve_io80_ambiguity,
    validate_io80_map_fields,
)
from .reference import (
    IOBridgeRow,
    IOConcordanceRow,
    IOReferenceCatalog,
    PsicTaxonomy,
    load_builtin_io_reference,
    load_builtin_psic_taxonomy,
)

RESOLUTIONS = ("io16", "io80", "io240")
PSIC_LEVELS = ("section", "division", "group", "class", "subclass")
CODE_DELIMITER = "; "
NAME_DELIMITER = " | "
CONFIDENCE_ORDER = ("High", "High with caveat", "Medium-High", "Medium", "Low")
NOT_MAPPED = "Not mapped"


class IOMappingStatus(StrEnum):
    MAPPED_GROUP = "MAPPED_GROUP"
    MAPPED_DIVISION = "MAPPED_DIVISION"
    MAPPED_SECTION = "MAPPED_SECTION"
    PROVISIONAL_GROUP = "PROVISIONAL_GROUP"
    PROVISIONAL_DIVISION = "PROVISIONAL_DIVISION"
    PROVISIONAL_SECTION = "PROVISIONAL_SECTION"
    NO_IO_CORRESPONDENCE = "NO_IO_CORRESPONDENCE"
    PROVISIONAL_NO_IO_CORRESPONDENCE = "PROVISIONAL_NO_IO_CORRESPONDENCE"
    NO_PSIC2019_COUNTERPART = "NO_PSIC2019_COUNTERPART"
    PROVISIONAL_NO_PSIC2019_COUNTERPART = "PROVISIONAL_NO_PSIC2019_COUNTERPART"
    UNMAPPED_NO_PSIC = "UNMAPPED_NO_PSIC"
    UNMAPPED_UNKNOWN_PSIC_CODE = "UNMAPPED_UNKNOWN_PSIC_CODE"
    UNMAPPED_NO_BRIDGE = "UNMAPPED_NO_BRIDGE"
    MAPPED_UNION = "MAPPED_UNION"
    PROVISIONAL_UNION = "PROVISIONAL_UNION"
    UNMAPPED_UNION_PARTIAL = "UNMAPPED_UNION_PARTIAL"


_MAPPED_AT = {
    "group": IOMappingStatus.MAPPED_GROUP,
    "division": IOMappingStatus.MAPPED_DIVISION,
    "section": IOMappingStatus.MAPPED_SECTION,
}
_PROVISIONAL_AT = {
    "group": IOMappingStatus.PROVISIONAL_GROUP,
    "division": IOMappingStatus.PROVISIONAL_DIVISION,
    "section": IOMappingStatus.PROVISIONAL_SECTION,
}

IO_OUTPUT_COLUMNS = (
    "io_mapping_status",
    "io_mapping_psic_level",
    "io_mapping_psic_code",
    "io_mapping_psic2019_codes",
    "io_mapping_bridge_relation",
    "io_mapping_bridge_basis",
    "io_mapping_refinement_code",
    "io_mapping_refinement_basis",
    "io_mapping_provisional",
    "io16_codes",
    "io16_map_code",
    "io16_map_status",
    "io16_names",
    "io16_confidence",
    "io80_codes",
    "io80_map_code",
    "io80_map_status",
    *IO80_RESOLUTION_COLUMNS,
    "io80_names",
    "io80_confidence",
    "io240_codes",
    "io240_map_code",
    "io240_map_status",
    "io240_names",
    "io240_confidence",
)


def _normalize_title(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("&", " and ")
    return re.sub(r"[^0-9a-z]+", " ", text).strip()


def _weakest(confidences: list[str]) -> str:
    ranked = [CONFIDENCE_ORDER.index(value) for value in confidences if value in CONFIDENCE_ORDER]
    return CONFIDENCE_ORDER[max(ranked)] if ranked else NOT_MAPPED


def _empty(status: IOMappingStatus) -> dict[str, str]:
    row = dict.fromkeys(IO_OUTPUT_COLUMNS, "")
    row["io_mapping_status"] = str(status)
    row["io_mapping_provisional"] = "false"
    for resolution in RESOLUTIONS:
        row[f"{resolution}_map_status"] = "UNMAPPED"
        row[f"{resolution}_confidence"] = NOT_MAPPED
    return row


def _set_map_fields(out: dict[str, str], resolution: str, codes: list[str]) -> None:
    if len(codes) == 1:
        out[f"{resolution}_map_code"] = codes[0]
        out[f"{resolution}_map_status"] = "SINGLETON_CANDIDATE"
    elif codes:
        out[f"{resolution}_map_code"] = ""
        out[f"{resolution}_map_status"] = "AMBIGUOUS_SET"
    else:
        out[f"{resolution}_map_code"] = ""
        out[f"{resolution}_map_status"] = "UNMAPPED"


def _split_codes(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def _resolution(row: IOConcordanceRow, name: str) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    return (
        getattr(row, f"{name}_codes"),
        getattr(row, f"{name}_names"),
        getattr(row, f"{name}_confidence"),
    )


@dataclass
class IOMapping:
    taxonomy: PsicTaxonomy
    reference: IOReferenceCatalog

    def __post_init__(self) -> None:
        self._bridge = {
            (row.rev5_level, row.rev5_code): row for row in self.reference.bridge
        }
        self._concordance = {
            (row.psic_level, row.psic_code): row for row in self.reference.concordance
        }
        for link in self.reference.bridge:
            for code in link.psic2019_codes:
                target_level = (
                    "section"
                    if re.fullmatch(r"[A-Z]", code)
                    else "division"
                    if re.fullmatch(r"[0-9]{2}", code)
                    else "group"
                )
                if (target_level, code) not in self._concordance:
                    raise ValueError(
                        f"PSIC bridge target {code!r} is absent from the I-O concordance"
                    )
        self._names: dict[str, dict[str, str]] = {}
        for resolution in RESOLUTIONS:
            known_names: dict[str, str] = {}
            for row in self.reference.concordance:
                codes, labels, _ = _resolution(row, resolution)
                for io_code, label in zip(codes, labels, strict=True):
                    previous = known_names.setdefault(io_code, label)
                    if previous != label:
                        raise ValueError(
                            f"{resolution} code {io_code} has conflicting names: "
                            f"{previous!r} and {label!r}"
                        )
            self._names[resolution] = known_names
        # IO80 -> IO16 parent, taken from concordance rows with a single IO16 code.
        self._io16_of: dict[str, str] = {}
        for row in self.reference.concordance:
            if len(row.io16_codes) == 1:
                for io80 in row.io80_codes:
                    previous = self._io16_of.setdefault(io80, row.io16_codes[0])
                    if previous != row.io16_codes[0]:
                        raise ValueError(f"IO80 {io80} has two IO16 parents in the concordance")
        self._io80_of = self.reference.io240_parent_map
        # A refinement row is used only when its code and title match the taxonomy
        # in use (the same safety rule as for bridge rows).
        self._refine = {}
        for row in self.reference.refinement:
            node = self.taxonomy.nodes.get(row.rev5_code)
            if node is None or node.level.casefold() != row.rev5_level:
                continue
            if _normalize_title(node.title) != _normalize_title(row.rev5_title):
                continue
            self._refine[row.rev5_code] = row

    @classmethod
    def load_builtin(cls, taxonomy: PsicTaxonomy | None = None) -> IOMapping:
        taxonomy = taxonomy or load_builtin_psic_taxonomy()
        reference = load_builtin_io_reference()
        issues = reference.validate_against(taxonomy)
        if issues:
            raise ValueError(
                f"built-in PSIC/I-O reference has {len(issues)} mismatch(es): "
                + "; ".join(issues[:5])
            )
        return cls(taxonomy, reference)

    def provenance(self) -> dict[str, Any]:
        return {
            "bridge_rows": len(self.reference.bridge),
            "concordance_rows": len(self.reference.concordance),
            "bridge_sha256": self.reference.bridge_sha256,
            "concordance_sha256": self.reference.concordance_sha256,
            "bridge_basis_counts": dict(
                sorted(Counter(row.basis for row in self.reference.bridge).items())
            ),
            "bridge_relation_counts": dict(
                sorted(Counter(row.relation for row in self.reference.bridge).items())
            ),
            "refinement_rows": len(self.reference.refinement),
            "refinement_rows_in_taxonomy": len(self._refine),
            "refinement_sha256": self.reference.refinement_sha256,
            "io240_parent_rows": len(self.reference.io240_parents),
            "io240_parents_sha256": self.reference.parents_sha256,
        }

    def map_psic(self, code: str | None) -> dict[str, str]:
        """Candidate IO sets for one PSIC code: bridge and concordance, then refinement."""
        result = self._map_bridge(code)
        if code is not None and str(code).strip() in self.taxonomy.nodes:
            result = self._apply_refinement(str(code).strip(), result)
        return _with_provisional_flag(result)

    def map_union(self, codes: list[str] | tuple[str, ...]) -> dict[str, str]:
        """Candidate IO sets for a PSIC decision that is a union of subtrees.

        The result is the union of the members' IO sets. If any member has no IO
        correspondence, the union is incomplete and nothing is mapped.
        """
        members = [str(code).strip() for code in codes if str(code).strip()]
        members = list(dict.fromkeys(code for code in members if code in self.taxonomy.nodes))
        if not members:
            return _empty(IOMappingStatus.UNMAPPED_UNKNOWN_PSIC_CODE)
        if len(members) == 1:
            return self.map_psic(members[0])
        parts = [self.map_psic(code) for code in members]
        if any(not part["io240_codes"] and not part["io80_codes"] for part in parts):
            row = _empty(IOMappingStatus.UNMAPPED_UNION_PARTIAL)
            row["io_mapping_psic_code"] = "|".join(members)
            return row
        out = dict.fromkeys(IO_OUTPUT_COLUMNS, "")
        provisional = any(part["io_mapping_provisional"] == "true" for part in parts)
        out.update(
            {
                "io_mapping_status": str(
                    IOMappingStatus.PROVISIONAL_UNION
                    if provisional
                    else IOMappingStatus.MAPPED_UNION
                ),
                "io_mapping_psic_level": "union",
                "io_mapping_psic_code": "|".join(members),
                "io_mapping_psic2019_codes": CODE_DELIMITER.join(
                    dict.fromkeys(
                        code
                        for part in parts
                        for code in _split_codes(part["io_mapping_psic2019_codes"])
                    )
                ),
                "io_mapping_bridge_relation": "|".join(
                    dict.fromkeys(part["io_mapping_bridge_relation"] for part in parts)
                ),
                "io_mapping_bridge_basis": "|".join(
                    dict.fromkeys(part["io_mapping_bridge_basis"] for part in parts)
                ),
                "io_mapping_refinement_code": "|".join(
                    part["io_mapping_refinement_code"]
                    for part in parts
                    if part["io_mapping_refinement_code"]
                ),
                "io_mapping_refinement_basis": "|".join(
                    dict.fromkeys(
                        part["io_mapping_refinement_basis"]
                        for part in parts
                        if part["io_mapping_refinement_basis"]
                    )
                ),
                "io_mapping_provisional": "true" if provisional else "false",
            }
        )
        for resolution in RESOLUTIONS:
            codes = sorted({c for part in parts for c in _split_codes(part[f"{resolution}_codes"])})
            names = self._names[resolution]
            out[f"{resolution}_codes"] = CODE_DELIMITER.join(codes)
            out[f"{resolution}_names"] = NAME_DELIMITER.join(names.get(c, "") for c in codes)
            out[f"{resolution}_confidence"] = _weakest(
                [part[f"{resolution}_confidence"] for part in parts]
            )
            _set_map_fields(out, resolution, codes)
        return {column: str(out[column]) for column in IO_OUTPUT_COLUMNS}

    def _apply_refinement(self, code: str, result: dict[str, str]) -> dict[str, str]:
        row = next(
            (
                self._refine[ancestor]
                for ancestor in self.taxonomy.ancestors(code, include_self=True)
                if ancestor in self._refine
            ),
            None,
        )
        if row is None or not result["io240_codes"]:
            return result
        out = dict(result)
        out["io_mapping_refinement_code"] = row.rev5_code
        base240 = set(_split_codes(result["io240_codes"]))
        base80 = set(_split_codes(result["io80_codes"]))
        base16 = set(_split_codes(result["io16_codes"]))
        refined240 = sorted(row.io240_codes)
        parents80 = {self._io80_of.get(c) for c in refined240}
        parents16 = {self._io16_of.get(c) for c in parents80}
        if (
            not set(refined240) <= base240
            or None in parents80
            or not parents80 <= base80
            or None in parents16
            or not parents16 <= base16
        ):
            # Refinement may only narrow the bridge result; otherwise it is reported, not used.
            out["io_mapping_refinement_basis"] = "not_applied"
            return out
        out["io_mapping_refinement_basis"] = row.basis
        for resolution, codes in (
            ("io240", refined240),
            ("io80", sorted(parents80)),
            ("io16", sorted(parents16)),
        ):
            names = self._names[resolution]
            out[f"{resolution}_codes"] = CODE_DELIMITER.join(codes)
            out[f"{resolution}_names"] = NAME_DELIMITER.join(names.get(c, "") for c in codes)
            _set_map_fields(out, resolution, codes)
        return out

    def _map_bridge(self, code: str | None) -> dict[str, str]:
        if code is None or not str(code).strip():
            return _empty(IOMappingStatus.UNMAPPED_NO_PSIC)
        code = str(code).strip()
        if code not in self.taxonomy.nodes:
            return _empty(IOMappingStatus.UNMAPPED_UNKNOWN_PSIC_CODE)

        chain: list[tuple[str, IOBridgeRow]] = []
        for ancestor in self.taxonomy.ancestors(code, include_self=True):
            node = self.taxonomy.get(ancestor)
            level = node.level.casefold()
            if level not in _MAPPED_AT:
                continue
            link = self._bridge.get((level, node.code))
            if link is None:
                continue
            if _normalize_title(link.rev5_title) != _normalize_title(node.title):
                continue
            chain.append((level, link))

        if not chain:
            return _empty(IOMappingStatus.UNMAPPED_NO_BRIDGE)

        candidate = self._compose(*chain[0])
        first = chain[0][1]
        if first.basis != "draft" or first.relation == "no_counterpart":
            return candidate

        accepted = next(
            ((level, link) for level, link in chain[1:] if link.basis != "draft"),
            None,
        )
        if accepted is not None and accepted[1].relation != "no_counterpart":
            fallback = self._compose(*accepted)
            if all(
                fallback[f"{resolution}_codes"] == candidate[f"{resolution}_codes"]
                for resolution in RESOLUTIONS
            ):
                return fallback
        return candidate

    def _compose(self, level: str, link: IOBridgeRow) -> dict[str, str]:
        targets: list[IOConcordanceRow] = []
        for code in link.psic2019_codes:
            target_level = (
                "section"
                if re.fullmatch(r"[A-Z]", code)
                else "division"
                if re.fullmatch(r"[0-9]{2}", code)
                else "group"
            )
            target = self._concordance.get((target_level, code))
            if target is None:
                raise ValueError(
                    f"PSIC bridge target {code!r} is absent from the I-O concordance"
                )
            targets.append(target)

        out = dict.fromkeys(IO_OUTPUT_COLUMNS, "")
        out.update(
            {
                "io_mapping_psic_level": level,
                "io_mapping_psic_code": link.rev5_code,
                "io_mapping_psic2019_codes": CODE_DELIMITER.join(link.psic2019_codes),
                "io_mapping_bridge_relation": link.relation,
                "io_mapping_bridge_basis": link.basis,
            }
        )

        has_io = False
        for resolution in RESOLUTIONS:
            names: dict[str, str] = {}
            confidences: list[str] = []
            for row in targets:
                codes, labels, confidence = _resolution(row, resolution)
                for io_code, label in zip(codes, labels, strict=True):
                    previous = names.setdefault(io_code, label)
                    if previous != label:
                        raise ValueError(
                            f"{resolution} code {io_code} has conflicting names: "
                            f"{previous!r} and {label!r}"
                        )
                if codes and confidence != NOT_MAPPED:
                    confidences.append(confidence)

            codes = sorted(names)
            has_io = has_io or bool(codes)
            out[f"{resolution}_codes"] = CODE_DELIMITER.join(codes)
            out[f"{resolution}_names"] = NAME_DELIMITER.join(names[code] for code in codes)
            out[f"{resolution}_confidence"] = _weakest(confidences)
            _set_map_fields(out, resolution, codes)

        if link.relation == "no_counterpart":
            status = (
                IOMappingStatus.PROVISIONAL_NO_PSIC2019_COUNTERPART
                if link.basis == "draft"
                else IOMappingStatus.NO_PSIC2019_COUNTERPART
            )
        elif link.basis == "draft":
            status = (
                _PROVISIONAL_AT[level]
                if has_io
                else IOMappingStatus.PROVISIONAL_NO_IO_CORRESPONDENCE
            )
        else:
            status = _MAPPED_AT[level] if has_io else IOMappingStatus.NO_IO_CORRESPONDENCE
        out["io_mapping_status"] = str(status)
        return {column: str(out[column]) for column in IO_OUTPUT_COLUMNS}


def enrich_frame_with_io(
    frame: pd.DataFrame,
    *,
    taxonomy: PsicTaxonomy | None = None,
    mapping: IOMapping | None = None,
) -> pd.DataFrame:
    """Add PSA 2018 IO16/IO80/IO240 candidate and map fields to a classified frame."""
    if "psic_code" not in frame.columns:
        raise ValueError("I-O enrichment requires a psic_code column")
    taxonomy = taxonomy or load_builtin_psic_taxonomy()
    mapping = mapping or IOMapping.load_builtin(taxonomy)

    codes = frame["psic_code"].astype("string").fillna("").str.strip()
    keys = [
        ("union", union) if not code and union else ("code", code)
        for code, union in zip(codes, _union_members(frame), strict=True)
    ]
    lookup: dict[tuple[str, object], dict[str, str]] = {}
    for key in dict.fromkeys(keys):
        kind, value = key
        lookup[key] = (
            mapping.map_union(value) if kind == "union" else mapping.map_psic(value or None)
        )
    # Explicit columns keep the I-O schema when the frame has no rows.
    mapped = pd.DataFrame(
        [lookup[key] for key in keys], index=frame.index, columns=list(IO_OUTPUT_COLUMNS)
    )

    out = frame.copy()
    for column in IO_OUTPUT_COLUMNS:
        out[column] = mapped[column].astype("string")
    return resolve_io80_ambiguity(out)


def _with_provisional_flag(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    provisional = str(out.get("io_mapping_status", "")).startswith("PROVISIONAL") or (
        out.get("io_mapping_refinement_basis") == "draft"
    )
    out["io_mapping_provisional"] = "true" if provisional else "false"
    return out


def _union_members(frame: pd.DataFrame) -> list[tuple[str, ...]]:
    """Member codes of PSIC decisions whose status is UNION, else an empty tuple.

    The fusion candidate codes recorded in the PSIC audit are the union roots. Older
    frames without an audit fall back to ``psic_candidate_codes``.
    """
    if "psic_status" not in frame.columns:
        return [()] * len(frame)
    statuses = frame["psic_status"].astype("string").fillna("")
    blank = pd.Series("", index=frame.index)
    audits = frame["psic_audit"] if "psic_audit" in frame.columns else blank
    candidates = (
        frame["psic_candidate_codes"]
        if "psic_candidate_codes" in frame.columns
        else pd.Series("", index=frame.index)
    )
    out: list[tuple[str, ...]] = []
    for status, audit, fallback in zip(statuses, audits, candidates, strict=True):
        if status != "UNION":
            out.append(())
            continue
        members: list[str] = []
        try:
            payload = json.loads(str(audit)) if audit and str(audit).strip() else {}
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get("fusion_candidate_codes"), list):
            members = [str(code) for code in payload["fusion_candidate_codes"]]
        if not members and isinstance(fallback, str):
            members = [part.strip() for part in fallback.split("|") if part.strip()]
        out.append(tuple(sorted(set(members))))
    return out


def _nonblank(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip().ne("")


def _share(count: int, total: int) -> float:
    return float(count / total) if total else 0.0


def io_coverage_summary(frame: pd.DataFrame) -> dict[str, Any]:
    """Summarize PSIC and I-O coverage; this is coverage, not an accuracy metric."""
    required = {
        "psic_code",
        "psic_status",
        "io_mapping_status",
        *(f"{resolution}_codes" for resolution in RESOLUTIONS),
        *(f"{resolution}_map_code" for resolution in RESOLUTIONS),
        *(f"{resolution}_map_status" for resolution in RESOLUTIONS),
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"I-O coverage summary is missing columns {sorted(missing)}")

    total = int(len(frame))
    psic_mask = _nonblank(frame["psic_code"])
    result: dict[str, Any] = {
        "total_rows": total,
        "psic_coded_rows": int(psic_mask.sum()),
        "psic_coded_share": _share(int(psic_mask.sum()), total),
        "io_mapping_status_counts": {
            str(key): int(value)
            for key, value in frame["io_mapping_status"].value_counts().items()
        },
        "resolutions": {},
    }
    for resolution in RESOLUTIONS:
        parsed = frame[f"{resolution}_codes"].map(parse_candidate_codes)
        counts = parsed.map(len).astype("int64")
        if resolution == "io80":
            validate_io80_map_fields(frame, counts)
        ready = _nonblank(frame[f"{resolution}_map_code"])
        result["resolutions"][resolution] = {
            "available_rows": int(counts.gt(0).sum()),
            "singleton_candidate_rows": int(counts.eq(1).sum()),
            "multiple_candidate_rows": int(counts.gt(1).sum()),
            "map_ready_rows": int(ready.sum()),
            "map_ready_share": _share(int(ready.sum()), total),
            "map_status_counts": {
                str(key): int(value)
                for key, value in frame[f"{resolution}_map_status"].value_counts().items()
            },
            "evidence_resolved_rows": int(
                frame[f"{resolution}_map_status"].isin(IO80_RESOLVED_STATUSES).sum()
            )
            if resolution == "io80"
            else 0,
        }
    return result

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MappingKind(StrEnum):
    EXACT = "EXACT"
    SUBTREE = "SUBTREE"
    UNION = "UNION"
    NOT_ACTIVITY = "NOT_ACTIVITY"
    UNCODEABLE = "UNCODEABLE"


class SourceField(StrEnum):
    CATEGORY = "category"
    NAME = "name"


class FusionStatus(StrEnum):
    EMPTY = "EMPTY"
    SINGLE = "SINGLE"
    NESTED = "NESTED"
    INTERSECT = "INTERSECT"
    UNION = "UNION"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class MappingRule:
    source: str
    source_value: str
    mapping_kind: MappingKind
    codes: tuple[str, ...] = ()
    match_type: str = "exact"
    confidence: float | None = None
    notes: str = ""
    source_field: SourceField = SourceField.CATEGORY


@dataclass(frozen=True, slots=True)
class Evidence:
    source: str
    category: str | None
    name: str | None
    dependency_group: str
    mapping: MappingRule | None = None
    mapping_origin: str = ""
    candidate_codes: tuple[str, ...] = ()
    candidate_scores: tuple[float, ...] = ()
    query_text: str = ""
    rule: str = ""


@dataclass(slots=True)
class FusionDecision:
    status: FusionStatus
    code: str | None
    candidate_codes: list[str] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    independent_groups: int = 0
    flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PsicDecision:
    code: str | None
    level: str | None
    title: str | None
    status: str
    method: str
    candidate_codes: list[str] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    retrieval_score: float | None = None
    rule: str = ""
    query_text: str = ""
    traversal_agreement: float | None = None
    model: str = ""
    audit: dict[str, Any] = field(default_factory=dict)

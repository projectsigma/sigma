from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from importlib import resources

from .normalize import normalize_key, normalize_match_key
from .types import MappingKind, MappingRule, SourceField

_ALLOWED_SOURCES = frozenset({"osm", "overture"})
_ALLOWED_MATCH_TYPES = frozenset({"exact", "contains", "regex"})
_BUILTIN_RULE_FILES = ("psic_rev5.csv", "psic_rev5_reviewed.csv")


class CrosswalkError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CrosswalkMatches:
    entries: tuple[MappingRule, ...] = ()
    ambiguities: tuple[str, ...] = field(default=())

    def __bool__(self) -> bool:
        return bool(self.entries)


def _signature(entry: MappingRule) -> tuple[MappingKind, tuple[str, ...]]:
    codes = tuple(sorted(entry.codes)) if entry.mapping_kind == MappingKind.UNION else entry.codes
    return entry.mapping_kind, codes


class CrosswalkIndex:
    def __init__(self, entries: list[MappingRule]):
        self.entries = list(entries)
        self._exact: dict[tuple[str, str, str], MappingRule] = {}
        self._scanned: dict[
            tuple[str, str], list[tuple[MappingRule, re.Pattern[str] | None, str]]
        ] = defaultdict(list)

        for entry in self.entries:
            source = entry.source.casefold().strip()
            if source not in _ALLOWED_SOURCES:
                raise CrosswalkError(f"unsupported source {entry.source!r}")
            field_name = entry.source_field.value
            kind = entry.match_type.casefold().strip()
            if kind not in _ALLOWED_MATCH_TYPES:
                raise CrosswalkError(f"unsupported match_type {entry.match_type!r}")
            if entry.confidence is not None and not 0.0 <= float(entry.confidence) <= 1.0:
                raise CrosswalkError("crosswalk confidence must be in [0, 1]")
            match_key = normalize_match_key(entry.source_value)
            bucket = (source, field_name)
            if kind == "exact":
                key = (source, field_name, match_key)
                previous = self._exact.get(key)
                if previous is not None and _signature(previous) != _signature(entry):
                    raise CrosswalkError(
                        f"conflicting exact crosswalk rows for {source}:{entry.source_value!r}"
                    )
                self._exact.setdefault(key, entry)
            elif kind == "regex":
                try:
                    pattern = re.compile(entry.source_value, flags=re.I)
                except re.error as exc:
                    raise CrosswalkError(
                        f"invalid regex for {source}:{entry.source_value!r}: {exc}"
                    ) from exc
                self._scanned[bucket].append((entry, pattern, ""))
            else:
                if not match_key:
                    raise CrosswalkError(
                        f"contains crosswalk value normalizes to blank: {entry.source_value!r}"
                    )
                self._scanned[bucket].append((entry, None, match_key))

    @classmethod
    def load_builtin(cls) -> CrosswalkIndex:
        base = resources.files("sigma.resources.classification").joinpath("crosswalks")
        entries: list[MappingRule] = []
        errors: list[str] = []
        for name in _BUILTIN_RULE_FILES:
            target = base.joinpath(name)
            try:
                raw = target.read_bytes().decode("utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{target.name}: {exc}")
                continue
            reader = csv.DictReader(io.StringIO(raw))
            required = {"source", "source_value", "mapping_kind", "codes"}
            missing = required - set(reader.fieldnames or ())
            if missing:
                # Audit-only/suggestion files are valid bundle members but are not rule tables.
                continue
            for line_no, row in enumerate(reader, start=2):
                raw_kind = str(row.get("mapping_kind") or "").strip().upper()
                if not raw_kind:
                    continue
                source = str(row.get("source") or "").strip().casefold()
                if source not in _ALLOWED_SOURCES:
                    continue
                try:
                    kind = MappingKind("EXACT" if raw_kind == "CLASS" else raw_kind)
                except ValueError:
                    errors.append(f"{target.name}:{line_no}: bad mapping_kind {raw_kind!r}")
                    continue
                raw_field = str(row.get("source_field") or "category").strip().casefold()
                try:
                    source_field = SourceField(raw_field)
                except ValueError:
                    errors.append(f"{target.name}:{line_no}: bad source_field {raw_field!r}")
                    continue
                codes = tuple(
                    c.strip()
                    for c in str(row.get("codes") or "").split("|")
                    if c.strip()
                )
                if kind in {MappingKind.EXACT, MappingKind.SUBTREE} and len(codes) != 1:
                    errors.append(
                        f"{target.name}:{line_no}: {kind} requires exactly one code"
                    )
                    continue
                if kind == MappingKind.UNION and len(set(codes)) < 2:
                    errors.append(f"{target.name}:{line_no}: UNION requires at least two codes")
                    continue
                if kind in {MappingKind.NOT_ACTIVITY, MappingKind.UNCODEABLE} and codes:
                    errors.append(f"{target.name}:{line_no}: {kind} must not carry codes")
                    continue
                confidence: float | None = None
                raw_conf = str(row.get("confidence") or "").strip()
                if raw_conf:
                    try:
                        confidence = float(raw_conf)
                    except ValueError:
                        errors.append(f"{target.name}:{line_no}: invalid confidence {raw_conf!r}")
                        continue
                entries.append(
                    MappingRule(
                        source=source,
                        source_value=str(row.get("source_value") or "").strip(),
                        mapping_kind=kind,
                        codes=codes,
                        match_type=str(row.get("match_type") or "exact").strip().casefold(),
                        confidence=confidence,
                        notes=str(row.get("notes") or ""),
                        source_field=source_field,
                    )
                )
        if errors:
            raise CrosswalkError("invalid bundled crosswalk rows:\n- " + "\n- ".join(errors))
        return cls(entries)

    def _field_matches(self, source: str, field_name: str, value: str | None) -> list[MappingRule]:
        if not value:
            return []
        source = source.casefold().strip()
        match_key = normalize_key(value)
        raw = str(value)
        found: list[MappingRule] = []
        exact = self._exact.get((source, field_name, match_key))
        if exact is not None:
            found.append(exact)
        for entry, pattern, contains_key in self._scanned.get((source, field_name), ()):  # type: ignore[arg-type]
            if pattern is not None:
                if pattern.search(raw):
                    found.append(entry)
            elif contains_key in match_key:
                found.append(entry)
        return found

    def matches(
        self,
        source: str,
        *,
        category: str | None,
        name: str | None,
    ) -> CrosswalkMatches:
        category_entries = self._field_matches(source, SourceField.CATEGORY.value, category)
        name_entries = self._field_matches(source, SourceField.NAME.value, name)

        ambiguities: list[str] = []
        chosen: list[MappingRule] = []
        for field_name, candidates in (
            (SourceField.CATEGORY.value, category_entries),
            (SourceField.NAME.value, name_entries),
        ):
            if not candidates:
                continue
            signatures = {_signature(item) for item in candidates}
            if len(signatures) > 1:
                ambiguities.append(f"{source}:{field_name}")
                continue
            chosen.append(candidates[0])

        # Freeze source normalization to prevent accidental caller-specific casing.
        chosen = [replace(item, source=item.source.casefold().strip()) for item in chosen]
        return CrosswalkMatches(tuple(chosen), tuple(ambiguities))

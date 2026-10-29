"""Direct IO80 rules on OpenStreetMap tags.

Rules match parsed ``key=value`` tags of the source category, never substrings of the
text and never the establishment name. A rule term ``key=value`` matches that exact tag
(a semicolon list such as ``cuisine=pizza;burger`` counts each value); ``key=`` matches
any value of the key.

Primary tags are matched first. Auxiliary keys (``cuisine``, ``brand``, ``operator``)
only decide when no primary tag matches any rule, so ``tourism=hotel | cuisine=filipino``
is accommodation, not food service. When the matching tags point to different IO80
codes, every code is returned and the caller treats the place as a conflict.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from importlib import resources

import yaml

from sigma.places.text import clean_text

AUXILIARY_KEYS = frozenset({"brand", "cuisine", "operator"})


@dataclass(frozen=True, slots=True)
class Industry:
    io80_code: str
    io80_label: str
    io16_code: str
    io16_label: str


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    any_terms: tuple[str, ...]
    all_terms: tuple[str, ...]
    reason: str


def load_catalog() -> dict[str, Industry]:
    text = (
        resources.files("sigma.resources.tagging.compatibility")
        .joinpath("industries.csv")
        .read_text(encoding="utf-8")
    )
    out: dict[str, Industry] = {}
    for row in csv.DictReader(io.StringIO(text)):
        industry = Industry(
            io80_code=row["io80_code"],
            io80_label=row["io80_label"],
            io16_code=row["io16_code"],
            io16_label=row["io16_label"],
        )
        out[industry.io80_code] = industry
    return out


def _term(value: object) -> str:
    """Normalize a rule term to ``key=value`` or ``key=`` (lower case, trimmed)."""
    text = clean_text(value).casefold()
    if "=" not in text:
        raise ValueError(f"direct IO rule term must be key=value or key=: {value!r}")
    key, val = text.split("=", 1)
    key, val = key.strip(), val.strip()
    if not key:
        raise ValueError(f"direct IO rule term has no key: {value!r}")
    return f"{key}={val}"


def load_rules() -> list[Rule]:
    text = resources.files("sigma.resources.tagging.compatibility").joinpath("rules.yml").read_text(encoding="utf-8")
    payload = yaml.safe_load(text) or {}
    return [
        Rule(
            code=str(row["code"]).zfill(2),
            any_terms=tuple(_term(x) for x in row.get("any", []) if str(x).strip()),
            all_terms=tuple(_term(x) for x in row.get("all", []) if str(x).strip()),
            reason=str(row.get("reason") or "deterministic rule"),
        )
        for row in payload.get("rules", [])
    ]


def parse_tags(category: object) -> list[tuple[str, str]]:
    """``key=value`` pairs of an OSM-style category; other parts are ignored."""
    pairs: list[tuple[str, str]] = []
    for part in clean_text(category).split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().casefold()
        if not key:
            continue
        for item in value.split(";"):
            item = item.strip().casefold()
            if item:
                pairs.append((key, item))
    return pairs


def _term_matches(term: str, tags: list[tuple[str, str]]) -> bool:
    key, value = term.split("=", 1)
    if value:
        return (key, value) in tags
    return any(tag_key == key for tag_key, _ in tags)


def _rule_match(tags: list[tuple[str, str]], rule: Rule) -> bool:
    all_ok = all(_term_matches(term, tags) for term in rule.all_terms)
    any_ok = not rule.any_terms or any(_term_matches(term, tags) for term in rule.any_terms)
    return bool(rule.any_terms or rule.all_terms) and all_ok and any_ok


def deterministic_matches(
    category: object, rules: list[Rule] | None = None
) -> list[tuple[str, str]]:
    """Distinct ``(io80_code, reason)`` hits for a category; empty when nothing matches."""
    rules = rules if rules is not None else load_rules()
    tags = parse_tags(category)
    primary = [tag for tag in tags if tag[0] not in AUXILIARY_KEYS]
    for subset in (primary, tags):
        hits: dict[str, str] = {}
        for rule in rules:
            if _rule_match(subset, rule):
                hits.setdefault(rule.code, rule.reason)
        if hits:
            return list(hits.items())
    return []


def deterministic_code(name: object, category: object, rules: list[Rule] | None = None):
    """Single direct IO80 code for a category, or None when no rule or several codes match.

    ``name`` is accepted for backward compatibility and is not used.
    """
    hits = deterministic_matches(category, rules)
    return hits[0] if len(hits) == 1 else None

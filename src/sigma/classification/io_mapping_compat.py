from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from importlib import resources

import yaml

from sigma.places.text import combine, fold


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


def load_rules() -> list[Rule]:
    text = resources.files("sigma.resources.tagging.compatibility").joinpath("rules.yml").read_text(encoding="utf-8")
    payload = yaml.safe_load(text) or {}
    return [
        Rule(
            code=str(row["code"]).zfill(2),
            any_terms=tuple(fold(x) for x in row.get("any", []) if str(x).strip()),
            all_terms=tuple(fold(x) for x in row.get("all", []) if str(x).strip()),
            reason=str(row.get("reason") or "deterministic rule"),
        )
        for row in payload.get("rules", [])
    ]


def _rule_match(text: str, rule: Rule) -> bool:
    # fold() turns `key=value` into `key value`; substring matching remains stable.
    all_ok = all(term in text for term in rule.all_terms)
    any_ok = not rule.any_terms or any(term in text for term in rule.any_terms)
    return all_ok and any_ok


def deterministic_code(name: object, category: object, rules: list[Rule] | None = None):
    text = fold(combine(name, category))
    for rule in rules or load_rules():
        if _rule_match(text, rule):
            return rule.code, rule.reason
    return None

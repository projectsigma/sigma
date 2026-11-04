#!/usr/bin/env python3
"""Review nationwide hospital matches without certifying branches or changing ownership.

Consumes the existing read-only national candidate audit CSV, plus the official
installed or repository registry snapshot. Does NOT open or alter GeoParquet,
workspace files, sector tagging, or verified institution_links.json.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from sigma.classification.national_registry import load_national_registry
from sigma.classification.registry import key

ADDITIONAL = (
    "registered_city", "registered_address", "registered_source_id", "registered_id_kind",
    "registered_as_of", "relationship_hypothesis", "locality_basis",
    "current_ownership_side", "ownership_opportunity", "verification_required",
    "promotion_allowed", "review_priority",
)
SIDE_BY_CODE = {"74": "public", "75": "private", "76": "public", "77": "private"}
CONFLICT_STATUSES = frozenset({
    "CANONICAL_NAME_CONFLICT", "EXTERNAL_ID_NAME_CONFLICT", "IDENTITY_AMBIGUOUS",
    "OWNERSHIP_CONFLICT", "CITY_CONFLICT", "REGISTRY_MATCH_REVIEW",
})


def _s(value: object) -> str:
    return "" if value is None else str(value).strip()


def _reference_id(value: str) -> tuple[str, str] | None:
    """Parse `source:source_id`, preserving colons inside publication row IDs."""
    value = _s(value)
    if not value or "|" in value or ";" in value or ":" not in value:
        return None
    source, identifier = value.split(":", 1)
    return (source, identifier) if source and identifier else None


def _locality_class(registered_city: str, address: str, workspace_city: str) -> tuple[str, str]:
    """Location hints are triage clues, never institutional identity proof."""
    city = key(registered_city)
    place = key(workspace_city)
    addr = key(address)
    if not place:
        return "INSTITUTIONAL_AFFILIATION_CANDIDATE", "workspace_locality_not_supplied"
    if city:
        if city == place:
            return "SAME_LOCALITY_SITE_CANDIDATE", "registered_city_equals_workspace_city"
        return "CROSS_LOCALITY_BRANCH_OR_AFFILIATE_CANDIDATE", "registered_city_differs_from_workspace_city"
    # Official snapshots may supply only an address string, not a separate municipality.
    if place in addr:
        return "SAME_LOCALITY_SITE_CANDIDATE", "address_mentions_workspace_city_not_official_psgc"
    return "INSTITUTIONAL_AFFILIATION_CANDIDATE", "registered_city_missing_no_inference_from_address"


def review_rows(audit_rows: list[dict[str, str]], registry_records, *, workspace_city: str = ""):
    """Produce a strictly provisional, deterministic review queue and its counts."""
    records = {(r.source, r.source_id): r for r in registry_records}
    results: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    for raw in audit_rows:
        row = dict(raw)
        ref = _reference_id(row.get("registry_ids", ""))
        rec = records.get(ref) if ref else None
        status = _s(row.get("registry_status"))
        current_side = SIDE_BY_CODE.get(_s(row.get("io80_code")), "")
        suggested = _s(row.get("registry_ownership"))
        if not rec or status in CONFLICT_STATUSES:
            hypothesis = "IDENTITY_CONFLICT_REVIEW"
            locality = "official_identity_not_uniquely_resolved"
        elif status == "EXTERNAL_ID_LOCALITY_REVIEW":
            hypothesis = "CROSS_LOCALITY_BRANCH_OR_AFFILIATE_CANDIDATE"
            locality = "official_code_and_location_disagree_needs_manual_resolution"
        else:
            hypothesis, locality = _locality_class(rec.city, rec.address, workspace_city)
        if not suggested or not rec or status in CONFLICT_STATUSES:
            opportunity = "IDENTITY_REVIEW_FIRST"
        elif not current_side:
            opportunity = "CURRENT_IO80_UNASSIGNED"
        elif current_side == suggested:
            opportunity = "CURRENT_IO80_ALREADY_AGREES"
        else:
            opportunity = "CURRENT_IO80_DISAGREES_REVIEW"
        if hypothesis == "IDENTITY_CONFLICT_REVIEW":
            requirement = "Resolve conflicting names/identifiers; verify actual entity and activity"
        elif hypothesis == "CROSS_LOCALITY_BRANCH_OR_AFFILIATE_CANDIDATE":
            requirement = "Independent official branch/affiliate link or site ID; verify legal owner and activity"
        else:
            requirement = "Independent official site/campus ID or independently verified canonical link"
        row.update({
            "registered_city": rec.city if rec else "",
            "registered_address": rec.address if rec else "",
            "registered_source_id": rec.source_id if rec else "",
            "registered_id_kind": rec.id_kind if rec else "",
            "registered_as_of": rec.as_of if rec else "",
            "relationship_hypothesis": hypothesis,
            "locality_basis": locality,
            "current_ownership_side": current_side,
            "ownership_opportunity": opportunity,
            "verification_required": requirement,
            "promotion_allowed": "false",  # diagnostic output must not certify identities
            "review_priority": "HIGH" if opportunity == "CURRENT_IO80_UNASSIGNED" else "REVIEW",
        })
        results.append(row)
        counts["total"] += 1
        counts[f"relationship:{hypothesis}"] += 1
        counts[f"opportunity:{opportunity}"] += 1
        counts[f"status:{status}"] += 1
    return results, dict(sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True, type=Path, help="Existing read-only QC candidate CSV")
    parser.add_argument("--registry", required=True, type=Path, help="Installed/packaged hospital reference")
    parser.add_argument("--workspace-city", default="", help="Triage hint, not an identity/geographic filter")
    parser.add_argument("--output", required=True, type=Path, help="New review CSV; refuses overwrite")
    parser.add_argument("--summary", type=Path, help="Optional new JSON summary; refuses overwrite")
    args = parser.parse_args()
    out = args.output.resolve()
    summary = args.summary.resolve() if args.summary else None
    if out.exists() or (summary and summary.exists()):
        raise FileExistsError("review output exists; refusing to overwrite")
    if summary and summary == out:
        raise ValueError("summary and CSV must have different paths")
    registry = args.registry.resolve()
    input_path = args.audit.resolve()
    if out in {registry, input_path} or (summary and summary in {registry, input_path}):
        raise ValueError("refusing to write over input files")
    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = tuple(reader.fieldnames or ())
        if not {"registry_status", "registry_ids", "registry_ownership", "io80_code"} <= set(fields):
            raise ValueError("audit missing expected v1 candidate columns")
        audit_rows = list(reader)
    matched, counts = review_rows(
        audit_rows, load_national_registry(registry), workspace_city=args.workspace_city,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    if summary:
        summary.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*fields, *ADDITIONAL], lineterminator="\n")
        writer.writeheader()
        writer.writerows(matched)
    result = {"input_audit": str(input_path), "registry": str(registry),
              "review_csv": str(out), "workspace_city_hint": args.workspace_city,
              "verified_matches_created": 0, "ownership_changes": 0,
              "counts": counts}
    if summary:
        with summary.open("x", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

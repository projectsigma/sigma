#!/usr/bin/env python3
"""Run the opt-in PSIC/ownership shadow resolver against a read-only QC Parquet.

Writes reports only under --out (must not be inside workspace or repo).
Does not invoke source loading, economic builds, SIGMA runs, or scoring.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


def text(x: object) -> str:
    if x is None:
        return ""
    return str(x).strip()


def readcsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def writecsv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--evaluation-csv", type=Path, help="Holdout institutions CSV: evaluation labels only, never input features")
    ap.add_argument("--matched-records-csv", type=Path, help="Earlier 274-record diagnostic to check non-main negatives")
    ap.add_argument("--registry-links", type=Path, help="Optional independently VERIFIED canonical_id links; never the benchmark roster")
    ap.add_argument("--no-seed-registry", action="store_true", help="Disable bundled official QC registry snapshot")
    ap.add_argument("--registry-csv", type=Path, action="append", default=[], help="Additional curated official registry CSV snapshot")
    ap.add_argument("--doh-export", type=Path, help="Optional DOH NHFR export CSV/XLSX (must contain official facility code and ownership)")
    ap.add_argument("--deped-export", type=Path, help="Optional DepEd masterlist CSV/XLSX (must contain school ID and public/private type)")
    ap.add_argument("--doh-as-of", help="As-of date for the DOH export (required when supplied)")
    ap.add_argument("--deped-as-of", help="As-of date for the DepEd export (required when supplied)")
    args = ap.parse_args()
    ws, out = args.workspace.resolve(), args.out.resolve()
    source = ws / "places" / "places.parquet"
    if not source.is_file():
        ap.error(f"missing places Parquet: {source}")
    repo = Path(__file__).resolve().parents[1]
    if is_inside(out, ws) or is_inside(out, repo):
        ap.error("--out must be outside the SIGMA workspace and Git repository")
    if any(path and not path.is_file() for path in (args.evaluation_csv, args.matched_records_csv, args.registry_links, args.doh_export, args.deped_export, *args.registry_csv)):
        ap.error("an optional CSV/registry file was not found")
    try:
        import pandas as pd
        import pyarrow.parquet as pq
    except ImportError as ex:
        ap.error(f"requires SIGMA environment dependencies pandas and pyarrow: {ex}")

    # Prefer this checkout even if conda also contains another sigma installation.
    sys.path.insert(0, str(repo / "src"))
    # The add-on is imported directly without changing SIGMA's public __init__.
    from sigma.classification.reference import load_builtin_psic_taxonomy
    from sigma.classification.io_mapping import IOMapping
    from sigma.classification.shadow import ShadowResolver, load_registry_links, domain_of, summarize
    from sigma.classification.registry import RegistryIndex, records_from_csv, import_export, sha256, key

    parquet = pq.ParquetFile(source)
    columns = set(parquet.schema_arrow.names)
    needed = (
        "canonical_id", "name", "osm_name", "overture_name", "osm_category",
        "overture_category", "osm_operator", "overture_operator", "osm_ownership",
        "overture_ownership", "osm_owner_type", "overture_owner_type",
        "psic_code", "psic_level", "psic_status", "psic_flags",
        "io80_codes", "io240_codes", "io80_code", "io240_code",
        "ownership_side", "ownership_reason", "economy_code",
        "city", "municipality", "osm_city", "overture_city", "address", "osm_address", "overture_address",
        "deped_school_id", "school_id", "nhfr_code", "doh_facility_code",
    )
    read_cols = [c for c in needed if c in columns]
    if not {"canonical_id", "psic_code", "psic_status", "io80_codes", "io240_codes"} <= columns:
        ap.error("Parquet is missing essential PSIC/IO candidate fields")
    frame = pq.read_table(source, columns=read_cols).to_pandas()
    for c in needed:
        if c not in frame.columns:
            frame[c] = ""
    all_count = len(frame)
    assert all_count == parquet.metadata.num_rows
    matched = readcsv(args.matched_records_csv) if args.matched_records_csv else []
    eval_rows = readcsv(args.evaluation_csv) if args.evaluation_csv else []
    evaluation_ids = {x["canonical_id"] for x in eval_rows if x.get("canonical_id")}
    negatives = {x["canonical_id"] for x in matched if x.get("match_role") != "main" and x.get("canonical_id")}
    relevant_ids = evaluation_ids | negatives
    # Load versioned public official records *before* selection so that upstream
    # PSIC-blocked hospitals or schools can be audited as well.
    registry_sources = []
    registry_records = []
    if not args.no_seed_registry:
        seed = repo / "scripts" / "registry_qc_official_sources.csv"
        if not seed.is_file():
            ap.error(f"bundled official registry snapshot missing: {seed}")
        registry_records.extend(records_from_csv(seed))
        registry_sources.append({"kind": "bundled_curated_official", "path": str(seed), "sha256": sha256(seed)})
    for registry_csv in args.registry_csv:
        registry_records.extend(records_from_csv(registry_csv))
        registry_sources.append({"kind": "curated_csv", "path": str(registry_csv.resolve()), "sha256": sha256(registry_csv)})
    imports = (
        ("doh_nhfr", args.doh_export, args.doh_as_of, "https://nhfr.doh.gov.ph/VActivefacilitiesList"),
        ("deped_masterlist", args.deped_export, args.deped_as_of, "https://www.deped.gov.ph/"),
    )
    for kind, path, as_of, url in imports:
        if path is not None:
            if not as_of:
                ap.error(f"--{kind.split('_')[0]}-as-of is required for an official export")
            rows = import_export(path, kind, as_of=as_of, source_url=url)
            registry_records.extend(rows)
            registry_sources.append({"kind": kind, "path": str(path.resolve()), "sha256": sha256(path), "parsed_rows": len(rows)})
    registry_index = RegistryIndex(registry_records)
    print(f"Independent official registry rows: {len(registry_index.records)} from {len(registry_sources)} snapshot(s)")
    eligible = frame.apply(lambda row: bool(domain_of(row)), axis=1)
    registry_name_keys = set(registry_index.by_name)
    # Include exact-name registry references even when PSIC was misclassified.
    registry_names = frame[["name", "osm_name", "overture_name"]].fillna("").astype(str).apply(
        lambda col: col.map(lambda v: key(v) in registry_name_keys)
    ).any(axis=1) if registry_name_keys else pd.Series(False, index=frame.index)
    selected = frame.loc[eligible | frame["canonical_id"].isin(relevant_ids) | registry_names].copy()

    registry = {}
    if args.registry_links:
        # Read and hash independent registry link manifest. It must NOT have the
        # schema of the diagnostic ground-truth roster.
        payload = json.loads(args.registry_links.read_text(encoding="utf-8"))
        registry = load_registry_links(payload)
        if any(x in registry for x in evaluation_ids):
            print("WARNING: Registry links overlap evaluated IDs: these evaluation results are NOT blind!", file=sys.stderr)

    taxonomy = load_builtin_psic_taxonomy()
    mapping = IOMapping.load_builtin(taxonomy)
    resolver = ShadowResolver(taxonomy, mapping, registry, registry_index=registry_index)
    result = resolver.resolve_frame(selected)
    # These assertions are hard safety gates for the saved report.
    for key in ("psic_code", "psic_status", "io80_codes", "io240_codes", "io80_code", "io240_code", "ownership_side", "economy_code"):
        if not result[key].equals(selected[key]):
            raise AssertionError(f"active SIGMA field changed by shadow resolver: {key}")
    if not result["canonical_id"].equals(selected["canonical_id"]):
        raise AssertionError("canonical IDs changed by shadow resolver")
    if len(result) != len(selected):
        raise AssertionError("shadow resolver altered row count")

    out.mkdir(parents=True, exist_ok=True)
    out_fields = [
        "canonical_id", "name", "psic_code", "psic_status", "io80_codes", "io240_codes",
        "io80_code", "io240_code", "ownership_side", "ownership_reason",
        *[c for c in result.columns if c.startswith("shadow_")],
    ]
    saved = result[out_fields].fillna("").astype(str).to_dict("records")
    writecsv(out / "shadow_candidate_records.csv", saved, out_fields)
    by_id = {x["canonical_id"]: x for x in saved}

    eval_results = []
    counts = Counter()
    for x in eval_rows:
        pred = by_id.get(x["canonical_id"])
        if pred is None:
            pred = {}
        actual = x["expected"].strip().casefold()
        side = pred.get("shadow_side", "")
        mapped = pred.get("shadow_status", "") == "PROPOSED_IO"
        # Scored only on actual IO proposals, not unresolved attribute hints.
        if mapped and side in ("public", "private"):
            outcome = "correct" if side == actual else "wrong"
        else:
            outcome = "abstained_or_blocked"
        counts[outcome] += 1
        eval_results.append({
            "roster_id": x["roster_id"], "institution": x["institution"],
            "domain": x["domain"], "expected": actual, "canonical_id": x["canonical_id"],
            "name": x["name"], "existing": x["baseline"],
            "entity_risk_existing": x.get("entity_risk", ""),
            "shadow_side": side, "shadow_basis": pred.get("shadow_basis", ""),
            "shadow_status": pred.get("shadow_status", "NO_MATCH"),
            "shadow_entity_reason": pred.get("shadow_entity_reason", ""),
            "shadow_psic_candidates": pred.get("shadow_psic_candidates", ""),
            "shadow_io80": pred.get("shadow_io80", ""),
            "shadow_refinement_status": pred.get("shadow_refinement_status", ""),
            "outcome": outcome,
        })
    eval_fields = ["roster_id", "institution", "domain", "expected", "canonical_id", "name", "existing",
                   "entity_risk_existing", "shadow_side", "shadow_basis", "shadow_status",
                   "shadow_entity_reason", "shadow_psic_candidates", "shadow_io80",
                   "shadow_refinement_status", "outcome"]
    writecsv(out / "shadow_institution_evaluation.csv", eval_results, eval_fields)

    negative_results = []
    for x in matched:
        if x.get("match_role") == "main":
            continue
        pred = by_id.get(x.get("canonical_id", ""), {})
        if pred.get("shadow_side"):
            negative_results.append({"canonical_id": x["canonical_id"], "name": x["name"],
                                     "match_role": x["match_role"], "shadow_side": pred["shadow_side"],
                                     "shadow_status": pred.get("shadow_status", ""),
                                     "shadow_entity_reason": pred.get("shadow_entity_reason", "")})
    negative_fields = ["canonical_id", "name", "match_role", "shadow_side", "shadow_status", "shadow_entity_reason"]
    writecsv(out / "shadow_nonmain_risks.csv", negative_results, negative_fields)

    # Independently sourced registry matches and unresolved identity risks.
    registry_report = [x for x in saved if x.get("shadow_registry_status") not in {"", "NO_MATCH"}]
    reg_fields = ["canonical_id", "name", "psic_code", "psic_status", "io80_code", "ownership_side",
                  "shadow_entity_role", "shadow_registry_status", "shadow_registry_ownership", "shadow_registry_kind",
                  "shadow_registry_source", "shadow_registry_ids", "shadow_registry_name", "shadow_registry_urls",
                  "shadow_registry_note", "shadow_status", "shadow_side", "shadow_io80", "shadow_baseline_conflict"]
    writecsv(out / "shadow_registry_matches.csv", registry_report, reg_fields)
    # Inspect known registry cases that remain unresolved without hiding them.
    blocked_registry = [r for r in registry_report if r.get("shadow_status") != "PROPOSED_IO"]
    writecsv(out / "shadow_registry_blocked.csv", blocked_registry, reg_fields)
    (out / "shadow_registry_sources.json").write_text(
        json.dumps({"snapshots": registry_sources, "records": len(registry_records),
                    "note": "Names/city are provisional entity links; official code matches are stronger. No benchmark reference labels imported."},
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = summarize(result)
    summary.update({
        "source": str(source), "source_sha256_not_computed": True, "workspace_rows": all_count,
        "records_selected": len(selected), "eligible_candidate_pair_rows": int(eligible.sum()),
        "evaluation_institutions": len(eval_rows), "evaluation_scores": dict(counts),
        "nonmain_exclusion_controls": len([x for x in matched if x.get("match_role") != "main"]),
        "nonmain_records_with_shadow_side": len(negative_results),
        "registry_links_supplied": len(registry),
        "official_registry_records": len(registry_records),
        "official_registry_source_snapshots": registry_sources,
        "registry_match_statuses": dict(Counter(x.get("shadow_registry_status", "NO_MATCH") for x in saved)),
        "registry_matched_records": len(registry_report),
        "registry_blocked_matches": len(blocked_registry),
        "registry_matched_evaluation_institutions": sum(1 for x in eval_results if by_id.get(x["canonical_id"], {}).get("shadow_registry_ownership")),
        "evaluation_uses_independent_registry_names": bool(registry_records),
        "evaluation_is_blind_to_registry": not bool(set(registry) & evaluation_ids) and not any(
            by_id.get(x.get("canonical_id", ""), {}).get("shadow_registry_ownership") for x in eval_rows),
        "safety": "read-only input; no active fields changed; outputs outside workspace/repo",
        "reference": {"taxonomy_fingerprint": taxonomy.fingerprint,
                      "bridge_sha256": mapping.reference.bridge_sha256,
                      "refinement_sha256": mapping.reference.refinement_sha256},
        "limitations": [
            "No new OSM/Overture source refresh or external registry lookup.",
            "Existing exact-name institution benchmark may have entity-boundary errors.",
            "Government operator is evidence of operation, not legal ownership.",
            "No ownership is guessed from weak institution-name tokens.",
            "IO proposals may result from fully typed PSIC subtrees or exact IO-only evidence constraints; IO-only does not refine PSIC.",
            "Education PSIC nodes with untyped leaves remain coarse at PSIC; both row and installed parent IO pairs are required for IO-only refinement.",
            "Registry names and matched source sectors are independent from the 45-label benchmark, but matching to the same named institutions is not out-of-sample validation.",
            "PhilHealth accreditation register is a 2025 snapshot, not the DOH NHFR; original document row indices are not permanent facility IDs.",
            "DepEd public-school and CHED CMO references are selective and may not cover private basic education or all HEIs; DOH NHFR requires a separately downloaded official export.",
            "Exact names and QC city prove a candidate link, not identity. No fuzzy/substring matching, no inheritance by tenants/subunits.",
            "Registry link validation requires independently verified canonical_id and external IDs; benchmark roster not used.",
            "The 45-institution benchmark is purposive and not a population accuracy estimate.",
        ],
    })
    (out / "shadow_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("SIGMA PSIC OWNERSHIP SHADOW — QC READ ONLY")
    print(f"Source: {source}")
    print(f"Workspace rows: {all_count}; selected: {len(selected)}; eligible pairs: {int(eligible.sum())}")
    print("Shadow statuses:", summary["shadow_status"])
    print("Evidence:", summary["shadow_basis"])
    print("Official registry match statuses:", summary["registry_match_statuses"])
    print(f"Official matches: {len(registry_report)}; blocked/review: {len(blocked_registry)}; registry-overlapping controls: {summary['registry_matched_evaluation_institutions']}")
    print("PSIC mapping:", summary["shadow_refinement_status"])
    print(f"Independent controls: {len(eval_rows)}; proposed-IO evaluation: {dict(counts)}")
    print(f"Non-main shadow-side risks: {len(negative_results)}; review the CSV")
    print(f"Outputs: {out}")
    print("No workspace, scoring, clustering, or active PSIC/IO fields changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

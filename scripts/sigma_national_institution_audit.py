"""Read-only, source-provenanced national institution candidate audit for SIGMA.

Only a small set of fields is loaded from the workspace GeoParquet; routes,
geometry and networks are not read. Output is review-only, never verified links.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from sigma.classification.national_registry import (
    NationalRegistryIndex, load_national_registry, national_registry_path,
)
from sigma.classification.shadow import domain_of

FIELDS = ("canonical_id", "name", "psic_code", "io80_codes", "io240_codes", "io80_code",
          "io240_code", "registry_status", "registry_source", "registry_ids",
          "registry_name", "registry_ownership", "registry_source_urls", "registry_note", "action")
READ_COLUMNS = (
    "canonical_id", "name", "canonical_name", "osm_name", "overture_name",
    "osm_category", "overture_category", "city", "municipality", "osm_city", "overture_city",
    "nhfr_code", "doh_facility_code",
    "psic_code", "psic_status", "io80_codes", "io240_codes", "io80_code", "io240_code", "ownership_domain",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Review-only CSV; choose a path outside the workspace")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    target = args.output.resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing audit output: {target}")
    if workspace in target.parents:
        raise ValueError("audit output must be outside the workspace")
    registry_path = national_registry_path(workspace)
    index = NationalRegistryIndex(load_national_registry(registry_path))
    places = workspace / "places" / "places.parquet"
    if not places.is_file():
        raise FileNotFoundError(f"workspace handoff missing: {places}")
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(places)
    columns = [c for c in READ_COLUMNS if c in pf.schema.names]
    if not {"name", "io80_codes", "io240_codes"} <= set(columns):
        raise ValueError("places file lacks required name and IO-candidate fields")
    report, stats = [], Counter()
    for batch in pf.iter_batches(columns=columns, batch_size=4096):
        for row in batch.to_pylist():
            stats["rows"] += 1
            c80 = set(str(row.get("io80_codes") or "").replace(" ", "").split(";"))
            c240 = set(str(row.get("io240_codes") or "").replace(" ", "").split(";"))
            if c80 not in ({"74", "75"}, {"76", "77"}) and c240 not in ({"229", "230"}, {"231", "232"}):
                continue
            stats["eligible"] += 1
            domain = domain_of(row)
            if not domain:
                continue
            hit = index.match(row, domain)
            stats[hit.status] += 1
            if hit.status == "NO_MATCH":
                continue
            report.append({
                "canonical_id": row.get("canonical_id") or "",
                "name": row.get("name") or "",
                "psic_code": row.get("psic_code") or "",
                "io80_codes": row.get("io80_codes") or "",
                "io240_codes": row.get("io240_codes") or "",
                "io80_code": row.get("io80_code") or "",
                "io240_code": row.get("io240_code") or "",
                "registry_status": hit.status,
                "registry_source": hit.source,
                "registry_ids": hit.source_ids,
                "registry_name": hit.name,
                "registry_ownership": hit.side,
                "registry_source_urls": hit.source_urls,
                "registry_note": hit.note,
                "action": "REVIEW_ONLY_NOT_VERIFIED",
            })
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(report)
    print(json.dumps({"workspace": str(workspace), "registry": str(registry_path),
                      "audit": str(target), "review_candidates": len(report),
                      "counts": dict(sorted(stats.items()))}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

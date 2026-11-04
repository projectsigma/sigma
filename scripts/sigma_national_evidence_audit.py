#!/usr/bin/env python3
"""Read-only SIGMA national hospital establishment-evidence enrichment (v6).

Joins a v5 review CSV to an existing places.parquet on canonical_id. Exports
candidate evidence, a review queue, grouped registry IDs and a JSON summary.
Never modifies the repository, the SIGMA workspace, IO tags, or verified links.
No source-name, locality, address or location comparison verifies identity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PATCH_VERSION = "sigma-national-establishment-evidence-v6-20261104"
FIELDS = (
    "canonical_id", "poi_id", "name", "canonical_name", "osm_name", "overture_name",
    "osm_id", "osm_element_id", "overture_id", "overture_source_id", "sources",
    "osm_category", "overture_category", "osm_tags", "overture_tags",
    "osm_operator", "overture_operator", "osm_ownership", "overture_ownership",
    "osm_owner_type", "overture_owner_type",
    "city", "municipality", "osm_city", "overture_city", "address",
    "osm_address", "overture_address", "osm_website", "overture_website", "website",
    "nhfr_code", "doh_facility_code", "deped_school_id",
    "latitude", "longitude", "lat", "lon", "lng",
    "osm_lat", "osm_lon", "overture_lat", "overture_lon", "geometry",
)
EXTRA = (
    "join_status", "matched_source_rows", "place_source_names", "place_canonical_name",
    "source_name_relation",
    "source_categories", "osm_id", "overture_id", "source_websites",
    "source_external_id_values", "source_operational_evidence",
    "source_ownership_evidence", "ownership_evidence_relation",
    "official_ids_observed", "official_id_relation", "official_id_namespace",
    "place_city_values", "place_address_values", "locality_comparison",
    "place_longitude", "place_latitude", "coordinate_basis", "geometry_crs",
    "subunit_or_branch_signal", "candidate_review_reasons", "evidence_priority",
    "identity_verified", "ownership_promotion_allowed",
)
# Institution activity/branches are hints, never a blanket block or identity proof.
SUBUNIT = re.compile(
    r"\b(?:\d+(?:st|nd|rd|th)\s+floor|wing|annex|ward|radiology|"
    r"diagnostic\s+imaging|outpatient|department|emergency\s+room|"
    r"branch|campus|extension\s+campus|laboratory)\b", re.I
)
PUBLIC = {"public", "government", "state", "local_government", "national_government"}
PRIVATE = {"private", "privately_owned"}
NHFR_FIELDS = ("nhfr_code", "doh_facility_code")


def txt(x: Any) -> str:
    if x is None:
        return ""
    try:
        if bool(pd.isna(x)):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(x).strip()
    return "" if s.casefold() in {"nan", "none", "<na>", "nat"} else s


def norm(x: Any) -> str:
    s = unicodedata.normalize("NFKD", txt(x).casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ").replace("’", "").replace("'", "")
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in (txt(x) for x in values) if v))


def combine(values: list[str]) -> str:
    return " | ".join(unique(values))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_review(path: Path) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = tuple(reader.fieldnames or ())
        needed = {"canonical_id", "name", "registry_status", "registry_ids", "registry_ownership",
                  "relationship_hypothesis", "ownership_opportunity", "promotion_allowed"}
        if not needed <= set(fields):
            raise ValueError(f"v5 review is missing columns: {sorted(needed-set(fields))}")
        rows = list(reader)
    ids = [txt(r["canonical_id"]) for r in rows]
    if not rows or not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("v5 review must have nonempty, unique canonical_id values")
    if any(txt(r["promotion_allowed"]).lower() != "false" for r in rows):
        raise ValueError("refusing a review file with promotion enabled")
    return rows, fields


def _get_crs(metadata: Mapping[bytes, bytes] | None) -> str:
    """GeoParquet metadata defaults to OGC:CRS84 only when geo metadata exists."""
    if not metadata or b"geo" not in metadata:
        return "UNKNOWN"
    try:
        geo = json.loads(metadata[b"geo"].decode("utf-8"))
        main = geo.get("primary_column", "geometry")
        item = geo.get("columns", {}).get(main, {})
        if "crs" not in item:
            return "OGC:CRS84"  # GeoParquet spec default
        crs = item["crs"]
        if crs is None:
            return "UNKNOWN"
        if isinstance(crs, str):
            return crs
        if isinstance(crs, dict):
            try:
                from pyproj import CRS
                return CRS.from_json_dict(crs).to_string()
            except (ImportError, ValueError, TypeError):
                return "UNPARSEABLE_PROJJSON"
    except (json.JSONDecodeError, UnicodeError, AttributeError, KeyError):
        return "INVALID_GEO_METADATA"
    return "UNKNOWN"


def read_places(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Column-selective Parquet read. No workspace modification, no network calls."""
    if not path.is_file():
        raise FileNotFoundError(f"places handoff not found: {path}")
    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError(
                "pyarrow is required to read the workspace places.parquet"
            ) from exc
        schema = pq.read_schema(path)
        fields = [n for n in FIELDS if n in schema.names]
        if "canonical_id" not in fields:
            raise ValueError("places.parquet missing canonical_id; cannot safely join")
        frame = pq.read_table(path, columns=fields).to_pandas()
        geometry_crs = _get_crs(schema.metadata)
        all_columns = schema.names
    elif path.suffix.lower() == ".csv":  # small, fixture-based test support
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        all_columns = list(frame.columns)
        if "canonical_id" not in all_columns:
            raise ValueError("places CSV missing canonical_id")
        frame = frame[[c for c in FIELDS if c in frame.columns]]
        geometry_crs = "UNKNOWN"
    else:
        raise ValueError("places must be Parquet or CSV")
    frame["canonical_id"] = frame["canonical_id"].map(txt)
    dup = frame.loc[frame["canonical_id"].ne("") & frame["canonical_id"].duplicated(),
                    "canonical_id"].head(3).tolist()
    if dup:
        raise ValueError(f"duplicate canonical_id in places; refusing ambiguous join: {dup}")
    frame = frame.set_index("canonical_id", drop=False)
    return frame, {"places_rows": len(frame), "schema_columns": len(all_columns),
                   "selected_columns": list(frame.columns), "geometry_crs": geometry_crs,
                   "missing_optional_columns": sorted(set(FIELDS)-set(all_columns))}


def _tags(record: Mapping[str, Any]) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = defaultdict(list)
    for col in ("osm_category", "overture_category"):
        for seg in txt(record.get(col)).split("|"):
            if "=" not in seg:
                continue
            k, v = seg.split("=", 1)
            if k.strip() and v.strip():
                tags[k.strip().casefold()].append(v.strip())
    for col in ("osm_tags", "overture_tags"):
        raw = record.get(col)
        if isinstance(raw, dict):
            pairs = raw.items()
        else:
            try:
                obj = json.loads(txt(raw))
                pairs = obj.items() if isinstance(obj, dict) else []
            except (TypeError, json.JSONDecodeError):
                pairs = []
        for k, v in pairs:
            if k and txt(v):
                tags[str(k).casefold()].append(txt(v))
    return tags


def _all_external_ids(row: Mapping[str, Any], tags: dict[str, list[str]]) -> str:
    listed = []
    for col in (*NHFR_FIELDS, "deped_school_id"):
        value = txt(row.get(col))
        if value:
            listed.append(f"{col}={value}")
    for tag_name in ("ref:nhfr", "nhfr:code", "ref:deped"):
        for v in tags.get(tag_name, []):
            listed.append(f"{tag_name}={v}")
    return combine(listed)


def _source_ids(row: Mapping[str, Any], tags: dict[str, list[str]], source: str, kind: str,
                registry_id: str) -> tuple[str, str, str]:
    """Only an actual official-code namespace is comparable. Never match PDF row numbers."""
    if not registry_id or not source:
        return "NO_UNIQUE_REGISTRY_RECORD", "", ""
    if kind != "official_code":
        return "NOT_COMPARABLE_PUBLICATION_ROW", "", "publication_row_is_not_facility_code"
    if source == "doh_nhfr":
        candidates = unique([*(txt(row.get(k)) for k in NHFR_FIELDS),
                             *tags.get("ref:nhfr", []), *tags.get("nhfr:code", [])])
        namespace = "doh_nhfr"
    else:
        return "NO_COMPARABLE_OFFICIAL_CODE_NAMESPACE", "", source
    if not candidates:
        return "NO_COMPARABLE_ID", "", namespace
    if len({c.casefold() for c in candidates}) > 1:
        return "SOURCE_OFFICIAL_IDS_DISAGREE", combine(candidates), namespace
    if candidates[0].casefold() == registry_id.casefold():
        return "OFFICIAL_CODE_EQUALS_REGISTRY_REVIEW", candidates[0], namespace
    return "OFFICIAL_CODE_CONFLICT_REVIEW", candidates[0], namespace


def _ownership(
    row: Mapping[str, Any], tags: dict[str, list[str]], registered: str
) -> tuple[str, str]:
    values = unique([*(txt(row.get(k)) for k in ("osm_ownership", "overture_ownership",
                    "osm_owner_type", "overture_owner_type")),
                    *tags.get("ownership", []), *tags.get("owner:type", []),
                    *tags.get("owner_type", []), *tags.get("ownership:type", [])])
    sides = set()
    for val in values:
        n = norm(val).replace(" ", "_")
        if n in PUBLIC:
            sides.add("public")
        elif n in PRIVATE:
            sides.add("private")
    if len(sides) > 1:
        return combine(values), "SOURCE_OWNERSHIP_CONFLICT_REVIEW"
    if not sides:
        return combine(values), "NO_EXPLICIT_OWNERSHIP"
    return combine(values), ("EXPLICIT_OWNERSHIP_AGREES_WITH_REGISTRY" if registered in sides
                             else "EXPLICIT_OWNERSHIP_CONFLICTS_WITH_REGISTRY")


def _name_relation(row: Mapping[str, Any], official: str) -> tuple[str, str]:
    names = unique([txt(row.get("osm_name")), txt(row.get("overture_name"))])
    normalized = {norm(v) for v in names}
    if len(normalized) > 1:
        return combine(names), "RAW_SOURCE_NAMES_DISAGREE_REVIEW"
    if not names:
        return "", "NO_RAW_SOURCE_NAMES"
    return combine(names), ("RAW_NAME_EQUALS_OFFICIAL" if norm(names[0]) == norm(official)
                             else "RAW_NAME_DIFFERS_FROM_OFFICIAL_REVIEW")


def _locality(row: Mapping[str, Any], registered_city: str) -> tuple[str, str]:
    observed = unique([txt(row.get(k)) for k in
                       ("city", "municipality", "osm_city", "overture_city")])
    values = {norm(x) for x in observed}
    registered = norm(registered_city)
    if not registered:
        return combine(observed), "OFFICIAL_CITY_MISSING"
    if not values:
        return "", "PLACE_CITY_MISSING"
    if len(values) > 1:
        return combine(observed), "PLACE_LOCALITY_DISAGREEMENT_REVIEW"
    if registered in values:
        return combine(observed), "LOCALITY_TEXT_AGREES_NOT_IDENTITY_PROOF"
    return combine(observed), "CROSS_LOCALITY_BRANCH_OR_SITE_REVIEW_NOT_REJECTION"


def _coord(row: Mapping[str, Any], geometry_crs: str) -> tuple[str, str, str]:
    """Provide coordinates only if explicit WGS84 fields or known GeoParquet CRS."""
    for lat_key, lon_key in (("latitude", "longitude"), ("lat", "lon"), ("lat", "lng"),
                             ("osm_lat", "osm_lon"), ("overture_lat", "overture_lon")):
        a, b = txt(row.get(lat_key)), txt(row.get(lon_key))
        if not a or not b:
            continue
        try:
            lat, lon = float(a), float(b)
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return f"{lon:.8f}", f"{lat:.8f}", f"explicit_WGS84:{lat_key}/{lon_key}"
        except (TypeError, ValueError):
            pass
    value = row.get("geometry")
    if value is None or (isinstance(value, str) and not value.strip()):
        return "", "", "NO_USABLE_COORDINATE"
    try:
        from shapely import wkb
        if isinstance(value, (bytes, bytearray, memoryview)):
            geom = wkb.loads(bytes(value))
        elif isinstance(value, str):
            geom = wkb.loads(value, hex=True)
        else:
            geom = value
        if geom is None or geom.is_empty or geom.geom_type != "Point":
            return "", "", "NON_POINT_OR_EMPTY_GEOMETRY"
        x, y = float(geom.x), float(geom.y)
        if geometry_crs in ("OGC:CRS84", "EPSG:4326", "WGS 84"):
            lon, lat = x, y
        elif geometry_crs in ("UNKNOWN", "INVALID_GEO_METADATA", "UNPARSEABLE_PROJJSON"):
            return "", "", "GEOMETRY_CRS_UNVERIFIED"
        else:
            from pyproj import Transformer
            transform = Transformer.from_crs(geometry_crs, "EPSG:4326", always_xy=True)
            lon, lat = transform.transform(x, y)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return f"{lon:.8f}", f"{lat:.8f}", f"GeoParquet:{geometry_crs}"
        return "", "", "INVALID_GEOMETRY_COORDINATES"
    except Exception:  # optional GIS decoding must not fabricate a coordinate
        return "", "", "GEOMETRY_DECODE_OR_CRS_UNAVAILABLE"


def _registry_id(raw: str) -> tuple[str, str] | None:
    # `source:source_id` where source_id may contain colons (PhilHealth row).
    raw = txt(raw)
    if not raw or "|" in raw or ";" in raw or ":" not in raw:
        return None
    a, b = raw.split(":", 1)
    return (a, b) if a and b else None


def enrich(
    review: list[dict[str, str]], places: pd.DataFrame, *, geometry_crs: str = "UNKNOWN"
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    results = []
    counts: Counter[str] = Counter()
    for raw in review:
        row = dict(raw)
        id_ = txt(row["canonical_id"])
        if id_ not in places.index:
            extra = {k: "" for k in EXTRA}
            extra.update(join_status="MISSING_FROM_PLACES", matched_source_rows="0",
                         candidate_review_reasons="candidate_not_found_in_places_parquet",
                         evidence_priority="BLOCKED_MISSING_PLACE", identity_verified="false",
                         ownership_promotion_allowed="false", geometry_crs=geometry_crs)
        else:
            r = places.loc[id_].to_dict()
            # canonical_id is unique (validated at Parquet load); no unsafe fuzzy joins.
            tags = _tags(r)
            source_names, name_relation = _name_relation(r, row.get("registry_name", ""))
            registry_ref = _registry_id(row.get("registry_ids", ""))
            registry_src = registry_ref[0] if registry_ref else ""
            registry_id = registry_ref[1] if registry_ref else ""
            id_relation, observed_ids, namespace = _source_ids(
                r, tags, registry_src, row.get("registered_id_kind", ""), registry_id)
            own_sources, own_relation = _ownership(r, tags, txt(row.get("registry_ownership")))
            cities, locality = _locality(r, row.get("registered_city", ""))
            lon, lat, coord_basis = _coord(r, geometry_crs)
            subs = combine([v for v in [txt(row.get("name")), txt(r.get("osm_name")),
                                       txt(r.get("overture_name"))] if SUBUNIT.search(v)])
            issues = []
            if txt(row.get("registry_status")) != "NAME_LOCATION_UNVERIFIED":
                issues.append("prior_registry_status_requires_review")
            if name_relation in (
                "RAW_SOURCE_NAMES_DISAGREE_REVIEW", "RAW_NAME_DIFFERS_FROM_OFFICIAL_REVIEW"
            ):
                issues.append("raw_name_evidence_requires_review")
            if "CONFLICT" in id_relation or id_relation == "SOURCE_OFFICIAL_IDS_DISAGREE":
                issues.append("official_code_conflict")
            if own_relation in (
                "SOURCE_OWNERSHIP_CONFLICT_REVIEW",
                "EXPLICIT_OWNERSHIP_CONFLICTS_WITH_REGISTRY",
            ):
                issues.append("direct_ownership_conflict")
            if locality in (
                "PLACE_LOCALITY_DISAGREEMENT_REVIEW",
                "CROSS_LOCALITY_BRANCH_OR_SITE_REVIEW_NOT_REJECTION",
            ):
                issues.append("site_locality_review_not_institution_rejection")
            if subs:
                issues.append("possible_subunit_or_branch")
            if id_relation == "OFFICIAL_CODE_EQUALS_REGISTRY_REVIEW":
                issues.append("official_code_present_requires_independent_verification")
            if not issues:
                issues.append("independent_entity_or_branch_verification_required")
            priority = ("HIGH_CONFLICT" if any("conflict" in x for x in issues) else
                        "HIGH_UNASSIGNED"
                        if txt(row.get("ownership_opportunity")) == "CURRENT_IO80_UNASSIGNED"
                        else
                        "REVIEW")
            extra = {
                "join_status": "JOINED_CANONICAL_ID", "matched_source_rows": "1",
                "place_source_names": source_names,
                "place_canonical_name": combine([txt(r.get("name")), txt(r.get("canonical_name"))]),
                "source_name_relation": name_relation,
                "source_categories": combine([
                    txt(r.get("osm_category")), txt(r.get("overture_category"))]),
                "osm_id": combine([txt(r.get("osm_id")), txt(r.get("osm_element_id"))]),
                "overture_id": combine([
                    txt(r.get("overture_id")), txt(r.get("overture_source_id"))]),
                "source_websites": combine([
                    txt(r.get(k)) for k in ("website", "osm_website", "overture_website")]),
                "source_external_id_values": _all_external_ids(r, tags),
                "source_operational_evidence": combine([
                    txt(r.get("osm_operator")), txt(r.get("overture_operator"))]),
                "source_ownership_evidence": own_sources,
                "ownership_evidence_relation": own_relation,
                "official_ids_observed": observed_ids, "official_id_relation": id_relation,
                "official_id_namespace": namespace, "place_city_values": cities,
                "place_address_values": combine([
                    txt(r.get(k)) for k in ("address", "osm_address", "overture_address")]),
                "locality_comparison": locality, "place_longitude": lon, "place_latitude": lat,
                "coordinate_basis": coord_basis, "geometry_crs": geometry_crs,
                "subunit_or_branch_signal": subs, "candidate_review_reasons": ";".join(issues),
                "evidence_priority": priority, "identity_verified": "false",
                "ownership_promotion_allowed": "false",
            }
        row.update(extra)
        results.append(row)
        counts[f"join:{row['join_status']}"] += 1
        counts[f"official_id:{row['official_id_relation']}"] += 1
        counts[f"name:{row['source_name_relation']}"] += 1
        counts[f"ownership:{row['ownership_evidence_relation']}"] += 1
        counts[f"priority:{row['evidence_priority']}"] += 1
        counts[f"coord:{row['coordinate_basis']}"] += 1
        counts[f"relationship:{txt(row.get('relationship_hypothesis'))}"] += 1
    counts["candidates"] = len(results)
    counts["verified_matches_created"] = 0
    counts["ownership_changes"] = 0
    return results, dict(sorted(counts.items()))


def grouped(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        if _registry_id(r.get("registry_ids", "")):
            groups[r["registry_ids"]].append(r)
    out = []
    for official_id, items in sorted(groups.items()):
        out.append({
            "registry_ids": official_id,
            "registry_name": items[0].get("registry_name", ""),
            "registry_ownership": items[0].get("registry_ownership", ""),
            "candidate_observations": str(len(items)),
            "unassigned_io80_observations": str(sum(
                r.get("ownership_opportunity") == "CURRENT_IO80_UNASSIGNED" for r in items)),
            "canonical_ids": " | ".join(sorted(r["canonical_id"] for r in items)),
            "candidate_relationships": combine([
                r.get("relationship_hypothesis", "") for r in items]),
            "official_id_evidence": combine([r.get("official_id_relation", "") for r in items]),
            "independently_verified": "false",
        })
    return out


def safe_csv_cell(value: Any) -> str:
    """Neutralize spreadsheet formula interpretation in untrusted OSM/Overture text."""
    text = txt(value)
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return text
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def csv_write(path: Path, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> None:
    with path.open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: safe_csv_cell(row.get(k, "")) for k in fields})


def analyze(*, review_path: Path, places_path: Path, out_dir: Path,
            registry_path: Path | None = None, workspace: Path | None = None) -> dict[str, Any]:
    review_path = review_path.resolve()
    places_path = places_path.resolve()
    out_dir = out_dir.expanduser().resolve()
    if out_dir.exists():
        raise FileExistsError(f"output folder already exists; refusing to overwrite: {out_dir}")
    for inp in (review_path, places_path, registry_path):
        if inp is not None and (out_dir == inp.resolve() or out_dir in inp.resolve().parents):
            raise ValueError("output directory overlaps an input path")
    if workspace is not None and (
        out_dir == workspace.resolve() or workspace.resolve() in out_dir.parents
    ):
        raise ValueError("audit output must be outside SIGMA workspace")
    if places_path.suffix.lower() == ".parquet" and (
            out_dir == places_path.parent or places_path.parent in out_dir.parents):
        raise ValueError("audit output must be outside the places workspace")
    review, columns = read_review(review_path)
    places, meta = read_places(places_path)
    if registry_path is not None:
        # Read-only provenance check; the review already contains official IDs.
        with registry_path.open("r", encoding="utf-8-sig", newline="") as f:
            source = list(csv.DictReader(f))
        known = {f"{r['source']}:{r['source_id']}" for r in source}
        unknown = sorted({
            r["registry_ids"] for r in review if _registry_id(r.get("registry_ids", ""))
                          and r["registry_ids"] not in known})
        if unknown:
            raise ValueError(f"review cites unknown official reference ID(s): {unknown[:5]}")
    records, counts = enrich(review, places, geometry_crs=meta["geometry_crs"])
    queue = sorted(records, key=lambda r: ({"HIGH_CONFLICT": 0, "HIGH_UNASSIGNED": 1,
                                           "BLOCKED_MISSING_PLACE": 2, "REVIEW": 3}.get(
                        r["evidence_priority"], 4), r["canonical_id"]))
    groups = grouped(records)
    summary = {
        "version": PATCH_VERSION,
        "read_only": True,
        "verified_matches_created": 0,
        "ownership_changes": 0,
        "warnings": ["Name/city/address/coordinate similarity is NOT proof of identity.",
                     "PhilHealth publication row numbers are NOT facility codes.",
                     "Cross-locality records can be legitimate branches or affiliates."],
        "inputs": {"review": str(review_path), "review_sha256": file_sha256(review_path),
                   "places": str(places_path), "places_sha256": file_sha256(places_path),
                   "registry": str(registry_path) if registry_path else "",
                   "registry_sha256": file_sha256(registry_path) if registry_path else ""},
        "places_schema": meta,
        "counts": counts,
        "distinct_official_registry_records_in_review": len(groups),
    }
    out_dir.mkdir(parents=True, exist_ok=False)
    try:
        evidence_path = out_dir / "sigma_qc_institution_evidence_v6.csv"
        queue_path = out_dir / "sigma_qc_institution_review_queue_v6.csv"
        groups_path = out_dir / "sigma_qc_institution_registry_groups_v6.csv"
        allfields = tuple(dict.fromkeys([*columns, *EXTRA]))
        csv_write(evidence_path, records, allfields)
        csv_write(queue_path, queue, allfields)
        group_fields = ("registry_ids", "registry_name", "registry_ownership",
                        "candidate_observations", "unassigned_io80_observations", "canonical_ids",
                        "candidate_relationships", "official_id_evidence", "independently_verified")
        csv_write(groups_path, groups, group_fields)
        (out_dir / "sigma_qc_institution_evidence_summary_v6.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except BaseException:
        # Only this newly-created folder is removed on a failed write.
        for p in out_dir.iterdir():
            if p.is_file():
                p.unlink()
        out_dir.rmdir()
        raise
    return summary


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--workspace", required=True, type=Path, help="Existing SIGMA workspace (read only)")
    cli.add_argument("--review", required=True, type=Path, help="V5 identity review CSV")
    cli.add_argument("--registry", type=Path, help="Installed national reference CSV (read only)")
    cli.add_argument(
        "--out-dir", required=True, type=Path, help="New output folder outside workspace")
    args = cli.parse_args()
    workspace = args.workspace.resolve()
    result = analyze(review_path=args.review, places_path=workspace / "places" / "places.parquet",
                     out_dir=args.out_dir, registry_path=args.registry, workspace=workspace)
    print(json.dumps({"out_dir": str(args.out_dir.resolve()), "counts": result["counts"],
                      "verified_matches_created": 0, "ownership_changes": 0}, indent=2))


if __name__ == "__main__":
    main()

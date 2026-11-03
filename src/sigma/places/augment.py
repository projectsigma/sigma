"""Post-load, source-identified place augmentation (no acquisition-stage changes).

Uses the existing OSM/Overture name-distance candidate matcher.  The canonical
handoff is a *user-editable* GeoParquet and augmentation never mutates the C8
managed artifacts, OSM cache, or Overture snapshot.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from .reconcile import _candidate_pairs, _pick_name, _poi_id

_REQUIRED = ("source_id", "name", "lon", "lat")
_SOURCE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}\Z")


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_input(path: Path) -> gpd.GeoDataFrame:
    """Validate the four-field contract and retain all additional columns."""
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, dtype={"source_id": "string", "name": "string",
                                         "io16": "string", "io80": "string", "io240": "string",
                                         "psic_code": "string"},
                            keep_default_na=False)
    elif path.suffix.lower() in (".parquet", ".pq"):
        frame = pd.read_parquet(path)
    else:
        raise ValueError("augment input must be .csv, .parquet, or .pq")
    if not all(isinstance(col, str) for col in frame.columns):
        raise ValueError("augment column names must be strings")
    if frame.columns.duplicated().any():
        raise ValueError("augment input has duplicate column names")
    if "io_code" in frame.columns:
        raise ValueError(
            "legacy io_code column is not accepted by this augment schema; "
            "use separate io16, io80, io240 columns so each level can be validated"
        )
    absent = sorted(set(_REQUIRED) - set(frame.columns))
    if absent:
        raise ValueError(f"augment input missing required columns: {absent}")
    if frame.empty:
        raise ValueError("augment input has no records")
    # Required lon/lat are the authoritative point location. Preserve any
    # separate geometry column as a namespaced source attribute for later use.
    if "geometry" in frame.columns:
        key = "input_geometry"
        while key in frame.columns:
            key += "_"
        def _geometry_text(value):
            if hasattr(value, "wkt"):
                return value.wkt
            if isinstance(value, (bytes, bytearray)):
                return value.hex()
            return _text(value)
        frame = frame.copy()
        frame[key] = frame["geometry"].map(_geometry_text)
        frame = frame.drop(columns=["geometry"])
    frame = pd.DataFrame(frame).reset_index(drop=True)
    for col in ("source_id", "name"):
        frame[col] = frame[col].map(_text)
        if frame[col].eq("").any():
            raise ValueError(f"augment {col} must be nonblank for every record")
    if frame.source_id.duplicated().any():
        raise ValueError(f"augment source_id must be unique; duplicates: {frame.loc[frame.source_id.duplicated(), 'source_id'].head(5).tolist()}")
    for col, low, high in (("lon", -180., 180.), ("lat", -90., 90.)):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
        if not frame[col].map(lambda x: math.isfinite(float(x)) if pd.notna(x) else False).all():
            raise ValueError(f"augment {col} must contain only finite numeric values")
        if not frame[col].between(low, high).all():
            raise ValueError(f"augment {col} values must be in [{low}, {high}]")
    for optional in ("category", "io16", "io80", "io240", "psic_code"):
        if optional not in frame:
            frame[optional] = ""
        frame[optional] = frame[optional].map(_text)
    return gpd.GeoDataFrame(frame, geometry=gpd.points_from_xy(frame.lon, frame.lat), crs="EPSG:4326")


def validate_io_codes(frame: pd.DataFrame) -> dict[int, dict[str, str]]:
    """Validate optional IO16, IO80 and IO240 inputs and infer ONLY ancestors.

    All three columns may be blank (automatic classification).  Otherwise the
    finest supplied resolution wins, and any supplied coarser code must agree
    with its validated parent. We never infer children from a coarser tag.

    Explicit residual sectors are deliberately not source IO tags: they are
    derived locally after the loaded places define an area's IO partition.
    """
    from sigma.classification import load_builtin_io_reference
    from sigma.classification.io_mapping_compat import load_catalog

    parents240 = load_builtin_io_reference().io240_parent_map
    catalog = load_catalog()
    parents80 = {code: item.io16_code for code, item in catalog.items()}
    known16 = set(parents80.values())
    result: dict[int, dict[str, str]] = {}
    conflicts: list[str] = []
    for i in range(1, len(frame) + 1):
        # zip by named column access rather than by position, so extra columns
        # and arbitrary column order never change the meaning of IO evidence.
        record = frame.iloc[i - 1]
        c16, c80, c240 = (_text(record.get(col)) for col in ("io16", "io80", "io240"))
        if not (c16 or c80 or c240):
            continue
        errors = []
        if c16 and c16 not in known16:
            errors.append(f"unknown io16={c16!r}")
        if c80 and c80 not in parents80:
            errors.append(f"unknown io80={c80!r}")
        if c240 and c240 not in parents240:
            errors.append(f"unknown io240={c240!r}")
        if c240 and c240 in parents240:
            expected80 = parents240[c240]
            if c80 and c80 != expected80:
                errors.append(f"io240={c240} belongs to io80={expected80}, not io80={c80}")
            c80 = expected80
        if c80 and c80 in parents80:
            expected16 = parents80[c80]
            if c16 and c16 != expected16:
                errors.append(f"io80={c80} belongs to io16={expected16}, not io16={c16}")
            c16 = expected16
        if errors:
            source_id = _text(record.get("source_id")) or str(i)
            conflicts.append(f"input row {i} (source_id={source_id}): " + "; ".join(errors))
            continue
        sparse = ":".join(part for part in (c16, c80, c240) if part)
        result[i - 1] = {
            "io16_code": c16, "io80_code": c80, "io240_code": c240,
            "augment_io_code": sparse,
        }
    if conflicts:
        raise ValueError(
            f"{len(conflicts)} conflicting or unknown IO tag row(s); nothing will be written. "
            "Correct the input and rerun --check.\n" + "\n".join(conflicts[:30])
            + (f"\n... and {len(conflicts)-30} more" if len(conflicts) > 30 else "")
        )
    return result


def _explicit_conflicts(older: dict[str, str], newer: dict[str, str]) -> list[str]:
    return [f"{level}: {older[level]} vs {newer[level]}"
            for level in ("io16_code", "io80_code", "io240_code")
            if older.get(level) and newer.get(level) and older[level] != newer[level]]


def _recorded_manual_tag(record: pd.Series) -> dict[str, str] | None:
    if _text(record.get("augment_tag_source")) != "user_supplied":
        return None
    return {key: _text(record.get(key)) for key in ("io16_code", "io80_code", "io240_code")}


def _comparison_warnings(record: pd.Series, manual: dict[str, str], source_id: str,
                         *, context: str) -> list[str]:
    """Report only definite singleton disagreements, not ambiguous candidates."""
    return [
        f"{context} source_id={source_id}: user {field}={manual[field]} overrides "
        f"inferred/existing {field}={_text(record.get(field))}"
        for field in ("io16_code", "io80_code", "io240_code")
        if manual.get(field) and _text(record.get(field))
        and manual[field] != _text(record.get(field))
    ]

def _classify_new(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reuse baseline PSIC and IO machinery, via a transparent source proxy.

    The current classifier accepts OSM and Overture evidence. Map key=value
    categories through OSM rules; other categories through Overture rules.
    The proxy source columns are stripped before persistence, and the actual
    data provider remains recorded in augment source provenance.
    """
    if frame.empty:
        return frame
    from sigma.classification import (EconomicTagger, PsicClassifier,
                                      TaggingReferences, load_builtin_psic_taxonomy)
    from sigma.economy import Economy
    taxonomy = load_builtin_psic_taxonomy()
    economy = Economy.builtin("io80")
    refs = TaggingReferences.builtin(taxonomy, economy)
    temp = frame.copy()
    osm_like = temp["category"].map(lambda x: "=" in _text(x))
    temp["osm_name"] = temp["name"].where(osm_like, "")
    temp["osm_category"] = temp["category"].where(osm_like, "")
    temp["overture_name"] = temp["name"].where(~osm_like, "")
    temp["overture_category"] = temp["category"].where(~osm_like, "")
    classifier = PsicClassifier(taxonomy=taxonomy, crosswalk=refs.source_to_psic,
                                top_n=5, min_score=0.45, min_margin=0.12)
    tagged = classifier.classify_frame(temp)
    manual_psic = frame["augment_requested_psic_code"].map(_text)
    unknown = sorted(set(manual_psic[manual_psic.ne("")]) - set(taxonomy.nodes))
    if unknown:
        raise ValueError(f"unknown explicit psic_code values: {unknown[:8]}")
    manual_mask = manual_psic.ne("")
    if manual_mask.any():
        tagged.loc[manual_mask, "psic_code"] = manual_psic[manual_mask]
        tagged.loc[manual_mask, "psic_method"] = "user_supplied"
        tagged.loc[manual_mask, "psic_status"] = "MANUAL"
        tagged.loc[manual_mask, "psic_level"] = manual_psic[manual_mask].map(lambda c: taxonomy.get(c).level)
        tagged.loc[manual_mask, "psic_title"] = manual_psic[manual_mask].map(lambda c: taxonomy.get(c).title)
        tagged.loc[manual_mask, "psic_candidate_codes"] = manual_psic[manual_mask]
        tagged.loc[manual_mask, "psic_flags"] = "USER_SUPPLIED_PSIC"
    tagged = EconomicTagger(taxonomy=taxonomy, economy=economy, references=refs).tag(tagged)
    # Do not misrepresent a user dataset as an OSM/Overture observation.
    for col in ("osm_name", "osm_category", "overture_name", "overture_category"):
        tagged[col] = ""
    tagged["augment_classification_proxy"] = "osm_if_key_value_else_overture"
    return gpd.GeoDataFrame(tagged, geometry="geometry", crs="EPSG:4326")


def _override_psic(frame: gpd.GeoDataFrame, overrides: dict[int, str]) -> None:
    """Re-tag matched canonical rows only when a user provided PSIC evidence."""
    if not overrides:
        return
    from sigma.classification import (EconomicTagger, TaggingReferences,
                                      load_builtin_psic_taxonomy)
    from sigma.economy import Economy
    taxonomy = load_builtin_psic_taxonomy()
    unknown = sorted(set(overrides.values()) - set(taxonomy.nodes))
    if unknown:
        raise ValueError(f"unknown explicit psic_code values: {unknown[:8]}")
    economy = Economy.builtin("io80")
    refs = TaggingReferences.builtin(taxonomy, economy)
    indices = list(overrides)
    subset = frame.loc[indices].copy()
    for i, code in overrides.items():
        node = taxonomy.get(code)
        subset.at[i, "psic_code"] = code
        subset.at[i, "psic_level"] = node.level
        subset.at[i, "psic_title"] = node.title
        subset.at[i, "psic_method"] = "user_supplied"
        subset.at[i, "psic_status"] = "MANUAL"
        subset.at[i, "psic_candidate_codes"] = code
        subset.at[i, "psic_flags"] = "USER_SUPPLIED_PSIC"
    tagged = EconomicTagger(taxonomy=taxonomy, economy=economy, references=refs).tag(subset)
    for col in tagged:
        if not (col.startswith("io") or col.startswith("psic_") or col.startswith("economy_")):
            continue
        if col not in frame:
            frame[col] = pd.Series([None] * len(frame), dtype=object)
        for i in indices:
            frame.at[i, col] = tagged.at[i, col]


def _override_io(frame: gpd.GeoDataFrame, tags: dict[int, dict[str, str]],
                 positions: list[int]) -> None:
    """Mutate only annotated records, making user evidence authoritative."""
    for row_position in positions:
        if row_position not in tags:
            continue
        record = tags[row_position]
        for field in ("io16_code", "io80_code", "io240_code"):
            frame.at[row_position, field] = record[field]
            for suffix in ("_source", "_status"):
                key = field.replace("_code", suffix)
                frame.at[row_position, key] = "user_supplied"
        for level in ("16", "80", "240"):
            key = f"io{level}_codes"
            frame.at[row_position, key] = record[f"io{level}_code"]
        # The builder parses the singular tags above; plural candidate sets are
        # kept consistent to prevent a stale automatic result overriding manual.
        frame.at[row_position, "augment_io_code"] = record["augment_io_code"]
        frame.at[row_position, "augment_tag_source"] = "user_supplied"
        frame.at[row_position, "economy_code"] = record["io80_code"]
        frame.at[row_position, "economy_source"] = "user_supplied"
        frame.at[row_position, "economy_status"] = "MANUAL_IO"


def _extra_column(source: str, column: str) -> str:
    # A namespace makes arbitrary columns collision-free across uploads and
    # impossible to impersonate system-owned fields such as economy_code.
    return f"aug_{source}__{column}"


def _metric_column(source: str, name: str, user_keys: set[str]) -> str:
    """Keep user-defined columns even when their names resemble match metrics."""
    candidate = _extra_column(source, name)
    if candidate not in user_keys:
        return candidate
    suffix = 0
    while True:
        tag = "sigma_" if suffix == 0 else f"sigma_{suffix}_"
        candidate = _extra_column(source, tag + name)
        if candidate not in user_keys:
            return candidate
        suffix += 1


def _safe_extra(value: object) -> object:
    """Keep Arrow-compatible primitives and lists; encode exotic structures."""
    if value is None:
        return None
    if isinstance(value, (str, bytes, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_extra(v) for v in value]
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "tolist"):
        return _safe_extra(value.tolist())
    return str(value)


def _record_to_new(item: pd.Series, source: str) -> dict[str, object]:
    sid = str(item.source_id)
    pid = _poi_id([f"user:{source}:{sid}"])
    return {
        "poi_id": pid, "canonical_id": pid, "name": str(item["name"]),
        "category": str(item.get("category", "")),
        "lon": float(item.lon), "lat": float(item.lat),
        "sources": f"user:{source}", "source_count": 1,
        "osm_id": "", "overture_id": "", "osm_name": "", "osm_category": "",
        "overture_name": "", "overture_category": "", "overture_providers": "",
        "aliases": [], "match_distance_m": None, "match_name_score": None,
        "source_licenses": "",
    }


def build_augmented(base: gpd.GeoDataFrame, supplied: gpd.GeoDataFrame,
                    *, source: str, boundary=None) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    """Reconcile a new source one-to-one with the loaded canonical handoff."""
    if not _SOURCE_RE.fullmatch(source):
        raise ValueError("--source must match [a-z][a-z0-9_]{0,39}")
    if source in ("osm", "overture"):
        raise ValueError("--source cannot impersonate the built-in OSM/Overture sources")
    if not isinstance(base, gpd.GeoDataFrame) or base.crs is None:
        raise ValueError("loaded places must be a GeoParquet with a declared CRS")
    if base.crs.to_epsg() != 4326:
        raise ValueError("loaded places CRS must be EPSG:4326; refusing lon/lat mismatch")
    base = base.reset_index(drop=True)
    if "canonical_id" not in base or not {"name", "lon", "lat"}.issubset(base):
        raise ValueError("loaded places missing canonical_id/name/lon/lat; run sigma load first")
    if base.canonical_id.astype(str).duplicated().any():
        raise ValueError("loaded places have duplicate canonical_id; refusing ambiguous match")
    token = f"user:{source}"
    if "sources" in base and base["sources"].fillna("").astype(str).map(
            lambda s: token in s.split("|")).any():
        raise ValueError(f"source {source!r} already exists in this handoff; do not augment it twice")
    input_frame = supplied.sort_values("source_id", kind="stable").reset_index(drop=True)
    tags = validate_io_codes(input_frame)
    # Match against the original loaded GeoParquet, never against freshly added
    # source rows from this same file. This is the same candidate policy as load.
    candidates = _candidate_pairs(base, input_frame)
    used_left: set[int] = set()
    used_right: set[int] = set()
    pairs = []
    for c in candidates:
        if c.left not in used_left and c.right not in used_right:
            used_left.add(c.left); used_right.add(c.right)
            pairs.append(c)

    out = base.copy()
    if "aliases" not in out:
        out["aliases"] = [[] for _ in range(len(out))]
    if "category" not in out:
        out["category"] = ""
    passthrough = [col for col in input_frame.columns if col != "geometry"]
    for col in passthrough:
        key = _extra_column(source, col)
        if key in out.columns:
            raise ValueError(f"augmentation column collision: {key}")
        out[key] = None
    for col in ("augment_io_code", "augment_tag_source", "augment_classification_proxy"):
        if col not in out:
            out[col] = ""
    input_keys = {_extra_column(source, col) for col in passthrough}
    dist_col = _metric_column(source, "match_distance_m", input_keys)
    score_col = _metric_column(source, "match_name_score", input_keys | {dist_col})
    for col in (dist_col, score_col):
        out[col] = None

    manual_psic_matches: dict[int, str] = {}
    manual_io_matches: dict[int, dict[str, str]] = {}
    warnings: list[str] = []
    for match in pairs:
        i, j = match.left, match.right
        src = input_frame.loc[j]
        prior_name = _text(out.at[i, "name"])
        new_name = str(src["name"])
        name = _pick_name(prior_name, new_name)
        existing_aliases = out.at[i, "aliases"] if "aliases" in out else []
        if not isinstance(existing_aliases, (tuple, list)):
            existing_aliases = existing_aliases.tolist() if hasattr(existing_aliases, "tolist") else []
        out.at[i, "aliases"] = sorted(({_text(x) for x in existing_aliases} | {prior_name, new_name}) - {name, ""})
        out.at[i, "name"] = name
        count = int(out.at[i, "source_count"]) if "source_count" in out and pd.notna(out.at[i, "source_count"]) else 1
        if count < 1:
            raise ValueError(f"invalid source_count on canonical row {i}")
        x = (float(out.at[i, "lon"]) * count + float(src.lon)) / (count + 1)
        y = (float(out.at[i, "lat"]) * count + float(src.lat)) / (count + 1)
        if boundary is not None and not boundary.covers(Point(x, y)):
            # Same concave-boundary safeguard as original reconcile(): a
            # weighted centroid can fall inside a polygon hole or outside a
            # concavity despite both observations being within the area.
            old = Point(float(out.at[i, "lon"]), float(out.at[i, "lat"]))
            new = Point(float(src.lon), float(src.lat))
            if boundary.covers(old):
                x, y = old.x, old.y
            elif boundary.covers(new):
                x, y = new.x, new.y
            else:
                raise ValueError(f"matched place {i} has no in-boundary coordinate")
        out.at[i, "lon"] = x; out.at[i, "lat"] = y
        out.at[i, "geometry"] = Point(x, y)
        out.at[i, "source_count"] = count + 1
        prev = _text(out.at[i, "sources"]) if "sources" in out else ""
        out.at[i, "sources"] = "|".join(part for part in (prev, token) if part)
        out.at[i, dist_col] = round(match.distance_m, 3)
        out.at[i, score_col] = round(match.name_score, 4)
        if _text(src.category):
            parts = [_text(out.at[i, "category"]), _text(src.category)]
            out.at[i, "category"] = " | ".join(dict.fromkeys(part for part in parts if part))
        for key in passthrough:
            out.at[i, _extra_column(source, key)] = _safe_extra(src[key])
        if _text(src.get("psic_code")):
            manual_psic_matches[i] = _text(src["psic_code"])
        if j in tags:
            incoming = tags[j].copy()
            older = _recorded_manual_tag(out.loc[i])
            if older is not None:
                conflicts = _explicit_conflicts(older, incoming)
                if conflicts:
                    raise ValueError(
                        f"matched canonical place {out.at[i, 'canonical_id']} has "
                        f"contradictory explicit IO tags from different user sources: "
                        + "; ".join(conflicts) + ". Nothing will be written."
                    )
                # Coarser manual evidence may corroborate but must not erase a
                # more specific compatible tag already recorded for this place.
                for field in ("io16_code", "io80_code", "io240_code"):
                    if not incoming[field]:
                        incoming[field] = older.get(field, "")
                incoming["augment_io_code"] = ":".join(
                    v for v in (incoming["io16_code"], incoming["io80_code"], incoming["io240_code"]) if v)
            manual_io_matches[i] = incoming

    # Explicit PSIC evidence is applied first, then an explicit hierarchical IO
    # tag (if present) takes final precedence. No other matched row is retagged.
    _override_psic(out, manual_psic_matches)
    if manual_io_matches:
        for i, manual in manual_io_matches.items():
            source_id = _text(out.loc[i].get(_extra_column(source, "source_id")))
            warnings.extend(_comparison_warnings(out.loc[i], manual, source_id,
                                                  context="matched"))
        _override_io(out, manual_io_matches, list(manual_io_matches))

    new_positions = [j for j in range(len(input_frame)) if j not in used_right]
    if new_positions:
        rows = []
        for j in new_positions:
            src = input_frame.loc[j]
            record = _record_to_new(src, source)
            record.update({_extra_column(source, key): _safe_extra(src[key]) for key in passthrough})
            record[dist_col] = None
            record[score_col] = None
            record["augment_io_code"] = ""
            record["augment_requested_psic_code"] = _text(src.get("psic_code"))
            record["augment_tag_source"] = ""
            rows.append(record)
        added = gpd.GeoDataFrame(pd.DataFrame(rows), geometry=gpd.points_from_xy(
            [r["lon"] for r in rows], [r["lat"] for r in rows]), crs="EPSG:4326")
        classified = _classify_new(added)
        new_tags = {position: tags[j] for position, j in enumerate(new_positions) if j in tags}
        if new_tags:
            for position, tag in new_tags.items():
                warnings.extend(_comparison_warnings(classified.loc[position], tag,
                                                      str(input_frame.loc[new_positions[position], "source_id"]),
                                                      context="new"))
            _override_io(classified, new_tags, list(new_tags))
        # Matching columns from a user source are not Overture provider metadata.
        # Existing columns and arbitrary extras survive concat unchanged.
        out = gpd.GeoDataFrame(pd.concat([out, classified], ignore_index=True, sort=False),
                               geometry="geometry", crs="EPSG:4326")

    if "canonical_name" in out:
        out["canonical_name"] = out["name"].astype("string")
    ids = out["canonical_id"].astype("string")
    if ids.isna().any() or ids.duplicated().any():
        raise RuntimeError("augment introduced invalid canonical identities")
    # Ensure the input's optional columns are NOT confused with internal output
    # fields: passthroughs are all namespace-prefixed, including source_id.
    return out, {"matched": len(pairs), "added": len(new_positions),
                 "total": len(out), "input": len(input_frame),
                 "warnings": warnings, "warning_count": len(warnings)}


def augment_workspace(workspace: Path, input_file: Path, *, source: str,
                      check: bool = False, boundary=None) -> dict[str, object]:
    """Preflight or atomically publish a post-load augmentation."""
    workspace = Path(workspace).expanduser().resolve()
    input_file = Path(input_file).expanduser().resolve()
    path = workspace / "places" / "places.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"loaded places not found: {path}; run sigma load first")
    if input_file == path:
        raise ValueError("input CSV/Parquet must not be the loaded places handoff itself")
    registry_path = path.parent / "augmentations.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {"schema_version": 1, "sources": {}}
    if registry.get("schema_version") != 1:
        raise ValueError("unsupported augmentations registry; not overwriting")
    token = f"user:{source}"
    base = gpd.read_parquet(path)
    previously_added = ("sources" in base and base["sources"].fillna("").astype(str).map(
        lambda s: token in s.split("|")).any())
    previous = registry.get("sources", {}).get(source)
    data_hash = _digest(input_file)
    if previously_added and previous and previous.get("input_sha256") == data_hash:
        return {"source": source, "status": "already_applied", "input_sha256": data_hash,
                "workspace": str(workspace), "total": int(len(base))}
    new_frame = read_input(input_file)
    selection_path = workspace / "economy-selection.json"
    if selection_path.is_file():
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        io_level = selection.get("io_level")
        manual_io = new_frame[["io16", "io80", "io240"]].apply(
            lambda col: col.map(_text)).ne("").any(axis=1)
        if io_level == "custom" and manual_io.any():
            raise ValueError("explicit PSA IO16/IO80/IO240 tags cannot be used with a custom economy")
    input_rows = len(new_frame)
    excluded = 0
    if boundary is not None:
        covered = new_frame.geometry.covered_by(boundary)
        excluded = int((~covered).sum())
        new_frame = new_frame.loc[covered].reset_index(drop=True)
        if new_frame.empty:
            raise ValueError("augment input has no places inside the selected area boundary")
    output, stats = build_augmented(base, new_frame, source=source, boundary=boundary)
    report = {"schema_version": 1, "source": source, "status": "checked" if check else "applied",
              "input": str(input_file), "input_sha256": data_hash, "workspace": str(workspace),
              "places_path": str(path), **stats,
              "input_total_before_clip": input_rows, "excluded_outside_boundary": excluded,
              "classification": "same PSIC/IO classifier for new unmatched records; consistent explicit IO16/IO80/IO240 wins",
              "reconciliation": "same candidate match thresholds and greedy pairing as OSM/Overture",
              "hierarchical": "derived per-area hierarchy must refresh on the next sigma run or explicit hierarchical-refresh"}
    if check:
        return report
    tmp = path.with_name("places.augment.tmp.parquet")
    registry_tmp = registry_path.with_suffix(".json.tmp")
    meta_path = path.parent / "places.meta.json"
    meta_tmp = path.parent / "places.meta.augment.tmp.json"
    baseline = path.parent / "places.pre-first-augment.parquet"
    if tmp.exists() or registry_tmp.exists() or meta_tmp.exists():
        raise FileExistsError("stale augmentation temporary output exists; inspect before retrying")
    try:
        output.to_parquet(tmp, index=False)
        check_output = gpd.read_parquet(tmp)
        if len(check_output) != stats["total"] or check_output.canonical_id.duplicated().any():
            raise RuntimeError("augmentation GeoParquet failed roundtrip validation")
        if not baseline.exists():
            # Retain exactly one initial-handoff recovery snapshot, never
            # silently overwrite a previous user's backup.
            shutil.copy2(path, baseline)
        registry.setdefault("sources", {})[source] = {
            "input_sha256": data_hash, "input_path": str(input_file),
            "matched": stats["matched"], "added": stats["added"],
            "total": stats["total"], "input": stats["input"],
            "warning_count": stats["warning_count"]
        }
        registry_tmp.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            meta = {"schema_version": 1, "editable_handoff": True}
        meta.update(rows=stats["total"], augmented=True,
                    augmented_source_count=len(registry["sources"]),
                    last_augmentation_source=source)
        meta_tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # The places handoff remains an independent file, replaced only after
        # the full classified output has been validated.
        os.replace(tmp, path)
        os.replace(registry_tmp, registry_path)
        os.replace(meta_tmp, meta_path)
    finally:
        tmp.unlink(missing_ok=True)
        registry_tmp.unlink(missing_ok=True)
        meta_tmp.unlink(missing_ok=True)
    return report

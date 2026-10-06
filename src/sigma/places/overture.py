from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import from_wkb

from .text import clean_text, combine
from ..sources.cache import cache_matches_bbox, write_cache_identity
from .overture_policy import evaluate_overture_sources

ProgressCallback = Callable[[str], None]

# Bump whenever normalization/provenance policy changes in a way that makes an
# older cached Overture layer unsafe to reuse.
OVERTURE_NORMALIZATION_VERSION = 3


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "as_py"):
        try:
            value = value.as_py()
        except Exception:
            return None
    return value if isinstance(value, Mapping) else None


def _primary_name(value: object) -> str:
    mapped = _mapping(value)
    if mapped is not None:
        primary = clean_text(mapped.get("primary"))
        common = mapped.get("common")
        if primary:
            return primary
        common_map = _mapping(common)
        if common_map is not None:
            for candidate in common_map.values():
                text = clean_text(candidate)
                if text:
                    return text
    return clean_text(value)


def _category(row: pd.Series) -> str:
    parts: list[str] = []

    taxonomy = _mapping(row.get("taxonomy"))
    if taxonomy is not None:
        primary = clean_text(taxonomy.get("primary"))
        if primary:
            parts.append(primary)

        alternates = taxonomy.get("alternates")
        if hasattr(alternates, "tolist"):
            try:
                alternates = alternates.tolist()
            except Exception:
                pass
        if isinstance(alternates, (list, tuple)):
            for value in alternates:
                text = clean_text(value)
                if text and text not in parts:
                    parts.append(text)

    # Backward compatibility with pre-September-2026 cached/source schemas.
    categories = _mapping(row.get("categories"))
    if categories is not None:
        primary = clean_text(categories.get("primary"))
        if primary and primary not in parts:
            parts.append(primary)
        alternate = categories.get("alternate")
        if hasattr(alternate, "tolist"):
            try:
                alternate = alternate.tolist()
            except Exception:
                pass
        if isinstance(alternate, (list, tuple)):
            for value in alternate:
                text = clean_text(value)
                if text and text not in parts:
                    parts.append(text)

    basic = clean_text(row.get("basic_category"))
    if basic and basic not in parts:
        parts.append(basic)

    return combine(*parts)


def _point_from_geometry(value: object):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        geometry = from_wkb(bytes(value))
    else:
        geometry = value
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "Point":
        return geometry
    return geometry.representative_point()


def _policy_metadata_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".overture.json")


def _policy_cache_matches(
    cache_file: Path,
    bbox: tuple[float, float, float, float],
) -> bool:
    if not cache_matches_bbox(cache_file, bbox):
        return False

    path = _policy_metadata_path(cache_file)
    if not path.exists():
        return False

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    return (
        payload.get("normalization_version") == OVERTURE_NORMALIZATION_VERSION
        and payload.get("bbox") == [float(v) for v in bbox]
    )


def _write_policy_metadata(
    cache_file: Path,
    bbox: tuple[float, float, float, float],
    *,
    raw_rows: int,
    accepted_rows: int,
) -> None:
    path = _policy_metadata_path(cache_file)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            {
                "normalization_version": OVERTURE_NORMALIZATION_VERSION,
                "bbox": [float(v) for v in bbox],
                "raw_rows": int(raw_rows),
                "accepted_rows": int(accepted_rows),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def fetch_overture(
    bbox: tuple[float, float, float, float],
    cache_file: Path,
    *,
    refresh: bool = False,
    progress: ProgressCallback | None = None,
) -> gpd.GeoDataFrame:
    """Stream Overture Places for bbox and cache a normalized point layer."""
    required = {
        "source",
        "source_id",
        "name",
        "category",
        "lon",
        "lat",
        "upstream_license",
        "overture_providers",
    }
    if not refresh and _policy_cache_matches(cache_file, bbox):
        cached = gpd.read_parquet(cache_file)
        if required.issubset(cached.columns):
            _emit(progress, f"Overture: using compatible cache — {len(cached):,} POIs")
            return cached

    from overturemaps import record_batch_reader

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    _emit(progress, "Overture: opening Places stream")
    reader = record_batch_reader("place", bbox=bbox, stac=True)

    records: list[dict[str, object]] = []
    reject_reasons: Counter[str] = Counter()
    datasets_seen: Counter[str] = Counter()
    batch_number = 0
    raw_total = 0
    closed_total = 0
    nameless_total = 0
    geometry_total = 0
    policy_rejected_total = 0

    if reader is not None:
        for batch_number, batch in enumerate(reader, start=1):
            table = batch.to_pandas()
            raw_total += len(table)
            accepted_before = len(records)
            rejected_before = policy_rejected_total

            for _, row in table.iterrows():
                status = clean_text(row.get("operating_status")).casefold()
                if status == "permanently_closed":
                    closed_total += 1
                    continue

                name = _primary_name(row.get("names"))
                if not name:
                    nameless_total += 1
                    continue

                point = _point_from_geometry(row.get("geometry"))
                if point is None:
                    geometry_total += 1
                    continue

                decision = evaluate_overture_sources(row.get("sources"))
                for dataset in decision.datasets:
                    datasets_seen[dataset] += 1

                if not decision.allowed:
                    policy_rejected_total += 1
                    reject_reasons[decision.reason] += 1
                    continue

                source_id = clean_text(row.get("id"))
                if not source_id:
                    reject_reasons["missing Overture id"] += 1
                    policy_rejected_total += 1
                    continue

                records.append(
                    {
                        "source": "overture",
                        "source_id": source_id,
                        "name": name,
                        "category": _category(row),
                        "lon": float(point.x),
                        "lat": float(point.y),
                        "provenance": clean_text(row.get("sources")),
                        "upstream_license": "|".join(decision.licenses),
                        "overture_providers": "|".join(decision.providers),
                        "geometry": point,
                    }
                )

            accepted = len(records) - accepted_before
            rejected = policy_rejected_total - rejected_before
            _emit(
                progress,
                f"Overture: batch {batch_number} — {len(table):,} raw, "
                f"{accepted:,} accepted, {rejected:,} provenance-policy rejected; "
                f"{len(records):,} accepted total",
            )

    # Never silently persist a fresh zero-row result. It previously allowed a
    # schema/provenance mismatch to masquerade as a successful acquisition.
    if raw_total == 0:
        raise RuntimeError(
            "Overture returned zero raw Places rows for this bbox. "
            "No empty cache was written; retry the acquisition."
        )

    if not records:
        top_reasons = "; ".join(
            f"{reason} ({count:,})"
            for reason, count in reject_reasons.most_common(5)
        ) or "no rejection reason recorded"
        top_datasets = ", ".join(
            f"{dataset}={count:,}"
            for dataset, count in datasets_seen.most_common(10)
        ) or "none parsed"

        raise RuntimeError(
            "Overture returned data but zero Places survived normalization. "
            f"Raw rows: {raw_total:,}; permanently closed: {closed_total:,}; "
            f"nameless: {nameless_total:,}; invalid geometry: {geometry_total:,}; "
            f"provenance-policy rejected: {policy_rejected_total:,}. "
            f"Datasets seen: {top_datasets}. "
            f"Top rejection reasons: {top_reasons}. "
            "No empty cache was written."
        )

    columns = [
        "source",
        "source_id",
        "name",
        "category",
        "lon",
        "lat",
        "provenance",
        "upstream_license",
        "overture_providers",
        "geometry",
    ]
    frame = pd.DataFrame(records)
    if frame.empty:
        frame = pd.DataFrame(columns=columns)
    gdf = gpd.GeoDataFrame(frame, geometry="geometry", crs="EPSG:4326")

    # Write data first, then both compatibility markers. An interrupted write
    # therefore cannot make a stale/partial layer look current.
    temporary = cache_file.with_suffix(cache_file.suffix + ".tmp")
    gdf.to_parquet(temporary, index=False)
    temporary.replace(cache_file)
    write_cache_identity(cache_file, bbox)
    _write_policy_metadata(
        cache_file,
        bbox,
        raw_rows=raw_total,
        accepted_rows=len(gdf),
    )

    _emit(
        progress,
        f"Overture: complete — {raw_total:,} raw rows, {len(gdf):,} accepted, "
        f"{policy_rejected_total:,} provenance-policy rejected, "
        f"{closed_total:,} permanently closed",
    )

    if datasets_seen:
        summary = ", ".join(
            f"{dataset}={count:,}"
            for dataset, count in datasets_seen.most_common(10)
        )
        _emit(progress, f"Overture: source datasets observed — {summary}")

    return gdf

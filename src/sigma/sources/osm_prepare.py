from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from ..area.catalog import load_areas
from ..area.boundary import load_boundary
from ..places.osm import extract_national_osm_pois, read_osm_cache

ProgressCallback = Callable[[str], None]

STATE_SCHEMA_VERSION = 1
STATE_FLUSH_INTERVAL = 25


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_parquet(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


def _parquet_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        return None


def _parquet_ok(path: Path) -> bool:
    return _parquet_rows(path) is not None


def _source_version(cache_base: Path, pbf_file: Path) -> str:
    meta = _read_json(cache_base / "geofabrik" / "philippines-latest.meta.json")
    version = str(meta.get("source_version") or "").strip()
    if version:
        return version

    stat = pbf_file.stat()
    return f"local-{stat.st_size}-{stat.st_mtime_ns}"


def _prepared_root(cache_base: Path) -> Path:
    return cache_base / "geofabrik" / "prepared"


def _final_dir(cache_base: Path, version: str) -> Path:
    return _prepared_root(cache_base) / version


def _work_dir(cache_base: Path, version: str) -> Path:
    return _prepared_root(cache_base) / f"{version}.incomplete"


def _manifest_path(directory: Path) -> Path:
    return directory / "manifest.json"


def _state_path(directory: Path) -> Path:
    return directory / "state.json"


def _new_state(version: str) -> dict[str, object]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "status": "incomplete",
        "source_version": version,
        "created_at": _now(),
        "updated_at": _now(),
        "stages": {
            "national_extraction": {"status": "pending"},
            "boundaries": {"status": "pending"},
            "assignment": {"status": "pending"},
            "area_caches": {"status": "pending", "completed": 0, "total": None},
            "composites": {"status": "pending", "completed": 0, "total": None},
            "validation": {"status": "pending"},
        },
    }


def _load_state(directory: Path, version: str) -> dict[str, object]:
    state = _read_json(_state_path(directory))
    if (
        state.get("schema_version") != STATE_SCHEMA_VERSION
        or str(state.get("source_version") or "") != version
    ):
        state = _new_state(version)
        _atomic_json(_state_path(directory), state)
    return state


def _save_state(directory: Path, state: dict[str, object]) -> None:
    state["updated_at"] = _now()
    _atomic_json(_state_path(directory), state)


def _stage(state: dict[str, object], name: str) -> dict[str, object]:
    stages = state.setdefault("stages", {})
    if not isinstance(stages, dict):
        stages = {}
        state["stages"] = stages
    value = stages.setdefault(name, {"status": "pending"})
    if not isinstance(value, dict):
        value = {"status": "pending"}
        stages[name] = value
    return value


def _set_stage(
    directory: Path,
    state: dict[str, object],
    name: str,
    status: str,
    **fields: object,
) -> None:
    stage = _stage(state, name)
    stage["status"] = status
    stage.update(fields)
    _save_state(directory, state)


def _is_complete(directory: Path, version: str) -> bool:
    manifest = _read_json(_manifest_path(directory))
    return (
        manifest.get("status") == "complete"
        and str(manifest.get("source_version") or "") == version
        and _parquet_ok(directory / "national-pois.parquet")
        and (directory / "areas").is_dir()
    )


def _empty_like(points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return points.iloc[0:0].copy()


def _build_boundaries(
    *,
    areas_file: Path | None,
    progress: ProgressCallback | None,
) -> tuple[dict[str, object], gpd.GeoDataFrame, list[object]]:
    areas = load_areas(areas_file)
    localities = [
        area for area in areas.values()
        if area.kind in {"city", "municipality"}
    ]
    composites = [
        area for area in areas.values()
        if area.kind == "composite"
    ]

    rows: list[dict[str, object]] = []
    total = len(localities)
    _emit(progress, f"OSM preparation: loading boundaries for {total:,} LGUs")

    for number, area in enumerate(localities, start=1):
        rows.append(
            {
                "area_slug": area.slug,
                "psgc_code": area.psgc_code or "",
                "geometry": load_boundary(area),
            }
        )
        if number % 100 == 0 or number == total:
            _emit(
                progress,
                f"OSM preparation: boundaries loaded {number:,}/{total:,}",
            )

    boundaries = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return areas, boundaries, composites


def _assign_localities(
    points: gpd.GeoDataFrame,
    boundaries: gpd.GeoDataFrame,
    *,
    progress: ProgressCallback | None,
) -> tuple[pd.DataFrame, int, int]:
    if points.empty:
        return pd.DataFrame(columns=["point_index", "area_slug"]), 0, 0

    indexed_points = points.reset_index(drop=True).copy()
    indexed_points["point_index"] = indexed_points.index

    _emit(
        progress,
        f"OSM preparation: assigning {len(points):,} POIs to LGUs with one spatial join",
    )
    joined = gpd.sjoin(
        indexed_points[["point_index", "geometry"]],
        boundaries[["area_slug", "psgc_code", "geometry"]],
        how="left",
        predicate="within",
    )

    matched = joined[joined["area_slug"].notna()].copy()
    within_counts = matched.groupby("point_index").size()
    overlap_points = set(within_counts[within_counts > 1].index.tolist())

    if not matched.empty:
        matched = matched.sort_values(
            ["point_index", "psgc_code", "area_slug"],
            kind="stable",
        ).drop_duplicates("point_index", keep="first")

    assigned_indices = set(matched["point_index"].astype(int).tolist())
    all_indices = set(indexed_points["point_index"].astype(int).tolist())
    unmatched_indices = sorted(all_indices - assigned_indices)

    boundary_ambiguous = 0
    if unmatched_indices:
        _emit(
            progress,
            f"OSM preparation: resolving {len(unmatched_indices):,} boundary-edge POIs",
        )
        remaining = indexed_points.loc[unmatched_indices, ["point_index", "geometry"]]
        edge = gpd.sjoin(
            remaining,
            boundaries[["area_slug", "psgc_code", "geometry"]],
            how="left",
            predicate="intersects",
        )
        edge_matched = edge[edge["area_slug"].notna()].copy()

        if not edge_matched.empty:
            edge_counts = edge_matched.groupby("point_index").size()
            boundary_ambiguous = int((edge_counts > 1).sum())
            edge_matched = edge_matched.sort_values(
                ["point_index", "psgc_code", "area_slug"],
                kind="stable",
            ).drop_duplicates("point_index", keep="first")
            matched = pd.concat([matched, edge_matched], ignore_index=True)

    matched = matched[["point_index", "area_slug"]].copy()
    final_assigned = set(matched["point_index"].astype(int).tolist())
    unassigned_count = len(all_indices - final_assigned)

    return (
        matched.sort_values("point_index", kind="stable").reset_index(drop=True),
        len(overlap_points) + boundary_ambiguous,
        unassigned_count,
    )


def _assignment_metrics_path(directory: Path) -> Path:
    return directory / "assignment-metrics.json"


def _load_assignment_metrics(directory: Path) -> tuple[int, int] | None:
    payload = _read_json(_assignment_metrics_path(directory))
    try:
        return (
            int(payload["ambiguous_boundary_or_overlap_count"]),
            int(payload["unassigned_count"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _write_assignment_metrics(
    directory: Path,
    *,
    ambiguous_count: int,
    unassigned_count: int,
) -> None:
    _atomic_json(
        _assignment_metrics_path(directory),
        {
            "ambiguous_boundary_or_overlap_count": int(ambiguous_count),
            "unassigned_count": int(unassigned_count),
        },
    )


def _read_current_complete_dir(cache_base: Path) -> tuple[str, Path] | None:
    payload = _read_json(_prepared_root(cache_base) / "current.json")
    version = str(payload.get("source_version") or "").strip()
    if not version:
        return None

    # Derive the path from the active cache root so moving the repository/cache
    # does not leave current.json pointing at a stale absolute path.
    path = _final_dir(cache_base, version)
    if _is_complete(path, version):
        return version, path
    return None


def _write_current(cache_base: Path, version: str, directory: Path) -> None:
    _atomic_json(
        _prepared_root(cache_base) / "current.json",
        {
            "source_version": version,
            "prepared_dir": str(directory),
            "updated_at": _now(),
        },
    )


def _prepare_national_stage(
    *,
    directory: Path,
    state: dict[str, object],
    cache_base: Path,
    pbf_file: Path,
    progress: ProgressCallback | None,
) -> gpd.GeoDataFrame:
    path = directory / "national-pois.parquet"

    if _parquet_ok(path):
        rows = _parquet_rows(path) or 0
        _set_stage(
            directory,
            state,
            "national_extraction",
            "complete",
            rows=rows,
        )
        _emit(
            progress,
            f"OSM resume: nationwide POI extraction already complete — {rows:,} rows",
        )
        return gpd.read_parquet(path)

    _set_stage(directory, state, "national_extraction", "running")
    node_cache = cache_base / "geofabrik" / "node-locations.cache"
    # A failed libosmium pass may leave a partial location index. Restart this stage cleanly.
    node_cache.unlink(missing_ok=True)

    points = extract_national_osm_pois(
        pbf_file,
        node_cache=node_cache,
        progress=progress,
    )
    _atomic_parquet(points, path)
    _set_stage(
        directory,
        state,
        "national_extraction",
        "complete",
        rows=len(points),
    )
    _emit(
        progress,
        f"OSM checkpoint saved: national-pois.parquet — {len(points):,} rows",
    )
    return points


def _prepare_boundary_stage(
    *,
    directory: Path,
    state: dict[str, object],
    areas_file: Path | None,
    progress: ProgressCallback | None,
) -> tuple[dict[str, object], gpd.GeoDataFrame, list[object]]:
    all_areas = load_areas(areas_file)
    composites = [
        area for area in all_areas.values()
        if area.kind == "composite"
    ]
    path = directory / "boundaries.parquet"

    if _parquet_ok(path):
        boundaries = gpd.read_parquet(path)
        _set_stage(
            directory,
            state,
            "boundaries",
            "complete",
            rows=len(boundaries),
        )
        _emit(
            progress,
            f"OSM resume: prepared LGU boundaries already complete — "
            f"{len(boundaries):,} rows",
        )
        return all_areas, boundaries, composites

    _set_stage(directory, state, "boundaries", "running")
    all_areas, boundaries, composites = _build_boundaries(
        areas_file=areas_file,
        progress=progress,
    )
    _atomic_parquet(boundaries, path)
    _set_stage(
        directory,
        state,
        "boundaries",
        "complete",
        rows=len(boundaries),
    )
    _emit(
        progress,
        f"OSM checkpoint saved: boundaries.parquet — {len(boundaries):,} LGUs",
    )
    return all_areas, boundaries, composites


def _prepare_assignment_stage(
    *,
    directory: Path,
    state: dict[str, object],
    points: gpd.GeoDataFrame,
    boundaries: gpd.GeoDataFrame,
    progress: ProgressCallback | None,
) -> tuple[pd.DataFrame, int, int]:
    assignments_path = directory / "assignments.parquet"
    assigned_layer_path = directory / "national-pois-assigned.parquet"
    metrics = _load_assignment_metrics(directory)

    if _parquet_ok(assignments_path) and metrics is not None:
        assignments = pd.read_parquet(assignments_path)
        ambiguous_count, unassigned_count = metrics

        if not _parquet_ok(assigned_layer_path):
            assigned = points.copy()
            area_by_index = dict(
                zip(
                    assignments["point_index"].astype(int),
                    assignments["area_slug"].astype(str),
                    strict=False,
                )
            )
            assigned["area_slug"] = [
                area_by_index.get(i, "")
                for i in range(len(assigned))
            ]
            _atomic_parquet(assigned, assigned_layer_path)

        _set_stage(
            directory,
            state,
            "assignment",
            "complete",
            assigned_rows=len(assignments),
            ambiguous_count=ambiguous_count,
            unassigned_count=unassigned_count,
        )
        _emit(
            progress,
            f"OSM resume: nationwide LGU assignment already complete — "
            f"{len(assignments):,} assigned",
        )
        return assignments, ambiguous_count, unassigned_count

    _set_stage(directory, state, "assignment", "running")
    assignments, ambiguous_count, unassigned_count = _assign_localities(
        points,
        boundaries,
        progress=progress,
    )
    _atomic_parquet(assignments, assignments_path)
    _write_assignment_metrics(
        directory,
        ambiguous_count=ambiguous_count,
        unassigned_count=unassigned_count,
    )

    assigned = points.copy()
    area_by_index = dict(
        zip(
            assignments["point_index"].astype(int),
            assignments["area_slug"].astype(str),
            strict=False,
        )
    )
    assigned["area_slug"] = [
        area_by_index.get(i, "")
        for i in range(len(assigned))
    ]
    _atomic_parquet(assigned, assigned_layer_path)

    _set_stage(
        directory,
        state,
        "assignment",
        "complete",
        assigned_rows=len(assignments),
        ambiguous_count=ambiguous_count,
        unassigned_count=unassigned_count,
    )
    _emit(
        progress,
        f"OSM checkpoint saved: nationwide LGU assignment — "
        f"{len(assignments):,} assigned",
    )
    return assignments, ambiguous_count, unassigned_count


def _write_locality_caches(
    *,
    directory: Path,
    state: dict[str, object],
    points: gpd.GeoDataFrame,
    assignments: pd.DataFrame,
    all_areas: dict[str, object],
    progress: ProgressCallback | None,
) -> dict[str, int]:
    areas_dir = directory / "areas"
    areas_dir.mkdir(parents=True, exist_ok=True)

    assignment_map: dict[str, list[int]] = {}
    for row in assignments.itertuples(index=False):
        assignment_map.setdefault(str(row.area_slug), []).append(int(row.point_index))

    localities = sorted(
        (
            area for area in all_areas.values()
            if area.kind in {"city", "municipality"}
        ),
        key=lambda area: area.slug,
    )
    total = len(localities)

    valid_existing = sum(
        _parquet_ok(areas_dir / f"{area.slug}.parquet")
        for area in localities
    )
    _set_stage(
        directory,
        state,
        "area_caches",
        "running" if valid_existing < total else "complete",
        completed=valid_existing,
        total=total,
    )

    if valid_existing:
        _emit(
            progress,
            f"OSM resume: {valid_existing:,}/{total:,} LGU caches already complete",
        )

    counts: dict[str, int] = {}
    completed = valid_existing

    for area in localities:
        target = areas_dir / f"{area.slug}.parquet"
        rows = _parquet_rows(target)

        if rows is None:
            indices = assignment_map.get(area.slug, [])
            frame = points.iloc[indices].copy() if indices else _empty_like(points)
            _atomic_parquet(frame, target)
            rows = len(frame)
            completed += 1

            if completed % STATE_FLUSH_INTERVAL == 0 or completed == total:
                _set_stage(
                    directory,
                    state,
                    "area_caches",
                    "running" if completed < total else "complete",
                    completed=completed,
                    total=total,
                )
                _emit(
                    progress,
                    f"OSM checkpoint: LGU caches {completed:,}/{total:,}",
                )

        counts[area.slug] = int(rows)

    _set_stage(
        directory,
        state,
        "area_caches",
        "complete",
        completed=total,
        total=total,
    )
    return counts


def _write_composite_caches(
    *,
    directory: Path,
    state: dict[str, object],
    points: gpd.GeoDataFrame,
    composites: list[object],
    progress: ProgressCallback | None,
) -> dict[str, int]:
    areas_dir = directory / "areas"
    areas_dir.mkdir(parents=True, exist_ok=True)

    composites = sorted(composites, key=lambda area: area.slug)
    total = len(composites)
    counts: dict[str, int] = {}
    completed = 0

    for area in composites:
        target = areas_dir / f"{area.slug}.parquet"
        rows = _parquet_rows(target)
        if rows is None:
            boundary = load_boundary(area)
            if points.empty:
                frame = _empty_like(points)
            else:
                frame = points.loc[points.geometry.covered_by(boundary)].copy()
            _atomic_parquet(frame, target)
            rows = len(frame)
            _emit(
                progress,
                f"OSM checkpoint: composite {area.slug} — {rows:,} POIs",
            )
        else:
            _emit(
                progress,
                f"OSM resume: composite {area.slug} already complete — {rows:,} POIs",
            )

        completed += 1
        counts[area.slug] = int(rows)
        _set_stage(
            directory,
            state,
            "composites",
            "running" if completed < total else "complete",
            completed=completed,
            total=total,
        )

    if not composites:
        _set_stage(
            directory,
            state,
            "composites",
            "complete",
            completed=0,
            total=0,
        )
    return counts


def _validate_and_manifest(
    *,
    directory: Path,
    state: dict[str, object],
    version: str,
    points: gpd.GeoDataFrame,
    all_areas: dict[str, object],
    ambiguous_count: int,
    unassigned_count: int,
    progress: ProgressCallback | None,
) -> dict[str, object]:
    expected_areas = sorted(all_areas.values(), key=lambda area: area.slug)
    area_counts: dict[str, int] = {}
    missing: list[str] = []

    _set_stage(directory, state, "validation", "running")
    for area in expected_areas:
        path = directory / "areas" / f"{area.slug}.parquet"
        rows = _parquet_rows(path)
        if rows is None:
            missing.append(area.slug)
        else:
            area_counts[area.slug] = int(rows)

    required_files = [
        directory / "national-pois.parquet",
        directory / "boundaries.parquet",
        directory / "assignments.parquet",
        directory / "national-pois-assigned.parquet",
    ]
    broken_required = [str(path.name) for path in required_files if not _parquet_ok(path)]

    if missing or broken_required:
        _set_stage(
            directory,
            state,
            "validation",
            "failed",
            missing_area_count=len(missing),
            broken_required=broken_required,
        )
        raise RuntimeError(
            "Prepared OSM cache validation failed: "
            f"{len(missing)} area cache(s) missing/corrupt; "
            f"{len(broken_required)} required checkpoint(s) missing/corrupt."
        )

    locality_count = sum(
        area.kind in {"city", "municipality"}
        for area in all_areas.values()
    )
    composite_count = sum(
        area.kind == "composite"
        for area in all_areas.values()
    )

    manifest: dict[str, object] = {
        "status": "complete",
        "source_version": version,
        "created_at": _now(),
        "national_poi_count": int(len(points)),
        "locality_count": int(locality_count),
        "composite_count": int(composite_count),
        "ambiguous_boundary_or_overlap_count": int(ambiguous_count),
        "unassigned_count": int(unassigned_count),
        "area_counts": area_counts,
    }
    _atomic_json(_manifest_path(directory), manifest)
    _set_stage(
        directory,
        state,
        "validation",
        "complete",
        area_count=len(area_counts),
    )
    state["status"] = "complete"
    _save_state(directory, state)

    _emit(
        progress,
        f"OSM validation complete — {len(area_counts):,} area caches verified",
    )
    return manifest


def prepare_all_area_osm_caches(
    *,
    cache_base: Path,
    pbf_file: Path,
    areas_file: Path | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Path, str]:
    """Prepare all area OSM caches with durable stage checkpoints."""
    version = _source_version(cache_base, pbf_file)
    prepared_root = _prepared_root(cache_base)
    prepared_root.mkdir(parents=True, exist_ok=True)

    final_dir = _final_dir(cache_base, version)
    if _is_complete(final_dir, version):
        _emit(
            progress,
            f"OSM prepared cache: Geofabrik {version} already complete",
        )
        _write_current(cache_base, version, final_dir)
        return final_dir, version

    work_dir = _work_dir(cache_base, version)
    work_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(work_dir, version)

    _emit(
        progress,
        f"OSM prepared cache: resumable preparation for Geofabrik {version}",
    )

    points = _prepare_national_stage(
        directory=work_dir,
        state=state,
        cache_base=cache_base,
        pbf_file=pbf_file,
        progress=progress,
    )

    all_areas, boundaries, composites = _prepare_boundary_stage(
        directory=work_dir,
        state=state,
        areas_file=areas_file,
        progress=progress,
    )

    assignments, ambiguous_count, unassigned_count = _prepare_assignment_stage(
        directory=work_dir,
        state=state,
        points=points,
        boundaries=boundaries,
        progress=progress,
    )

    _write_locality_caches(
        directory=work_dir,
        state=state,
        points=points,
        assignments=assignments,
        all_areas=all_areas,
        progress=progress,
    )

    _write_composite_caches(
        directory=work_dir,
        state=state,
        points=points,
        composites=composites,
        progress=progress,
    )

    manifest = _validate_and_manifest(
        directory=work_dir,
        state=state,
        version=version,
        points=points,
        all_areas=all_areas,
        ambiguous_count=ambiguous_count,
        unassigned_count=unassigned_count,
        progress=progress,
    )

    # Do not disturb the previous live prepared version until validation has passed.
    if final_dir.exists():
        quarantine = (
            prepared_root
            / f".{version}.invalid-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        )
        final_dir.replace(quarantine)

    work_dir.replace(final_dir)
    _write_current(cache_base, version, final_dir)

    _emit(
        progress,
        f"OSM prepared cache complete — {manifest['national_poi_count']:,} "
        f"nationwide POIs; {manifest['locality_count']:,} LGUs",
    )
    return final_dir, version


def load_prepared_area_osm(
    *,
    cache_base: Path,
    pbf_file: Path,
    area_slug: str,
    areas_file: Path | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[gpd.GeoDataFrame, str, bool]:
    """Load area OSM cache, falling back to the last complete version if needed."""
    current_before = _read_current_complete_dir(cache_base)

    try:
        prepared_dir, version = prepare_all_area_osm_caches(
            cache_base=cache_base,
            pbf_file=pbf_file,
            areas_file=areas_file,
            progress=progress,
        )
        fallback = False
    except Exception as exc:
        if current_before is None:
            raise

        previous_version, previous_dir = current_before
        target = previous_dir / "areas" / f"{area_slug}.parquet"
        if not _parquet_ok(target):
            raise

        _emit(
            progress,
            f"OSM preparation for the new Geofabrik version failed "
            f"({type(exc).__name__}: {exc}).",
        )
        _emit(
            progress,
            f"OSM fallback: using previous complete Geofabrik "
            f"{previous_version} cache for {area_slug}",
        )
        prepared_dir = previous_dir
        version = previous_version
        fallback = True

    area_path = prepared_dir / "areas" / f"{area_slug}.parquet"
    frame = read_osm_cache(area_path)
    _emit(
        progress,
        f"OSM: using prepared {area_slug} cache — {len(frame):,} POIs "
        f"(Geofabrik {version})",
    )
    return frame, version, fallback

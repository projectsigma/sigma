from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class BoundarySpec:
    gpkg: Path
    layer: str | None = None
    field: str | None = None
    value: str | int | float | tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Area:
    slug: str
    name: str
    kind: str
    bbox: tuple[float, float, float, float]
    psgc_code: str | None = None
    province: str | None = None
    aliases: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    boundary: BoundarySpec | None = None

def default_areas_path() -> Path:
    return Path(
        resources.files("sigma.resources.areas").joinpath("data", "areas.yml")
    )


def _boundary(value: Any, base: Path) -> BoundarySpec | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict) or not value.get("gpkg"):
        raise ValueError("boundary must be null or a mapping with a gpkg path")
    gpkg = Path(str(value["gpkg"]))
    if not gpkg.is_absolute():
        gpkg = (base / gpkg).resolve()
    if value.get("value") is not None and value.get("values") is not None:
        raise ValueError("boundary cannot define both value and values")
    boundary_value: str | int | float | tuple[str, ...] | None
    if value.get("values") is not None:
        values = value["values"]
        if not isinstance(values, list) or not values:
            raise ValueError("boundary values must be a non-empty list")
        boundary_value = tuple(str(v).strip() for v in values if str(v).strip())
        if not boundary_value:
            raise ValueError("boundary values must contain at least one value")
    else:
        boundary_value = value.get("value")
    return BoundarySpec(
        gpkg=gpkg,
        layer=str(value["layer"]) if value.get("layer") else None,
        field=str(value["field"]) if value.get("field") else None,
        value=boundary_value,
    )


@lru_cache(maxsize=8)
def _load_areas_cached(path_text: str, mtime_ns: int, size: int) -> tuple[tuple[str, Area], ...]:
    # mtime/size are deliberately part of the cache key so edited custom catalogs
    # are re-read while the packaged catalog is parsed only once per process.
    del mtime_ns, size
    path = Path(path_text)
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}
    raw_areas = payload.get("areas")
    if not isinstance(raw_areas, dict):
        raise ValueError(f"{path}: expected an 'areas' mapping")

    out: dict[str, Area] = {}
    for slug, raw in raw_areas.items():
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: area {slug!r} must be a mapping")
        bbox = raw.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"{path}: area {slug!r} needs bbox [west, south, east, north]")
        west, south, east, north = (float(v) for v in bbox)
        if not (west < east and south < north):
            raise ValueError(f"{path}: invalid bbox for {slug!r}")

        aliases_raw = raw.get("aliases") or []
        if not isinstance(aliases_raw, list):
            raise ValueError(f"{path}: aliases for {slug!r} must be a list")
        aliases = tuple(str(v).strip() for v in aliases_raw if str(v).strip())

        members_raw = raw.get("members") or []
        if not isinstance(members_raw, list):
            raise ValueError(f"{path}: members for {slug!r} must be a list")
        members = tuple(str(v).strip() for v in members_raw if str(v).strip())

        out[str(slug)] = Area(
            slug=str(slug),
            name=str(raw.get("name") or slug),
            kind=str(raw.get("kind") or "area"),
            bbox=(west, south, east, north),
            psgc_code=str(raw["psgc_code"]) if raw.get("psgc_code") is not None else None,
            province=str(raw["province"]) if raw.get("province") else None,
            aliases=aliases,
            members=members,
            boundary=_boundary(raw.get("boundary"), path.parent),
        )
    return tuple(out.items())


def load_areas(path: Path | None = None) -> dict[str, Area]:
    resolved = (path or default_areas_path()).resolve()
    stat = resolved.stat()
    return dict(_load_areas_cached(str(resolved), stat.st_mtime_ns, stat.st_size))


def resolve_area(value: str, path: Path | None = None) -> Area:
    areas = load_areas(path)

    # Canonical slug wins immediately.
    if value in areas:
        return areas[value]

    query = value.casefold().strip()
    matches: list[Area] = []
    for area in areas.values():
        candidates = {area.slug.casefold(), area.name.casefold()}
        candidates.update(alias.casefold() for alias in area.aliases)
        if query in candidates:
            matches.append(area)

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        labels = ", ".join(
            f"{area.slug} ({area.name}, PSGC {area.psgc_code})" for area in matches
        )
        raise KeyError(f"ambiguous area {value!r}; matches: {labels}")

    raise KeyError(
        f"unknown area {value!r}; use `sigma areas list --search <name>` "
        "to find a locality or pass its 10-digit PSGC code"
    )


# Architectural aliases/wrappers. The procedural functions above intentionally retain
# the proven Siphon behavior; this OO surface gives the unified system one catalog owner.
def load_area_catalog(path: Path | None = None) -> dict[str, Area]:
    return load_areas(path)


def list_areas(
    path: Path | None = None,
    *,
    kind: str | None = None,
    search: str | None = None,
) -> tuple[Area, ...]:
    areas = load_areas(path).values()
    normalized_kind = kind.casefold().strip() if kind else None
    query = search.casefold().strip() if search else None
    selected: list[Area] = []
    for area in areas:
        if normalized_kind and area.kind.casefold() != normalized_kind:
            continue
        if query:
            haystack = [area.slug, area.name, area.psgc_code or "", *area.aliases]
            if not any(query in value.casefold() for value in haystack):
                continue
        selected.append(area)
    return tuple(sorted(selected, key=lambda area: (area.name.casefold(), area.slug)))


class AreaCatalog:
    """Canonical area-catalog facade around the preserved Siphon implementation."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser().resolve() if path is not None else default_areas_path()

    def load(self) -> dict[str, Area]:
        return load_areas(self.path)

    def resolve(self, value: str) -> Area:
        return resolve_area(value, self.path)

    def list(self, *, kind: str | None = None, search: str | None = None) -> tuple[Area, ...]:
        return list_areas(self.path, kind=kind, search=search)

    def identity(self) -> dict[str, object]:
        """Return a content identity for the catalog and every referenced boundary file."""
        import hashlib
        import json

        catalog_sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        boundary_files = sorted(
            {area.boundary.gpkg for area in self.load().values() if area.boundary is not None},
            key=lambda path: str(path),
        )
        boundaries = []
        for boundary_path in boundary_files:
            if not boundary_path.is_file():
                raise FileNotFoundError(f"boundary GeoPackage does not exist: {boundary_path}")
            boundaries.append(
                {
                    "path": str(boundary_path),
                    "sha256": hashlib.sha256(boundary_path.read_bytes()).hexdigest(),
                }
            )
        payload = {
            "catalog_sha256": catalog_sha256,
            "boundary_sha256": [item["sha256"] for item in boundaries],
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "catalog": str(self.path),
            "catalog_sha256": catalog_sha256,
            "boundaries": boundaries,
            "fingerprint": fingerprint,
        }

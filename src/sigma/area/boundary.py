from __future__ import annotations

import hashlib
import json

import geopandas as gpd
from shapely import union_all
from shapely.geometry import box

from .catalog import Area, BoundarySpec

WGS84 = "EPSG:4326"


def _wanted_values(spec: BoundarySpec) -> tuple[str, ...]:
    raw = spec.value if isinstance(spec.value, tuple) else (spec.value,)
    return tuple(str(value).strip() for value in raw if value is not None)


def boundary_identity(area: Area, geometry=None) -> dict[str, object]:
    """Return a content-addressed identity for the effective clipping boundary."""
    if area.boundary is None:
        report: dict[str, object] = {
            "mode": "bbox",
            "bbox": [float(value) for value in area.bbox],
        }
        fingerprint_payload = report
    else:
        spec = area.boundary
        if not spec.gpkg.exists():
            raise FileNotFoundError(f"boundary GeoPackage does not exist: {spec.gpkg}")
        effective = geometry if geometry is not None else load_boundary(area)
        geometry_sha256 = hashlib.sha256(effective.wkb).hexdigest()
        fingerprint_payload = {
            "mode": "gpkg",
            "geometry_sha256": geometry_sha256,
            "layer": spec.layer,
            "field": spec.field,
            "values": list(_wanted_values(spec)),
        }
        report = {
            **fingerprint_payload,
            "gpkg": str(spec.gpkg),
        }

    encoded = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        **report,
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
    }


def load_boundary(area: Area):
    """Return the configured clipping geometry in WGS84, or the area's bbox polygon."""
    if area.boundary is None:
        return box(*area.bbox)

    spec = area.boundary
    if not spec.gpkg.exists():
        raise FileNotFoundError(f"boundary GeoPackage does not exist: {spec.gpkg}")

    # The GeoPackage contains every Philippine locality. Restrict the read to
    # the area's acquisition envelope before applying the exact PSGC filter.
    columns = [spec.field] if spec.field else None
    frame = gpd.read_file(
        spec.gpkg,
        layer=spec.layer,
        bbox=area.bbox,
        columns=columns,
    )
    if frame.empty:
        raise ValueError(
            f"boundary layer has no geometry intersecting {area.slug!r}: {spec.gpkg}"
        )

    if spec.field:
        if spec.field not in frame.columns:
            raise ValueError(f"boundary field {spec.field!r} not found in {spec.gpkg}")
        values = (
            frame[spec.field]
            .astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
        )

        wanted_values = _wanted_values(spec)
        mask = values.isin(wanted_values)
        for wanted in wanted_values:
            if wanted.isdigit():
                mask |= values.str.replace(r"^0+", "", regex=True) == wanted.lstrip("0")
        frame = frame.loc[mask]
        if frame.empty:
            raise ValueError(
                f"no boundary row where {spec.field} matches {spec.value!r} in {spec.gpkg}"
            )

        matched = set(
            frame[spec.field]
            .astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
        )
        stripped_matched = {value.lstrip("0") for value in matched}
        missing = [
            wanted
            for wanted in wanted_values
            if wanted not in matched
            and not (wanted.isdigit() and wanted.lstrip("0") in stripped_matched)
        ]
        if missing:
            raise ValueError(
                f"boundary rows missing for {spec.field} values {missing!r} in {spec.gpkg}"
            )

    if frame.crs is None:
        raise ValueError(f"boundary layer has no CRS: {spec.gpkg}")
    frame = frame.to_crs(WGS84)
    geometry = union_all(frame.geometry.dropna().to_numpy())
    if geometry.is_empty:
        raise ValueError(f"boundary geometry is empty: {spec.gpkg}")
    return geometry


def clip_points(frame: gpd.GeoDataFrame, geometry) -> gpd.GeoDataFrame:
    if frame.empty:
        return frame.copy()
    if frame.crs is None:
        frame = frame.set_crs(WGS84)
    elif str(frame.crs) != WGS84:
        frame = frame.to_crs(WGS84)
    mask = frame.geometry.intersects(geometry)
    return frame.loc[mask].reset_index(drop=True)


def materialize_area_boundary(
    area: Area,
    target,
    *,
    layer: str = "boundary",
):
    """Publish the canonical WGS84 boundary as one compatibility GPKG feature."""
    from pathlib import Path

    destination = Path(target).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    geometry = load_boundary(area)
    selected = gpd.GeoDataFrame(
        {"area_slug": [area.slug], "area_name": [area.name]},
        geometry=[geometry],
        crs=WGS84,
    )
    if destination.exists():
        destination.unlink()
    selected.to_file(destination, layer=layer, driver="GPKG")
    return destination


class BoundaryResolver:
    """Thin canonical facade over the preserved boundary implementation."""

    def load(self, area: Area):
        return load_boundary(area)

    def identity(self, area: Area, geometry=None) -> dict[str, object]:
        return boundary_identity(area, geometry=geometry)

    def materialize(self, area: Area, target, *, layer: str = "boundary"):
        return materialize_area_boundary(area, target, layer=layer)

"""Dependency-free Mapbox Vector Tile (MVT v2) writer for SIGMA points.

Geographic previews use deterministic subsets of *real points*, never generated
centroids. Zooms 12 and 13 contain all published locations. This is a
read-only display format, not a SIGMA analytical transformation.
"""
from __future__ import annotations

import hashlib
import math
import struct
from collections import defaultdict
from pathlib import Path
from typing import Any

EXTENT = 8192  # ~1.2m at z12, ~0.6m at z13 near the equator
ZOOM_RATES = {8: 0.015, 9: 0.04, 10: 0.10, 11: 0.30, 12: 1.0, 13: 1.0}


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("unsigned varint must be nonnegative")
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def _field_number(field: int, value: int) -> bytes:
    return _varint(field * 8) + _varint(value)


def _field_bytes(field: int, value: bytes) -> bytes:
    return _varint(field * 8 + 2) + _varint(len(value)) + value


def _signed(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def _encode_value(value: Any) -> bytes:
    if isinstance(value, bool):
        return _field_number(7, int(value))
    if isinstance(value, int):
        if value >= 0:
            return _field_number(5, value)
        return _field_number(6, (abs(value) * 2 - 1))
    if isinstance(value, float):
        if math.isfinite(value):
            return bytes([0x19]) + struct.pack("<d", value)
        return _field_bytes(1, b"")
    return _field_bytes(1, str(value).encode("utf-8"))


def _mercator(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = max(-85.051128, min(85.051128, lat))
    n = float(2 ** zoom)
    return ((lon + 180) / 360 * n,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) * 0.5 * n)


def _keep(identifier: str, rate: float) -> bool:
    if rate >= 1:
        return True
    # Stable across refreshes and levels: z10's points are a subset of z11's.
    digest = hashlib.blake2b(identifier.encode("utf-8"), digest_size=8, person=b"sigmaLOD").digest()
    return int.from_bytes(digest, "big") / (2 ** 64) < rate


def _feature_properties(raw: dict[str, Any]) -> dict[str, Any]:
    # Keep click/hover identity and score, but avoid verbose provenance in every
    # vector tile. Detailed provenance remains in the original exact JSON tiles.
    keys = ("id", "name", "type", "original_type", "node_id", "cluster",
            "score", "unclustered", "psic")
    return {key: value for key in keys if (value := raw.get(key)) is not None}


def _tile_layer(points: list[tuple[int, int, dict[str, Any]]]) -> bytes:
    keys: list[str] = []
    values: list[bytes] = []
    key_idx: dict[str, int] = {}
    value_idx: dict[tuple[str, str], int] = {}
    feature_bytes: list[bytes] = []
    for ordinal, (x, y, props) in enumerate(points, 1):
        tags = bytearray()
        for key, value in props.items():
            if key not in key_idx:
                key_idx[key] = len(keys)
                keys.append(key)
            identity = (type(value).__name__, repr(value))
            if identity not in value_idx:
                value_idx[identity] = len(values)
                values.append(_encode_value(value))
            tags.extend(_varint(key_idx[key]))
            tags.extend(_varint(value_idx[identity]))
        # Geometry: MoveTo(1), delta-x, delta-y. Single point per feature.
        geometry = _varint(9) + _varint(_signed(x)) + _varint(_signed(y))
        feature_bytes.append(b"".join((
            _field_number(1, ordinal), _field_bytes(2, bytes(tags)),
            _field_number(3, 1), _field_bytes(4, geometry),
        )))
    parts = [_field_number(15, 2), _field_bytes(1, b"places")]
    parts.extend(_field_bytes(2, f) for f in feature_bytes)
    parts.extend(_field_bytes(3, key.encode("utf-8")) for key in keys)
    parts.extend(_field_bytes(4, val) for val in values)
    parts.append(_field_number(5, EXTENT))
    return _field_bytes(3, b"".join(parts))


def write_point_tiles(root: Path, source_tiles: dict[tuple[int, int], list[dict[str, Any]]]) -> dict[str, Any]:
    """Write real-coordinate point vector tiles, preserving all input files.

    Never call for public-profile exports: coordinates and names are included.
    """
    # Process ONE zoom at a time. Holding all six zooms' feature dictionaries
    # simultaneously multiplies memory for a 240k-point Metro Manila bundle.
    tile_count = 0
    byte_count = 0
    for z, rate in ZOOM_RATES.items():
        groups: dict[tuple[int, int], list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
        for original_tile, features in source_tiles.items():
            for feature in features:
                props = feature.get("properties") or {}
                if props.get("unclustered") is True:
                    continue  # legacy explicit opt-in hollow layer, never leaked by default
                coords = feature.get("geometry", {}).get("coordinates")
                if not coords or len(coords) != 2:
                    continue
                lon, lat = float(coords[0]), float(coords[1])
                if not (math.isfinite(lon) and math.isfinite(lat)):
                    continue
                identifier = str(props.get("id") or f"{original_tile}/{lon}/{lat}")
                if not _keep(identifier, rate):
                    continue
                xx, yy = _mercator(lon, lat, z)
                tx, ty = math.floor(xx), math.floor(yy)
                fx, fy = round((xx - tx) * EXTENT), round((yy - ty) * EXTENT)
                groups[(tx, ty)].append((fx, fy, _feature_properties(props)))
        for (x, y), entries in groups.items():
            target = root / f"data/points-v7/{z}/{x}/{y}.pbf"
            target.parent.mkdir(parents=True, exist_ok=True)
            encoded = _tile_layer(entries)
            target.write_bytes(encoded)
            tile_count += 1
            byte_count += len(encoded)
        # Nearby empty tiles carry a valid zero-feature layer, avoiding 404
        # churn as users pan across the interior of a bounded city extent.
        if groups:
            xs = [key[0] for key in groups]
            ys = [key[1] for key in groups]
            xmin, xmax = min(xs) - 1, max(xs) + 1
            ymin, ymax = min(ys) - 1, max(ys) + 1
            if (xmax - xmin + 1) * (ymax - ymin + 1) <= 2500:
                empty = _tile_layer([])
                for x in range(xmin, xmax + 1):
                    for y in range(ymin, ymax + 1):
                        if (x, y) in groups:
                            continue
                        target = root / f"data/points-v7/{z}/{x}/{y}.pbf"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(empty)
                        tile_count += 1
                        byte_count += len(empty)
        del groups
    return {"minzoom": min(ZOOM_RATES), "maxzoom": max(ZOOM_RATES),
            "exact_from_zoom": 12, "preview_rates": {str(z): value for z, value in ZOOM_RATES.items() if value < 1},
            "tiles": tile_count, "bytes": byte_count}

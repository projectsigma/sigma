from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import from_wkb, to_wkb


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        # GeoParquet may materialize list-valued/object fields as ndarrays on read.
        # Canonicalize them recursively so the managed JSON representation remains
        # portable and preserves the same logical list values.
        return _json_value(value.tolist())
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and bool(missing):
            return None
    except (TypeError, ValueError):
        pass
    return value


def write_geoframe(frame: gpd.GeoDataFrame, path: Path) -> None:
    """Portable managed-artifact encoding independent of Parquet availability.

    Public compatibility exports remain Parquet. This JSON encoding is an internal
    C8 artifact representation and intentionally preserves list-valued audit fields.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    geometry_name = frame.geometry.name if hasattr(frame, "geometry") else "geometry"
    columns = [str(column) for column in frame.columns if str(column) != geometry_name]
    # ``frame.values`` is the object table that ``DataFrame.iterrows`` walks through, so
    # each cell has the same Python value as before; only the per-row Series is avoided.
    table = frame.values
    column_positions = [frame.columns.get_loc(column) for column in columns]
    geometry_wkb = to_wkb(table[:, frame.columns.get_loc(geometry_name)])
    rows = [
        {
            "values": {
                column: _json_value(record[position])
                for column, position in zip(columns, column_positions, strict=True)
            },
            "geometry_wkb_hex": None if wkb is None else wkb.hex(),
        }
        for record, wkb in zip(table, geometry_wkb, strict=True)
    ]
    payload = {
        "schema_version": 1,
        "crs": str(frame.crs) if frame.crs is not None else None,
        "geometry_column": geometry_name,
        "columns": columns,
        "rows": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def read_geoframe(path: Path) -> gpd.GeoDataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported managed geoframe schema")
    columns = list(payload.get("columns") or [])
    records = []
    geometries = []
    for item in payload.get("rows") or []:
        values = dict(item.get("values") or {})
        records.append({column: values.get(column) for column in columns})
        raw = item.get("geometry_wkb_hex")
        geometries.append(None if raw in (None, "") else from_wkb(bytes.fromhex(str(raw))))
    frame = pd.DataFrame(records, columns=columns)
    return gpd.GeoDataFrame(frame, geometry=geometries, crs=payload.get("crs"))

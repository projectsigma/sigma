"""Managed (internal) geoframe artifacts.

Stage tables are written as compact Parquet (``*.parquet``).  Each cell is first
reduced to the JSON-compatible value that the original JSON encoding stored, and the
reader rebuilds the frame from those values exactly as the JSON reader did, so a
table reads back identically in either format.  Artifacts written earlier as
``*.json`` remain readable.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely import from_wkb, to_wkb

_PARQUET_METADATA_KEY = b"sigma_geoframe"

# Appended to the recipe version of every stage that writes managed tables.  Moving
# those tables from JSON to Parquet changed the stages' files; the artifact store
# keeps one immutable output per recipe, so the recipe identity must change too.
# Existing JSON artifacts stay readable; they are rebuilt once under the new recipe.
MANAGED_TABLES_VERSION = "+tables-parquet-v1"


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


def _arrow_column(values: list) -> tuple[pa.Array, bool]:
    """Arrow column for JSON-compatible cell values; ``True`` when stored as JSON text.

    A column whose non-null cells all have one exact type (int, float, str or bool) is
    stored natively, which round-trips the Python values exactly.  Any other column
    (lists, dicts, mixed types, very large ints) stores each cell as JSON text, which
    decodes to the same values as the original JSON encoding.
    """
    kinds = {type(value) for value in values if value is not None}
    native = {int: pa.int64(), float: pa.float64(), str: pa.string(), bool: pa.bool_()}
    if not kinds:
        return pa.nulls(len(values)), False
    if len(kinds) == 1 and next(iter(kinds)) in native:
        try:
            return pa.array(values, type=native[next(iter(kinds))]), False
        except (pa.ArrowException, OverflowError, UnicodeEncodeError):
            pass
    text = [None if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            for value in values]
    return pa.array(text, type=pa.string()), True


def write_geoframe(frame: gpd.GeoDataFrame, path: Path) -> None:
    """Write a managed stage table: Parquet for ``*.parquet`` paths, else legacy JSON.

    Public compatibility exports remain GeoParquet.  This internal encoding keeps the
    original JSON value model (including list-valued audit fields); see the module
    docstring.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    geometry_name = frame.geometry.name if hasattr(frame, "geometry") else "geometry"
    columns = [str(column) for column in frame.columns if str(column) != geometry_name]
    # ``frame.values`` is the object table that ``DataFrame.iterrows`` walks through, so
    # each cell has the same Python value as before; only the per-row Series is avoided.
    table = frame.values
    column_positions = [frame.columns.get_loc(column) for column in columns]
    geometry_wkb = to_wkb(table[:, frame.columns.get_loc(geometry_name)])
    if path.suffix == ".parquet":
        arrays, json_columns = [], []
        for position, column in zip(column_positions, columns, strict=True):
            array, as_json = _arrow_column([_json_value(value) for value in table[:, position]])
            arrays.append(array)
            if as_json:
                json_columns.append(column)
        arrays.append(pa.array(list(geometry_wkb), type=pa.binary()))
        names = [f"c{index}" for index in range(len(columns))] + ["geometry_wkb"]
        metadata = {
            "schema_version": 2,
            "crs": str(frame.crs) if frame.crs is not None else None,
            "geometry_column": geometry_name,
            "columns": columns,
            "json_columns": json_columns,
        }
        schema = pa.schema(
            [pa.field(name, array.type) for name, array in zip(names, arrays, strict=True)],
            metadata={_PARQUET_METADATA_KEY: json.dumps(metadata).encode("utf-8")},
        )
        pq.write_table(pa.Table.from_arrays(arrays, schema=schema), path, compression="zstd")
        return
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


def _read_parquet_geoframe(path: Path) -> gpd.GeoDataFrame:
    table = pq.read_table(path)
    metadata = json.loads(table.schema.metadata[_PARQUET_METADATA_KEY])
    if metadata.get("schema_version") != 2:
        raise ValueError("unsupported managed geoframe schema")
    columns = list(metadata["columns"])
    json_columns = set(metadata["json_columns"])
    values = []
    for index, column in enumerate(columns):
        cells = table.column(f"c{index}").to_pylist()
        if column in json_columns:
            cells = [None if cell is None else json.loads(cell) for cell in cells]
        values.append(cells)
    # Same construction as the JSON reader: one dict per row, then pandas inference.
    records = [dict(zip(columns, row, strict=True)) for row in zip(*values, strict=True)]
    if not columns:
        records = [{} for _ in range(table.num_rows)]
    frame = pd.DataFrame(records, columns=columns)
    geometries = list(from_wkb(table.column("geometry_wkb").to_pylist()))
    return gpd.GeoDataFrame(frame, geometry=geometries, crs=metadata.get("crs"))


def read_geoframe(path: Path) -> gpd.GeoDataFrame:
    """Read a managed stage table; a missing ``x.parquet`` falls back to legacy ``x.json``."""
    path = Path(path)
    if path.suffix == ".parquet":
        if path.is_file():
            return _read_parquet_geoframe(path)
        path = path.with_suffix(".json")
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

"""Small I/O helpers shared across the SIGMA engine.

This module deliberately keeps file-format concerns and sector-code normalization out of
algorithm modules.  Doing that gives the rest of the package one simple contract:

* vector inputs arrive as :class:`geopandas.GeoDataFrame` objects; and
* economic sector identifiers are either a normalized string or ``None``.
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np
from pathlib import Path

import geopandas as gpd
import pandas as pd

# Spreadsheet programs commonly coerce codes such as ``01`` to ``1`` or ``1.0``.
# SIGMA's IO16/IO80 identifiers are integer-like, so accept only an integer with an
# optional all-zero decimal suffix.  Textual labels (for synthetic/test IO tables) pass
# through untouched.
_NUMERIC_CODE = re.compile(r"^([+-]?\d+)(?:\.0+)?$")


def normalize_sector_id(value: object) -> str | None:
    """Return SIGMA's canonical string representation of one sector identifier.

    Numeric spreadsheet representations are normalized without going through binary
    floating point.  Avoiding ``float(value)`` matters because it prevents accidental
    precision loss for long identifiers, even though today's IO16/IO80 codes are short.

    Examples
    --------
    ``1``, ``1.0``, ``"1"`` and ``"01"`` all become ``"01"``.  Non-numeric labels
    such as ``"A"`` are stripped but otherwise preserved.  Missing/blank values become
    ``None``.
    """
    if value is None:
        return None
    if not isinstance(value, str) and pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    match = _NUMERIC_CODE.fullmatch(text)
    if match is None:
        return text

    integer = int(match.group(1))
    # ``02d`` means "at least two digits"; it does not truncate larger identifiers.
    return f"{integer:02d}"


def read_vector(path: str | Path, layer: str | None = None) -> gpd.GeoDataFrame:
    """Read a vector dataset supported by GeoPandas.

    GeoParquet is handled explicitly because ``geopandas.read_file`` does not read it.
    All other formats (GeoPackage, Shapefile, etc.) are delegated to GeoPandas/Fiona or
    Pyogrio.  ``layer`` is relevant only to container formats such as GeoPackage.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"vector input does not exist: {path}")
    if path.suffix.lower() in {".parquet", ".pq"}:
        return gpd.read_parquet(path)
    return gpd.read_file(path, layer=layer)


def write_geoparquet(frame: gpd.GeoDataFrame, path: str | Path) -> Path:
    """Write and immediately validate a GeoParquet artifact.

    The read-back is intentional.  A successful ``to_parquet`` call alone does not prove
    that the file retained geospatial metadata in a form GeoPandas/QGIS can consume.  The
    small extra I/O cost buys an early, local failure instead of a bad final deliverable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if frame.crs is None:
        raise ValueError("GeoParquet output requires a CRS")
    if "geometry" not in frame.columns:
        raise ValueError("GeoParquet output requires an active geometry column")

    frame.to_parquet(path, index=False)

    # Round-trip through GeoPandas to verify both row count and CRS metadata.  Geometry
    # validity is *not* universally required (e.g. some workflows intentionally carry
    # invalid source geometry), so we do not silently repair or reject it here.
    check = gpd.read_parquet(path)
    if check.crs is None:
        raise RuntimeError(f"GeoParquet round-trip lost CRS metadata: {path}")
    if len(check) != len(frame):
        raise RuntimeError(
            f"GeoParquet round-trip changed row count for {path}: "
            f"expected {len(frame)}, got {len(check)}"
        )
    return path


# Transaction-table readers migrated from sigma-engine without MWAS code.

def _normalized_axis(values, *, axis_name: str) -> list[str]:
    """Normalize one IO-table axis and reject blank/duplicate sector IDs."""
    normalized = [normalize_sector_id(value) for value in values]
    if any(value is None for value in normalized):
        raise ValueError(f"IO {axis_name} sector identifiers must be non-blank")
    out = [str(value) for value in normalized]
    counts = Counter(out)
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(
            f"IO {axis_name} sector identifiers are not unique after normalization: "
            f"{duplicates[:10]}"
        )
    return out

def _validated_transaction_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize and validate one already-extracted square transaction block."""
    if frame.empty:
        raise ValueError("IO transaction table is empty")

    row_ids = _normalized_axis(frame.index, axis_name="row")
    column_ids = _normalized_axis(frame.columns, axis_name="column")
    frame = frame.copy()
    frame.index = row_ids
    frame.columns = column_ids

    row_set = set(row_ids)
    column_set = set(column_ids)
    if row_set != column_set or len(row_ids) != len(column_ids):
        only_rows = sorted(row_set - column_set)
        only_columns = sorted(column_set - row_set)
        raise ValueError(
            "IO transaction block must be square with identical normalized row and column "
            f"sector IDs; only in rows={only_rows[:10]}, only in columns={only_columns[:10]}"
        )

    frame = frame.loc[row_ids, row_ids]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    values = frame.to_numpy(dtype=float, copy=False)
    if not np.isfinite(values).all():
        raise ValueError("IO transaction block contains missing or non-finite values")
    if (values < 0).any():
        raise ValueError("IO transaction weights must be non-negative")
    return frame.astype(float)

def _display_token(value: object) -> str | None:
    """Comparable token for labels in presentation-style spreadsheets."""
    if value is None or pd.isna(value):
        return None
    token = " ".join(str(value).split()).strip().casefold()
    return token or None

def _extract_presentation_block(raw: pd.DataFrame, sector_count: int) -> pd.DataFrame:
    """Locate an ``N x N`` intermediate-transaction block in a formatted worksheet.

    PSA-style workbooks place titles, units, descriptions, totals and final-demand columns
    around the transaction matrix.  The robust structural signal is that the same ordered
    sector labels appear once horizontally above the numeric block and once vertically to
    its left.  They may be industry codes *or* descriptions; SIGMA needs only their order.
    """
    if sector_count < 2:
        raise ValueError("presentation IO sector_count must be >= 2")
    rows, columns = raw.shape
    if rows < sector_count or columns < sector_count:
        raise ValueError(
            f"worksheet is too small to contain a {sector_count}x{sector_count} transaction block"
        )

    candidates: list[tuple[int, int, int, int, pd.DataFrame, list[object]]] = []
    max_header_row = rows - sector_count
    max_data_column = columns - sector_count

    for header_row in range(max_header_row + 1):
        for data_column in range(max_data_column + 1):
            horizontal_raw = raw.iloc[
                header_row, data_column : data_column + sector_count
            ].tolist()
            horizontal = [_display_token(value) for value in horizontal_raw]
            if any(token is None for token in horizontal) or len(set(horizontal)) != sector_count:
                continue

            first = horizontal[0]
            # Row labels for a transaction block must be to the left of its numeric cells.
            for label_column in range(data_column):
                possible_starts = [
                    row
                    for row in range(header_row + 1, rows - sector_count + 1)
                    if _display_token(raw.iat[row, label_column]) == first
                ]
                for data_row in possible_starts:
                    vertical_raw = raw.iloc[
                        data_row : data_row + sector_count, label_column
                    ].tolist()
                    vertical = [_display_token(value) for value in vertical_raw]
                    if vertical != horizontal:
                        continue

                    block = raw.iloc[
                        data_row : data_row + sector_count,
                        data_column : data_column + sector_count,
                    ].apply(pd.to_numeric, errors="coerce")
                    values = block.to_numpy(dtype=float, copy=False)
                    if not np.isfinite(values).all():
                        continue
                    candidates.append(
                        (
                            header_row,
                            data_column,
                            data_row,
                            label_column,
                            block,
                            horizontal_raw,
                        )
                    )

    if not candidates:
        raise ValueError(
            f"could not locate a {sector_count}x{sector_count} presentation-style IO block"
        )

    # Prefer the earliest/left-most structurally valid block.  On PSA transaction sheets
    # this selects intermediate demand, before totals/final-demand columns.
    candidates.sort(key=lambda item: item[:4])
    _, _, _, _, block, labels = candidates[0]
    block = block.copy()
    block.index = labels
    block.columns = labels
    return block

def _canonicalize_expected_order(frame: pd.DataFrame, sector_count: int | None) -> pd.DataFrame:
    """Map a published 16/80-sector ordering to SIGMA's ``01..N`` identifiers.

    A clean machine table that already carries canonical IDs is left unchanged.  A published
    table often uses PSIC ranges or long descriptions on both axes; when the caller has
    explicitly selected IO16 or IO80, positional order is the interoperability contract.
    """
    if sector_count is None:
        return frame
    if frame.shape != (sector_count, sector_count):
        raise ValueError(
            f"selected IO resolution expects {sector_count} sectors, but the transaction "
            f"block is {frame.shape[0]}x{frame.shape[1]}"
        )
    canonical = [f"{position:02d}" for position in range(1, sector_count + 1)]
    if list(frame.index) == canonical and list(frame.columns) == canonical:
        return frame
    out = frame.copy()
    out.index = canonical
    out.columns = canonical
    return out

def read_io_table(
    path: str | Path,
    sheet_name: str | int = 0,
    expected_sector_count: int | None = None,
) -> pd.DataFrame:
    """Read and validate a square IO transaction table.

    The first column is the row-sector identifier and the remaining column names are
    column-sector identifiers.  Rows are suppliers and columns are users, so a positive
    entry ``z[i,j]`` produces a directed edge ``i -> j``.

    SIGMA intentionally requires the normalized row and column sector *sets* to match
    exactly.  Silently dropping unmatched sectors can change the MWAS objective and therefore
    the selected IO DAG, without an obvious error in the final spatial network.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"IO table does not exist: {path}")

    suffix = path.suffix.lower()
    if expected_sector_count is not None and expected_sector_count not in {16, 80}:
        raise ValueError("expected_sector_count must be None, 16, or 80")

    if suffix in {".xlsx", ".xlsm"}:
        frame = pd.read_excel(path, sheet_name=sheet_name, index_col=0)
        used_presentation = False
        try:
            validated = _validated_transaction_frame(frame)
        except ValueError as strict_error:
            # Formatted publication workbooks are not machine-square tables.  Only invoke
            # structural extraction when a concrete IO16/IO80 size is known; otherwise the
            # strict error is more informative than guessing a matrix size.
            if expected_sector_count is None:
                raise strict_error
            raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
            extracted = _extract_presentation_block(raw, expected_sector_count)
            validated = _validated_transaction_frame(extracted)
            used_presentation = True
        validated = _canonicalize_expected_order(validated, expected_sector_count)
        validated.attrs["source_layout"] = (
            "presentation-published-order" if used_presentation else "clean-square"
        )
        return validated
    elif suffix == ".xls":
        raise ValueError(
            "legacy .xls input is not supported by SIGMA's dependency set; "
            "save the workbook as .xlsx or CSV"
        )
    elif suffix == ".csv":
        frame = pd.read_csv(path, index_col=0)
    elif suffix in {".parquet", ".pq"}:
        frame = pd.read_parquet(path)
        # A Parquet table may have been written without preserving a semantic index.  In
        # that common case, interpret the first column exactly as CSV/Excel do.
        if isinstance(frame.index, pd.RangeIndex):
            if frame.shape[1] < 2:
                raise ValueError("IO Parquet table must include a sector-id column")
            frame = frame.set_index(frame.columns[0])
    else:
        raise ValueError(f"unsupported IO table format: {suffix or '<no suffix>'}")

    validated = _validated_transaction_frame(frame)
    validated = _canonicalize_expected_order(validated, expected_sector_count)
    validated.attrs["source_layout"] = "canonical-or-clean-square"
    return validated

# Total-output / coefficient adapters migrated from sigma-engine.

def _locate_presentation_transaction_block(
    raw: pd.DataFrame,
    sector_count: int,
) -> tuple[int, int, int, int]:
    """Locate the same supplier-user block selected by ``read_io_table``.

    The selection rule intentionally mirrors ``io_dag._extract_presentation_block``:
    matching ordered sector labels must appear horizontally above the numeric block and
    vertically to its left, and the earliest/left-most structurally valid block wins.
    Returning its coordinates lets the total-output reader align ``x`` with the same rows.
    """
    if sector_count < 2:
        raise ValueError("sector_count must be >= 2")
    rows, columns = raw.shape
    if rows < sector_count or columns < sector_count:
        raise ValueError(
            f"worksheet is too small to contain a {sector_count}x{sector_count} transaction block"
        )

    candidates: list[tuple[int, int, int, int]] = []
    max_header_row = rows - sector_count
    max_data_column = columns - sector_count
    for header_row in range(max_header_row + 1):
        for data_column in range(max_data_column + 1):
            horizontal_raw = raw.iloc[
                header_row, data_column : data_column + sector_count
            ].tolist()
            horizontal = [_display_token(value) for value in horizontal_raw]
            if any(token is None for token in horizontal) or len(set(horizontal)) != sector_count:
                continue

            first = horizontal[0]
            for label_column in range(data_column):
                possible_starts = [
                    row
                    for row in range(header_row + 1, rows - sector_count + 1)
                    if _display_token(raw.iat[row, label_column]) == first
                ]
                for data_row in possible_starts:
                    vertical_raw = raw.iloc[
                        data_row : data_row + sector_count, label_column
                    ].tolist()
                    vertical = [_display_token(value) for value in vertical_raw]
                    if vertical != horizontal:
                        continue
                    block = raw.iloc[
                        data_row : data_row + sector_count,
                        data_column : data_column + sector_count,
                    ].apply(pd.to_numeric, errors="coerce")
                    values = block.to_numpy(dtype=float, copy=False)
                    if np.isfinite(values).all():
                        candidates.append(
                            (header_row, data_column, data_row, label_column)
                        )

    if not candidates:
        raise ValueError(
            f"could not locate a {sector_count}x{sector_count} presentation-style IO block"
        )
    candidates.sort()
    return candidates[0]

def read_total_output_vector(
    path: str | Path,
    *,
    sheet_name: str | int = 0,
    sector_ids: list[str] | pd.Index,
) -> pd.Series:
    """Read sector gross output ``x`` from a full presentation-style IO workbook.

    Automatic derivation deliberately requires an explicit ``Total Output`` column in
    the same worksheet as the transaction block. The square packaged/intermediate-only
    matrices do not contain enough information and are never normalized by their column
    sums as a substitute.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"IO transaction table does not exist: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(
            "automatic technical-coefficient derivation currently requires an .xlsx/.xlsm "
            "transaction workbook containing an explicit Total Output column"
        )

    ids = [str(value) for value in sector_ids]
    sector_count = len(ids)
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    header_row, data_column, data_row, _ = _locate_presentation_transaction_block(
        raw, sector_count
    )

    header_candidates: list[int] = []
    for row in range(header_row, data_row):
        for column in range(data_column + sector_count, raw.shape[1]):
            if _display_token(raw.iat[row, column]) == "total output":
                header_candidates.append(column)
    header_candidates = sorted(set(header_candidates))

    valid: list[tuple[int, np.ndarray]] = []
    for column in header_candidates:
        values = pd.to_numeric(
            raw.iloc[data_row : data_row + sector_count, column],
            errors="coerce",
        ).to_numpy(dtype=float)
        if np.isfinite(values).all() and np.all(values > 0):
            valid.append((column, values))

    if not valid:
        raise ValueError(
            "transaction workbook does not expose a usable Total Output column aligned "
            "with the selected IO sector rows; supply the full transaction workbook or "
            "provide --technical-coefficients explicitly"
        )
    if len(valid) > 1:
        columns = [column for column, _ in valid]
        raise ValueError(
            "transaction workbook has multiple usable Total Output columns aligned with "
            f"the IO block at columns {columns}; derivation is ambiguous"
        )

    column, values = valid[0]
    output = pd.Series(values, index=ids, dtype=float, name="total_output")
    output.attrs["source_column_zero_based"] = int(column)
    output.attrs["source_sheet"] = sheet_name
    return output

def derive_technical_coefficients(
    transactions: pd.DataFrame,
    total_output: pd.Series,
) -> pd.DataFrame:
    """Derive ``A_ij = Z_ij / x_j`` using gross output for each user sector."""
    z = transactions.copy()
    if list(z.index) != list(z.columns):
        raise ValueError("transaction matrix axes must be aligned")
    ids = [str(value) for value in z.index]
    z.index = ids
    z.columns = [str(value) for value in z.columns]

    x = pd.Series(total_output, copy=True, dtype=float)
    x.index = [str(value) for value in x.index]
    if x.index.duplicated().any():
        raise ValueError("total-output sector identifiers must be unique")
    if set(x.index) != set(ids):
        only_z = sorted(set(ids) - set(x.index))
        only_x = sorted(set(x.index) - set(ids))
        raise ValueError(
            "transactions and total output must contain exactly the same sectors; "
            f"only in transactions={only_z[:10]}, only in total output={only_x[:10]}"
        )
    x = x.loc[ids]
    values = x.to_numpy(dtype=float, copy=False)
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError("total output must be finite and strictly positive for every sector")

    z_values = z.to_numpy(dtype=float, copy=False)
    if not np.isfinite(z_values).all() or np.any(z_values < 0):
        raise ValueError("transactions must be finite and non-negative")

    coefficients = z.astype(float).div(x, axis="columns")
    a_values = coefficients.to_numpy(dtype=float, copy=False)
    if not np.isfinite(a_values).all() or np.any(a_values < 0):
        raise RuntimeError("derived technical coefficients are not finite and non-negative")
    coefficients.attrs["technical_coefficient_source"] = (
        "derived_from_transaction_total_output"
    )
    return coefficients

def read_technical_coefficients(
    path: str | Path,
    *,
    sheet_name: str | int = 0,
    expected_sector_count: int | None = None,
) -> pd.DataFrame:
    """Read an explicit square technical-coefficient matrix override."""
    coefficients = read_io_table(
        path,
        sheet_name=sheet_name,
        expected_sector_count=expected_sector_count,
    )
    coefficients.attrs["technical_coefficient_source"] = "explicit_matrix"
    return coefficients

#!/usr/bin/env python3
"""Build and validate the permanent national PSA IO240 reference package (patch v3).

Reads the official PSA 2018 240-industry transaction workbook and the 2018 I-O
industry classification workbook, derives the 240-sector economy, reconciles it
with SIGMA's bundled IO80 and IO16 tables, and writes versionable reference files
into this SIGMA source repository.  Per-area economies are always built by
'sigma load'.

v3 changes: line-ending-independent SHA-256 manifest; labels from the versioned
io240_parents.csv; tolerance derived from the published decimals; diagnostics
that locate a failed reconciliation; --replace-existing for older packages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sigma.classification.io_mapping_compat import load_catalog  # noqa: E402
from sigma.economy import Economy  # noqa: E402

PACKAGER_VERSION = "v3"
HASH_NORMALIZATION = "crlf-to-lf"
# PSA's published release, 9 December 2021 (2018 reference year).
BASE = "https://psa.gov.ph/system/files/"
SOURCES = {
    "transactions": [
        BASE + "240-Industry%2520Transaction%2520Table%252C%25202018.xlsx",
        BASE + "240-Industry%20Transaction%20Table%2C%202018.xlsx",
    ],
    "classification": [
        BASE + "2018%2520Input-Output%2520Industry%2520Classification_0.xlsx",
        BASE + "2018%20Input-Output%20Industry%20Classification_0.xlsx",
    ],
}
RELEASE_PAGE = "https://psa.gov.ph/statistics/supply-and-use-input-output/tables"
REFERENCE_FILES = (
    "crosswalk.csv", "economy/economy.yml", "economy/sectors.csv",
    "economy/transactions.csv", "economy/total_output.csv",
)
# Relative criterion kept from v2 (max-relative and L1-relative error).
RELATIVE_TOLERANCE = 2e-7
# Archived October 29 source-economy fingerprint (labels are part of it).
ARCHIVED_FINGERPRINT = "fbca581fa5c40a9f6c5db65559bc0bbb084486394b96de96950583bb57bdc270"

# The verified SIGMA PR #17 IO240 parent table is the ONLY hierarchy source.
N = 240


# ---------------------------------------------------------------------------
# Hashing and writing

def canonical_sha256(payload: bytes) -> str:
    """SHA-256 of text with CRLF/CR normalized to LF (same rule as economy/builtin.py)."""
    return hashlib.sha256(payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def file_sha256(path: Path) -> str:
    """Raw-byte SHA-256, used only for the source workbooks (binary files)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(2 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_lf(path: Path, text: str) -> None:
    """Write UTF-8 with LF line endings on every platform (Path.write_text uses CRLF on Windows)."""
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# Source workbooks

def fetch_xlsx(name: str, target: Path, *, local: Path | None = None) -> None:
    if target.is_file():
        raise RuntimeError(f"Unexpected existing file: {target}; refusing to overwrite")
    if local:
        if not local.is_file():
            raise FileNotFoundError(local)
        print(f"  Copying supplied PSA workbook: {local}", flush=True)
        payload = local.read_bytes()
    else:
        payload = None
        problems = []
        for url in SOURCES[name]:
            try:
                print(f"  Downloading PSA {name} XLSX: {url}", flush=True)
                req = Request(url, headers={"User-Agent": "Mozilla/5.0 SIGMA-reference/1.0",
                                            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"})
                with urlopen(req, timeout=90) as handle:
                    candidate = handle.read(12 * 1024 * 1024 + 1)
                if 10000 < len(candidate) <= 12 * 1024 * 1024 and candidate[:2] == b"PK":
                    payload = candidate
                    break
                problems.append(f"not a valid XLSX payload ({len(candidate)} bytes)")
            except (OSError, HTTPError, URLError) as exc:
                problems.append(f"{type(exc).__name__}: {exc}")
        if payload is None:
            raise RuntimeError(
                f"Could not download the official PSA {name} workbook.\n"
                + "\n".join("  - " + p for p in problems)
                + "\nDownload both workbooks ('240-Industry Transaction Table, 2018' and "
                "'2018 Input-Output Industry Classification') from " + RELEASE_PAGE
                + " and re-run with BOTH --transactions-xlsx PATH and --classification-xlsx PATH."
            )
    if len(payload) < 10000 or payload[:2] != b"PK":
        raise RuntimeError(f"{name} is not a valid XLSX file")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    print(f"  Saved {target.name} ({len(payload):,} bytes)", flush=True)


def _as_code(value: object) -> int | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{1,3}(?:\.0+)?", text):
        return int(float(text))
    return None


def parent_table() -> pd.DataFrame:
    from importlib.resources import files
    ref = files("sigma.resources.classification").joinpath("io", "io240_parents.csv")
    return pd.read_csv(ref, dtype=str, keep_default_na=False)


def crosswalk() -> pd.DataFrame:
    """Use the exact versioned PR #17 parent map, never old range cutpoints."""
    from sigma.classification.reference import load_builtin_io_reference
    from sigma.economy.hierarchical import require_sigma_io80_io16, tagging_consistency

    parents = parent_table()
    if not {"io240_code", "io80_code"}.issubset(parents):
        raise RuntimeError("Current SIGMA PR #17 parent reference is malformed")
    if len(parents) != N or parents.io240_code.duplicated().any():
        raise RuntimeError("Current SIGMA PR #17 parent reference is not a 240-leaf map")
    actual = dict(zip(parents.io240_code, parents.io80_code, strict=True))
    codes = [f"{i:03d}" for i in range(1, N + 1)]
    if set(actual) != set(codes):
        raise RuntimeError("IO240 parent reference is missing or contains unexpected codes")
    canonical = dict(load_builtin_io_reference().io240_parent_map)
    different = [(c, actual.get(c), canonical.get(c)) for c in codes if actual.get(c) != canonical.get(c)]
    if different:
        raise RuntimeError("SIGMA PR #17 IO240 parent map disagrees with its tagging resolver: "
                           + repr(different[:10]))
    catalog = load_catalog()
    if set(actual.values()) != set(catalog) or len(catalog) != 80:
        raise RuntimeError("PR #17 IO240 parents do not cover all 80 industries")
    h = pd.DataFrame({"io240_code": codes, "io80_code": [actual[c] for c in codes]})
    h["io16_code"] = h.io80_code.map(lambda c: catalog[c].io16_code)
    require_sigma_io80_io16(h)
    consistency = tagging_consistency(h)
    if not consistency["consistent"]:
        raise RuntimeError("National IO240 hierarchy conflicts with SIGMA tagging: " + repr(consistency))
    if [h.loc[h.io240_code.eq(f"{i:03d}"), "io80_code"].iat[0] for i in (124, 125, 126)] != ["42"] * 3:
        raise RuntimeError("PSA 2018 IO240 124-126 parent regression detected")
    return h


def _workbook_labels(classification_path: Path) -> dict[str, str]:
    """Heuristic scan of the classification workbook (diagnostic and gap-filling only)."""
    names: dict[str, str] = {}
    try:
        sheets = pd.read_excel(classification_path, sheet_name=None, header=None, dtype=object)
        for raw in sheets.values():
            for c in range(max(0, raw.shape[1] - 1)):
                observed = [v for v in (_as_code(raw.iat[r, c]) for r in range(raw.shape[0]))
                            if v is not None and 1 <= v <= N]
                if len(set(observed)) < 230 or len(observed) > 280:
                    continue
                candidate: dict[str, str] = {}
                for r in range(raw.shape[0]):
                    val = _as_code(raw.iat[r, c])
                    if val is None or not 1 <= val <= N:
                        continue
                    title = raw.iat[r, c + 1]
                    if pd.notna(title) and isinstance(title, str) and len(title.strip()) >= 3:
                        candidate[f"{val:03d}"] = " ".join(title.split())
                if len(candidate) > len(names):
                    names = candidate
    except Exception as exc:  # labels never block the build
        print(f"  Classification descriptions could not be read: {exc}", flush=True)
    return names


def industry_labels(classification_path: Path) -> tuple[list[str], dict]:
    """Labels WITHOUT a code prefix, deterministic first.

    Priority: SIGMA's versioned io240_parents.csv names, then the official
    workbook, then SIGMA's concordance names, then a neutral code name.  The
    hierarchy builder adds 'IO240 <code> ·' itself, so a prefix here would repeat
    the code.  Labels are part of the economy fingerprint, which is why the
    versioned names come first.
    """
    parents = parent_table()
    versioned = {c: " ".join(n.split()) for c, n in zip(parents.io240_code, parents.io240_name) if n.strip()}
    workbook = _workbook_labels(classification_path)
    concordance: dict[str, str] = {}
    try:
        from sigma.classification.reference import load_builtin_io_reference
        for row in load_builtin_io_reference().concordance:
            for code, label in zip(row.io240_codes, row.io240_names, strict=False):
                if code and label:
                    concordance.setdefault(str(code).zfill(3), str(label).strip())
    except Exception as exc:
        print(f"  SIGMA concordance label fallback unavailable: {exc}", flush=True)
    codes = [f"{i:03d}" for i in range(1, N + 1)]
    labels, sources = [], {"io240_parents.csv": 0, "workbook": 0, "concordance": 0, "neutral": 0}
    for code in codes:
        for source, table in (("io240_parents.csv", versioned), ("workbook", workbook), ("concordance", concordance)):
            if table.get(code):
                labels.append(table[code])
                sources[source] += 1
                break
        else:
            labels.append(f"2018 IO240 industry {code}")
            sources["neutral"] += 1
    # SectorCatalog requires unique labels; disambiguate any repeated name by its code.
    repeated = {label for label in labels if labels.count(label) > 1}
    labels = [f"{label} ({code})" if label in repeated else label for label, code in zip(labels, codes)]
    key = lambda s: " ".join(s.casefold().split())  # noqa: E731
    differ = sorted(c for c in versioned if c in workbook and key(versioned[c]) != key(workbook[c]))
    return labels, {"label_sources": sources, "workbook_label_differences": len(differ),
                    "workbook_label_difference_codes": differ[:40]}


def official_classification_links(path: Path) -> dict[str, str]:
    """Extract 240->80 nesting when the classification workbook uses a nested layout.

    Cross-check only; never derive a parent from the names of sectors.
    """
    best: dict[str, str] = {}
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
        for raw in sheets.values():
            for child_col in range(2, raw.shape[1]):
                codes = [_as_code(v) for v in raw.iloc[:, child_col]]
                if len({x for x in codes if x is not None and 1 <= x <= 240}) < 230:
                    continue
                for parent_col in range(max(0, child_col - 4), child_col):
                    parent = None
                    mapping: dict[str, str] = {}
                    for r, child in enumerate(codes):
                        raw_parent = _as_code(raw.iat[r, parent_col])
                        if raw_parent is not None and 1 <= raw_parent <= 80:
                            parent = raw_parent
                        if child is not None and 1 <= child <= 240 and parent is not None:
                            mapping[f"{child:03d}"] = f"{parent:02d}"
                    if len(mapping) > len(best) and len(set(mapping.values())) >= 70:
                        best = mapping
    except Exception as exc:
        print(f"  Could not parse published classification links: {exc}", flush=True)
    return best


# ---------------------------------------------------------------------------
# Numerical reconciliation

def decimals(values: np.ndarray, max_decimals: int = 9) -> int | None:
    """Smallest d such that every nonzero value is a multiple of 10**-d.

    None means no such d up to ``max_decimals``: the table is not rounded to a
    fixed number of decimals (for example, values computed in a spreadsheet).
    """
    v = np.asarray(values, dtype=float).ravel()
    v = v[np.isfinite(v) & (v != 0)]
    if v.size == 0:
        return 0
    for d in range(0, max_decimals + 1):
        scaled = v * 10.0 ** d
        if float(np.abs(scaled).max()) > 1e15:
            return None  # beyond float precision: the test can no longer tell
        # Float representation error of v*10^d is about 1e-16*|v*10^d|.
        if np.all(np.abs(scaled - np.round(scaled)) <= 1e-6 + 1e-14 * np.abs(scaled)):
            return d
    return None


def _relative_error(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    err = np.abs(a - b)
    return (float(err.max() / max(float(np.abs(b).max()), 1.0)),
            float(err.sum() / max(float(np.abs(b).sum()), 1.0)))


def _membership(h: pd.DataFrame, resolution: str) -> tuple[np.ndarray, list[str]]:
    parents = [f"{i:02d}" for i in range(1, 81 if resolution == "io80" else 17)]
    m = np.zeros((len(parents), N), dtype=np.float64)
    for index, code in enumerate(h[f"{resolution}_code"]):
        m[int(code) - 1, index] = 1.0
    return m, parents


def reconcile(aggregated: np.ndarray, reference: np.ndarray, children: np.ndarray, *,
              source_decimals: int | None, reference_decimals: int | None,
              codes: list[str], what: str) -> dict:
    """Accept an aggregation if EITHER criterion holds.

    1. Relative (v2): max-relative and L1-relative error both <= 2e-7.
    2. Rounding envelope: every cell difference is at most the error that the
       published rounding can produce, i.e. 0.5*10^-d for each source cell summed
       into it (children_i * children_j cells for a matrix, children_i for a
       vector), plus 0.5*10^-d_ref for the reference cell, plus float noise.
       Applies only when the source is rounded to a fixed number of decimals.

    A wrong parent link moves a whole sector's values and exceeds both, unless the
    sector is smaller than the rounding envelope.
    """
    aggregated = np.asarray(aggregated, float)
    reference = np.asarray(reference, float)
    diff = aggregated - reference
    max_rel, l1_rel = _relative_error(aggregated, reference)
    relative_ok = max_rel <= RELATIVE_TOLERANCE and l1_rel <= RELATIVE_TOLERANCE
    noise = 1e-10 * max(float(np.abs(reference).max()), 1.0)
    unit_ref = 0.5 * 10.0 ** -reference_decimals if reference_decimals is not None else 0.0
    if source_decimals is not None:
        unit = 0.5 * 10.0 ** -source_decimals
        cells = np.outer(children, children) if diff.ndim == 2 else np.asarray(children, float)
        envelope = cells * unit + unit_ref + noise
        envelope_ok = bool(np.all(np.abs(diff) <= envelope))
        worst_ratio = float(np.max(np.abs(diff) / envelope))
    else:
        envelope_ok, worst_ratio = False, None
    accepted = relative_ok or envelope_ok
    result = {
        "what": what, "accepted": bool(accepted),
        "criterion": ("relative" if relative_ok else "rounding_envelope" if envelope_ok else "none"),
        "max_relative_error": max_rel, "l1_relative_error": l1_rel,
        "relative_tolerance": RELATIVE_TOLERANCE,
        "source_decimals": source_decimals, "reference_decimals": reference_decimals,
        "worst_difference_over_envelope": worst_ratio,
        "max_absolute_difference": float(np.abs(diff).max()),
    }
    if not accepted:
        result["diagnosis"] = diagnose(aggregated, reference, codes)
    return result


def diagnose(aggregated: np.ndarray, reference: np.ndarray, codes: list[str]) -> str:
    """Describe WHERE an aggregation fails, to separate likely causes."""
    diff = aggregated - reference
    lines = []
    total_ref = float(np.abs(reference).sum())
    ratio = float(aggregated.sum() / reference.sum()) if reference.sum() else float("nan")
    if math.isfinite(ratio) and ratio > 0:
        power = math.log10(ratio)
        if abs(power - round(power)) < 0.01 and round(power) != 0:
            lines.append(f"Totals differ by a factor of about 10^{round(power)}: likely a unit difference "
                         "(for example thousand vs million pesos). The packager does not rescale.")
    abs_diff = np.abs(diff)
    if diff.ndim == 2:
        rows = abs_diff.sum(axis=1)
        cols = abs_diff.sum(axis=0)
        total = float(abs_diff.sum()) or 1.0
        top_rows = np.argsort(rows)[::-1][:5]
        top_cols = np.argsort(cols)[::-1][:5]
        share2 = float((rows[top_rows[:2]].sum()) / total)
        lines.append("Rows with the largest differences (IO80 code: sum |diff|): "
                     + ", ".join(f"{codes[i]}: {rows[i]:.6g}" for i in top_rows))
        lines.append("Columns with the largest differences: "
                     + ", ".join(f"{codes[i]}: {cols[i]:.6g}" for i in top_cols))
        flat = np.argsort(abs_diff.ravel())[::-1][:5]
        lines.append("Largest cells (row, column, aggregated, reference): " + "; ".join(
            f"({codes[k // len(codes)]}, {codes[k % len(codes)]}, {aggregated.ravel()[k]:.6g}, {reference.ravel()[k]:.6g})"
            for k in flat))
        if share2 >= 0.5:
            lines.append(f"{share2:.0%} of the total difference is in two rows: this pattern fits a wrong "
                         "IO240 -> IO80 parent link (values counted under the wrong parent).")
        else:
            lines.append(f"The two largest rows hold only {share2:.0%} of the total difference: this pattern "
                         "fits rounding or a different table version rather than one wrong link.")
    else:
        top = np.argsort(abs_diff)[::-1][:5]
        lines.append("Sectors with the largest differences (code, aggregated, reference): " + "; ".join(
            f"({codes[i]}, {aggregated[i]:.6g}, {reference[i]:.6g})" for i in top))
    lines.append(f"Total absolute difference: {float(abs_diff.sum()):.6g} against a reference total of {total_ref:.6g}.")
    return "\n    ".join(lines)


def _children(h: pd.DataFrame, resolution: str, parents: list[str]) -> np.ndarray:
    counts = h[f"{resolution}_code"].value_counts()
    return np.array([int(counts.get(p, 0)) for p in parents], dtype=float)


def check_against_builtins(h: pd.DataFrame, z: np.ndarray, x: np.ndarray, *,
                           z_decimals: int | None, x_decimals: int | None, label: str) -> dict:
    results = {}
    for resolution in ("io80", "io16"):
        base = Economy.builtin(resolution)
        m, parents = _membership(h, resolution)
        kids = _children(h, resolution, parents)
        ref_z = base.Z_raw.to_numpy(float)
        ref_x = base.x.to_numpy(float)
        rz = reconcile(m @ z @ m.T, ref_z, kids, source_decimals=z_decimals,
                       reference_decimals=decimals(ref_z), codes=parents,
                       what=f"{label} transactions vs {resolution.upper()}")
        rx = reconcile(m @ x, ref_x, kids, source_decimals=x_decimals,
                       reference_decimals=decimals(ref_x), codes=parents,
                       what=f"{label} gross output vs {resolution.upper()}")
        for result in (rz, rx):
            if not result["accepted"]:
                raise RuntimeError(
                    f"{result['what']} does NOT reconcile (max relative {result['max_relative_error']:.3g}, "
                    f"L1 relative {result['l1_relative_error']:.3g}, source decimals {result['source_decimals']}).\n"
                    f"    {result['diagnosis']}\n"
                    "Rejecting dataset. Do not change PR #17 parent links or rescale the matrix to make it pass."
                )
        results[resolution] = {"transactions": rz, "total_output": rx}
    return results


# ---------------------------------------------------------------------------
# Worksheet extraction

def _clean_numeric(raw: pd.DataFrame, *, allow_blank_zero: bool = False) -> np.ndarray:
    # A literal hyphen in a PSA published table is a zero.  Unexplained text
    # becomes NaN and is rejected by the caller; it is never turned into zero.
    dash = raw.isin(["-", "–", "—"])
    clean = raw.mask(dash, 0)
    blank = clean.isna()
    values = clean.apply(pd.to_numeric, errors="coerce")
    invalid = values.isna() & ~blank
    if invalid.to_numpy().any():
        return values.to_numpy(dtype=float)
    if allow_blank_zero:
        values = values.fillna(0)
    return values.to_numpy(dtype=float)


def _locate_relaxed_block(raw: pd.DataFrame) -> tuple[int, int, int, int]:
    """Fallback locator for a PSA sheet containing blank/dash zero cells.

    Locating is not accepting: reconciliation with IO80/IO16 decides acceptance.
    """
    from sigma.economy.io_utils import _display_token
    rows, columns = raw.shape
    limit_row = min(65, rows - N)
    limit_col = min(35, columns - N)
    for header_row in range(limit_row + 1):
        for data_col in range(limit_col + 1):
            labels = [_display_token(v) for v in raw.iloc[header_row, data_col:data_col + N]]
            if any(x is None for x in labels) or len(set(labels)) != N:
                continue
            for label_col in range(min(data_col, 16)):
                for data_row in range(header_row + 1, min(header_row + 35, rows - N + 1)):
                    row_labels = [_display_token(v) for v in raw.iloc[data_row:data_row + N, label_col]]
                    if row_labels == labels:
                        return header_row, data_col, data_row, label_col
    raise ValueError("No ordered matching 240 sector axes found in the transaction workbook")


def _numeric_sweep(raw: pd.DataFrame, group80: np.ndarray, expected: np.ndarray) -> tuple[int, int, int, int]:
    """Last-resort locator when the row and column captions differ.

    A position is LOCATED when its 240x240 values aggregate to within 1e-3 (L1
    relative) of SIGMA's IO80 matrix; a wrong offset gives errors of order 1.
    Acceptance is decided afterwards by the full reconciliation.
    """
    rows, cols = raw.shape
    if rows < N or cols < N:
        raise ValueError("sheet smaller than a 240x240 matrix")
    empty = raw.isna() | raw.isin(["", "-", "–", "—"])
    nums = raw.mask(raw.isin(["-", "–", "—"]), 0).apply(pd.to_numeric, errors="coerce")
    invalid = nums.isna() & ~empty
    bad = invalid.to_numpy(dtype=np.int64)
    prefix = np.pad(bad, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    nums = nums.fillna(0).to_numpy(dtype=float)
    pair = (group80[:, None] * 80 + group80[None, :]).ravel()
    best_error = (float("inf"), float("inf"))
    for r in range(min(rows - N, 75) + 1):
        for c in range(min(cols - N, 55) + 1):
            illegal = prefix[r + N, c + N] - prefix[r, c + N] - prefix[r + N, c] + prefix[r, c]
            if illegal:
                continue
            block = nums[r:r + N, c:c + N]
            if not np.isfinite(block).all() or (block < 0).any():
                continue
            grouped = np.bincount(pair, weights=block.ravel(), minlength=80 * 80).reshape((80, 80))
            err = _relative_error(grouped, expected)
            best_error = min(best_error, err)
            if err[1] <= 1e-3:
                return max(0, r - 1), c, r, max(0, c - 1)
    raise ValueError(f"no 240x240 numeric region aggregates close to SIGMA IO80; best relative error {best_error}")


def extract_transactions_and_output(path: Path, h: pd.DataFrame, *, io80: Economy) -> tuple[np.ndarray, np.ndarray, dict]:
    """Locate the published 240x240 intermediate-demand block and gross output.

    Read-only extraction: no guessed gross-output vector, scaling factor or
    manual sector reordering.  Acceptance is decided by check_against_builtins.
    """
    from sigma.economy.io_utils import _locate_presentation_transaction_block
    m, _ = _membership(h, "io80")
    ref_z = io80.Z_raw.to_numpy(dtype=float)
    ref_x = io80.x.to_numpy(dtype=float)
    problems = []
    best = None
    parent_ids = h.io80_code.astype(int).to_numpy() - 1
    for sheet, raw in pd.read_excel(path, sheet_name=None, header=None, dtype=object).items():
        located = None
        for locator in ("presentation", "relaxed", "numeric"):
            try:
                if locator == "presentation":
                    located = _locate_presentation_transaction_block(raw, N)
                elif locator == "relaxed":
                    located = _locate_relaxed_block(raw)
                else:
                    located = _numeric_sweep(raw, parent_ids, ref_z)
            except (ValueError, IndexError) as exc:
                if locator == "numeric":
                    problems.append(f"sheet {sheet!r}: {exc}")
                continue
            header_row, data_col, data_row, label_col = located
            z = _clean_numeric(raw.iloc[data_row:data_row + N, data_col:data_col + N], allow_blank_zero=True)
            if z.shape == (N, N) and np.isfinite(z).all() and not np.any(z < 0):
                break
            problems.append(f"sheet {sheet!r}: {locator} locator found an invalid 240x240 block")
            located = None
        if located is None:
            continue
        dz = _relative_error(m @ z @ m.T, ref_z)
        print(f"  Sheet {sheet!r} ({locator} locator): IO80 transaction max relative={dz[0]:.3g}; "
              f"L1 relative={dz[1]:.3g}", flush=True)
        if best is None or dz < best[0]:
            best = (dz, sheet, raw, z, header_row, data_col, data_row, label_col)
    if best is None:
        raise RuntimeError("Could not extract a valid 240x240 transaction table.\n" + "\n".join(problems))
    dz, sheet, raw, z, header_row, data_col, data_row, label_col = best
    number = _clean_numeric(raw)
    candidates: list[tuple[float, float, np.ndarray, str]] = []
    for c in range(data_col + N, raw.shape[1]):
        values = number[data_row:data_row + N, c]
        if len(values) == N and np.isfinite(values).all() and np.all(values > 0):
            score = _relative_error(m @ values, ref_x)
            title = " ".join(str(raw.iat[r, c]) for r in range(max(0, header_row - 2), data_row) if pd.notna(raw.iat[r, c]))
            candidates.append((score[0], score[1], values, f"column {c + 1}, {title[:60]}"))
    for r in range(data_row + N, raw.shape[0]):
        values = number[r, data_col:data_col + N]
        if len(values) == N and np.isfinite(values).all() and np.all(values > 0):
            score = _relative_error(m @ values, ref_x)
            title = " ".join(str(raw.iat[r, c]) for c in range(label_col, data_col) if pd.notna(raw.iat[r, c]))
            candidates.append((score[0], score[1], values, f"row {r + 1}, {title[:60]}"))
    if not candidates:
        raise RuntimeError("No positive total-output vector found in the transaction sheet. "
                           "The output vector must come from PSA, not column sums of transactions.")
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, _, output, source = candidates[0]
    print(f"  Gross output candidate: {source}", flush=True)
    return z, output, {"workbook_sheet": str(sheet), "data_row_1based": data_row + 1,
                       "data_column_1based": data_col + 1, "output_location": source}


def verify_serialized_economy(original: Economy, serialized: Economy) -> None:
    """Validate the persisted economy without requiring bit-identical CSV floats."""
    for field in ("economy_id", "label", "version", "reference_year"):
        if getattr(original, field) != getattr(serialized, field):
            raise RuntimeError(f"Serialized economy changed {field}: "
                               f"{getattr(original, field)!r} -> {getattr(serialized, field)!r}")
    if original.sectors.codes != serialized.sectors.codes:
        raise RuntimeError("Serialized economy changed sector codes or their order")
    if original.sectors.labels != serialized.sectors.labels:
        raise RuntimeError("Serialized economy changed sector descriptions")
    for field, source, saved in (
        ("transactions", original.Z_raw.to_numpy(float), serialized.Z_raw.to_numpy(float)),
        ("total output", original.x.to_numpy(float), serialized.x.to_numpy(float)),
    ):
        if source.shape != saved.shape or not np.allclose(source, saved, rtol=5e-14, atol=1e-9, equal_nan=False):
            error = np.abs(source - saved)
            max_diff = float(error.max()) if source.shape == saved.shape else float("nan")
            raise RuntimeError(f"Serialized economy changed {field} beyond CSV precision "
                               f"(max absolute difference: {max_diff:.12g})")


# ---------------------------------------------------------------------------
# Existing package

def verify_existing(root: Path) -> None:
    final_economy, final_crosswalk = root / "economy", root / "crosswalk.csv"
    if not final_economy.is_dir() or not final_crosswalk.is_file():
        raise RuntimeError("Partially populated reference exists; inspect it before retrying: " + str(root))
    audit_path = root / "validation.json"
    if not audit_path.is_file():
        raise RuntimeError("Existing national IO240 package lacks validation.json")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("packager_version") != PACKAGER_VERSION or audit.get("hash_normalization") != HASH_NORMALIZATION:
        raise RuntimeError(
            "Existing national IO240 package was written by an older packager (raw-byte hashes and "
            "code-prefixed labels). Re-run with --replace-existing and both workbook paths to rebuild it."
        )
    saved = audit.get("reference_files_sha256")
    if not isinstance(saved, dict) or set(saved) != set(REFERENCE_FILES):
        raise RuntimeError("Existing national IO240 package has an incomplete hash manifest")
    for filename, expected in saved.items():
        if canonical_sha256((root / filename).read_bytes()) != expected:
            raise RuntimeError(f"Existing national IO240 file changed: {filename}")
    e = Economy.from_directory(final_economy)
    current = pd.read_csv(final_crosswalk, dtype=str, keep_default_na=False)
    expected_h = crosswalk()
    if not current[list(expected_h.columns)].equals(expected_h):
        raise RuntimeError("Existing crosswalk differs from verified PSA hierarchy; refusing to reuse it")
    if len(e.sectors) != N or e.x is None:
        raise RuntimeError("Existing national IO240 economy is incomplete")
    z, x = e.Z_raw.to_numpy(float), e.x.to_numpy(float)
    check_against_builtins(current, z, x, z_decimals=decimals(z), x_decimals=decimals(x), label="existing IO240")


# ---------------------------------------------------------------------------
# Build

def run(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve()
    if not (repo / "src" / "sigma" / "cli.py").is_file():
        raise RuntimeError(f"Not a SIGMA repository: {repo}")
    root = repo / "src" / "sigma" / "resources" / "economy" / "psa_2018_io240"
    root.mkdir(parents=True, exist_ok=True)
    source_dir = Path(args.workbook_dir)
    transaction_path = source_dir / "240-Industry Transaction Table, 2018.xlsx"
    classification_path = source_dir / "2018 Input-Output Industry Classification.xlsx"
    print(f"SIGMA reference directory: {root}", flush=True)

    final_economy = root / "economy"
    final_crosswalk = root / "crosswalk.csv"
    final_audit = root / "validation.json"
    exists = final_economy.exists() or final_crosswalk.exists() or final_audit.exists()
    if exists and not args.replace_existing:
        verify_existing(root)
        print("  Existing IO240 economy and canonical crosswalk verified. Reusing unchanged.", flush=True)
        print("\nNational IO240 resource package is ready to commit to SIGMA Git.", flush=True)
        return

    fetch_xlsx("transactions", transaction_path, local=args.transactions_xlsx)
    fetch_xlsx("classification", classification_path, local=args.classification_xlsx)
    h = crosswalk()
    official_links = official_classification_links(classification_path)
    if len(official_links) == 240:
        actual = dict(zip(h.io240_code, h.io80_code, strict=True))
        conflicts = [(k, v, actual[k]) for k, v in official_links.items() if actual.get(k) != v]
        if conflicts:
            raise RuntimeError(f"Official PSA classification disagrees with the embedded IO240->IO80 "
                               f"hierarchy for {len(conflicts)} industries: {conflicts[:12]}")
        print("  Official classification workbook confirms all 240 IO240->IO80 links", flush=True)
    else:
        print("  Note: classification workbook could not independently confirm all parent links; "
              "IO80/IO16 matrix reconciliation remains mandatory.", flush=True)
    codes = h.io240_code.tolist()
    sector_names, label_report = industry_labels(classification_path)
    print(f"  Labels: {label_report['label_sources']}; workbook names differing from "
          f"io240_parents.csv: {label_report['workbook_label_differences']}", flush=True)
    io80 = Economy.builtin("io80")
    z, x, details = extract_transactions_and_output(transaction_path, h, io80=io80)
    z_dec, x_dec = decimals(z), decimals(x)
    print(f"  Published decimals: transactions={z_dec}, gross output={x_dec} "
          "(None = not rounded to a fixed number of decimals)", flush=True)
    checks = check_against_builtins(h, z, x, z_decimals=z_dec, x_decimals=x_dec, label="PSA IO240")
    for resolution, pair in checks.items():
        for name, result in pair.items():
            print(f"  {resolution.upper()} {name}: accepted by {result['criterion']} "
                  f"(max rel {result['max_relative_error']:.3g}, L1 rel {result['l1_relative_error']:.3g})", flush=True)
    if any(not math.isfinite(float(v)) or v <= 0 for v in x):
        raise RuntimeError("Invalid PSA gross output vector")

    from sigma.economy import Sector, SectorCatalog
    catalog = SectorCatalog(Sector(code, label) for code, label in zip(codes, sector_names, strict=True))
    model = Economy(economy_id="psa-2018-io240", sectors=catalog,
                    raw_transactions=pd.DataFrame(z, index=codes, columns=codes),
                    total_output=pd.Series(x, index=codes, name="total_output"),
                    label="Philippine PSA 2018 240-industry input-output economy",
                    version="2018", reference_year=2018,
                    provenance={"source_kind": "psa_official_2018_io240", "source_url": RELEASE_PAGE,
                                "transactions_xlsx_sha256": file_sha256(transaction_path),
                                "classification_xlsx_sha256": file_sha256(classification_path)})
    stage = root / (".stage-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        e_dir = stage / "economy"
        e_dir.mkdir()
        pd.DataFrame({"code": codes, "label": list(catalog.labels)}).to_csv(
            e_dir / "sectors.csv", index=False, lineterminator="\n")
        model.Z_raw.to_csv(e_dir / "transactions.csv", index_label="sector", float_format="%.17g", lineterminator="\n")
        model.x.rename_axis("sector").reset_index().to_csv(
            e_dir / "total_output.csv", index=False, float_format="%.17g", lineterminator="\n")
        metadata = {"id": model.economy_id, "label": model.label, "version": "2018", "reference_year": 2018,
                    "sectors": "sectors.csv", "transactions": "transactions.csv", "total_output": "total_output.csv",
                    "provenance": dict(model.provenance)}
        write_text_lf(e_dir / "economy.yml", yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False))
        h.to_csv(stage / "crosswalk.csv", index=False, lineterminator="\n")
        roundtrip = Economy.from_directory(e_dir)
        verify_serialized_economy(model, roundtrip)
        # Reconcile the persisted (not merely in-memory) tables with both resolutions.
        zr, xr = roundtrip.Z_raw.to_numpy(float), roundtrip.x.to_numpy(float)
        persisted = check_against_builtins(h, zr, xr, z_decimals=z_dec, x_decimals=x_dec, label="persisted IO240")
        if Economy.from_directory(e_dir).economy_fingerprint != roundtrip.economy_fingerprint:
            raise RuntimeError("Saved SIGMA Economy fingerprint is not reproducible")
        if roundtrip.economy_fingerprint != ARCHIVED_FINGERPRINT:
            print("  Note: the archived October 29 economy fingerprint differs. Labels are part of that "
                  "fingerprint, so this alone does not mean the numbers differ; component fingerprints "
                  "are recorded in validation.json. Exact historical replay is NOT established.", flush=True)
        audit = {
            "packager_version": PACKAGER_VERSION,
            "hash_normalization": HASH_NORMALIZATION,
            "psa_source": RELEASE_PAGE,
            "transaction_workbook_sha256": file_sha256(transaction_path),
            "classification_workbook_sha256": file_sha256(classification_path),
            "io240_matrix_shape": [N, N], "crosswalk_rows": len(h),
            "published_decimals": {"transactions": z_dec, "total_output": x_dec},
            "reconciliation": checks, "persisted_reconciliation": persisted,
            "labels": label_report,
            "fingerprints": {"economy": roundtrip.economy_fingerprint,
                             "sector": roundtrip.sector_fingerprint,
                             "transactions": roundtrip.transaction_fingerprint,
                             "total_output": roundtrip.output_fingerprint,
                             "archived_2026_10_29_economy": ARCHIVED_FINGERPRINT},
            **details,
        }
        audit["reference_files_sha256"] = {name: canonical_sha256((stage / name).read_bytes())
                                           for name in REFERENCE_FILES}
        audit_path = stage / "validation.json"
        write_text_lf(audit_path, json.dumps(audit, indent=2, sort_keys=True, default=float) + "\n")
        publish(stage, root, [(e_dir, final_economy), (stage / "crosswalk.csv", final_crosswalk),
                              (audit_path, final_audit)], replace_existing=args.replace_existing)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print(f"  Verified IO240 economy saved: {final_economy}", flush=True)
    print(f"  Complete crosswalk saved: {final_crosswalk}", flush=True)
    print("\nNational IO240 resource package is ready to commit to SIGMA Git.", flush=True)
    print("  Package:", root, flush=True)
    print("  Review and git-add the packaged IO240 files (and .gitattributes), then commit.", flush=True)


def publish(stage: Path, root: Path, items: list[tuple[Path, Path]], *, replace_existing: bool) -> None:
    """Move validated files into place; restore the previous package on any failure."""
    backup = stage / "previous"
    backup.mkdir()
    moved: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        present = [target for _, target in items if target.exists()]
        if present and not replace_existing:
            raise RuntimeError("Reference appeared during build; refusing to overwrite")
        for target in present:
            kept = backup / target.name
            target.rename(kept)
            moved.append((kept, target))
        for original, target in items:
            original.rename(target)
            published.append(target)
    except BaseException:
        for target in reversed(published):
            if target.is_dir():
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
        for kept, target in reversed(moved):
            kept.rename(target)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1], help="SIGMA repository root")
    parser.add_argument("--transactions-xlsx", type=Path, help="Official PSA '240-Industry Transaction Table, 2018' XLSX")
    parser.add_argument("--classification-xlsx", type=Path, help="Official PSA '2018 Input-Output Industry Classification' XLSX")
    parser.add_argument("--replace-existing", action="store_true",
                        help="Rebuild and replace an existing package (for example one written by patch v2)")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="sigma-io240-source-") as working:
            args.workbook_dir = working
            run(args)
    except Exception as exc:
        print(f"\nSETUP NOT COMPLETED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

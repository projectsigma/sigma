"""Per-workspace economic-model selection recorded by ``sigma load``.

A fixed resolution (16, 80 or 240) is a view of an immutable national economy; it
is NOT a hierarchical partition.  A hierarchical selection records the identity of
the profile used at load time, so a later change of settings is reported instead
of being adopted silently by ``sigma run``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, NamedTuple

import geopandas as gpd
import pandas as pd

from sigma.economy import Economy
from sigma.economy.hierarchical import _file_sha256
from sigma.errors import EconomyValidationError


SCHEMA_VERSION = 2
READABLE_SCHEMAS = (1, 2)          # 1 = written by patch v2 (no profile identity)
CLI_IO_LEVELS = ("hierarchical", "16", "80", "240")
SUPPORTED_IO_LEVELS = (*CLI_IO_LEVELS, "custom")
_BUILTIN_SPECS = {"io16", "io80", "builtin:io16", "builtin:io80", "psa-2018-io16", "psa-2018-io80"}


class FixedPreview(NamedTuple):
    path: Path
    assigned: int
    total: int

    @property
    def coverage(self) -> dict[str, Any]:
        share = (self.assigned / self.total) if self.total else 0.0
        return {"assigned_places": self.assigned, "total_places": self.total, "assigned_share": share}


def selection_path(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve() / "economy-selection.json"


def read_selection(workspace: str | Path) -> dict | None:
    path = selection_path(workspace)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema_version") not in READABLE_SCHEMAS
            or data.get("io_level") not in SUPPORTED_IO_LEVELS):
        raise EconomyValidationError(f"invalid or obsolete economic selection: {path}")
    return data


def _write_json_atomic(target: Path, payload: dict) -> None:
    temp = target.with_name(target.name + ".tmp")
    temp.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(temp, target)


def write_selection(
    workspace: str | Path,
    level: str,
    *,
    economy: Economy | None = None,
    economy_spec: str | None = None,
    profile_identity: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
) -> Path:
    if level not in SUPPORTED_IO_LEVELS:
        raise ValueError(f"invalid IO level: {level}")
    root = Path(workspace).expanduser().resolve()
    source = root / "places" / "places.parquet"
    if not source.is_file():
        raise FileNotFoundError(source)
    if level == "custom" and (not economy_spec or economy is None):
        raise EconomyValidationError("custom selection requires an explicit economy")
    if level == "custom" and economy_spec.casefold().strip() not in _BUILTIN_SPECS:
        # The CLI accepted the path relative to its current directory; persist an
        # absolute path so later runs from elsewhere select the same model.
        economy_spec = str(Path(economy_spec).expanduser().resolve())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "io_level": level,
        "places_sha256": _file_sha256(source),
        "economy_fingerprint": economy.economy_fingerprint if economy is not None else None,
        "economy_spec": economy_spec if level == "custom" else None,
        "profile_identity": profile_identity if level == "hierarchical" else None,
        "coverage": coverage,
    }
    target = selection_path(root)
    _write_json_atomic(target, payload)
    return target


# ---------------------------------------------------------------------------
# Hierarchical profile identity

def profile_identity(profile: dict[str, Any]) -> dict[str, Any]:
    """Settings and inputs that determine an area's hierarchical typology."""
    policy = profile.get("coarse_policy", "residual")
    crosswalk = Path(profile["crosswalk"]).expanduser().resolve()
    source = Economy.from_directory(Path(profile["io240_dir"]).expanduser().resolve())
    return {
        "coarse_policy": policy,
        "min_places": int(profile["min_places"]),
        # Only the containment rule uses the straddle share.
        "max_straddle_share": float(profile.get("max_straddle_share", 0.25)) if policy == "contain" else None,
        "crosswalk_sha256": _file_sha256(crosswalk),
        "source_economy_fingerprint": source.economy_fingerprint,
        # Informational only (not compared): where the profile came from.
        "profile_source": str(profile.get("_source", "")),
    }


_COMPARED = ("coarse_policy", "min_places", "max_straddle_share", "crosswalk_sha256",
             "source_economy_fingerprint")


def identity_differences(recorded: dict[str, Any], current: dict[str, Any]) -> list[str]:
    changes = []
    for key in _COMPARED:
        if recorded.get(key) != current.get(key):
            before, after = recorded.get(key), current.get(key)
            if key in ("crosswalk_sha256", "source_economy_fingerprint"):
                before = str(before)[:12] if before else before
                after = str(after)[:12] if after else after
            changes.append(f"{key}: {before} -> {after}")
    return changes


def update_profile_identity(workspace: str | Path, identity: dict[str, Any]) -> None:
    """Record that the area's outputs were deliberately rebuilt with new settings."""
    record = read_selection(workspace)
    if record is None or record["io_level"] != "hierarchical":
        return
    record["schema_version"] = SCHEMA_VERSION
    record["profile_identity"] = identity
    _write_json_atomic(selection_path(workspace), record)


# ---------------------------------------------------------------------------
# Fixed national resolutions

def build_fixed_preview(workspace: str | Path, level: str, economy: Economy) -> FixedPreview:
    """Materialize exact 16/80/240 tagging; never pretend coarse tags are IO240."""
    if level not in ("16", "80", "240"):
        raise ValueError("fixed level must be 16, 80, or 240")
    root = Path(workspace).expanduser().resolve()
    source = root / "places" / "places.parquet"
    if not source.is_file():
        raise FileNotFoundError(source)
    frame = gpd.read_parquet(source)
    col = f"io{level}_code"
    if col not in frame:
        raise EconomyValidationError(f"loaded places have no {col}; rerun 'sigma load'")
    valid = set(economy.sectors.codes)
    raw = frame[col].astype("string").str.strip()
    mapped = raw.where(raw.isin(valid), pd.NA).astype("string")
    # Invalid non-empty codes are not safely equivalent to unresolved values.
    bad = raw.notna() & raw.ne("") & ~raw.isin(valid)
    if bool(bad.any()):
        raise EconomyValidationError(
            f"{col} has {int(bad.sum())} codes outside the requested IO{level} economy; "
            "refusing to publish a mismatched classification"
        )
    frame = frame.copy()
    frame["economy_code"] = mapped
    labels = {item.code: item.label for item in economy.sectors}
    frame["economy_label"] = mapped.map(labels).astype("string")
    status_col, source_col = f"io{level}_status", f"io{level}_source"
    frame["economy_status"] = (
        frame[status_col].astype("string") if status_col in frame else
        mapped.map(lambda c: f"IO{level}" if pd.notna(c) else "UNRESOLVED").astype("string")
    )
    frame["economy_source"] = (
        frame[source_col].astype("string") if source_col in frame else
        mapped.map(lambda c: "fixed_io" if pd.notna(c) else "").astype("string")
    )
    out_dir = root / "fixed-io" / level
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "places.parquet"
    temporary = out_dir / "places.tmp.parquet"
    try:
        frame.to_parquet(temporary, index=False)
        # Validate published codes before replacing the last good preview.
        check = gpd.read_parquet(temporary)
        if len(check) != len(frame) or check["economy_code"].astype("string").fillna("").tolist() != (
            frame["economy_code"].astype("string").fillna("").tolist()
        ):
            raise EconomyValidationError("fixed IO preview failed GeoParquet roundtrip")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return FixedPreview(target, int(mapped.notna().sum()), int(len(frame)))


def selected_custom_economy(workspace: str | Path, record: dict) -> Economy:
    """Load exactly the user-selected custom Economy; fail on missing or changed inputs."""
    spec = record.get("economy_spec")
    if not isinstance(spec, str) or not spec.strip():
        raise EconomyValidationError("custom IO selection has no economy path or identifier")
    key = spec.strip().casefold()
    aliases = {"io16": "io16", "builtin:io16": "io16", "psa-2018-io16": "io16",
               "io80": "io80", "builtin:io80": "io80", "psa-2018-io80": "io80"}
    model = Economy.builtin(aliases[key]) if key in aliases else Economy.from_directory(Path(spec))
    if model.economy_fingerprint != record.get("economy_fingerprint"):
        raise EconomyValidationError("selected custom IO economy changed; rerun sigma load with --economy")
    return model


def fixed_selected_places(workspace: str | Path, economy: Economy) -> Path | None:
    """Return the fixed-resolution preview for this exact national economy.

    The preview depends only on places/places.parquet and the level, so an edited
    or filtered handoff regenerates it here (the documented inspect-then-run
    workflow), instead of asking for 'sigma load', which would discard the edits.
    """
    record = read_selection(workspace)
    if record is None or record["io_level"] in ("hierarchical", "custom"):
        return None
    root = Path(workspace).expanduser().resolve()
    level = record["io_level"]
    if record.get("economy_fingerprint") != economy.economy_fingerprint:
        expected_id = "psa-2018-io" + level
        if economy.economy_id == expected_id:
            raise EconomyValidationError(
                "selected national IO reference has changed since sigma load; "
                f"run 'sigma load AREA --io-level {level}' to select it again"
            )
        return None  # Explicit --economy supersedes an area's normal selection.
    source = root / "places" / "places.parquet"
    if not source.is_file():
        raise EconomyValidationError(f"loaded places missing: {source}; run 'sigma load AREA --io-level {level}'")
    preview = root / "fixed-io" / level / "places.parquet"
    if not preview.is_file() or _file_sha256(source) != record.get("places_sha256"):
        rebuilt = build_fixed_preview(root, level, economy)
        write_selection(root, level, economy=economy, coverage=rebuilt.coverage)
        return rebuilt.path
    return preview

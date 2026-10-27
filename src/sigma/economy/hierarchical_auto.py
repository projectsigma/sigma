"""Opt-in reference configuration and safe per-area hierarchical selection.

One *reference* IO240 table and crosswalk can serve many workspaces, but each
workspace has its OWN partition and its own transaction/economy package.  The
normal editable places/places.parquet handoff is never overwritten by this module.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from sigma.errors import EconomyValidationError
from sigma.paths import sigma_home
from .hierarchical import _file_sha256, require_sigma_io80_io16
from .model import Economy

_PROFILE_VERSION = 1


def profile_path() -> Path:
    return sigma_home() / "hierarchical-defaults.json"


def read_profile() -> dict[str, Any] | None:
    path = profile_path()
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema_version") != _PROFILE_VERSION
            or data.get("mode") != "area_hierarchical"
            or not isinstance(data.get("io240_dir"), str)
            or not isinstance(data.get("crosswalk"), str)
            or type(data.get("min_places")) is not int
            or data["min_places"] < 1):
        raise EconomyValidationError(f"invalid hierarchical configuration {path}")
    return data


def save_profile(io240_dir: str | Path, crosswalk: str | Path, *, min_places: int = 5,
                 check_psa: bool = True) -> Path:
    if type(min_places) is not int or min_places < 1:
        raise ValueError("min_places must be a positive integer")
    src = Path(io240_dir).expanduser().resolve()
    cw = Path(crosswalk).expanduser().resolve()
    if not src.is_dir() or not cw.is_file():
        raise FileNotFoundError("IO240 Economy directory and crosswalk CSV must exist")
    e = Economy.from_directory(src)
    if len(e.sectors) != 240 or e.x is None:
        raise EconomyValidationError("reference economy must contain 240 sectors and total output")
    h = pd.read_csv(cw, dtype=str, keep_default_na=False)
    if not {"io240_code", "io80_code", "io16_code"}.issubset(h):
        raise EconomyValidationError("crosswalk must contain io240_code,io80_code,io16_code")
    if len(h) != 240 or h["io240_code"].duplicated().any() or set(h["io240_code"]) != set(e.sectors.codes):
        raise EconomyValidationError("crosswalk must have exactly one row per IO240 sector")
    require_sigma_io80_io16(h)
    payload = {
        "schema_version": _PROFILE_VERSION, "mode": "area_hierarchical",
        "io240_dir": str(src), "crosswalk": str(cw),
        "min_places": min_places, "check_psa": bool(check_psa),
    }
    dst = profile_path()
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=".hierarchical-defaults-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(tmp, dst)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return dst


def auto_economy(workspace: str | Path, *, explicit: str | None = None) -> Economy | None:
    """Only choose a generated model if caller did not request a different one.

    Never infer a compatible economy merely from the presence of a CSV or a
    workspace directory. A generated economy carries an identifiable marker.
    """
    if explicit is not None:
        return None
    root = Path(workspace).expanduser().resolve() / "hierarchical"
    marker = root / ".sigma-hierarchical-manifest.json"
    economy_dir = root / "economy"
    if not marker.exists() and not economy_dir.exists():
        return None
    if not marker.is_file() or not (economy_dir / "economy.yml").is_file():
        raise EconomyValidationError(
            f"incomplete hierarchical output at {root}; rebuild with 'sigma economy hierarchical-refresh'"
        )
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    if manifest.get("artifact_kind") != "sigma-hierarchical-residual":
        raise EconomyValidationError(f"unrecognized hierarchical output at {root}")
    if manifest.get("sector_code_scheme") != "sparse-v1":
        raise EconomyValidationError(
            f"legacy hierarchical IDs at {root}; rebuild with "
            "sigma economy hierarchical-refresh --workspace <workspace> "
            "before using the default hierarchical economy"
        )
    e = Economy.from_directory(economy_dir)
    if (not isinstance(e.provenance.get("metadata"), dict)
            or e.provenance["metadata"].get("derivation", {}).get("source_kind") != "hierarchical_io240_residual"):
        raise EconomyValidationError(f"incorrect hierarchical Economy provenance at {root}")
    if manifest.get("partition_sha256") != e.provenance["metadata"]["derivation"].get("partition_sha256"):
        raise EconomyValidationError(f"hierarchical partition manifest disagrees with Economy at {root}")
    return e


def selected_places(workspace: str | Path, economy: Economy) -> Path | None:
    """Return per-area classified preview only for its exact matching Economy.

    Verify the editable baseline's hash. If users filtered or edited places after
    building the partition, fail instead of applying a stale classification.
    """
    root = Path(workspace).expanduser().resolve() / "hierarchical"
    model = root / "economy" / "economy.yml"
    preview = root / "places.parquet"
    if not model.is_file():
        return None
    derived = Economy.from_directory(root / "economy")
    if derived.economy_fingerprint != economy.economy_fingerprint:
        return None
    if not preview.is_file():
        raise EconomyValidationError("hierarchical Economy has no matching places preview; rebuild it")
    audit_path = root / "economy" / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    previous_hash = audit.get("places_input", {}).get("sha256")
    original = Path(workspace) / "places" / "places.parquet"
    if not previous_hash or not original.is_file() or _file_sha256(original) != previous_hash:
        raise EconomyValidationError(
            "loaded places changed since the area's hierarchical grouping was built. "
            "Run 'sigma economy hierarchical-refresh --workspace <workspace>' to reconstruct it."
        )
    return preview


def profile_is_current(workspace: str | Path, profile: dict[str, Any]) -> bool:
    """Rebuild on changed places, crosswalk or source IO240 Economy fingerprint."""
    root = Path(workspace).expanduser().resolve()
    audit_path = root / "hierarchical" / "economy" / "audit.json"
    marker = root / "hierarchical" / ".sigma-hierarchical-manifest.json"
    if not audit_path.is_file() or not marker.is_file():
        return False
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        seen = json.loads(marker.read_text(encoding="utf-8"))
        source = Path(profile["io240_dir"]).expanduser().resolve()
        ref = Economy.from_directory(source)
        return bool(
            seen.get("artifact_kind") == "sigma-hierarchical-residual"
            and seen.get("sector_code_scheme") == "sparse-v1"
            and audit.get("sector_code_scheme") == "sparse-v1"
            and seen.get("source_economy_fingerprint") == ref.economy_fingerprint
            and audit.get("min_places") == profile["min_places"]
            and audit.get("places_input", {}).get("sha256")
                == _file_sha256(root / "places" / "places.parquet")
            and audit.get("crosswalk_input", {}).get("sha256")
                == _file_sha256(Path(profile["crosswalk"]).expanduser().resolve())
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
# sigma-canonical-sparse-hierarchy-v1

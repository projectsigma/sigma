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
from .hierarchical import (
    COARSE_POLICIES,
    DEFAULT_COARSE_POLICY,
    DEFAULT_MAX_STRADDLE_SHARE,
    _file_sha256,
    require_sigma_io80_io16,
)
from .model import Economy

_PROFILE_VERSION = 1


def _valid_share(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def profile_path() -> Path:
    return sigma_home() / "hierarchical-defaults.json"


PACKAGE_REFERENCE = "package:psa_2018_io240"
_REFERENCE_FILES = (
    "crosswalk.csv", "economy/economy.yml", "economy/sectors.csv",
    "economy/transactions.csv", "economy/total_output.csv",
)


def _canonical_sha256(payload: bytes) -> str:
    """Line-ending-independent text hash (same rule as economy/builtin.py)."""
    import hashlib
    return hashlib.sha256(payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def packaged_reference(root: Any = None) -> dict[str, str]:
    """Verified repository-owned PSA IO240 reference; never consults workspace data.

    Hashes ignore CRLF/LF differences, so a Windows checkout with core.autocrlf
    and a Linux checkout verify the same package.
    """
    import io
    from importlib.resources import files
    from sigma.classification.io_mapping_compat import load_catalog
    from sigma.classification.reference import load_builtin_io_reference
    from .hierarchical import tagging_consistency

    base = files("sigma.resources.economy.psa_2018_io240") if root is None else root
    audit_file = base.joinpath("validation.json")
    if not audit_file.is_file():
        raise EconomyValidationError(
            "national PSA IO240 reference not installed in SIGMA package; "
            "run scripts/sigma_pack_io240_repo.py and commit the validated reference files"
        )
    manifest = json.loads(audit_file.read_text(encoding="utf-8"))
    if manifest.get("hash_normalization") != "crlf-to-lf":
        raise EconomyValidationError(
            "national IO240 package was written by an older packager; rebuild it with "
            "scripts/sigma_pack_io240_repo.py --replace-existing"
        )
    hashes = manifest.get("reference_files_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(_REFERENCE_FILES):
        raise EconomyValidationError("national IO240 package has incomplete SHA-256 manifest")
    for name, expected in hashes.items():
        resource = base.joinpath(*name.split("/"))
        if not resource.is_file() or _canonical_sha256(resource.read_bytes()) != expected:
            raise EconomyValidationError(f"national IO240 reference failed integrity check: {name}")
    hierarchy = pd.read_csv(io.StringIO(base.joinpath("crosswalk.csv").read_text(encoding="utf-8")),
                            dtype=str, keep_default_na=False)
    if len(hierarchy) != 240 or hierarchy.io240_code.duplicated().any():
        raise EconomyValidationError("bundled IO240 reference must have exactly 240 unique leaves")
    current = dict(zip(hierarchy.io240_code, hierarchy.io80_code, strict=True))
    if current != dict(load_builtin_io_reference().io240_parent_map):
        raise EconomyValidationError("bundled IO240 hierarchy differs from current PR #17 tagging parents")
    catalog = load_catalog()
    for row in hierarchy.itertuples(index=False):
        if row.io80_code not in catalog or row.io16_code != catalog[row.io80_code].io16_code:
            raise EconomyValidationError("bundled IO240 parent links differ from current IO80/IO16")
    require_sigma_io80_io16(hierarchy)
    if not tagging_consistency(hierarchy)["consistent"]:
        raise EconomyValidationError("bundled IO240 hierarchy conflicts with current PSIC IO tagging")
    resolved = Path(str(base)).resolve()
    return {"io240_dir": str(resolved / "economy"), "crosswalk": str(resolved / "crosswalk.csv")}


def default_profile_document() -> dict[str, Any]:
    """Settings written to a new local hierarchical-defaults.json.

    Package references are resolved when read, so reinstalling SIGMA does not
    break the profile. New configurations use the residual assignment policy.
    Existing local profiles (including historical residual) remain untouched.
    """
    return {
        "schema_version": _PROFILE_VERSION,
        "mode": "area_hierarchical",
        "io240_dir": PACKAGE_REFERENCE,
        "crosswalk": PACKAGE_REFERENCE,
        "min_places": 5,
        "check_psa": True,
        "coarse_policy": "residual",
        "max_straddle_share": DEFAULT_MAX_STRADDLE_SHARE,
        "created_by": "sigma load (portable-hierarchy patch v4) from the packaged PSA IO240 reference",
    }


def _resolve_profile(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Resolve the source location lazily, without requiring IO240 for fixed runs.

    The existing run command calls read_profile() before resolving area selection.
    IO240 validation must happen only for hierarchical builds, never implicitly
    for fixed IO16/IO80, custom, or legacy IO80 workspaces.
    """
    from importlib.resources import files
    data = dict(data)
    using_package = PACKAGE_REFERENCE in (data.get("io240_dir"), data.get("crosswalk"))
    if using_package:
        root = Path(str(files("sigma.resources.economy.psa_2018_io240"))).resolve()
        paths = {"io240_dir": str(root / "economy"), "crosswalk": str(root / "crosswalk.csv")}
        for key in ("io240_dir", "crosswalk"):
            if data.get(key) == PACKAGE_REFERENCE:
                data[key] = paths[key]
    data["_package_reference"] = using_package
    data["_source"] = source
    return data


def validate_profile_inputs(profile: dict[str, Any]) -> None:
    """Check the complete 240-sector national reference before loading places."""
    from sigma.classification.reference import load_builtin_io_reference
    from .hierarchical import tagging_consistency
    if profile.get("_package_reference"):
        checked = packaged_reference()  # SHA checks and canonical reference structure
        for key in ("io240_dir", "crosswalk"):
            if Path(profile[key]).expanduser().resolve() != Path(checked[key]).resolve():
                raise EconomyValidationError(f"national package {key} moved unexpectedly")
    source = Path(profile["io240_dir"]).expanduser().resolve()
    crosswalk_path = Path(profile["crosswalk"]).expanduser().resolve()
    if not (source / "economy.yml").is_file() or not crosswalk_path.is_file():
        raise EconomyValidationError(
            "hierarchical reference files are missing: "
            f"economy={source}; crosswalk={crosswalk_path}. "
            "They may have been removed during storage cleanup. Set io240_dir "
            "and crosswalk to 'package:psa_2018_io240' in hierarchical-defaults.json, "
            "or configure other verified references before sigma load."
        )
    model = Economy.from_directory(source)
    if len(model.sectors) != 240 or model.x is None:
        raise EconomyValidationError("the hierarchical source must be a complete 240-sector IO economy")
    crosswalk = pd.read_csv(crosswalk_path, dtype=str, keep_default_na=False)
    columns = {"io240_code", "io80_code", "io16_code"}
    if not columns.issubset(crosswalk):
        raise EconomyValidationError("hierarchy crosswalk lacks io240_code, io80_code, or io16_code")
    if (len(crosswalk) != 240 or crosswalk["io240_code"].duplicated().any()
            or set(crosswalk["io240_code"]) != set(model.sectors.codes)):
        raise EconomyValidationError("hierarchy crosswalk is not the complete 240-industry partition")
    require_sigma_io80_io16(crosswalk)
    current = load_builtin_io_reference().io240_parent_map
    parents = dict(zip(crosswalk.io240_code, crosswalk.io80_code, strict=True))
    if parents != current:
        mismatches = [c for c in sorted(set(parents) | set(current)) if parents.get(c) != current.get(c)]
        raise EconomyValidationError(
            "hierarchical crosswalk differs from current PR #17 IO240 parents "
            f"(e.g. IO240 {mismatches[:8]}). Use the validated reference."
        )
    report = tagging_consistency(crosswalk)
    if not report["consistent"]:
        raise EconomyValidationError(
            "hierarchical reference conflicts with current IO tagging: " + str(report)[:800]
        )


def packaged_profile() -> dict[str, Any]:
    """The default profile with package references resolved; nothing is written."""
    return _resolve_profile(default_profile_document(), source="package default (no local file yet)")


def ensure_local_profile() -> tuple[Path, bool]:
    """Create SIGMA_HOME/hierarchical-defaults.json from the package default if absent."""
    path = profile_path()
    if path.is_file():
        return path, False
    packaged_reference()  # never write a profile that points to a missing or altered package
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".hierarchical-defaults-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(default_profile_document(), stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return path, True


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
            or data["min_places"] < 1
            or data.get("coarse_policy", "residual") not in COARSE_POLICIES
            or not _valid_share(data.get("max_straddle_share", DEFAULT_MAX_STRADDLE_SHARE))):
        raise EconomyValidationError(f"invalid hierarchical configuration {path}")
    # Historical profiles were built with the residual rule. Loading must not
    # silently adopt the new containment/parent-merging model on the next run.
    data.setdefault("coarse_policy", "residual")
    data.setdefault("max_straddle_share", DEFAULT_MAX_STRADDLE_SHARE)
    return _resolve_profile(data, source=str(path))


def save_profile(io240_dir: str | Path, crosswalk: str | Path, *, min_places: int = 5,
                 check_psa: bool = True, coarse_policy: str = DEFAULT_COARSE_POLICY,
                 max_straddle_share: float = DEFAULT_MAX_STRADDLE_SHARE) -> Path:
    if type(min_places) is not int or min_places < 1:
        raise ValueError("min_places must be a positive integer")
    if coarse_policy not in COARSE_POLICIES:
        raise ValueError(f"coarse_policy must be one of {COARSE_POLICIES}")
    if isinstance(max_straddle_share, bool) or not 0 <= float(max_straddle_share) <= 1:
        raise ValueError("max_straddle_share must be a number in [0, 1]")
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
        "coarse_policy": coarse_policy,
        "max_straddle_share": float(max_straddle_share),
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
    from .load_policy import read_selection
    chosen = read_selection(workspace)
    if chosen is not None and chosen["io_level"] == "custom":
        from .load_policy import selected_custom_economy
        return selected_custom_economy(workspace, chosen)
    if chosen is not None and chosen["io_level"] in ("16", "80"):
        return Economy.builtin("io" + chosen["io_level"])
    if chosen is not None and chosen["io_level"] == "240":
        return Economy.from_directory(packaged_reference()["io240_dir"])
    root = Path(workspace).expanduser().resolve() / "hierarchical"
    marker = root / ".sigma-hierarchical-manifest.json"
    economy_dir = root / "economy"
    if not marker.exists() and not economy_dir.exists():
        if chosen is not None and chosen["io_level"] == "hierarchical":
            raise EconomyValidationError(
                "this workspace is configured for hierarchical IO, but derived outputs are missing; "
                "rerun sigma load (or sigma run, which rebuilds them) to regenerate them, not IO80"
            )
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
    from .load_policy import fixed_selected_places
    fixed = fixed_selected_places(workspace, economy)
    if fixed is not None:
        return fixed
    # SIGMA_ITERATIVE_RESIDUAL_ROLLUP_PLACES_V1: the Economy/places pair
    # belongs to one immutable derived package, not the original hierarchy.
    metadata = economy.provenance.get("metadata")
    derivation = metadata.get("derivation") if isinstance(metadata, dict) else None
    if (isinstance(derivation, dict)
            and derivation.get("source_kind") == "hierarchical_io240_iterative_rollup"):
        from sigma.spatial.iterative_rollup import sha256_file
        workspace_root = Path(workspace).expanduser().resolve()
        package_root = Path(str(economy.provenance.get("economy_yml", ""))).resolve().parent.parent
        allowed = (workspace_root / "hierarchical" / "iterative_rollup").resolve()
        if not package_root.is_relative_to(allowed):
            raise EconomyValidationError("iterative roll-up Economy lies outside workspace package root")
        place_file = package_root / "places.parquet"
        base = workspace_root / "hierarchical" / "places.parquet"
        manifest_file = package_root / "rollup_manifest.json"
        if not place_file.is_file() or not base.is_file() or not manifest_file.is_file():
            raise EconomyValidationError("iterative roll-up package or original hierarchy is incomplete")
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        audit_path = workspace_root / "hierarchical" / "economy" / "audit.json"
        original = workspace_root / "places" / "places.parquet"
        if not audit_path.is_file() or not original.is_file():
            raise EconomyValidationError("original hierarchical source/audit is missing")
        source_audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if (manifest.get("recipe_sha256") != derivation.get("recipe_sha256")
                or sha256_file(base) != derivation.get("base_places_sha256")
                or sha256_file(original) != source_audit.get("places_input", {}).get("sha256")
                or sha256_file(place_file) != manifest.get("file_hashes", {}).get("places.parquet")):
            raise EconomyValidationError("iterative roll-up package is stale or altered; regenerate explicitly")
        return place_file
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


def _outputs_match_profile(workspace: str | Path, profile: dict[str, Any]) -> bool:
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
            # Builds from before coarse_policy existed used the legacy residual rule.
            and audit.get("coarse_policy", "residual")
                == profile.get("coarse_policy", "residual")
            and (profile.get("coarse_policy", "residual") != "contain"
                 or audit.get("max_straddle_share")
                 == float(profile.get("max_straddle_share", DEFAULT_MAX_STRADDLE_SHARE)))
            and audit.get("places_input", {}).get("sha256")
                == _file_sha256(root / "places" / "places.parquet")
            and audit.get("crosswalk_input", {}).get("sha256")
                == _file_sha256(Path(profile["crosswalk"]).expanduser().resolve())
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def profile_is_current(workspace: str | Path, profile: dict[str, Any]) -> bool:
    """Selection-aware staleness guard that cannot migrate a legacy IO80 area.

    A pre-patch workspace with no economy-selection.json and no hierarchical
    artifacts remains IO80 even if some *other* area created the global profile.
    Explicit fixed and custom choices bypass IO240 validation entirely.
    Only a selected hierarchy (or previously generated legacy hierarchy) may
    trigger the existing per-area hierarchy builder from sigma run.
    """
    from .load_policy import identity_differences, profile_identity, read_selection, update_profile_identity
    chosen = read_selection(workspace)
    if chosen is not None and chosen["io_level"] in ("16", "80", "240", "custom"):
        return True
    if chosen is None:
        # A legacy IO80 workspace has never published a complete hierarchy:
        # leave it IO80 even when another area created the global profile.
        # For a completed *legacy hierarchical* workspace, retain the original
        # checksum contract. An edited handoff or changed input must not make
        # a stale hierarchy look current. An implicit run will refuse to rebuild
        # an unrecorded legacy hierarchy (see the shared builder guard).
        legacy = Path(workspace).expanduser().resolve() / "hierarchical"
        if ((legacy / "economy" / "audit.json").is_file()
                and (legacy / ".sigma-hierarchical-manifest.json").is_file()):
            return _outputs_match_profile(workspace, profile)
        return True
    validate_profile_inputs(profile)
    recorded = chosen.get("profile_identity")
    if recorded is None:
        raise EconomyValidationError(
            "hierarchical workspace has no recorded reference/policy identity. "
            "Refusing to rebuild it implicitly; run sigma load AREA or "
            "sigma economy hierarchical-refresh explicitly."
        )
    if _outputs_match_profile(workspace, profile):
        if recorded:
            current = profile_identity(profile)
            if identity_differences(recorded, current):
                update_profile_identity(workspace, current)
        return True
    if recorded:
        changes = identity_differences(recorded, profile_identity(profile))
        if changes:
            raise EconomyValidationError(
                "this area's hierarchical settings changed since it was loaded ("
                + "; ".join(changes) + "). 'sigma run' will not change the area's typology silently. "
                "To adopt the new settings and keep edits to places/places.parquet, run "
                f"'sigma economy hierarchical-refresh --workspace {Path(workspace)}'; "
                "or rerun 'sigma load <area>' with the intended method."
            )
    return False
# sigma-canonical-sparse-hierarchy-v1

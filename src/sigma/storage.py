"""Read-only disk inventory and opt-in cleanup of SIGMA-owned workspace debris.

Never erase published results, user-reviewed inputs, active artifacts, or their
transitive dependencies. No part of this module runs during normal SIGMA jobs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Candidate:
    path: Path
    category: str
    bytes: int


@dataclass(frozen=True)
class Inventory:
    workspace: Path
    categories: dict[str, int]
    stage_sizes: dict[str, int]
    largest_files: tuple[tuple[Path, int], ...]
    candidates: tuple[Candidate, ...]
    older_than_days: int
    obsolete: bool
    quarantine: bool
    protected_reason: str | None = None


def _tree_stats(path: Path) -> tuple[int, float, bool]:
    """Return logical bytes, most recent activity, and whether any symlinks exist."""
    if path.is_symlink():
        return 0, 0, True
    if path.is_file():
        stat = path.stat()
        return stat.st_size, stat.st_mtime, False
    if not path.is_dir():
        return 0, 0, False
    total = 0
    newest = path.stat().st_mtime
    for parent, folders, files in os.walk(path, followlinks=False):
        base = Path(parent)
        for name in folders + files:
            child = base / name
            if child.is_symlink():
                return total, newest, True
            try:
                stat = child.stat()
            except OSError:
                return total, newest, True  # fail closed on unreadable entries
            newest = max(newest, stat.st_mtime)
            if child.is_file():
                total += stat.st_size
    return total, newest, False


def _eligible(path: Path, *, older_than_days: int, now: float) -> int | None:
    total, last_activity, unsafe = _tree_stats(path)
    if unsafe or not last_activity or now - last_activity < older_than_days * 86400:
        return None
    return total


def _safe_output(root: Path) -> Path | None:
    """Read only the workspace's configured output; never infer another output."""
    try:
        payload = json.loads((root / "workspace.json").read_text(encoding="utf-8"))
        value = payload["output_dir"]
        if not isinstance(value, str) or not value.strip():
            return None
        raw = Path(value).expanduser()
        return (raw if raw.is_absolute() else root / raw).resolve()
    except (OSError, KeyError, ValueError, TypeError):
        return None


def _trusted_artifact_graph(artifacts: Path) -> tuple[set[Path], str | None]:
    """Find closure of active artifact dependencies, failing closed on bad metadata."""
    active = artifacts / ".state" / "active.json"
    if not active.is_file() or active.is_symlink():
        return set(), "missing or unsafe active.json"
    try:
        payload = json.loads(active.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("artifacts"), dict):
            raise ValueError("unexpected active index schema")
        roots = payload["artifacts"]
        if not roots:
            raise ValueError("no active artifacts")
        by_identity = {}
        for stage_dir in artifacts.iterdir():
            if stage_dir.name.startswith(".") or not stage_dir.is_dir():
                continue
            if stage_dir.is_symlink():
                raise ValueError("symlinked artifact stage")
            for directory in stage_dir.iterdir():
                if not directory.is_dir() or directory.is_symlink():
                    raise ValueError("unsafe artifact directory")
                manifest_path = directory / "artifact.json"
                if manifest_path.is_symlink():
                    raise ValueError("symlinked manifest")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (manifest.get("stage") != stage_dir.name or
                        manifest.get("recipe_fingerprint") != directory.name or
                        not isinstance(manifest.get("artifact_id"), str)):
                    raise ValueError("artifact identity mismatch")
                key = (manifest["stage"], manifest["recipe_fingerprint"], manifest["artifact_id"])
                if key in by_identity:
                    raise ValueError("duplicate artifact identity")
                by_identity[key] = (directory, manifest)

        pending = []
        for entry in roots.values():
            if not isinstance(entry, dict):
                raise ValueError("invalid active entry")
            path = Path(str(entry["manifest"]))
            # Do not trust freeform paths or follow a pointer outside the artifact store.
            if path.is_absolute() or ".." in path.parts or path.name != "artifact.json":
                raise ValueError("unsafe active manifest path")
            key = (entry["stage"], entry["recipe_fingerprint"], entry["artifact_id"])
            stored = by_identity.get(key)
            if stored is None or stored[0] / "artifact.json" != artifacts / path:
                raise ValueError("active artifact missing or inconsistent")
            pending.append(key)
        retained = set()
        while pending:
            key = pending.pop()
            if key in retained:
                continue
            if key not in by_identity:
                raise ValueError("referenced dependency missing")
            retained.add(key)
            recipe = by_identity[key][1].get("recipe")
            if not isinstance(recipe, dict) or not isinstance(recipe.get("dependencies"), dict):
                raise ValueError("invalid recipe dependencies")
            for dependency in recipe["dependencies"].values():
                if not isinstance(dependency, dict) or not all(
                    isinstance(dependency.get(field), str)
                    for field in ("stage", "recipe_fingerprint", "artifact_id")
                ):
                    raise ValueError("incomplete dependency reference")
                pending.append((
                    dependency["stage"], dependency["recipe_fingerprint"],
                    dependency["artifact_id"],
                ))
        return {directory for key, (directory, _) in by_identity.items() if key not in retained}, None
    except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return set(), f"obsolete artifacts protected: {exc}"


def inspect_workspace(
    workspace: Path | str, *, older_than_days: int = 30, obsolete: bool = False,
    quarantine: bool = False, now: float | None = None,
) -> Inventory:
    """Produce a non-mutating inventory and narrowly-scoped deletion candidates."""
    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1")
    root = Path(workspace).expanduser().resolve()
    if not (root / "workspace.json").is_file():
        raise ValueError(f"Not a SIGMA workspace: {root}")
    now = time.time() if now is None else now
    artifacts = root / "artifacts"
    output = _safe_output(root)
    categories = {}
    for name in ("artifacts", "output", "places", "state", "runs"):
        path = output if name == "output" else root / name
        if path is not None:
            categories[name] = _tree_stats(path)[0]
    stage_sizes = {}
    if artifacts.is_dir() and not artifacts.is_symlink():
        for entry in artifacts.iterdir():
            if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith("."):
                stage_sizes[entry.name] = _tree_stats(entry)[0]

    # Report largest individual files, but never open or alter their content.
    largest = []
    roots = [root]
    if output is not None and output != root and root not in output.parents:
        roots.append(output)
    for scan_root in roots:
        if scan_root.is_symlink() or not scan_root.is_dir():
            continue
        for parent, folders, files in os.walk(scan_root, followlinks=False):
            folders[:] = [f for f in folders if not (Path(parent) / f).is_symlink()]
            for filename in files:
                candidate_path = Path(parent) / filename
                if candidate_path.is_symlink():
                    continue
                try:
                    largest.append((candidate_path, candidate_path.stat().st_size))
                except OSError:
                    continue
    largest.sort(key=lambda item: item[1], reverse=True)

    # Files of unrecognized provenance are inventoried, never removed.
    categories["other"] = max(0, _tree_stats(root)[0] - sum(
        value for name, value in categories.items()
        if name != "output" or (output is not None and output == root / "output")
    ))

    candidates: list[Candidate] = []

    def offer(path: Path, category: str) -> None:
        count = _eligible(path, older_than_days=older_than_days, now=now)
        if count is not None:
            candidates.append(Candidate(path, category, count))

    tmp = artifacts / ".tmp"
    if tmp.is_dir() and not tmp.is_symlink():
        for item in tmp.iterdir():
            if item.is_dir() and not item.is_symlink():
                offer(item, "abandoned artifact staging")
    state_tmp = artifacts / ".state" / "active.json.tmp"
    if (artifacts / ".state" / "active.json").is_file() and state_tmp.is_file():
        offer(state_tmp, "abandoned active-index temporary")

    # Publication targets can be outside the workspace. Limit scans to known SIGMA names.
    if output is not None and output.is_dir():
        for item in output.iterdir():
            if item.name.startswith(".sigma-export-") and item.is_dir():
                offer(item, "abandoned export staging")
            if re.fullmatch(r"\.explorer(?:-public)?\.staging-[\w-]+", item.name) and item.is_dir():
                offer(item, "abandoned Explorer staging")
            if re.fullmatch(r"\.(explorer(?:-public)?)\.backup-[0-9a-f]{32}", item.name) and item.is_dir():
                name = item.name.split(".backup-", 1)[0][1:]
                # A backup is never discarded until a functioning new Explorer exists.
                if ((output / name / "index.html").is_file() and
                        (output / name / ".sigma-explorer").is_file()):
                    offer(item, "superseded Explorer backup")
        for bundle_name in ("explorer", "explorer-public"):
            bundle = output / bundle_name
            if (bundle / ".sigma-explorer").is_file() and bundle.is_dir():
                for item in bundle.iterdir():
                    if item.is_file() and item.name.startswith(".sigma-ui-"):
                        offer(item, "abandoned Explorer UI temporary")

    protected_reason = None
    if obsolete:
        # Run archives can reference superseded versions. Never invalidate their lineage.
        runs = root / "runs"
        if runs.is_dir() and any(runs.iterdir()):
            protected_reason = "run archives are present"
        else:
            unused, protected_reason = _trusted_artifact_graph(artifacts)
            if protected_reason is None:
                for item in unused:
                    offer(item, "obsolete immutable artifact (opt-in)")
    if quarantine:
        q = artifacts / ".corrupt"
        if q.is_dir() and not q.is_symlink():
            for stage in q.iterdir():
                if stage.is_dir() and not stage.is_symlink():
                    for item in stage.iterdir():
                        if item.is_dir():
                            offer(item, "quarantined artifact (opt-in)")
    candidates.sort(key=lambda item: (item.category, str(item.path)))
    return Inventory(
        root, categories, stage_sizes, tuple(largest[:8]), tuple(candidates),
        older_than_days, obsolete, quarantine, protected_reason,
    )


def prune(inventory: Inventory, *, apply: bool = False) -> list[tuple[Candidate, str]]:
    """Delete only previously inventoried, old files; by default report intent."""
    outcomes = []
    # Revalidate *all* candidates just before application: an active graph may
    # have changed since the original preview/scan.
    current = (
        inspect_workspace(
            inventory.workspace, older_than_days=inventory.older_than_days,
            obsolete=inventory.obsolete, quarantine=inventory.quarantine,
        ) if apply else inventory
    )
    valid_paths = {item.path for item in current.candidates}
    for candidate in inventory.candidates:
        # Re-check age immediately before deletion, avoiding newly modified files.
        _, newest, unsafe = _tree_stats(candidate.path)
        if (candidate.path not in valid_paths or unsafe or not newest or
                time.time() - newest < inventory.older_than_days * 86400):
            outcomes.append((candidate, "skipped: changed or unsafe"))
        elif not apply:
            outcomes.append((candidate, "preview"))
        else:
            try:
                if candidate.path.is_dir():
                    shutil.rmtree(candidate.path)
                elif candidate.path.is_file() and not candidate.path.is_symlink():
                    candidate.path.unlink()
                outcomes.append((candidate, "deleted"))
            except OSError as exc:
                outcomes.append((candidate, f"failed: {exc}"))
    return outcomes

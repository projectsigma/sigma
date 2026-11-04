"""Explicit, fail-closed inventory and pruning of SIGMA-owned libosmium indexes.

Normal jobs never call this module to sweep indexes. Pruning is a deliberate
maintenance operation; callers must stop all extraction jobs first.
"""
from __future__ import annotations

import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

_ROAD = re.compile(r"[0-9a-f]{64}(?:\.[0-9a-f]{32})?\.nodes\.cache\Z", re.I)
_POI = re.compile(r"node-locations(?:\.[0-9a-f]{32})?\.cache\Z", re.I)


@dataclass(frozen=True)
class NodeIndexCandidate:
    path: Path
    size: int
    modified_ns: int
    device: int
    inode: int


@dataclass(frozen=True)
class NodeIndexInventory:
    sources_root: Path
    older_than_days: int
    found_count: int
    found_bytes: int
    eligible: tuple[NodeIndexCandidate, ...]


def new_poi_node_index(cache_base: Path) -> Path:
    """Choose a fresh location-index name owned only by this POI extraction."""
    return Path(cache_base) / "geofabrik" / f"node-locations.{uuid4().hex}.cache"


def _safe_directory(path: Path) -> bool:
    """Reject symlinks and missing paths rather than following them."""
    return not path.is_symlink() and path.is_dir()


def _paths(root: Path):
    road_parent = root / "geofabrik"
    road = road_parent / "road-node-index"
    if _safe_directory(road_parent) and _safe_directory(road):
        for item in road.iterdir():
            if _ROAD.fullmatch(item.name):
                yield item
    # Older installations may have used the shared root for national POIs.
    if _safe_directory(road_parent):
        for item in road_parent.iterdir():
            if _POI.fullmatch(item.name):
                yield item
    prepared = root / "prepared-osm-recipes"
    if _safe_directory(prepared):
        for recipe in prepared.iterdir():
            if not _safe_directory(recipe):
                continue
            # No recursive search: only known SIGMA cache layouts are eligible.
            for parent in (recipe, recipe / "geofabrik"):
                if not _safe_directory(parent):
                    continue
                for item in parent.iterdir():
                    if _POI.fullmatch(item.name):
                        yield item


def _candidate(path: Path, *, now: float, older_than_days: int) -> tuple[NodeIndexCandidate, bool] | None:
    try:
        entry = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
        return None
    item = NodeIndexCandidate(path, entry.st_size, entry.st_mtime_ns, entry.st_dev, entry.st_ino)
    old_enough = now - entry.st_mtime >= older_than_days * 86400
    return item, old_enough


def inspect_node_indexes(sources_root: Path | str, *, older_than_days: int = 30,
                         now: float | None = None) -> NodeIndexInventory:
    """Read-only survey; includes recent files in totals, but not in delete candidates."""
    if older_than_days < 1:
        raise ValueError("node-index cleanup requires --older-than-days of at least 1")
    raw = Path(sources_root).expanduser()
    if not _safe_directory(raw):
        raise ValueError(f"Not a safe SIGMA source-store directory: {raw}")
    root = raw.resolve()
    if now is None:
        now = time.time()
    total = count = 0
    eligible: list[NodeIndexCandidate] = []
    for path in _paths(root):
        candidate = _candidate(path, now=now, older_than_days=older_than_days)
        if candidate is None:
            continue
        info, ready = candidate
        total += info.size
        count += 1
        if ready:
            eligible.append(info)
    return NodeIndexInventory(root, older_than_days, count, total,
                              tuple(sorted(eligible, key=lambda c: str(c.path))))


def prune_node_indexes(inventory: NodeIndexInventory, *, apply: bool = False
                       ) -> list[tuple[NodeIndexCandidate, str]]:
    """Preview by default; re-inspect and compare file identities before any unlink.

    This does not detect running SIGMA jobs. They must be stopped by the operator.
    Other source files and non-matching names are never candidates.
    """
    if not apply:
        return [(item, "preview") for item in inventory.eligible]
    fresh = inspect_node_indexes(inventory.sources_root,
                                 older_than_days=inventory.older_than_days)
    allowed = {item.path: item for item in fresh.eligible}
    output = []
    for item in inventory.eligible:
        valid = allowed.get(item.path)
        if valid != item:
            output.append((item, "skipped: changed, too recent, or unsafe"))
            continue
        current = _candidate(item.path, now=time.time(),
                             older_than_days=inventory.older_than_days)
        if current is None or not current[1] or current[0] != item:
            output.append((item, "skipped: changed, too recent, or unsafe"))
            continue
        try:
            item.path.unlink()
        except OSError as exc:
            output.append((item, f"failed: {exc}"))
        else:
            output.append((item, "deleted"))
    return output

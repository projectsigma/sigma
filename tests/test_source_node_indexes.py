"""Focused tests for explicit libosmium index inventory and safe pruning."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sigma.source_node_indexes import (
    inspect_node_indexes, new_poi_node_index, prune_node_indexes,
)


def _old(path: Path, *, age_days: int = 40) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"libosmium-index")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_identifies_legacy_and_unique_road_and_poi_indexes_without_deleting(tmp_path):
    root = tmp_path / "sources"
    oldroad = _old(root / "geofabrik" / "road-node-index" / ("a" * 64 + ".nodes.cache"))
    freshroad = _old(root / "geofabrik" / "road-node-index" /
                     ("b" * 64 + "." + "c" * 32 + ".nodes.cache"))
    poi1 = _old(root / "prepared-osm-recipes" / "recipe01" / "geofabrik" /
                "node-locations.cache")
    poi2 = _old(root / "prepared-osm-recipes" / "recipe02" / "geofabrik" /
                ("node-locations." + "d" * 32 + ".cache"))
    unexpected = _old(root / "geofabrik" / "road-node-index" / "other.cache")
    pbf = _old(root / "geofabrik" / "philippines" / "philippines.osm.pbf")
    # Only narrowly recognized filenames in SIGMA source-index locations qualify.
    report = inspect_node_indexes(root)
    assert {p.path for p in report.eligible} == {oldroad, freshroad, poi1, poi2}
    assert report.found_count == 4
    assert all(status == "preview" for _, status in prune_node_indexes(report))
    assert all(p.exists() for p in (oldroad, freshroad, poi1, poi2, unexpected, pbf))
    results = prune_node_indexes(report, apply=True)
    assert all(status == "deleted" for _, status in results)
    assert unexpected.exists() and pbf.exists()
    assert all(not p.exists() for p in (oldroad, freshroad, poi1, poi2))


def test_recent_files_are_excluded_and_age_is_rechecked(tmp_path):
    root = tmp_path / "sources"
    old = _old(root / "geofabrik" / "road-node-index" /
               ("e" * 64 + ".nodes.cache"))
    recent = _old(root / "geofabrik" / "road-node-index" /
                  ("f" * 64 + ".nodes.cache"), age_days=0)
    report = inspect_node_indexes(root, older_than_days=1)
    assert {x.path for x in report.eligible} == {old}
    # Simulate a concurrent user replacing the index after preview.
    old.write_bytes(b"new-active-scan")
    results = prune_node_indexes(report, apply=True)
    assert len(results) == 1 and results[0][1].startswith("skipped")
    assert old.exists() and recent.exists()


def test_symlinks_are_never_candidates(tmp_path):
    root = tmp_path / "sources"
    hidden = _old(tmp_path / "external.cache")
    linkdir = root / "prepared-osm-recipes" / "recipe01"
    linkdir.parent.mkdir(parents=True)
    try:
        linkdir.symlink_to(hidden.parent, target_is_directory=True)
        linkfile = root / "geofabrik" / "road-node-index" / ("a" * 64 + ".nodes.cache")
        linkfile.parent.mkdir(parents=True)
        linkfile.symlink_to(hidden)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    report = inspect_node_indexes(root, older_than_days=1)
    assert not report.eligible
    assert hidden.exists()


def test_poi_index_names_are_unique_without_disk_side_effects(tmp_path):
    one = new_poi_node_index(tmp_path)
    two = new_poi_node_index(tmp_path)
    assert one != two
    assert one.parent == tmp_path / "geofabrik"
    assert one.name.startswith("node-locations.") and one.suffix == ".cache"
    assert not one.exists() and not two.exists()


def test_refuses_zero_age_and_symlink_root(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    with pytest.raises(ValueError):
        inspect_node_indexes(root, older_than_days=0)
    shortcut = tmp_path / "link"
    try:
        shortcut.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        inspect_node_indexes(shortcut)


def test_failed_unlink_is_reported_without_interrupting_other_candidates(tmp_path, monkeypatch):
    root = tmp_path / "sources"
    blocked = _old(root / "geofabrik" / "road-node-index" /
                   ("1" * 64 + ".nodes.cache"))
    ok = _old(root / "geofabrik" / "road-node-index" /
              ("2" * 64 + ".nodes.cache"))
    inventory = inspect_node_indexes(root)
    native_unlink = Path.unlink

    def simulated_lock(self, *args, **kwargs):
        if self == blocked:
            raise PermissionError("simulated Windows lock")
        return native_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", simulated_lock)
    results = prune_node_indexes(inventory, apply=True)
    outcomes = {item.path: status for item, status in results}
    assert outcomes[blocked].startswith("failed:")
    assert outcomes[ok] == "deleted"
    assert blocked.exists() and not ok.exists()


def test_traversal_of_unrecognized_subdirectories_is_not_allowed(tmp_path):
    root = tmp_path / "sources"
    # A correctly named file in an unrecognized directory is not SIGMA scratch.
    foreign = _old(root / "customer-data" / ("a" * 64 + ".nodes.cache"))
    nested = _old(root / "prepared-osm-recipes" / "recipe01" / "unexpected" /
                  "node-locations.cache")
    inventory = inspect_node_indexes(root)
    assert not inventory.eligible
    assert foreign.exists() and nested.exists()

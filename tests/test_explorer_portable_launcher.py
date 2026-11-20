"""Portable SIGMA Explorer distribution and legacy directory migration."""
from pathlib import Path
import json

import pytest

from sigma.cli import _explorer_paths, _migrate_legacy_explorer
from sigma.web.builder import STATIC_FILES, BUNDLE_FORMAT, BUNDLE_VERSION


def _make_legacy(root: Path, name: str, profile: str = "local") -> Path:
    old = root / name
    old.mkdir()
    (old / "index.html").write_text("<html></html>", encoding="utf-8")
    (old / "data").mkdir()
    (old / "data" / "graph.json").write_text("{\"nodes\":[]}", encoding="utf-8")
    (old / ".sigma-explorer").write_text(json.dumps({
        "format": BUNDLE_FORMAT, "version": BUNDLE_VERSION, "profile": profile,
    }), encoding="utf-8")
    return old


def test_named_explorer_default_and_explicit_override(tmp_path: Path):
    source, target = _explorer_paths("Metro Manila", None, tmp_path, None)
    assert source == tmp_path and target == tmp_path / "metro_manila-explorer"
    assert _explorer_paths("metro_manila", None, tmp_path, tmp_path / "custom")[1] == tmp_path / "custom"
    assert "sigma.exe" in STATIC_FILES and "about.html" in STATIC_FILES


def test_legacy_migration_keeps_data_byte_identical(tmp_path: Path):
    old = _make_legacy(tmp_path, "explorer")
    before = (old / "data/graph.json").read_bytes()
    dest = tmp_path / "metro_manila-explorer"
    assert _migrate_legacy_explorer(tmp_path, dest, public=False)
    assert not old.exists() and (dest / "data/graph.json").read_bytes() == before
    assert not _migrate_legacy_explorer(tmp_path, dest, public=False)


def test_legacy_migration_refuses_wrong_profile_and_bad_marker(tmp_path: Path):
    old = _make_legacy(tmp_path, "explorer", profile="public")
    dest = tmp_path / "metro_manila-explorer"
    with pytest.raises(ValueError, match="privacy profile"):
        _migrate_legacy_explorer(tmp_path, dest, public=False)
    assert old.is_dir() and not dest.exists()
    (old / ".sigma-explorer").write_text("garbled", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or unrecognized"):
        _migrate_legacy_explorer(tmp_path, dest, public=False)
    assert old.is_dir() and not dest.exists()


def test_migration_never_overwrites_a_named_explorer(tmp_path: Path):
    _make_legacy(tmp_path, "explorer")
    named = _make_legacy(tmp_path, "metro_manila-explorer")
    assert not _migrate_legacy_explorer(tmp_path, named, public=False)
    assert (tmp_path / "explorer").is_dir()


def test_native_launcher_resource_is_windows_gui_executable():
    from importlib import resources
    exe = resources.files("sigma.web").joinpath("static", "sigma.exe").read_bytes()
    assert exe[:2] == b"MZ"
    assert len(exe) < 128 * 1024

from __future__ import annotations

from pathlib import Path

import pytest

from sigma.errors import ConfigurationError
from sigma.initialization import initialize, load_initialization, require_initialization
from sigma.paths import initialization_path, sigma_home, source_store_root
from sigma.sources import SourceStore


def test_initialization_uses_visible_home_and_records_valid_geofabrik(tmp_path, monkeypatch):
    home = tmp_path / "Documents" / "SIGMA"
    monkeypatch.setenv("SIGMA_HOME", str(home))

    def fake_ensure(self, *, refresh=False, progress=None, downloader=None):
        pbf = self.root / "fixture" / "philippines.osm.pbf"
        pbf.parent.mkdir(parents=True, exist_ok=True)
        pbf.write_bytes(b"fixture-pbf")
        return self._register_geofabrik(
            pbf,
            metadata={"source_version": "fixture-v1"},
            managed=False,
        )

    monkeypatch.setattr(SourceStore, "ensure_geofabrik", fake_ensure)
    messages: list[str] = []
    state = initialize(progress=messages.append)

    assert sigma_home() == home.resolve()
    assert source_store_root() == (home / "sources").resolve()
    assert initialization_path().is_file()
    assert state.geofabrik.path.is_file()
    loaded = load_initialization()
    assert loaded is not None
    assert loaded.source_store == state.source_store
    assert loaded.geofabrik.source_id == state.geofabrik.source_id
    assert any("places and roads" in message for message in messages)


def test_initialization_is_required_before_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_HOME", str(tmp_path / "not-initialized"))
    assert load_initialization() is None
    with pytest.raises(ConfigurationError, match="sigma init"):
        require_initialization()

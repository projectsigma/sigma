"""Staleness contracts for pre-v4 workspaces, without changing legacy CLI bodies."""
from __future__ import annotations

import json

import pytest

from sigma.economy import hierarchical_auto as ha
from sigma.errors import EconomyValidationError
import sigma.cli as cli


def _legacy_artifacts(root):
    base = root / "hierarchical"
    (base / "economy").mkdir(parents=True)
    (base / "economy" / "audit.json").write_text("{}", encoding="utf-8")
    (base / ".sigma-hierarchical-manifest.json").write_text("{}", encoding="utf-8")


def _minimal_profile(root):
    return {"io240_dir": str(root / "io240"), "crosswalk": str(root / "crosswalk.csv"),
            "min_places": 5, "coarse_policy": "contain", "max_straddle_share": 0.25,
            "check_psa": True}


def test_old_io80_without_hierarchical_outputs_stays_current(tmp_path, monkeypatch):
    """A global profile never converts an existing fixed-default IO80 workspace."""
    monkeypatch.setattr(ha, "_outputs_match_profile", lambda *_: pytest.fail("unwanted legacy IO80 check"))
    assert ha.profile_is_current(tmp_path, _minimal_profile(tmp_path)) is True


def test_old_incomplete_hierarchy_is_not_implicitly_rebuilt(tmp_path, monkeypatch):
    """The earlier v4 nonmigration assertion must remain true."""
    (tmp_path / "hierarchical" / "economy").mkdir(parents=True)
    monkeypatch.setattr(ha, "_outputs_match_profile", lambda *_: pytest.fail("incomplete hierarchy"))
    assert ha.profile_is_current(tmp_path, _minimal_profile(tmp_path)) is True


def test_old_completed_hierarchy_keeps_original_staleness_check(tmp_path, monkeypatch):
    _legacy_artifacts(tmp_path)
    observed = []
    def stale(workspace, profile):
        observed.append((workspace, profile))
        return False
    monkeypatch.setattr(ha, "_outputs_match_profile", stale)
    p = _minimal_profile(tmp_path)
    assert ha.profile_is_current(tmp_path, p) is False
    assert observed == [(tmp_path, p)]
    monkeypatch.setattr(ha, "_outputs_match_profile", lambda *_: True)
    assert ha.profile_is_current(tmp_path, p) is True


def test_implicit_run_cannot_migrate_unrecorded_stale_hierarchy(tmp_path, monkeypatch):
    _legacy_artifacts(tmp_path)
    monkeypatch.setattr(cli, "hierarchical_build", lambda **kw: pytest.fail("unwanted hierarchy rebuild"))
    with pytest.raises(EconomyValidationError, match="legacy hierarchical output is stale"):
        cli._hierarchical_build_from_profile(tmp_path, _minimal_profile(tmp_path))


def test_explicit_load_may_replace_legacy_hierarchy(tmp_path, monkeypatch):
    _legacy_artifacts(tmp_path)
    called = []
    monkeypatch.setattr(cli, "hierarchical_build", lambda **kw: called.append(kw))
    cli._hierarchical_build_from_profile(
        tmp_path, _minimal_profile(tmp_path), allow_unselected_refresh=True
    )
    assert len(called) == 1
    assert called[0]["coarse_policy"] == "contain"
    assert called[0]["min_places"] == 5


def test_explicit_hierarchical_refresh_can_rebuild_legacy_hierarchy(tmp_path, monkeypatch):
    _legacy_artifacts(tmp_path)
    called = []
    monkeypatch.setattr(cli, "hierarchical_build", lambda **kw: called.append(kw))
    cli._hierarchical_build_from_profile(tmp_path, _minimal_profile(tmp_path), json_output=False)
    assert len(called) == 1


def test_recorded_hierarchical_selection_can_refresh_automatically(tmp_path, monkeypatch):
    _legacy_artifacts(tmp_path)
    (tmp_path / "economy-selection.json").write_text(json.dumps({
        "schema_version": 2, "io_level": "hierarchical", "profile_identity": {"min_places": 5}
    }), encoding="utf-8")
    called = []
    monkeypatch.setattr(cli, "hierarchical_build", lambda **kw: called.append(kw))
    cli._hierarchical_build_from_profile(tmp_path, _minimal_profile(tmp_path))
    assert len(called) == 1

"""SIGMA view --fast must be a behavioral alias for --ui-only.

No real browser, data rebuild, output publication, or workspace setup is needed.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner


def _exercise(monkeypatch, tmp_path, option, extra=()):
    import sigma.cli as cli
    import sigma.web as web

    source = tmp_path / "published"
    destination = tmp_path / "explorer"
    calls = []
    monkeypatch.setattr(cli, "_explorer_paths", lambda *_a, **_kw: (source, destination))
    monkeypatch.setattr(web, "bundle_profile", lambda _path: None)
    monkeypatch.setattr(web, "refresh_web_assets", lambda path, *, profile: calls.append(("assets", Path(path), profile)) or 4)
    monkeypatch.setattr(web, "serve_bundle", lambda path, **kwargs: calls.append(("server", Path(path), kwargs)))
    monkeypatch.setattr(web, "bundle_is_current", lambda *_a, **_kw: pytest.fail("fast mode checked data freshness"))
    monkeypatch.setattr(web, "build_web_bundle", lambda *_a, **_kw: pytest.fail("fast mode rebuilt analytical data"))
    result = CliRunner().invoke(cli.app, ["view", "example", option, "--no-browser", *extra])
    return result, calls, destination


@pytest.mark.parametrize("option", ["--fast", "--ui-only"])
def test_fast_and_legacy_alias_refresh_only_assets(monkeypatch, tmp_path, option):
    result, calls, dest = _exercise(monkeypatch, tmp_path, option)
    assert result.exit_code == 0, result.output
    assert ("assets", dest, "local") in calls
    assert len([x for x in calls if x[0] == "assets"]) == 1
    assert len([x for x in calls if x[0] == "server"]) == 1
    assert "analytical data reused" in result.output
    assert "--fast does not check source-data freshness" in result.output


@pytest.mark.parametrize("option", ["--fast", "--ui-only"])
def test_fast_conflicts_with_refresh(monkeypatch, tmp_path, option):
    result, calls, _dest = _exercise(monkeypatch, tmp_path, option, ["--refresh"])
    assert result.exit_code != 0
    assert "--fast/--ui-only cannot be combined with --refresh" in result.output
    assert calls == []


def test_help_lists_both_flags():
    from sigma.cli import app
    result = CliRunner().invoke(app, ["view", "--help"])
    assert result.exit_code == 0, result.output
    assert "--fast" in result.output
    assert "--ui-only" in result.output

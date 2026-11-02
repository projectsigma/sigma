"""Portability, selection and fixed-resolution regression checks (load portability patch v4)."""
import json
import shutil

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from sigma.economy import Economy
from sigma.economy.hierarchical_auto import (
    PACKAGE_REFERENCE, auto_economy, ensure_local_profile, packaged_profile,
    packaged_reference, profile_is_current, profile_path, read_profile, validate_profile_inputs,
)
from sigma.economy.load_policy import (
    SUPPORTED_IO_LEVELS, build_fixed_preview, fixed_selected_places, profile_identity,
    read_selection, selection_path, write_selection,
)
from sigma.errors import EconomyValidationError


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_HOME", str(tmp_path / "sigma_home"))
    return tmp_path / "sigma_home"


def _places(path, rows):
    frame = gpd.GeoDataFrame(pd.DataFrame(rows), geometry=[Point(121 + i * 1e-4, 14.6) for i in range(len(rows))],
                             crs="EPSG:4326")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def _hierarchy_rows(n=30):
    h = pd.read_csv(packaged_reference()["crosswalk"], dtype=str, keep_default_na=False).set_index("io240_code")
    rows = []
    for i in range(n):
        code = ("124", "001", "127")[i % 3]
        rows.append({"canonical_id": f"p{i}", "io240_code": code, "io80_code": h.loc[code, "io80_code"],
                     "io16_code": h.loc[code, "io16_code"], "economy_code": h.loc[code, "io80_code"]})
    return rows


# --- selection file -------------------------------------------------------------

def test_load_selection_uses_workspace_not_global_profile(tmp_path):
    assert SUPPORTED_IO_LEVELS == ("hierarchical", "16", "80", "240", "custom")
    assert selection_path(tmp_path).parent == tmp_path.resolve()
    assert read_selection(tmp_path) is None
    (tmp_path / "economy-selection.json").write_text(json.dumps({
        "schema_version": 1, "io_level": "80", "places_sha256": "hash", "economy_fingerprint": "x"
    }))
    assert read_selection(tmp_path)["io_level"] == "80"   # v2 files remain readable


def test_fixed_80_selects_canonical_economy(tmp_path):
    (tmp_path / "economy-selection.json").write_text(json.dumps({
        "schema_version": 2, "io_level": "80", "places_sha256": "hash", "economy_fingerprint": "x"
    }))
    assert auto_economy(tmp_path).economy_id == Economy.builtin("io80").economy_id
    assert auto_economy(tmp_path, explicit="builtin:io16") is None


def test_invalid_selection_refuses_silent_fallback(tmp_path):
    (tmp_path / "economy-selection.json").write_text('{"schema_version":2,"io_level":"bad"}')
    with pytest.raises(Exception, match="selection"):
        auto_economy(tmp_path)


def test_missing_hierarchical_outputs_fail_closed(tmp_path):
    (tmp_path / "economy-selection.json").write_text(json.dumps({
        "schema_version": 2, "io_level": "hierarchical", "places_sha256": "test", "economy_fingerprint": None,
    }))
    with pytest.raises(Exception, match="rerun sigma load"):
        auto_economy(tmp_path)


def test_custom_resolution_does_not_accidentally_restore_old_hierarchy(tmp_path):
    source = tmp_path / "places" / "places.parquet"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"deliberately minimal source handoff")
    model = Economy.builtin("io16")
    write_selection(tmp_path, "custom", economy=model, economy_spec="builtin:io16")
    assert auto_economy(tmp_path).economy_fingerprint == model.economy_fingerprint


# --- fixed resolutions ----------------------------------------------------------

def test_fixed_io16_preview_follows_edited_handoff(tmp_path):
    economy = Economy.builtin("io16")
    baseline = tmp_path / "places" / "places.parquet"
    rows = [{"canonical_id": "a", "economy_code": "12", "io16_code": "01", "io16_status": "PSIC"},
            {"canonical_id": "b", "economy_code": "22", "io16_code": "02", "io16_status": "PSIC"},
            {"canonical_id": "c", "economy_code": None, "io16_code": None, "io16_status": "UNRESOLVED"}]
    frame = _places(baseline, rows)
    preview = build_fixed_preview(tmp_path, "16", economy)
    write_selection(tmp_path, "16", economy=economy, coverage=preview.coverage)
    assert preview.assigned == 2 and preview.total == 3
    result = gpd.read_parquet(preview.path)
    assert result["economy_code"].astype("string").fillna("").tolist() == ["01", "02", ""]
    assert fixed_selected_places(tmp_path, economy) == preview.path
    assert auto_economy(tmp_path).economy_id == economy.economy_id
    assert fixed_selected_places(tmp_path, Economy.builtin("io80")) is None   # unrelated economy
    # The documented workflow: the user filters the handoff, then runs.
    frame.iloc[:2].assign(io16_code=["03", "02"]).to_parquet(baseline, index=False)
    refreshed = fixed_selected_places(tmp_path, economy)
    assert gpd.read_parquet(refreshed)["economy_code"].astype("string").tolist() == ["03", "02"]
    assert read_selection(tmp_path)["coverage"]["total_places"] == 2


def test_fixed_preview_rejects_codes_outside_economy(tmp_path):
    _places(tmp_path / "places" / "places.parquet", [{"canonical_id": "a", "io16_code": "99"}])
    with pytest.raises(EconomyValidationError, match="outside the requested IO16"):
        build_fixed_preview(tmp_path, "16", Economy.builtin("io16"))


def test_fixed_io240_does_not_impute_coarse_tag(tmp_path):
    model = Economy.from_directory(packaged_reference()["io240_dir"])
    rows = [{"canonical_id": "fine", "economy_code": "01", "io240_code": "001", "io240_status": "EXACT"},
            {"canonical_id": "coarse", "economy_code": "41", "io240_code": "", "io240_status": "AMBIGUOUS"},
            {"canonical_id": "unknown", "economy_code": "", "io240_code": "", "io240_status": "UNRESOLVED"}]
    _places(tmp_path / "places" / "places.parquet", rows)
    preview = build_fixed_preview(tmp_path, "240", model)
    write_selection(tmp_path, "240", economy=model, coverage=preview.coverage)
    assert gpd.read_parquet(preview.path)["economy_code"].astype("string").fillna("").tolist() == ["001", "", ""]
    assert read_selection(tmp_path)["coverage"]["assigned_places"] == 1
    assert fixed_selected_places(tmp_path, model) == preview.path
    assert auto_economy(tmp_path).economy_fingerprint == model.economy_fingerprint


# --- packaged national reference ------------------------------------------------

def test_io240_reference_is_portable_and_integrity_checked():
    reference = packaged_reference()
    model = Economy.from_directory(reference["io240_dir"])
    assert len(model.sectors) == 240 and model.x is not None


def test_integrity_check_ignores_crlf_checkouts(tmp_path):
    """A Windows checkout with core.autocrlf=true must verify the same package."""
    from pathlib import Path
    source = Path(packaged_reference()["io240_dir"]).parent
    copy = tmp_path / "psa_2018_io240"
    shutil.copytree(source, copy, ignore=shutil.ignore_patterns("__pycache__"))
    for path in copy.rglob("*"):
        if path.is_file() and path.suffix in {".csv", ".yml", ".json", ".md"}:
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert packaged_reference(copy)["crosswalk"].endswith("crosswalk.csv")
    (copy / "economy" / "sectors.csv").write_bytes(b"code,label\r\n001,changed\r\n")
    with pytest.raises(EconomyValidationError, match="integrity"):
        packaged_reference(copy)


def test_canonical_io240_parents_match_current_tagging():
    from sigma.classification.reference import load_builtin_io_reference
    from sigma.economy.hierarchical import tagging_consistency
    hierarchy = pd.read_csv(packaged_reference()["crosswalk"], dtype=str, keep_default_na=False)
    assert dict(zip(hierarchy.io240_code, hierarchy.io80_code, strict=True)) == \
        load_builtin_io_reference().io240_parent_map
    actual = hierarchy.set_index("io240_code").io80_code
    assert [actual.loc[c] for c in ("124", "125", "126")] == ["42", "42", "42"]
    assert tagging_consistency(hierarchy)["consistent"]


def test_packaged_labels_are_versioned_names_without_code_prefix():
    from importlib.resources import files
    parents = pd.read_csv(files("sigma.resources.classification").joinpath("io", "io240_parents.csv"),
                          dtype=str, keep_default_na=False)
    labels = {s.code: s.label for s in Economy.from_directory(packaged_reference()["io240_dir"]).sectors}
    for code, name in zip(parents.io240_code, parents.io240_name):
        if name.strip():
            assert labels[code] == " ".join(name.split())
            assert not labels[code].startswith(code + " ")


def test_packaged_io240_reconciles_with_io80_io16():
    """Uses the packager's own acceptance rule; no weighted allocation or improvised parents."""
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts" / "sigma_pack_io240_repo.py"
    spec = importlib.util.spec_from_file_location("sigma_pack_io240_repo", script)
    packer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packer)
    reference = packaged_reference()
    h = pd.read_csv(reference["crosswalk"], dtype=str, keep_default_na=False)
    io240 = Economy.from_directory(reference["io240_dir"])
    z, x = io240.Z_raw.to_numpy(float), io240.x.to_numpy(float)
    results = packer.check_against_builtins(h, z, x, z_decimals=packer.decimals(z),
                                            x_decimals=packer.decimals(x), label="packaged IO240")
    assert all(r["accepted"] for pair in results.values() for r in pair.values())


# --- local defaults file and recorded settings ------------------------------------

def test_no_local_file_keeps_legacy_run_inert_but_load_defaults_residual(home):
    # Never auto-convert an old IO80 workspace just because another area loaded hierarchy.
    assert read_profile() is None
    profile = packaged_profile()
    assert profile["coarse_policy"] == "residual" and profile["min_places"] == 5
    assert profile["max_straddle_share"] == 0.25
    assert profile["io240_dir"] == packaged_reference()["io240_dir"]
    assert not profile_path().exists()


def test_local_defaults_created_once_with_package_reference(home):
    path, created = ensure_local_profile()
    assert created and path == profile_path()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["io240_dir"] == PACKAGE_REFERENCE and stored["crosswalk"] == PACKAGE_REFERENCE
    assert read_profile()["io240_dir"] == packaged_reference()["io240_dir"]
    assert read_profile()["_source"] == str(path)
    assert ensure_local_profile() == (path, False)


def test_changed_settings_are_reported_not_adopted(home, tmp_path):
    from sigma.cli import _hierarchical_build_from_profile
    ws = tmp_path / "workspace"
    places = ws / "places" / "places.parquet"
    frame = _places(places, _hierarchy_rows())
    ensure_local_profile()
    profile = read_profile()
    _hierarchical_build_from_profile(ws, profile)
    write_selection(ws, "hierarchical", profile_identity=profile_identity(profile))
    assert profile_is_current(ws, profile)
    # Same settings + edited places: an ordinary rebuild is allowed.
    frame.iloc[:24].to_parquet(places, index=False)
    assert profile_is_current(ws, profile) is False
    _hierarchical_build_from_profile(ws, profile)
    # Different settings + stale outputs: report, never rebuild silently.
    stored = json.loads(profile_path().read_text(encoding="utf-8"))
    stored.update(coarse_policy="residual", min_places=2)
    profile_path().write_text(json.dumps(stored), encoding="utf-8")
    changed = read_profile()
    frame.iloc[:21].to_parquet(places, index=False)
    with pytest.raises(EconomyValidationError, match="settings changed since it was loaded"):
        profile_is_current(ws, changed)
    # A deliberate refresh with the new settings is accepted and recorded.
    _hierarchical_build_from_profile(ws, changed, json_output=False)
    assert profile_is_current(ws, changed)
    assert read_selection(ws)["profile_identity"]["coarse_policy"] == "residual"


def test_build_report_stays_off_stdout_for_load_and_run(monkeypatch, capsys, tmp_path):
    import sigma.cli as cli
    monkeypatch.setattr(cli, "hierarchical_build", lambda **kw: print('{"report": true}'))
    profile = {"io240_dir": str(tmp_path), "crosswalk": str(tmp_path / "c.csv"), "min_places": 5,
               "check_psa": True}
    cli._hierarchical_build_from_profile(tmp_path, profile)           # load / run
    out = capsys.readouterr()
    assert out.out == "" and '"report"' in out.err
    cli._hierarchical_build_from_profile(tmp_path, profile, json_output=True)   # hierarchical-refresh
    assert '"report"' in capsys.readouterr().out


# --- v4 nonmigration and early preflight contracts -------------------------------

def test_legacy_io80_workspace_is_not_auto_converted_even_after_other_area_load(home, tmp_path):
    ensure_local_profile()  # another area introduced the global hierarchical default
    profile = read_profile()
    assert profile["coarse_policy"] == "residual"
    old = tmp_path / "legacy-io80"
    _places(old / "places" / "places.parquet", _hierarchy_rows(6))
    assert read_selection(old) is None
    assert profile_is_current(old, profile) is True
    assert auto_economy(old) is None  # default Economy remains IO80


def test_unselected_legacy_hierarchy_is_not_rebuilt_automatically(home, tmp_path, monkeypatch):
    ensure_local_profile()
    old = tmp_path / "old-hierarchical"
    (old / "hierarchical" / "economy").mkdir(parents=True)
    # No selection file: do not change legacy economy parameters even if global
    # defaults point elsewhere. Its existing artifact checks remain authoritative.
    monkeypatch.setattr("sigma.economy.hierarchical_auto.validate_profile_inputs",
                        lambda _: (_ for _ in ()).throw(AssertionError("unexpected validation")))
    assert profile_is_current(old, read_profile()) is True


def test_fixed_io80_does_not_need_the_io240_data_even_with_global_profile(home, tmp_path, monkeypatch):
    ensure_local_profile()
    base = tmp_path / "fixed-area" / "places" / "places.parquet"
    _places(base, [{"canonical_id": "a", "io80_code": "01"}])
    economy = Economy.builtin("io80")
    selected = build_fixed_preview(tmp_path / "fixed-area", "80", economy)
    write_selection(tmp_path / "fixed-area", "80", economy=economy, coverage=selected.coverage)
    monkeypatch.setattr("sigma.economy.hierarchical_auto.packaged_reference",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            EconomyValidationError("simulated missing national IO240 files")))
    # Profile reading is path resolution only. Reading/validating the national IO240
    # files is not necessary for a fixed 80/16 or custom run.
    profile = read_profile()
    assert profile["_package_reference"] is True
    assert profile_is_current(tmp_path / "fixed-area", profile) is True
    assert auto_economy(tmp_path / "fixed-area").economy_id == economy.economy_id


def test_early_preflight_rejects_deleted_absolute_reference(home, tmp_path):
    missing = tmp_path / "already-cleaned-up"
    profile = {"io240_dir": str(missing / "economy"),
               "crosswalk": str(missing / "corrected.csv"),
               "coarse_policy": "contain", "min_places": 5,
               "check_psa": True}
    with pytest.raises(EconomyValidationError, match="reference files are missing"):
        validate_profile_inputs(profile)
    assert not (tmp_path / "workspace").exists()  # no area output required for preflight


def test_preflight_verifies_canonical_parents_and_packaged_integrity(home):
    profile = packaged_profile()
    assert profile["_package_reference"] is True
    validate_profile_inputs(profile)


def test_historical_explicit_residual_profile_remains_residual(home):
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {"schema_version": 1, "mode": "area_hierarchical",
           "io240_dir": PACKAGE_REFERENCE, "crosswalk": PACKAGE_REFERENCE,
           "min_places": 5, "check_psa": True}
    path.write_text(json.dumps(old), encoding="utf-8")
    assert read_profile()["coarse_policy"] == "residual"
    assert packaged_profile()["coarse_policy"] == "residual"


def test_v2_selection_without_policy_fingerprint_fails_closed(home, tmp_path):
    ensure_local_profile()
    ws = tmp_path / "older-selection"
    (ws / "places").mkdir(parents=True)
    (ws / "economy-selection.json").write_text(json.dumps({
        "schema_version": 1, "io_level": "hierarchical", "places_sha256": "old",
        "economy_fingerprint": None,
    }), encoding="utf-8")
    with pytest.raises(EconomyValidationError, match="no recorded reference/policy identity"):
        profile_is_current(ws, read_profile())

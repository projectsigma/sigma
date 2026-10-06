from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from sigma import Economy, GeofabrikRoadSource, Sigma, SigmaConfig
from sigma.cli import app, _config
from sigma.errors import ConfigurationError

runner = CliRunner()


@pytest.fixture(autouse=True)
def _initialized_cli(monkeypatch, tmp_path: Path):
    source_store = tmp_path / "initialized-sources"
    source_store.mkdir(parents=True, exist_ok=True)
    geofabrik_path = source_store / "philippines.osm.pbf"
    geofabrik_path.write_bytes(b"fixture")
    state = SimpleNamespace(
        home=tmp_path / "SIGMA",
        source_store=source_store,
        geofabrik=SimpleNamespace(path=geofabrik_path, version="fixture-v1", size=7),
    )
    monkeypatch.setattr("sigma.cli.require_initialization", lambda: state)
    monkeypatch.setattr("sigma.cli.load_initialization", lambda: state)



def test_cli_version_and_area_catalog_surface():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0.dev0" in result.stdout

    result = runner.invoke(app, ["areas", "list", "--search", "Quezon City", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [row["slug"] for row in payload] == ["quezon_city"]


def test_classification_check_verifies_packaged_bytes_without_requiring_pyarrow():
    result = runner.invoke(app, ["classification-check", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["verified_assets"] == payload["asset_count"] == 7
    assert payload["failures"] == []


def test_cli_config_matches_public_profile_constructors():
    canonical = _config(transaction_preprocessing="mwas_ras_fast", distance_tempering=0.25)
    assert canonical.economic.transaction_preprocessing == "mwas_ras_fast"
    assert canonical.economic.legacy_mwas_method is None
    assert canonical.analysis.centrality_method == "katz"
    assert canonical.analysis.distance_tempering == 0.25

    equivalent = _config(equivalent=True, mwas_method="exact")
    public = SigmaConfig.equivalent(mwas_method="exact")
    assert equivalent.spatial.classification == public.spatial.classification == "io80"
    assert equivalent.economic.legacy_mwas_method == public.economic.legacy_mwas_method == "exact"
    assert equivalent.economic.transaction_preprocessing == "none"
    assert equivalent.analysis.centrality_method == public.analysis.centrality_method == "eigenvector"


def test_economy_graph_cli_and_python_api_have_same_target_and_artifact(tmp_path: Path):
    cli_ws = tmp_path / "cli"
    api_ws = tmp_path / "api"
    result = runner.invoke(
        app,
        [
            "economy", "graph", "quezon_city",
            "--workspace", str(cli_ws),
            "--economy", "builtin:io16",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    cli_payload = json.loads(result.stdout)

    api = Sigma(
        "quezon_city",
        workspace=api_ws,
        economy=Economy.builtin("io16"),
        config=SigmaConfig.default(),
    )
    api_ref = api.run_economy().graph
    assert cli_payload["stage"] == api_ref.stage == "economy.graph"
    assert cli_payload["artifact_id"] == api_ref.artifact_id


def test_exact_stage_cli_matches_sigma_ensure(tmp_path: Path):
    cli_ws = tmp_path / "cli-stage"
    api_ws = tmp_path / "api-stage"
    args = [
        "stage", "quezon_city", "economy.coefficients",
        "--workspace", str(cli_ws), "--economy", "builtin:io16", "--json",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    cli_ref = json.loads(result.stdout)

    api = Sigma("quezon_city", workspace=api_ws, economy=Economy.builtin("io16"))
    api_ref = api.ensure("economy.coefficients")
    assert cli_ref["stage"] == "economy.coefficients"
    assert cli_ref["artifact_id"] == api_ref.artifact_id


def test_status_cli_is_inspection_only(tmp_path: Path):
    ws = tmp_path / "status"
    result = runner.invoke(
        app,
        ["status", "quezon_city", "--workspace", str(ws), "--economy", "builtin:io16", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["loaded_places"] == "missing"
    reopened = Sigma(
        "quezon_city", workspace=ws, economy=Economy.builtin("io16"),
        source_store=tmp_path / "initialized-sources",
    )
    assert reopened.workspace.artifacts.active_keys() == ()


def test_recompute_cli_uses_same_forced_stage_semantics(tmp_path: Path):
    ws = tmp_path / "recompute"
    api = Sigma(
        "quezon_city", workspace=ws, economy=Economy.builtin("io16"),
        source_store=tmp_path / "initialized-sources",
    )
    original = api.ensure("economy.graph")
    result = runner.invoke(
        app,
        [
            "recompute", "quezon_city", "economy.graph",
            "--workspace", str(ws), "--economy", "builtin:io16", "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["artifact_id"] == original.artifact_id


def test_full_run_command_delegates_to_sigma_run_without_cli_orchestration(monkeypatch, tmp_path: Path):
    roads = tmp_path / "roads.gpkg"
    roads.write_bytes(b"placeholder")
    calls = {}

    class FakeResult:
        run_manifest = tmp_path / "output" / "sigma_manifest.json"
        outputs = {"sigma_manifest.json": run_manifest}

    class FakeJob:
        places_path = tmp_path / "ws" / "places" / "places.parquet"

        def run(self, *, force=False):
            calls["force"] = force
            return FakeResult()

    def fake_job(**kwargs):
        calls.update(kwargs)
        return FakeJob()

    monkeypatch.setattr("sigma.cli._job", fake_job)
    result = runner.invoke(
        app,
        [
            "run", "quezon_city",
            "--workspace", str(tmp_path / "ws"),
            "--roads", str(roads),
            "--transaction-preprocessing", "mwas_ras_fast",
            "--distance-tempering", "0.3",
            "--force",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert calls["force"] is True
    config = calls["config"]
    assert config.economic.transaction_preprocessing == "mwas_ras_fast"
    assert config.analysis.centrality_method == "katz"
    assert config.analysis.distance_tempering == 0.3




def test_full_run_cli_accepts_explicit_eigenvector_centrality(monkeypatch, tmp_path: Path):
    calls = {}

    class FakeResult:
        run_manifest = tmp_path / "output" / "sigma_manifest.json"
        outputs = {"sigma_manifest.json": run_manifest}

    class FakeJob:
        places_path = tmp_path / "ws" / "places" / "places.parquet"

        def run(self, *, force=False):
            return FakeResult()

    def fake_job(**kwargs):
        calls.update(kwargs)
        return FakeJob()

    monkeypatch.setattr("sigma.cli._job", fake_job)
    result = runner.invoke(
        app,
        ["run", "quezon_city", "--workspace", str(tmp_path / "ws"),
         "--centrality-method", "eigenvector", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    assert calls["config"].analysis.centrality_method == "eigenvector"


def test_full_run_cli_defaults_to_managed_geofabrik_roads(monkeypatch, tmp_path: Path):
    calls = {}

    class FakeResult:
        run_manifest = tmp_path / "output" / "sigma_manifest.json"
        outputs = {"sigma_manifest.json": run_manifest}

    class FakeJob:
        places_path = tmp_path / "ws" / "places" / "places.parquet"

        def run(self, *, force=False):
            calls["force"] = force
            return FakeResult()

    def fake_job(**kwargs):
        calls.update(kwargs)
        return FakeJob()

    monkeypatch.setattr("sigma.cli._job", fake_job)
    result = runner.invoke(
        app,
        ["run", "quezon_city", "--workspace", str(tmp_path / "ws"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    assert isinstance(calls["roads"], GeofabrikRoadSource)
    assert calls["roads_layer"] is None


def test_full_run_cli_can_select_managed_geofabrik_roads(monkeypatch, tmp_path: Path):
    calls = {}

    class FakeResult:
        run_manifest = tmp_path / "output" / "sigma_manifest.json"
        outputs = {"sigma_manifest.json": run_manifest}

    class FakeJob:
        places_path = tmp_path / "ws" / "places" / "places.parquet"

        def run(self, *, force=False):
            calls["force"] = force
            return FakeResult()

    def fake_job(**kwargs):
        calls.update(kwargs)
        return FakeJob()

    monkeypatch.setattr("sigma.cli._job", fake_job)
    result = runner.invoke(
        app,
        [
            "run", "quezon_city",
            "--workspace", str(tmp_path / "ws"),
            "--managed-roads",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert isinstance(calls["roads"], GeofabrikRoadSource)
    assert calls["roads_layer"] is None


def test_managed_roads_and_file_roads_are_mutually_exclusive(tmp_path: Path):
    roads = tmp_path / "roads.gpkg"
    roads.write_bytes(b"fixture")
    result = runner.invoke(
        app,
        [
            "run", "quezon_city",
            "--workspace", str(tmp_path / "ws"),
            "--roads", str(roads),
            "--managed-roads",
        ],
    )
    assert result.exit_code == 2
    assert "either --roads FILE or --managed-roads" in result.output

def test_doctor_reports_complete_declared_runtime_dependency_surface():
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)
    required = {
        "geopandas", "networkx", "numpy", "openpyxl", "osmium", "overturemaps",
        "pandas", "pyarrow", "pyogrio", "PyYAML", "rapidfuzz", "requests", "rich",
        "scikit-learn", "scipy", "shapely", "typer",
    }
    assert set(payload["dependencies"]) == required
    assert set(payload["optional_dependencies"]) == {"openai"}
    expected = 0 if all(payload["dependencies"].values()) else 1
    assert result.exit_code == expected


def test_from_partitions_cli_delegates_to_public_constructor(monkeypatch, tmp_path: Path):
    files = {}
    for name in ("partitions.parquet", "centers.parquet", "points.parquet", "roads.gpkg"):
        path = tmp_path / name
        path.write_bytes(b"fixture")
        files[name] = path
    calls = {}

    class FakeResult:
        run_manifest = tmp_path / "out" / "sigma_manifest.json"
        outputs = {"sigma_manifest.json": run_manifest}

    class FakeJob:
        def run(self):
            calls["run"] = True
            return FakeResult()

    def fake_from_partitions(**kwargs):
        calls.update(kwargs)
        return FakeJob()

    monkeypatch.setattr(Sigma, "from_partitions", staticmethod(fake_from_partitions))
    result = runner.invoke(
        app,
        [
            "from-partitions",
            "--workspace", str(tmp_path / "ws"),
            "--partitions", str(files["partitions.parquet"]),
            "--centers", str(files["centers.parquet"]),
            "--points-with-center-distance", str(files["points.parquet"]),
            "--roads", str(files["roads.gpkg"]),
            "--mwas-method", "exact",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert calls["run"] is True
    assert calls["config"].economic.legacy_mwas_method == "exact"
    assert calls["partitions"] == files["partitions.parquet"]


def test_workflow_command_refuses_to_run_before_initialization(monkeypatch, tmp_path: Path):
    def missing():
        raise ConfigurationError("SIGMA has not been initialized. Run 'sigma init' first.")
    monkeypatch.setattr("sigma.cli.require_initialization", missing)
    result = runner.invoke(
        app, ["economy", "graph", "quezon_city", "--workspace", str(tmp_path / "ws")]
    )
    assert result.exit_code == 2
    assert "sigma init" in result.output


def test_quiet_suppresses_default_timed_progress(monkeypatch, tmp_path: Path):
    calls = {}

    class FakeResult:
        run_manifest = tmp_path / "out" / "sigma_manifest.json"
        outputs = {"sigma_manifest.json": run_manifest}

    class FakeJob:
        places_path = tmp_path / "ws" / "places" / "places.parquet"
        def run(self, *, force=False):
            return FakeResult()

    monkeypatch.setattr("sigma.cli._job", lambda **kwargs: FakeJob())
    normal = runner.invoke(app, ["run", "quezon_city", "--workspace", str(tmp_path / "ws"), "--json"])
    assert normal.exit_code == 0
    assert "analysis input:" in normal.stderr

    quiet = runner.invoke(app, ["--quiet", "run", "quezon_city", "--workspace", str(tmp_path / "ws"), "--json"])
    assert quiet.exit_code == 0
    assert quiet.stderr == ""


def test_load_is_primary_place_handoff_command_and_uses_default_workspace(monkeypatch, tmp_path: Path):
    calls = {}

    class Ref:
        stage = "places.classified"
        artifact_id = "art-fixture"
        path = tmp_path / "artifact"

    class FakeResult:
        canonical = Ref()
        psic_classified = Ref()
        classified_places = Ref()

    class FakeJob:
        def __init__(self, workspace):
            self.places_path = Path(workspace) / "places" / "places.parquet"

        def load(self, *, force=False):
            calls["force"] = force
            return FakeResult()

    def fake_job(**kwargs):
        calls.update(kwargs)
        return FakeJob(kwargs["workspace"])

    monkeypatch.setattr("sigma.cli._job", fake_job)
    result = runner.invoke(app, ["load", "quezon_city", "--json"])
    assert result.exit_code == 0, result.output
    expected = tmp_path / "SIGMA" / "workspaces" / "quezon_city"
    assert Path(calls["workspace"]) == expected
    payload = json.loads(result.stdout)
    assert Path(payload["places_geoparquet"]) == expected / "places" / "places.parquet"

def test_places_namespace_is_not_exposed():
    result = runner.invoke(app, ["places", "--help"])
    assert result.exit_code != 0
    assert "No such command 'places'" in result.output


def test_run_without_workspace_uses_same_initialized_area_workspace(monkeypatch, tmp_path: Path):
    calls = {}

    class FakeResult:
        run_manifest = tmp_path / "out" / "sigma_manifest.json"
        outputs = {"sigma_manifest.json": run_manifest}

    class FakeJob:
        def __init__(self, workspace):
            self.places_path = Path(workspace) / "places" / "places.parquet"
        def run(self, *, force=False):
            return FakeResult()

    def fake_job(**kwargs):
        calls.update(kwargs)
        return FakeJob(kwargs["workspace"])

    monkeypatch.setattr("sigma.cli._job", fake_job)
    result = runner.invoke(app, ["--quiet", "run", "quezon_city", "--json"])
    assert result.exit_code == 0, result.output
    assert Path(calls["workspace"]) == tmp_path / "SIGMA" / "workspaces" / "quezon_city"

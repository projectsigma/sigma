from __future__ import annotations

import json
from pathlib import Path

import pytest

from sigma import Sigma
from sigma.area import Area, BoundarySpec
from sigma.artifacts import ArtifactRecipe
from sigma.classification import crosswalk as crosswalk_module
from sigma.execution import ExecutionPlanner
from sigma.sources import SourceStore
from sigma.stages import StageSpec
from sigma.transport import GeofabrikRoadSource
from sigma.workspace import SigmaWorkspace, _fingerprint


def _area(boundary: Path) -> Area:
    return Area(
        slug="fixture",
        name="Fixture",
        kind="city",
        bbox=(120.0, 14.0, 121.0, 15.0),
        psgc_code="1234567890",
        aliases=("fixture",),
        boundary=BoundarySpec(boundary, layer="boundary", field="id", value="1"),
    )


def test_area_mode_defaults_to_managed_geofabrik_roads_without_running_network_io(tmp_path: Path):
    job = Sigma("quezon_city", workspace=tmp_path / "workspace")
    assert isinstance(job.components.transport.source, GeofabrikRoadSource)
    assert job.workspace.artifacts.active_keys() == ()


def test_workspace_area_identity_is_portable_across_packaged_boundary_paths(tmp_path: Path):
    first = _area(tmp_path / "install-a" / "areas.gpkg")
    root = tmp_path / "workspace"
    created = SigmaWorkspace.create(root, area=first, source_store=tmp_path / "sources")
    semantic_identity = created.area_identity

    moved = _area(tmp_path / "install-b" / "areas.gpkg")
    reopened = SigmaWorkspace.open(root, area=moved)
    assert reopened.area_identity == semantic_identity
    assert reopened.area is not None
    assert reopened.area.boundary is not None
    assert reopened.area.boundary.gpkg == moved.boundary.gpkg


def test_workspace_migrates_legacy_path_based_area_identity(tmp_path: Path):
    first = _area(tmp_path / "old-install" / "areas.gpkg")
    root = tmp_path / "workspace"
    SigmaWorkspace.create(root, area=first, source_store=tmp_path / "sources")
    path = root / "workspace.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["area_identity"] = _fingerprint(payload["area"])
    path.write_text(json.dumps(payload), encoding="utf-8")

    moved = _area(tmp_path / "new-install" / "areas.gpkg")
    reopened = SigmaWorkspace.open(root, area=moved)
    refreshed = json.loads(path.read_text(encoding="utf-8"))
    assert reopened.area_identity == refreshed["area_identity"]
    assert refreshed["area"]["boundary"]["gpkg"] == str(moved.boundary.gpkg)


def test_shapefile_source_identity_includes_sidecars(tmp_path: Path):
    shp = tmp_path / "roads.shp"
    shp.write_bytes(b"geometry")
    shp.with_suffix(".dbf").write_bytes(b"attributes-v1")
    shp.with_suffix(".prj").write_bytes(b"projection")
    store = SourceStore(tmp_path / "store")
    ref = store.register_user_file(shp, name="roads")
    assert {item["path"] for item in ref.metadata["members"]} == {
        "roads.shp", "roads.dbf", "roads.prj"
    }

    shp.with_suffix(".dbf").write_bytes(b"attributes-v2")
    validation = store.validate(ref)
    assert not validation.valid
    assert validation.reason in {"size_changed", "hash_mismatch"}


def test_planner_inspection_flag_is_restored_when_plan_or_status_raises(tmp_path: Path):
    workspace = SigmaWorkspace.create(tmp_path / "workspace", source_store=tmp_path / "sources")

    def recipe(planner, deps):
        return ArtifactRecipe.build("ok", implementation_version="1")

    def execute(planner, recipe, deps, write):
        return {}, {}

    planner = ExecutionPlanner(workspace, {"ok": StageSpec("ok", (), recipe, execute)})
    with pytest.raises(KeyError):
        planner.plan("missing")
    assert "_inspection" not in planner.runtime
    with pytest.raises(KeyError):
        planner.status(["missing"])
    assert "_inspection" not in planner.runtime


def test_builtin_crosswalk_executes_only_reviewed_rule_table():
    assert crosswalk_module._BUILTIN_RULE_FILES == ("psic_rev5.csv", "psic_rev5_reviewed.csv")

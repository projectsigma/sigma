from __future__ import annotations

from pathlib import Path

import pytest

import sigma
from sigma.area import Area, BoundarySpec
from sigma.artifacts import ArtifactRecipe
from sigma.errors import ConfigurationError
from sigma.workspace import SigmaWorkspace


def _area(tmp_path: Path) -> Area:
    return Area(
        slug="fixture",
        name="Fixture",
        kind="city",
        bbox=(120.0, 14.0, 121.0, 15.0),
        psgc_code="1234567890",
        aliases=("example",),
        boundary=BoundarySpec(tmp_path / "boundary.gpkg", layer="boundary", field="id", value="1"),
    )


def test_workspace_create_open_persists_identity_and_area(tmp_path):
    area = _area(tmp_path)
    workspace = SigmaWorkspace.create(
        tmp_path / "workspace",
        area=area,
        source_store=tmp_path / "sources",
        economy_fingerprint="econ",
        taxonomy_fingerprint="tax",
        tagging_fingerprint="tags",
        config_fingerprint="config",
    )
    identity = workspace.identity
    assert workspace.area == area
    assert workspace.sources.root == (tmp_path / "sources").resolve()
    assert workspace.artifacts.root == (tmp_path / "workspace" / "artifacts").resolve()

    reopened = SigmaWorkspace.open(tmp_path / "workspace")
    assert reopened.identity == identity
    assert reopened.area == area
    assert reopened.output_dir == (tmp_path / "workspace" / "output").resolve()


def test_workspace_refuses_accidental_recreate(tmp_path):
    SigmaWorkspace.create(tmp_path / "workspace", source_store=tmp_path / "sources")
    with pytest.raises(ConfigurationError, match="already exists"):
        SigmaWorkspace.create(tmp_path / "workspace", source_store=tmp_path / "sources")


def test_workspace_active_artifact_and_manifest_round_trip(tmp_path):
    workspace = SigmaWorkspace.create(tmp_path / "workspace", source_store=tmp_path / "sources")
    recipe = ArtifactRecipe.build("synthetic.stage", implementation_version="1")
    write = workspace.artifacts.begin_write(recipe)
    write.output("result.txt").write_text("ok", encoding="utf-8")
    ref = workspace.artifacts.commit(write, make_active=True)

    assert workspace.artifact("synthetic.stage") == ref
    assert workspace.manifest("synthetic.stage").artifact_id == ref.artifact_id
    status = workspace.status({"synthetic.stage": recipe})["synthetic.stage"]
    assert status.valid


def test_c16_public_boundary_exposes_workspace_and_facade():
    assert sigma.SigmaWorkspace is SigmaWorkspace
    assert hasattr(sigma, "Sigma")
    assert not hasattr(sigma, "ExecutionPlanner")


def test_workspace_open_rejects_different_area_identity(tmp_path):
    workspace_root = tmp_path / "workspace"
    SigmaWorkspace.create(workspace_root, area=_area(tmp_path), source_store=tmp_path / "sources")
    different = Area(
        slug="other",
        name="Other",
        kind="city",
        bbox=(121.0, 14.0, 122.0, 15.0),
    )
    with pytest.raises(ConfigurationError, match="area identity"):
        SigmaWorkspace.open(workspace_root, area=different)

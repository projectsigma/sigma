"""Safe incremental execution invariants: no historical artifact identity laundering."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sigma.artifacts import ArtifactRecipe, ArtifactStore
from sigma.incremental import (same_semantics, compatible_ref, inspect_plan,
                               guard_execution, restore_active_index_on_error,
                               read_only_plan, read_only_plan_context)
from sigma.config import SigmaConfig
from sigma.analysis.pipeline import AnalysisRunConfig


def test_producer_version_alone_does_not_invalidate_algorithm():
    recipe = ArtifactRecipe.build("analysis.x", implementation_version="stable-v1",
                                  parameters={"x": 2}, producer_version="0.1.0a8")
    assert same_semantics(recipe, replace(recipe, producer_version="0.1.0a9"))
    assert not same_semantics(recipe, replace(recipe, implementation_version="changed"))
    changed = ArtifactRecipe.build("analysis.x", implementation_version="stable-v1",
                                   parameters={"x": 3}, producer_version="0.1.0a9")
    assert not same_semantics(recipe, changed)


def test_area_adjustment_defaults_on_and_can_be_disabled():
    assert SigmaConfig.default().analysis.area_adjustment is True
    assert AnalysisRunConfig().area_adjustment is True
    assert AnalysisRunConfig(area_adjustment=False).area_adjustment is False


def test_read_only_compatible_reuse_checks_content(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    old = ArtifactRecipe.build("analysis.x", implementation_version="algo-v1",
                               producer_version="0.1.0a8")
    write = store.begin_write(old)
    write.output("x.txt").write_text("immutable", encoding="utf-8")
    ref = store.commit(write, make_active=True)
    new = ArtifactRecipe.build("analysis.x", implementation_version="algo-v1",
                               producer_version="0.1.0a9")
    assert compatible_ref(SimpleNamespace(artifacts=store), new).artifact_id == ref.artifact_id
    (ref.path / "x.txt").write_text("CORRUPTED", encoding="utf-8")
    with pytest.raises(RuntimeError, match="integrity"):
        compatible_ref(SimpleNamespace(artifacts=store), new)


def test_katz_area_switch_changes_only_centrality_recipe():
    from sigma.analysis.pipeline import AnalysisPipeline
    pipeline = object.__new__(AnalysisPipeline)
    pipeline.config = AnalysisRunConfig(area_adjustment=True)
    with_area = pipeline._recipe_centrality(None, {"analysis.x": "x",
                                                   "spatial.partitions": "p"})
    pipeline.config = AnalysisRunConfig(area_adjustment=False)
    without_area = pipeline._recipe_centrality(None, {"analysis.x": "x"})
    assert "spatial.partitions" in with_area.dependencies
    assert "spatial.partitions" not in without_area.dependencies
    assert with_area.implementation_version.startswith("tile-perspective")
    assert without_area.implementation_version == "balanced-directed-katz-geomean-v4-scaled-spectrum"


def test_preflight_marks_downstream_uncertain_and_stops_expensive_writes():
    from types import SimpleNamespace
    nodes = [SimpleNamespace(stage="spatial.clusters", action="run", reason="algorithm_changed"),
             SimpleNamespace(stage="spatial.partitions", action="reuse", reason="valid"),
             SimpleNamespace(stage="analysis.centrality", action="reuse", reason="valid")]
    specs = {
        "spatial.clusters": SimpleNamespace(dependencies=()),
        "spatial.partitions": SimpleNamespace(dependencies=("spatial.clusters",)),
        "analysis.centrality": SimpleNamespace(dependencies=("spatial.partitions",)),
    }
    workspace = SimpleNamespace(artifact=lambda stage: object() if stage == "export.bundle" else None)
    planner = SimpleNamespace(stages=specs, plan=lambda target: nodes, runtime={}, workspace=workspace)
    job = SimpleNamespace(_planner_for=lambda target: planner, _runtime_cache={}, workspace=workspace)
    assert inspect_plan(job, "analysis.centrality", print_plan=False, enforce=False) == nodes
    with pytest.raises(RuntimeError, match="Unsafe expensive"):
        inspect_plan(job, "analysis.centrality", print_plan=False)
    planner.runtime = job._runtime_cache
    with pytest.raises(RuntimeError, match="BEFORE expensive"):
        guard_execution(planner, "spatial.clusters")


def test_plan_read_only_context_resets():
    assert read_only_plan() is False
    with read_only_plan_context():
        assert read_only_plan() is True
    assert read_only_plan() is False


def test_failed_run_restores_active_references(tmp_path: Path):
    state = tmp_path / "artifacts" / ".state"
    state.mkdir(parents=True)
    index = state / "active.json"
    index.write_bytes(b'{"old":true}')
    with pytest.raises(RuntimeError, match="interrupted"):
        with restore_active_index_on_error(tmp_path):
            index.write_bytes(b'{"new":true}')
            raise RuntimeError("interrupted")
    assert index.read_bytes() == b'{"old":true}'

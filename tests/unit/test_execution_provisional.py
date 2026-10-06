"""A provisional artifact is accepted by the run that produced it and retried by the next run."""
from __future__ import annotations

from pathlib import Path

from sigma.artifacts import ArtifactRecipe
from sigma.execution import ExecutionPlanner
from sigma.stages import StageSpec
from sigma.workspace import SigmaWorkspace


def _stages(calls: list[int]) -> dict[str, StageSpec]:
    def recipe(planner, deps):
        return ArtifactRecipe.build("prepared", implementation_version="1")

    def execute(planner, recipe, deps, write):
        calls.append(1)
        write.output("value.txt").write_text("fallback", encoding="utf-8")
        return {"cache_reusable": False}, {}

    return {"prepared": StageSpec("prepared", (), recipe, execute)}


def test_provisional_artifact_is_executed_once_per_run_state(tmp_path: Path):
    workspace = SigmaWorkspace.create(tmp_path / "workspace", source_store=tmp_path / "sources")
    calls: list[int] = []
    stages = _stages(calls)

    first = ExecutionPlanner(workspace, stages)
    ref = first.ensure("prepared")
    assert len(calls) == 1

    # The same run: the planner itself, and a second planner that shares its run state.
    sibling = ExecutionPlanner(workspace, stages)
    sibling.runtime = first.runtime
    assert first.ensure("prepared").artifact_id == ref.artifact_id
    assert sibling.ensure("prepared").artifact_id == ref.artifact_id
    assert len(calls) == 1
    assert first.plan("prepared")[-1].action == "reuse"

    # The next run has new run state and retries the stage once.
    later = ExecutionPlanner(workspace, stages)
    step = later.plan("prepared")[-1]
    assert (step.action, step.reason) == ("run", "provisional")
    later.ensure("prepared")
    assert len(calls) == 2
    later.ensure("prepared")
    assert len(calls) == 2

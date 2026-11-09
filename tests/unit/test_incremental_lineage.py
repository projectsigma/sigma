"""Regression coverage for cached base/effective hierarchy swaps.

No road graph, establishment data or production workspace is required.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sigma.artifacts import ArtifactRecipe, ArtifactStore
from sigma.execution import ExecutionPlanner
from sigma.facade import Sigma
from sigma.incremental import (
    find_cached_iterative_rollup,
    guard_execution,
    inspect_plan,
)
from sigma.stages import StageSpec


def _materialize(store, recipe, *, name):
    write = store.begin_write(recipe)
    write.output("data.txt").write_text(name, encoding="utf-8")
    return store.commit(write, make_active=True)


def test_historical_effective_branch_plans_reuse_without_mutating_active(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    base_points = _materialize(
        store, ArtifactRecipe.build("spatial.points", implementation_version="v1",
                                    parameters={"handoff": "baseline"}), name="base"
    )
    base_clusters = _materialize(
        store, ArtifactRecipe.build("spatial.clusters", implementation_version="v1",
                                    dependencies={"spatial.points": base_points}), name="base cluster"
    )
    effective_points = _materialize(
        store, ArtifactRecipe.build("spatial.points", implementation_version="v1",
                                    parameters={"handoff": "effective"}), name="effective"
    )
    effective_clusters = _materialize(
        store, ArtifactRecipe.build("spatial.clusters", implementation_version="v1",
                                    dependencies={"spatial.points": effective_points}),
        name="effective cluster"
    )
    centers = _materialize(
        store, ArtifactRecipe.build("spatial.centers", implementation_version="v1",
                                    dependencies={"spatial.clusters": effective_clusters}), name="center"
    )
    x = _materialize(
        store, ArtifactRecipe.build("analysis.x", implementation_version="v1",
                                    dependencies={"spatial.centers": centers}), name="x"
    )
    _materialize(store, ArtifactRecipe.build("export.bundle", implementation_version="v1"), name="published")

    # Roll-up preparation temporarily selects the BASELINE active branch.
    store._mark_active_validated("spatial.points", base_points)
    store._mark_active_validated("spatial.clusters", base_clusters)
    workspace = SimpleNamespace(artifacts=store, artifact=store.active, root=tmp_path)
    stages = {
        "spatial.points": StageSpec(
            "spatial.points", (),
            lambda p, d: ArtifactRecipe.build("spatial.points", implementation_version="v1",
                                               parameters={"handoff": "effective"}),
            lambda *args: None,
        ),
        "spatial.clusters": StageSpec(
            "spatial.clusters", ("spatial.points",),
            lambda p, d: ArtifactRecipe.build("spatial.clusters", implementation_version="v1",
                                               dependencies=d), lambda *args: None,
        ),
        "spatial.centers": StageSpec(
            "spatial.centers", ("spatial.clusters",),
            lambda p, d: ArtifactRecipe.build("spatial.centers", implementation_version="v1",
                                               dependencies=d), lambda *args: None,
        ),
        "analysis.x": StageSpec(
            "analysis.x", ("spatial.centers",),
            lambda p, d: ArtifactRecipe.build("analysis.x", implementation_version="v1",
                                               dependencies=d), lambda *args: None,
        ),
    }
    planner = ExecutionPlanner(workspace, stages)
    index = tmp_path / "artifacts" / ".state" / "active.json"
    before = index.read_bytes()
    steps, refs = planner.plan_with_refs("analysis.x")
    assert [s.action for s in steps] == ["reuse"] * 4
    assert refs["spatial.points"].artifact_id == effective_points.artifact_id
    assert refs["spatial.clusters"].artifact_id == effective_clusters.artifact_id
    assert refs["analysis.x"].artifact_id == x.artifact_id
    assert index.read_bytes() == before
    job = SimpleNamespace(_planner_for=lambda _: planner, _runtime_cache=planner.runtime,
                          workspace=workspace)
    inspect_plan(job, "analysis.x", print_plan=False)


def test_execution_guard_survives_real_facade_scope(tmp_path):
    facade = object.__new__(Sigma)
    facade._runtime_cache = {
        "_protect_existing_run": True,
        "_allow_expensive": False,
        "_provisional_artifacts": {"previous-run"},
    }
    facade._runtime_depth = 0
    with facade._execution_scope():
        assert facade._runtime_cache["_protect_existing_run"] is True
        assert facade._runtime_cache["_allow_expensive"] is False
        assert "_provisional_artifacts" not in facade._runtime_cache
    assert facade._runtime_depth == 0
    workspace = SimpleNamespace(artifact=lambda s: object() if s == "export.bundle" else None)
    planner = SimpleNamespace(runtime=facade._runtime_cache, workspace=workspace)
    with pytest.raises(RuntimeError, match="BEFORE expensive"):
        guard_execution(planner, "spatial.points")


def test_find_cached_rollup_matches_receipt_and_validates_hashes(tmp_path):
    from sigma.spatial.iterative_rollup import sha256_file

    base = tmp_path / "hierarchical" / "places.parquet"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"test-only fake baseline input")
    baseline = SimpleNamespace(artifact_id="art-baseline", recipe_fingerprint="baseline-recipe")
    economy = SimpleNamespace(economy_fingerprint="economy-baseline")
    receipt = {
        "scheme": "sigma-iterative-residual-rollup-v1",
        "base_economy_fingerprint": economy.economy_fingerprint,
        "base_places_sha256": sha256_file(base),
        "cluster_artifact_id": baseline.artifact_id,
        "cluster_recipe_fingerprint": baseline.recipe_fingerprint,
        "rollup_map": {"one": "other"},
    }
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    identity = hashlib.sha256(raw).hexdigest()
    pack = tmp_path / "hierarchical" / "iterative_rollup" / identity[:24]
    economy_dir = pack / "economy"
    economy_dir.mkdir(parents=True)
    files = {}
    for filename in ["economy.yml", "sectors.csv", "transactions.csv", "total_output.csv",
                     "membership.csv", "rollup_audit.json"]:
        p = economy_dir / filename
        p.write_text(filename, encoding="utf-8")
        files[p.relative_to(pack).as_posix()] = sha256_file(p)
    p = pack / "places.parquet"
    p.write_bytes(b"test effective places")
    files["places.parquet"] = sha256_file(p)
    (pack / "rollup_manifest.json").write_text(
        json.dumps({"receipt": receipt, "recipe_sha256": identity, "file_hashes": files}),
        encoding="utf-8"
    )
    assert find_cached_iterative_rollup(
        workspace_root=tmp_path, base_economy=economy, base_places=base,
        baseline=baseline,
    ) == pack
    # Changing the real baseline input must NOT reuse this roll-up.
    base.write_bytes(b"changed")
    assert find_cached_iterative_rollup(
        workspace_root=tmp_path, base_economy=economy, base_places=base,
        baseline=baseline,
    ) is None
    base.write_bytes(b"test-only fake baseline input")
    (economy_dir / "sectors.csv").write_text("CORRUPTED", encoding="utf-8")
    with pytest.raises(RuntimeError, match="altered"):
        find_cached_iterative_rollup(
            workspace_root=tmp_path, base_economy=economy, base_places=base,
            baseline=baseline,
        )

"""Conservative SIGMA incremental cache compatibility, plan and run guards.

No historical artifact is rewritten or relabelled. Producer-version-only cache
compatibility requires identical stage, algorithm, schema, parameters, inputs,
source identities and resources, plus complete manifest/content validation.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import tempfile

from .artifacts import ArtifactRecipe, ArtifactRef, ArtifactValidation

# Heavy operations for which an existing completed workspace must explicitly opt in.
READ_ONLY_PLAN = ContextVar("sigma_read_only_plan", default=False)


@contextmanager
def read_only_plan_context():
    token = READ_ONLY_PLAN.set(True)
    try:
        yield
    finally:
        READ_ONLY_PLAN.reset(token)


def read_only_plan() -> bool:
    return bool(READ_ONLY_PLAN.get())


EXPENSIVE = frozenset({
    "source.osm_national_pois", "source.osm_area_index",
    "transport.roads", "spatial.points", "spatial.clusters", "spatial.centers",
    "spatial.point_distances", "spatial.partitions", "analysis.x",
})


def same_semantics(a: ArtifactRecipe, b: ArtifactRecipe) -> bool:
    """A package release alone is not an algorithm/data change.

    Algorithm version, schema and every other field MUST be exactly identical.
    """
    left, right = a.to_dict(), b.to_dict()
    left.pop("producer_version", None)
    right.pop("producer_version", None)
    return left == right


def compatible_ref(workspace, recipe: ArtifactRecipe) -> ArtifactRef | None:
    """Find an older immutable artifact with exactly matching semantic recipe.

    Fail closed on ambiguous artifacts and on a corrupted semantic match.
    """
    root = workspace.artifacts.root / recipe.stage
    if not root.is_dir():
        return None
    candidates = []
    for directory in root.iterdir():
        if not directory.is_dir() or not (directory / "artifact.json").is_file():
            continue
        ref = workspace.artifacts.lookup(recipe.stage, directory.name)
        if ref is None:
            continue
        manifest = workspace.artifacts.manifest(ref)
        if not same_semantics(manifest.recipe, recipe):
            continue
        validation = workspace.artifacts.validate(ref)
        if not validation.valid:
            raise RuntimeError(
                f"Cannot reuse {recipe.stage}: compatible artifact {ref.artifact_id} "
                f"failed integrity verification ({validation.reason})"
            )
        if manifest.metadata.get("cache_reusable") is False:
            continue
        candidates.append(ref)
    if len(candidates) > 1:
        raise RuntimeError(
            f"Multiple semantically compatible {recipe.stage} artifacts exist; "
            "select an explicit snapshot before continuing"
        )
    return candidates[0] if candidates else None


def mark_semantic_status(workspace, expected, results):
    """Display intact producer-version-only mismatches as compatible, not stale."""
    for stage, recipe in expected.items():
        item = results.get(stage)
        if item is None or item.valid or item.reason != "implementation_version_changed":
            continue
        ref = workspace.artifact(stage)
        if ref is None:
            continue
        actual = workspace.artifacts.manifest(ref).recipe
        if same_semantics(actual, recipe):
            results[stage] = ArtifactValidation(
                True, "complete", "compatible_producer_version", ref.artifact_id,
                recipe.fingerprint, ref.recipe_fingerprint,
            )
    return results


def guard_execution(planner, stage: str) -> None:
    """Called at the final point before writing an expensive stage."""
    runtime = planner.runtime
    if not runtime.get("_protect_existing_run", False):
        return
    if stage not in EXPENSIVE or runtime.get("_allow_expensive", False):
        return
    if planner.workspace.artifact("export.bundle") is None:
        return  # first-ever run without a completed snapshot
    raise RuntimeError(
        f"SIGMA stopped BEFORE expensive stage {stage!r} because its cache "
        "cannot be reused under current inputs/algorithm. The completed "
        "workspace is preserved. Run 'sigma run AREA --plan' to inspect, "
        "then explicitly use --allow-expensive if the change is intentional."
    )


def inspect_plan(job, target: str, *, allow_expensive: bool = False,
                 print_plan: bool = True, force_stage: str | None = None,
                 enforce: bool = True):
    """Inspect planner actions. Runtime guards ALSO protect unexpected invalidations.

    Planner.plan checks active input identities, but downstream future identities
    cannot always be predicted until a new upstream artifact is computed.
    """
    planner = job._planner_for(target)
    if target not in planner.stages:
        raise ValueError(f"Unknown stage {target!r}; valid stages: {', '.join(sorted(planner.stages))}")
    job._runtime_cache["_protect_existing_run"] = True
    job._runtime_cache["_allow_expensive"] = bool(allow_expensive)
    steps = planner.plan(target)
    # A plan cannot know the future artifact IDs of rerun prerequisites.
    # Conservatively mark descendants MAY_RUN, not misleadingly REUSE.
    dirty = set()
    forecast = []
    for step in steps:
        if force_stage == step.stage:
            action, reason = "RUN", "explicit_recompute"
        elif step.action == "run":
            action = "MAY_RUN" if step.reason == "upstream_output_pending" else "RUN"
            reason = step.reason
        elif any(dep in dirty for dep in planner.stages[step.stage].dependencies):
            action, reason = "MAY_RUN", "upstream_output_may_change"
        else:
            action, reason = "REUSE", step.reason
        if action != "REUSE":
            dirty.add(step.stage)
        forecast.append((step.stage, action, reason))
    if print_plan:
        print(f"SIGMA STAGE PLAN -> {target}")
        for stage, action, reason in forecast:
            print(f"  {action:<7} {stage:<32} {reason}")
        print("MAY_RUN is conservative: exact downstream identity depends on newly computed inputs. "
              "Expensive stages are guarded again at execution time.")
    candidates = [(stage, reason) for stage, action, reason in forecast
                  if action != "REUSE" and stage in EXPENSIVE]
    if (enforce and candidates and job.workspace.artifact("export.bundle") is not None
            and not allow_expensive):
        text = ", ".join(f"{stage} ({reason})" for stage, reason in candidates)
        raise RuntimeError(
            "Unsafe expensive recomputation blocked: " + text +
            ". Historical artifacts are untouched. Run '--plan' to inspect "
            "and use '--allow-expensive' only when you intend to rebuild."
        )
    return steps


@contextmanager
def restore_active_index_on_error(workspace_root: Path):
    """Best-effort active pointer rollback for an interrupted single-process run.

    Does not roll back immutable new artifacts or external published files.
    No claim of full cross-process transactional atomicity is made.
    """
    root = Path(workspace_root) / "artifacts" / ".state"
    path = root / "active.json"
    original = path.read_bytes() if path.exists() else None
    try:
        yield
    except BaseException:
        if original is not None:
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", dir=root, prefix=".rollback-",
                                             suffix=".json", delete=False) as stream:
                stream.write(original)
                temp = Path(stream.name)
            os.replace(temp, path)
        elif path.exists():
            path.unlink()
        print("SIGMA: restored active artifact references after unsuccessful run.", flush=True)
        raise


def find_cached_iterative_rollup(
    *, workspace_root: Path, base_economy, base_places: Path, baseline: ArtifactRef,
) -> Path | None:
    """Identify an existing validated rolled-up economy without rerunning trials.

    The receipt binds the baseline source and unrefined cluster artifact. A stale
    or ambiguous package is never selected. Historical packages are read-only.
    """
    import hashlib
    import json
    from .spatial.iterative_rollup import _validate_existing_package, sha256_file

    base_places_hash = sha256_file(Path(base_places))
    parent = Path(workspace_root) / "hierarchical" / "iterative_rollup"
    if not parent.is_dir():
        return None
    expected = {
        "scheme": "sigma-iterative-residual-rollup-v1",
        "base_economy_fingerprint": base_economy.economy_fingerprint,
        "base_places_sha256": base_places_hash,
        "cluster_artifact_id": baseline.artifact_id,
        "cluster_recipe_fingerprint": baseline.recipe_fingerprint,
    }
    matches: list[Path] = []
    for manifest in sorted(parent.glob("*/rollup_manifest.json")):
        directory = manifest.parent
        if directory.is_symlink() or manifest.is_symlink():
            raise RuntimeError(f"Unsafe roll-up package link: {directory}")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        receipt = data.get("receipt")
        if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items()):
            continue
        # The recipe ID is a SHA256 of the complete receipt, including rollup_map.
        sha = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if data.get("recipe_sha256") != sha or directory.name != sha[:24]:
            raise RuntimeError(f"Invalid cached roll-up receipt: {directory}")
        matches.append(_validate_existing_package(directory, sha))
    if len(matches) > 1:
        raise RuntimeError("Ambiguous matching cached roll-up packages; refusing automatic selection")
    return matches[0] if matches else None

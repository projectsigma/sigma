from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable, Mapping

from .artifacts import ArtifactRecipe, ArtifactRef, ArtifactValidation
from .errors import ArtifactValidationError, ConfigurationError
from .stages import StageSpec
from .workspace import SigmaWorkspace


@dataclass(frozen=True, slots=True)
class ExecutionStep:
    stage: str
    action: str
    reason: str


class ExecutionPlanner:
    """Dependency-aware executor over SIGMA's explicit static stage graph."""

    def __init__(
        self,
        workspace: SigmaWorkspace,
        stages: Mapping[str, StageSpec],
        *,
        progress=None,
    ):
        self.workspace = workspace
        self.stages = dict(stages)
        self.progress = progress
        self.runtime: dict[str, object] = {}
        self._validate_graph()

    def _say(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    def _validate_graph(self) -> None:
        for name, spec in self.stages.items():
            if name != spec.name:
                raise ConfigurationError(f"stage registry key {name!r} does not match spec {spec.name!r}")
            missing = [dep for dep in spec.dependencies if dep not in self.stages]
            if missing:
                raise ConfigurationError(f"stage {name!r} has unknown dependencies: {missing}")
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(name: str) -> None:
            if name in done:
                return
            if name in visiting:
                raise ConfigurationError(f"stage graph contains a cycle at {name!r}")
            visiting.add(name)
            for dep in self.stages[name].dependencies:
                visit(dep)
            visiting.remove(name)
            done.add(name)

        for name in self.stages:
            visit(name)

    def dependency_refs(self, spec: StageSpec, *, force: bool = False) -> dict[str, ArtifactRef]:
        return {dep: self.ensure(dep, force=False) for dep in spec.dependencies}

    def expected_recipe(self, stage: str, *, ensure_dependencies: bool = False) -> ArtifactRecipe:
        spec = self._spec(stage)
        deps: dict[str, ArtifactRef] = {}
        for dep in spec.dependencies:
            ref = self.ensure(dep) if ensure_dependencies else self.workspace.artifact(dep)
            if ref is None:
                raise ConfigurationError(f"cannot build recipe for {stage!r}: dependency {dep!r} is missing")
            deps[dep] = ref
        return spec.recipe(self, deps)

    def ensure(self, stage: str, *, force: bool = False) -> ArtifactRef:
        """Return a valid artifact for ``stage``, creating it and its prerequisites if needed."""
        return self._ensure(stage, force=force, resolved={})

    def _ensure(
        self, stage: str, *, force: bool, resolved: dict[str, ArtifactRef]
    ) -> ArtifactRef:
        """Resolve ``stage`` once per top-level ``ensure`` call.

        Several stages share prerequisites, so a plain recursion reaches the same stage
        through many paths and validates its files each time.  ``resolved`` holds the
        artifacts that this call has already validated or created.
        """
        if stage in resolved:
            self._announce_reuse(stage)
            return resolved[stage]

        spec = self._spec(stage)
        dependencies = {
            dep: self._ensure(dep, force=False, resolved=resolved) for dep in spec.dependencies
        }
        recipe = spec.recipe(self, dependencies)

        if not force:
            exact = self.workspace.artifacts.lookup(stage, recipe.fingerprint)
            if exact is not None:
                validation = self.workspace.artifacts.validate(exact, expected_recipe=recipe)
                if validation.valid:
                    if self._is_reusable(exact):
                        self.workspace.artifacts._mark_active_validated(stage, exact)
                        self._say(f"reuse {stage}")
                        resolved[stage] = exact
                        return exact
                    self._say(f"refresh {stage} (provisional artifact)")

        write = self.workspace.artifacts.begin_write(recipe)
        started = time.monotonic()
        self._say(f"run {stage}")
        try:
            result = spec.execute(self, recipe, dependencies, write)
            metadata: dict[str, object] = {}
            provenance: dict[str, object] = {}
            if result is not None:
                metadata, provenance = result
            ref = self.workspace.artifacts.commit(
                write,
                metadata=metadata,
                provenance=provenance,
                make_active=True,
                logical_key=stage,
            )
        except Exception:
            self.workspace.artifacts.abort(write)
            raise
        if metadata.get("cache_reusable") is False:
            self._provisional_artifacts().add(ref.artifact_id)
        self._say(f"done {stage} ({time.monotonic() - started:.1f}s)")
        resolved[stage] = ref
        return ref

    def _provisional_artifacts(self) -> set[str]:
        """Identities of the provisional artifacts produced in the current run.

        ``runtime`` is shared by all planners of one ``Sigma`` object.  A provisional
        artifact is therefore accepted by the run that produced it, so that analysis and
        export describe the same data, and it is retried by the next run.
        """
        produced = self.runtime.setdefault("_provisional_artifacts", set())
        assert isinstance(produced, set)
        return produced

    def _is_reusable(self, ref: ArtifactRef) -> bool:
        """Whether a valid stored artifact may satisfy its stage without execution."""
        metadata = self.workspace.artifacts.manifest(ref).metadata
        if metadata.get("cache_reusable") is not False:
            return True
        return ref.artifact_id in self._provisional_artifacts()

    def _announce_reuse(self, stage: str) -> None:
        """Report an already resolved stage with the same messages as a full revisit."""
        for dep in self._spec(stage).dependencies:
            self._announce_reuse(dep)
        self._say(f"reuse {stage}")

    def _spec(self, stage: str) -> StageSpec:
        try:
            return self.stages[stage]
        except KeyError as exc:
            raise KeyError(f"unknown SIGMA stage: {stage}") from exc

    def plan(self, target: str) -> tuple[ExecutionStep, ...]:
        """Explain reuse/recompute from current active state without source refresh/acquisition."""
        previous_inspection = self.runtime.get("_inspection")
        self.runtime["_inspection"] = True
        try:
            order: list[str] = []
            seen: set[str] = set()

            def visit(name: str) -> None:
                if name in seen:
                    return
                for dep in self._spec(name).dependencies:
                    visit(dep)
                seen.add(name)
                order.append(name)

            visit(target)
            steps: list[ExecutionStep] = []
            for name in order:
                spec = self._spec(name)
                deps = {dep: self.workspace.artifact(dep) for dep in spec.dependencies}
                if any(ref is None for ref in deps.values()):
                    steps.append(ExecutionStep(name, "run", "dependency_missing"))
                    continue
                try:
                    recipe = spec.recipe(self, {k: v for k, v in deps.items() if v is not None})
                except Exception as exc:
                    steps.append(ExecutionStep(name, "run", f"recipe_unavailable:{type(exc).__name__}"))
                    continue
                exact = self.workspace.artifacts.lookup(name, recipe.fingerprint)
                if exact is not None and self.workspace.artifacts.validate(
                    exact, expected_recipe=recipe
                ).valid:
                    if self._is_reusable(exact):
                        steps.append(ExecutionStep(name, "reuse", "valid"))
                    else:
                        steps.append(ExecutionStep(name, "run", "provisional"))
                    continue
                active = self.workspace.artifact(name)
                if active is None:
                    steps.append(ExecutionStep(name, "run", "missing"))
                else:
                    validation = self.workspace.artifacts.validate(active, expected_recipe=recipe)
                    steps.append(ExecutionStep(name, "run", validation.reason))
            return tuple(steps)
        finally:
            if previous_inspection is None:
                self.runtime.pop("_inspection", None)
            else:
                self.runtime["_inspection"] = previous_inspection

    def status(self, stages: Iterable[str] | None = None) -> dict[str, ArtifactValidation]:
        previous_inspection = self.runtime.get("_inspection")
        self.runtime["_inspection"] = True
        try:
            names = tuple(stages) if stages is not None else tuple(sorted(self.stages))
            expected: dict[str, ArtifactRecipe] = {}
            for name in names:
                spec = self._spec(name)
                deps = {dep: self.workspace.artifact(dep) for dep in spec.dependencies}
                if any(ref is None for ref in deps.values()):
                    continue
                try:
                    expected[name] = spec.recipe(
                        self, {k: v for k, v in deps.items() if v is not None}
                    )
                except Exception:
                    continue
            raw = self.workspace.artifacts.status(expected)
            for name in names:
                raw.setdefault(name, ArtifactValidation(False, "missing", "no_active_artifact"))
            return raw
        finally:
            if previous_inspection is None:
                self.runtime.pop("_inspection", None)
            else:
                self.runtime["_inspection"] = previous_inspection


from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, TYPE_CHECKING

from .artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite

if TYPE_CHECKING:
    from .execution import ExecutionPlanner

RecipeBuilder = Callable[["ExecutionPlanner", Mapping[str, ArtifactRef]], ArtifactRecipe]
StageExecutor = Callable[["ExecutionPlanner", ArtifactRecipe, Mapping[str, ArtifactRef], ArtifactWrite], tuple[dict[str, object], dict[str, object]] | None]


@dataclass(frozen=True, slots=True)
class StageSpec:
    """Small static declaration for one SIGMA stage.

    C8 intentionally keeps this as plain Python data rather than introducing a
    workflow DSL. Domain calculations remain in their owning modules.
    """

    name: str
    dependencies: tuple[str, ...]
    recipe: RecipeBuilder
    execute: StageExecutor

"""Support feasibility, deterministic repair, and RAS/IPF balancing."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

from sigma.errors import EconomyValidationError

from .mwas import MWASResult, fast_mwas, io_network


@dataclass(frozen=True, slots=True)
class SupportRepairResult:
    """Fast-MWAS support after diagonal preservation and deterministic repair."""

    support: np.ndarray
    mwas: MWASResult
    positive_diagonal_count: int
    repair_edge_count: int
    repair_edges: tuple[tuple[str, str, float], ...]


@dataclass(frozen=True, slots=True)
class RASResult:
    """Balanced effective transaction table and numerical diagnostics."""

    table: pd.DataFrame
    iterations: int
    max_abs_row_error: float
    max_rel_row_error: float
    max_abs_column_error: float
    max_rel_column_error: float


def _validate_policy(
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
    max_iterations: int,
) -> tuple[float, float, int]:
    absolute_tolerance = float(absolute_tolerance)
    relative_tolerance = float(relative_tolerance)
    max_iterations = int(max_iterations)
    if not np.isfinite(absolute_tolerance) or absolute_tolerance < 0:
        raise ValueError("RAS absolute tolerance must be finite and non-negative")
    if not np.isfinite(relative_tolerance) or relative_tolerance < 0:
        raise ValueError("RAS relative tolerance must be finite and non-negative")
    if absolute_tolerance == 0 and relative_tolerance == 0:
        raise ValueError("at least one RAS tolerance must be positive")
    if max_iterations < 1:
        raise ValueError("RAS max_iterations must be >= 1")
    return absolute_tolerance, relative_tolerance, max_iterations


def _margin_errors(
    current: np.ndarray,
    target: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    absolute = np.abs(current - target)
    relative = np.zeros_like(absolute, dtype=float)
    positive = np.abs(target) > 0
    relative[positive] = absolute[positive] / np.abs(target[positive])
    relative[~positive] = np.where(absolute[~positive] == 0, 0.0, np.inf)
    return absolute, relative


def _within_tolerance(
    current: np.ndarray,
    target: np.ndarray,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> bool:
    error = np.abs(current - target)
    allowed = absolute_tolerance + relative_tolerance * np.abs(target)
    return bool(np.all(error <= allowed))


def support_is_feasible(
    support: np.ndarray,
    row_targets: np.ndarray,
    column_targets: np.ndarray,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> bool:
    """Return whether non-negative flows on ``support`` can meet both margins.

    This is the standard capacitated transportation-feasibility reduction to a
    bipartite max-flow problem.  Only the support is tested; raw transaction
    magnitudes are not used as capacities on admissible row->column arcs.
    """
    support = np.asarray(support, dtype=bool)
    row_targets = np.asarray(row_targets, dtype=float)
    column_targets = np.asarray(column_targets, dtype=float)
    if support.shape != (len(row_targets), len(column_targets)):
        raise ValueError("support shape does not match row/column margins")
    if (
        not np.isfinite(row_targets).all()
        or not np.isfinite(column_targets).all()
        or np.any(row_targets < 0)
        or np.any(column_targets < 0)
    ):
        raise ValueError("transportation margins must be finite and non-negative")

    row_total = float(row_targets.sum())
    column_total = float(column_targets.sum())
    scale = max(1.0, abs(row_total), abs(column_total))
    total_tolerance = absolute_tolerance + relative_tolerance * scale
    if abs(row_total - column_total) > total_tolerance:
        return False
    if max(row_total, column_total) <= total_tolerance:
        return True

    source = ("source", -1)
    sink = ("sink", -1)
    flow = nx.DiGraph()
    for row, target in enumerate(row_targets):
        if target > 0:
            flow.add_edge(source, ("row", row), capacity=float(target))
    for column, target in enumerate(column_targets):
        if target > 0:
            flow.add_edge(("column", column), sink, capacity=float(target))

    # A capacity equal to the whole table total is effectively unbounded for any
    # single transportation cell while remaining finite for NetworkX algorithms.
    arc_capacity = max(row_total, column_total, 1.0)
    rows, columns = np.where(support)
    for row, column in zip(rows.tolist(), columns.tolist(), strict=True):
        if row_targets[row] > 0 and column_targets[column] > 0:
            flow.add_edge(
                ("row", int(row)),
                ("column", int(column)),
                capacity=arc_capacity,
            )

    value = float(
        nx.maximum_flow_value(
            flow,
            source,
            sink,
            flow_func=nx.algorithms.flow.preflow_push,
        )
    )
    return max(row_total, column_total) - value <= total_tolerance


def fast_mwas_support_with_repair(
    transactions: pd.DataFrame,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> SupportRepairResult:
    """Build the deterministic support used by ``mwas_ras_fast``.

    Fast MWAS proposes off-diagonal support.  Every original positive diagonal is
    then restored.  If the resulting support cannot carry the original row and
    column margins, removed original-positive cells are restored in descending
    ``Z_raw`` weight with stable source/target-code ties until feasibility first
    becomes true.  A monotone binary search finds the same smallest prefix that a
    literal one-edge-at-a-time loop would produce.
    """
    absolute_tolerance, relative_tolerance, _ = _validate_policy(
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        max_iterations=1,
    )
    z = transactions.copy(deep=True)
    if list(z.index) != list(z.columns):
        raise EconomyValidationError("transaction matrix axes must be aligned")
    codes = [str(value) for value in z.index]
    z.index = codes
    z.columns = [str(value) for value in z.columns]
    values = z.to_numpy(dtype=float, copy=False)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise EconomyValidationError("transactions must be finite and non-negative")

    source = io_network(z)
    mwas = fast_mwas(source)
    index = {code: position for position, code in enumerate(codes)}
    support = np.zeros(values.shape, dtype=bool)
    for source_code, target_code in mwas.graph.edges():
        support[index[str(source_code)], index[str(target_code)]] = True

    diagonal = np.diag(values) > 0
    diagonal_indices = np.arange(len(codes), dtype=int)
    support[diagonal_indices[diagonal], diagonal_indices[diagonal]] = True
    positive_diagonal_count = int(np.count_nonzero(diagonal))

    row_targets = values.sum(axis=1)
    column_targets = values.sum(axis=0)
    if support_is_feasible(
        support,
        row_targets,
        column_targets,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    ):
        return SupportRepairResult(
            support=support,
            mwas=mwas,
            positive_diagonal_count=positive_diagonal_count,
            repair_edge_count=0,
            repair_edges=(),
        )

    removed: list[tuple[int, int, float, str, str]] = []
    for row, source_code in enumerate(codes):
        for column, target_code in enumerate(codes):
            weight = float(values[row, column])
            if weight > 0 and not support[row, column]:
                removed.append((row, column, weight, source_code, target_code))
    removed.sort(key=lambda edge: (-edge[2], edge[3], edge[4]))
    if not removed:
        raise EconomyValidationError(
            "raw positive transaction support cannot satisfy its own row/column margins"
        )

    def support_with_prefix(count: int) -> np.ndarray:
        candidate = support.copy()
        for row, column, _weight, _source, _target in removed[:count]:
            candidate[row, column] = True
        return candidate

    # Original positive support is itself a witness, so the full prefix should
    # always be feasible unless numerical/margin validation is inconsistent.
    full = support_with_prefix(len(removed))
    if not support_is_feasible(
        full,
        row_targets,
        column_targets,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    ):
        raise EconomyValidationError(
            "original positive transaction support failed row/column feasibility validation"
        )

    low, high = 1, len(removed)
    while low < high:
        middle = (low + high) // 2
        candidate = support_with_prefix(middle)
        if support_is_feasible(
            candidate,
            row_targets,
            column_targets,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        ):
            high = middle
        else:
            low = middle + 1
    repair_count = low
    final_support = support_with_prefix(repair_count)
    repair_edges = tuple(
        (source_code, target_code, weight)
        for _row, _column, weight, source_code, target_code in removed[:repair_count]
    )
    return SupportRepairResult(
        support=final_support,
        mwas=mwas,
        positive_diagonal_count=positive_diagonal_count,
        repair_edge_count=repair_count,
        repair_edges=repair_edges,
    )


def ras_balance(
    transactions: pd.DataFrame,
    support: np.ndarray,
    *,
    absolute_tolerance: float = 1e-8,
    relative_tolerance: float = 1e-10,
    max_iterations: int = 10_000,
) -> RASResult:
    """Balance admissible cells to the raw table's row and column margins."""
    absolute_tolerance, relative_tolerance, max_iterations = _validate_policy(
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        max_iterations=max_iterations,
    )
    z = transactions.copy(deep=True)
    if list(z.index) != list(z.columns):
        raise EconomyValidationError("transaction matrix axes must be aligned")
    codes = [str(value) for value in z.index]
    z.index = codes
    z.columns = [str(value) for value in z.columns]
    raw = z.to_numpy(dtype=float, copy=True)
    if not np.isfinite(raw).all() or np.any(raw < 0):
        raise EconomyValidationError("transactions must be finite and non-negative")

    support = np.asarray(support, dtype=bool)
    if support.shape != raw.shape:
        raise ValueError("RAS support shape does not match transaction matrix")
    if np.any(support & ~(raw > 0)):
        raise EconomyValidationError(
            "RAS support may contain only cells that are positive in the raw transaction table"
        )

    row_targets = raw.sum(axis=1)
    column_targets = raw.sum(axis=0)
    if not support_is_feasible(
        support,
        row_targets,
        column_targets,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    ):
        raise EconomyValidationError("RAS support cannot satisfy the original row/column margins")

    balanced = np.where(support, raw, 0.0)

    def diagnostics() -> tuple[float, float, float, float, bool]:
        row_current = balanced.sum(axis=1)
        column_current = balanced.sum(axis=0)
        row_abs, row_rel = _margin_errors(row_current, row_targets)
        col_abs, col_rel = _margin_errors(column_current, column_targets)
        converged = _within_tolerance(
            row_current,
            row_targets,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        ) and _within_tolerance(
            column_current,
            column_targets,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        )
        return (
            float(np.max(row_abs, initial=0.0)),
            float(np.max(row_rel, initial=0.0)),
            float(np.max(col_abs, initial=0.0)),
            float(np.max(col_rel, initial=0.0)),
            bool(converged),
        )

    row_abs, row_rel, col_abs, col_rel, converged = diagnostics()
    if converged:
        out = pd.DataFrame(balanced, index=codes, columns=codes, dtype=float)
        return RASResult(out, 0, row_abs, row_rel, col_abs, col_rel)

    for iteration in range(1, max_iterations + 1):
        row_current = balanced.sum(axis=1)
        positive_rows = row_targets > 0
        if np.any(row_current[positive_rows] <= 0):
            raise EconomyValidationError("RAS encountered a positive target row with zero support")
        balanced[positive_rows, :] *= (
            row_targets[positive_rows] / row_current[positive_rows]
        )[:, None]

        column_current = balanced.sum(axis=0)
        positive_columns = column_targets > 0
        if np.any(column_current[positive_columns] <= 0):
            raise EconomyValidationError("RAS encountered a positive target column with zero support")
        balanced[:, positive_columns] *= (
            column_targets[positive_columns] / column_current[positive_columns]
        )[None, :]

        if not np.isfinite(balanced).all() or np.any(balanced < 0):
            raise EconomyValidationError("RAS produced invalid non-finite or negative values")
        if np.any(balanced[~support] != 0):
            raise EconomyValidationError("RAS created a value outside the admissible support")

        row_abs, row_rel, col_abs, col_rel, converged = diagnostics()
        if converged:
            out = pd.DataFrame(balanced, index=codes, columns=codes, dtype=float)
            return RASResult(out, iteration, row_abs, row_rel, col_abs, col_rel)

    raise EconomyValidationError(
        "RAS/IPF did not converge to the configured row/column margin tolerances "
        f"within {max_iterations} iterations; "
        f"max_abs_row_error={row_abs:.17g}, max_rel_row_error={row_rel:.17g}, "
        f"max_abs_column_error={col_abs:.17g}, max_rel_column_error={col_rel:.17g}"
    )

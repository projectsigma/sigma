"""Transaction preprocessing for the canonical economic pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import numpy as np
import pandas as pd

from sigma.errors import ConfigurationError, EconomyValidationError

from .ras import fast_mwas_support_with_repair, ras_balance


@dataclass(frozen=True, slots=True)
class PreprocessingResult:
    table: pd.DataFrame
    diagnostics: Mapping[str, object]


def _validated_transactions(transactions: pd.DataFrame) -> pd.DataFrame:
    z = transactions.copy(deep=True)
    if list(z.index) != list(z.columns):
        raise EconomyValidationError("transaction matrix axes must be aligned")
    ids = [str(value) for value in z.index]
    z.index = ids
    z.columns = [str(value) for value in z.columns]
    values = z.to_numpy(dtype=float, copy=False)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise EconomyValidationError("transactions must be finite and non-negative")
    return z.astype(float)


def preprocess_transactions(
    transactions: pd.DataFrame,
    *,
    mode: str = "none",
    ras_absolute_tolerance: float = 1e-8,
    ras_relative_tolerance: float = 1e-10,
    ras_max_iterations: int = 10_000,
) -> PreprocessingResult:
    """Materialize ``Z_effective`` under the selected execution policy.

    ``none`` is exact identity preprocessing.  ``mwas_ras_fast`` uses preserved
    fast MWAS only to propose sparse support, preserves positive diagonal cells,
    repairs the support using original-positive cells until the raw margins are
    feasible, and then balances to those margins with RAS/IPF.
    """
    normalized = str(mode).strip().casefold()
    if normalized not in {"none", "mwas_ras_fast"}:
        raise ConfigurationError(
            "transaction preprocessing must be 'none' or 'mwas_ras_fast'"
        )
    z = _validated_transactions(transactions)
    values = z.to_numpy(dtype=float, copy=False)

    if normalized == "none":
        diagnostics = MappingProxyType(
            {
                "mode": "none",
                "changed": False,
                "sector_count": int(len(z)),
                "nonzero_count": int(np.count_nonzero(values)),
                "transaction_sum": float(values.sum()),
            }
        )
        z.attrs["transaction_preprocessing"] = "none"
        return PreprocessingResult(z, diagnostics)

    repair = fast_mwas_support_with_repair(
        z,
        absolute_tolerance=float(ras_absolute_tolerance),
        relative_tolerance=float(ras_relative_tolerance),
    )
    balanced = ras_balance(
        z,
        repair.support,
        absolute_tolerance=float(ras_absolute_tolerance),
        relative_tolerance=float(ras_relative_tolerance),
        max_iterations=int(ras_max_iterations),
    )
    effective = balanced.table
    effective_values = effective.to_numpy(dtype=float, copy=False)
    raw_support = values > 0
    effective_support = effective_values > 0
    if np.any(effective_support & ~raw_support):
        raise EconomyValidationError(
            "mwas_ras_fast invented a positive transaction outside the raw support"
        )

    diagnostics = MappingProxyType(
        {
            "mode": "mwas_ras_fast",
            "changed": not np.array_equal(values, effective_values),
            "sector_count": int(len(z)),
            "raw_nonzero_count": int(np.count_nonzero(values)),
            "mwas_method": repair.mwas.method,
            "mwas_source_edge_count": int(repair.mwas.source_edge_count),
            "mwas_proposed_edge_count": int(repair.mwas.retained_edge_count),
            "mwas_retained_weight": float(repair.mwas.retained_weight),
            "mwas_removed_weight": float(repair.mwas.removed_weight),
            "mwas_self_loop_weight": float(repair.mwas.self_loop_weight),
            "positive_diagonal_count": int(repair.positive_diagonal_count),
            "support_repair_edge_count": int(repair.repair_edge_count),
            "final_support_count": int(np.count_nonzero(repair.support)),
            "final_nonzero_count": int(np.count_nonzero(effective_values)),
            "transaction_sum_raw": float(values.sum()),
            "transaction_sum_effective": float(effective_values.sum()),
            "ras_iterations": int(balanced.iterations),
            "ras_absolute_tolerance": float(ras_absolute_tolerance),
            "ras_relative_tolerance": float(ras_relative_tolerance),
            "ras_max_iterations": int(ras_max_iterations),
            "max_abs_row_error": float(balanced.max_abs_row_error),
            "max_rel_row_error": float(balanced.max_rel_row_error),
            "max_abs_column_error": float(balanced.max_abs_column_error),
            "max_rel_column_error": float(balanced.max_rel_column_error),
            "ras_converged": True,
        }
    )
    effective.attrs["transaction_preprocessing"] = "mwas_ras_fast"
    return PreprocessingResult(effective, diagnostics)

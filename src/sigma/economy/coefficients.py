"""Technical coefficients for the effective transaction table."""
from __future__ import annotations

import numpy as np
import pandas as pd

from sigma.errors import EconomyValidationError

from .io_utils import derive_technical_coefficients
from .model import Economy


def _validate_effective_table(economy: Economy, effective: pd.DataFrame) -> pd.DataFrame:
    z = effective.copy(deep=True)
    codes = list(economy.sectors.codes)
    if [str(value) for value in z.index] != codes or [str(value) for value in z.columns] != codes:
        raise EconomyValidationError(
            "effective transaction axes must exactly match the Economy sector catalog order"
        )
    values = z.to_numpy(dtype=float, copy=False)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise EconomyValidationError("effective transactions must be finite and non-negative")
    return z.astype(float)


def effective_technical_coefficients(
    economy: Economy,
    effective_transactions: pd.DataFrame,
    *,
    transaction_preprocessing: str = "none",
) -> pd.DataFrame:
    """Return canonical ``A_effective`` for the selected run.

    ``none`` accepts the legacy explicit-A override when present.  Otherwise
    coefficients are derived with the preserved Engine convention
    ``A_ij = Z_ij / x_j``.  Any future preprocessing mode must derive from the
    processed table and therefore requires ``x``.
    """
    mode = str(transaction_preprocessing).strip().casefold()
    z = _validate_effective_table(economy, effective_transactions)

    if mode == "none" and economy.coefficient_fingerprint is not None:
        a = economy.A_raw
        # Economy already validates this, but keep the execution boundary strict.
        if list(a.index) != list(z.index) or list(a.columns) != list(z.columns):
            raise EconomyValidationError(
                "explicit technical coefficients do not align with effective transactions"
            )
        a.attrs["technical_coefficient_source"] = "explicit_matrix"
        a.attrs["transaction_preprocessing"] = "none"
        return a

    x = economy.x
    if x is None:
        raise EconomyValidationError(
            "technical coefficients require total output when no explicit A override is usable"
        )
    a = derive_technical_coefficients(z, x)
    a.attrs["transaction_preprocessing"] = mode
    return a

"""Generic directed economic graph construction from effective Z and A."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

from sigma.errors import EconomyValidationError

from .model import SectorCatalog


EDGE_COLUMNS = [
    "source_type",
    "target_type",
    "transaction_value",
    "technical_coefficient",
    "weight",
]


@dataclass(frozen=True, slots=True)
class EconomicGraphResult:
    graph: nx.DiGraph
    rows: pd.DataFrame


def build_economic_graph(
    transactions: pd.DataFrame,
    technical_coefficients: pd.DataFrame,
    sectors: SectorCatalog,
) -> EconomicGraphResult:
    """Build the canonical directed economic graph without DAG assumptions.

    Every positive effective transaction becomes an edge and carries both the
    transaction audit value and the technical coefficient.  The technical
    coefficient is the downstream economic weight.  Positive diagonal cells are
    retained as self-loops; reciprocal and longer directed cycles are valid.
    """
    codes = list(sectors.codes)
    z = transactions.copy(deep=True)
    a = technical_coefficients.copy(deep=True)
    for name, frame in (("effective transactions", z), ("technical coefficients", a)):
        if [str(value) for value in frame.index] != codes or [str(value) for value in frame.columns] != codes:
            raise EconomyValidationError(f"{name} must exactly match the Economy sector order")
        values = frame.to_numpy(dtype=float, copy=False)
        if not np.isfinite(values).all() or np.any(values < 0):
            raise EconomyValidationError(f"{name} must be finite and non-negative")

    graph = nx.DiGraph()
    for sector in sectors:
        graph.add_node(sector.code, label=sector.label)

    rows: list[dict[str, object]] = []
    z_values = z.to_numpy(dtype=float, copy=False)
    a_values = a.to_numpy(dtype=float, copy=False)
    for row, source in enumerate(codes):
        for column, target in enumerate(codes):
            transaction_value = float(z_values[row, column])
            if transaction_value <= 0:
                continue
            technical_coefficient = float(a_values[row, column])
            if technical_coefficient <= 0:
                raise EconomyValidationError(
                    "a positive effective transaction must have a positive technical coefficient; "
                    f"got A[{source},{target}]={technical_coefficient}"
                )
            graph.add_edge(
                source,
                target,
                weight=technical_coefficient,
                transaction_value=transaction_value,
                technical_coefficient=technical_coefficient,
            )
            rows.append(
                {
                    "source_type": source,
                    "target_type": target,
                    "transaction_value": transaction_value,
                    "technical_coefficient": technical_coefficient,
                    "weight": technical_coefficient,
                }
            )

    return EconomicGraphResult(graph, pd.DataFrame(rows, columns=EDGE_COLUMNS))

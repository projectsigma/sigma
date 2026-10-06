"""Canonical SIGMA centrality methods for the directed spatial-economic X graph.

Canonical Katz centrality uses both directions of the full directed X graph.  SIGMA
computes raw incoming and outgoing Katz scores with the same attenuation, combines
them by geometric mean, then performs one final L2 normalization.  This suppresses
pure source/sink dominance while preserving directed economic structure.

The previous one-sided directed Katz helper is retained for API compatibility, and
the weighted eigenvector rule remains available explicitly on the positive-weight
undirected projection of X.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import networkx as nx
import numpy as np
from scipy.sparse.linalg import ArpackNoConvergence, eigs


@dataclass(frozen=True)
class CentralityResult:
    """Centrality result plus interpretation and parameter metadata."""

    values: dict[str, float]
    direction: str
    degenerate_dag: bool
    note: str | None
    method: str = "eigenvector"
    alpha: float | None = None
    beta: float | None = None
    spectral_radius: float | None = None
    spectral_scale_kind: str | None = None
    katz_in_raw: dict[str, float] | None = None
    katz_out_raw: dict[str, float] | None = None
    combination: str | None = None
    normalization: str | None = None


def _positive_directed_support(graph: nx.DiGraph) -> nx.DiGraph:
    """Copy X nodes and strictly positive finite weighted edges."""
    support = nx.DiGraph()
    support.add_nodes_from(graph.nodes(data=True))
    for source, target, data in graph.edges(data=True):
        weight = float(data.get("weight", 1.0))
        if not np.isfinite(weight) or weight < 0:
            raise ValueError(
                f"centrality edge {source!r}->{target!r} has invalid weight {weight!r}"
            )
        if weight > 0:
            support.add_edge(source, target, weight=weight)
    return support


def _positive_weight_support(graph: nx.DiGraph) -> nx.Graph:
    """Return the positive-weight undirected projection used by eigenvector mode."""
    support = nx.Graph()
    support.add_nodes_from(graph.nodes(data=True))
    for source, target, data in graph.edges(data=True):
        weight = float(data.get("weight", 1.0))
        if not np.isfinite(weight) or weight < 0:
            raise ValueError(
                f"centrality edge {source!r}->{target!r} has invalid weight {weight!r}"
            )
        if weight == 0:
            continue
        if support.has_edge(source, target):
            support[source][target]["weight"] += weight
        else:
            support.add_edge(source, target, weight=weight)
    return support


def _spectral_radius_or_safe_scale(graph: nx.DiGraph) -> tuple[float, float, str]:
    """Return ``(rho, alpha_scale, scale_kind)`` for a nonnegative directed graph.

    ``alpha_scale`` is always safe for ``alpha_factor / alpha_scale``.  For cyclic
    graphs we estimate the Perron spectral radius directly.  If sparse ARPACK does
    not converge, the maximum weighted row sum is a conservative upper bound.  For
    DAGs the true spectral radius is zero, so the row-sum scale is used only to keep
    the finite Katz path expansion numerically well conditioned.
    """
    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        return 0.0, 1.0, "unit_no_edges"

    row_bound = max(
        (
            sum(float(data.get("weight", 1.0)) for _, _, data in graph.out_edges(node, data=True))
            for node in graph.nodes
        ),
        default=0.0,
    )
    safe_bound = max(float(row_bound), 1.0)

    if nx.is_directed_acyclic_graph(graph):
        return 0.0, safe_bound, "weighted_row_sum_dag"

    nodes = list(graph.nodes)
    matrix = nx.to_scipy_sparse_array(
        graph,
        nodelist=nodes,
        weight="weight",
        dtype=float,
        format="csr",
    )
    try:
        if len(nodes) <= 3:
            eigenvalues = np.linalg.eigvals(matrix.toarray())
        else:
            eigenvalues = eigs(
                matrix,
                k=1,
                which="LM",
                return_eigenvectors=False,
                tol=1e-10,
                maxiter=max(5_000, 20 * len(nodes)),
            )
        rho = float(np.max(np.abs(eigenvalues))) if len(eigenvalues) else 0.0
        if not math.isfinite(rho) or rho < 0:
            raise RuntimeError("spectral-radius calculation returned a non-finite value")
        if rho <= 1e-15:
            return 0.0, safe_bound, "weighted_row_sum_zero_radius"
        return rho, rho, "spectral_radius"
    except (ArpackNoConvergence, RuntimeError, ValueError, TypeError):
        # rho is unknown here.  The induced infinity norm is >= spectral radius,
        # therefore alpha_factor / safe_bound remains strictly safe for factor < 1.
        return float("nan"), safe_bound, "weighted_row_sum_bound"


def _raw_katz(
    graph: nx.DiGraph,
    *,
    alpha: float,
    beta: float,
) -> dict[str, float]:
    """Compute unnormalized weighted Katz scores for one directed orientation."""
    try:
        values = nx.katz_centrality(
            graph,
            alpha=alpha,
            beta=beta,
            max_iter=10_000,
            tol=1e-10,
            normalized=False,
            weight="weight",
        )
    except nx.PowerIterationFailedConvergence as exc:
        raise RuntimeError("weighted directed Katz centrality failed to converge") from exc
    result = {str(node): float(value) for node, value in values.items()}
    array = np.fromiter(result.values(), dtype=float)
    if not np.isfinite(array).all() or (array < -1e-15).any():
        raise RuntimeError("directed Katz centrality produced invalid values")
    return result


def _katz_parameters(
    support: nx.DiGraph,
    *,
    alpha_factor: float,
    beta: float,
) -> tuple[float, float, float | None, str]:
    factor = float(alpha_factor)
    if not math.isfinite(factor) or not 0.0 < factor < 1.0:
        raise ValueError("katz alpha_factor must be finite and strictly between 0 and 1")
    beta_value = float(beta)
    if not math.isfinite(beta_value) or beta_value <= 0:
        raise ValueError("katz beta must be finite and strictly positive")
    rho, alpha_scale, scale_kind = _spectral_radius_or_safe_scale(support)
    alpha = factor / alpha_scale
    rho_value = None if not math.isfinite(rho) else float(rho)
    return alpha, beta_value, rho_value, scale_kind


def directed_katz_centrality(
    graph: nx.DiGraph,
    direction: str = "incoming",
    *,
    alpha_factor: float = 0.85,
    beta: float = 1.0,
) -> CentralityResult:
    """Compute one-sided weighted directed Katz centrality.

    This helper is retained for API compatibility and diagnostics.  Canonical SIGMA
    analysis uses :func:`balanced_katz_centrality` instead.
    """
    direction = str(direction).strip().casefold()
    if direction not in {"incoming", "outgoing"}:
        raise ValueError("centrality direction must be 'incoming' or 'outgoing'")
    support = _positive_directed_support(graph)
    alpha, beta_value, rho_value, scale_kind = _katz_parameters(
        support, alpha_factor=alpha_factor, beta=beta
    )
    if graph.number_of_nodes() == 0:
        return CentralityResult(
            {}, direction, False, "X is empty.", method="katz",
            alpha=alpha, beta=beta_value, spectral_radius=rho_value,
            spectral_scale_kind=scale_kind,
        )

    oriented = support if direction == "incoming" else support.reverse(copy=False)
    raw = _raw_katz(oriented, alpha=alpha, beta=beta_value)
    norm = math.sqrt(sum(value * value for value in raw.values()))
    if not math.isfinite(norm) or norm <= 0:
        raise RuntimeError("directed Katz normalization is undefined")
    values = {node: value / norm for node, value in raw.items()}

    note = (
        f"Centrality is one-sided weighted directed Katz centrality on X ({direction} orientation). "
        f"alpha={alpha:.17g} is derived from alpha_factor={float(alpha_factor):.17g}; "
        f"beta={beta_value:.17g}. Canonical SIGMA analysis uses balanced sender-receiver Katz."
    )
    return CentralityResult(
        values,
        direction,
        nx.is_directed_acyclic_graph(support),
        note,
        method="katz",
        alpha=float(alpha),
        beta=beta_value,
        spectral_radius=rho_value,
        spectral_scale_kind=scale_kind,
        normalization="l2",
    )


def balanced_katz_centrality(
    graph: nx.DiGraph,
    *,
    alpha_factor: float = 0.85,
    beta: float = 1.0,
) -> CentralityResult:
    """Compute sender-receiver Katz using geometric mean then one final normalization.

    Incoming and outgoing Katz components are computed *unnormalized* with the same
    ``alpha`` and ``beta``.  For each node ``i`` SIGMA forms

    ``g_i = sqrt(katz_in_raw_i * katz_out_raw_i)``

    and then L2-normalizes ``g`` exactly once.  The geometric mean is a monotone
    rescaling of the sender-receiver Katz product while keeping the combined score on
    a centrality-like scale and reducing pure source/sink dominance.
    """
    support = _positive_directed_support(graph)
    alpha, beta_value, rho_value, scale_kind = _katz_parameters(
        support, alpha_factor=alpha_factor, beta=beta
    )
    if graph.number_of_nodes() == 0:
        return CentralityResult(
            {}, "balanced", False, "X is empty.", method="katz",
            alpha=alpha, beta=beta_value, spectral_radius=rho_value,
            spectral_scale_kind=scale_kind, katz_in_raw={}, katz_out_raw={},
            combination="geometric_mean", normalization="l2_after_combination",
        )

    incoming = _raw_katz(support, alpha=alpha, beta=beta_value)
    outgoing = _raw_katz(support.reverse(copy=False), alpha=alpha, beta=beta_value)
    nodes = [str(node) for node in support.nodes]
    combined_raw: dict[str, float] = {}
    for node in nodes:
        left = max(0.0, float(incoming[node]))
        right = max(0.0, float(outgoing[node]))
        combined_raw[node] = math.sqrt(left * right)

    norm = math.sqrt(sum(value * value for value in combined_raw.values()))
    if not math.isfinite(norm) or norm <= 0:
        raise RuntimeError("balanced Katz normalization is undefined")
    values = {node: value / norm for node, value in combined_raw.items()}
    array = np.fromiter(values.values(), dtype=float)
    if not np.isfinite(array).all() or (array < -1e-15).any():
        raise RuntimeError("balanced Katz centrality produced invalid values")

    note = (
        "Centrality is balanced sender-receiver weighted Katz on directed X: SIGMA computes "
        "unnormalized incoming and outgoing Katz with the same alpha and beta, takes their "
        "nodewise geometric mean, then applies one final L2 normalization. "
        f"alpha={alpha:.17g} is derived from alpha_factor={float(alpha_factor):.17g}; "
        f"beta={beta_value:.17g}. Directed X is preserved without an undirected projection."
    )
    return CentralityResult(
        values,
        "balanced",
        nx.is_directed_acyclic_graph(support),
        note,
        method="katz",
        alpha=float(alpha),
        beta=beta_value,
        spectral_radius=rho_value,
        spectral_scale_kind=scale_kind,
        katz_in_raw=incoming,
        katz_out_raw=outgoing,
        combination="geometric_mean",
        normalization="l2_after_combination",
    )


def directed_eigenvector_centrality(
    graph: nx.DiGraph,
    direction: str = "incoming",
) -> CentralityResult:
    """Compute the preserved weighted eigenvector option on undirected X support.

    ``direction`` is retained for API compatibility but is deliberately ignored in
    eigenvector mode because the historical SIGMA rule removes direction only in the
    temporary graph used by eigenvector centrality.
    """
    if direction not in {"incoming", "outgoing"}:
        raise ValueError("centrality direction must be 'incoming' or 'outgoing'")
    if graph.number_of_nodes() == 0:
        return CentralityResult({}, "undirected", False, "X is empty.", method="eigenvector")

    work = _positive_weight_support(graph)
    if work.number_of_edges() == 0:
        scale = 1.0 / np.sqrt(work.number_of_nodes())
        values = {str(node): scale for node in work.nodes}
        note = (
            "X has no positive-weight edges after removing directionality; SIGMA assigns "
            "equal unit-norm centrality to all nodes."
        )
        return CentralityResult(values, "undirected", False, note, method="eigenvector")

    try:
        values = nx.eigenvector_centrality(
            work,
            weight="weight",
            max_iter=5_000,
            tol=1e-10,
        )
    except nx.PowerIterationFailedConvergence as exc:
        raise RuntimeError(
            "undirected weighted eigenvector centrality failed to converge"
        ) from exc

    result = {str(node): float(value) for node, value in values.items()}
    array = np.fromiter(result.values(), dtype=float)
    if not np.isfinite(array).all() or (array < -1e-15).any():
        raise RuntimeError("undirected eigenvector centrality produced invalid values")
    note = (
        "Centrality is weighted eigenvector centrality on the positive-weight undirected "
        "projection of X. Directed X edges remain unchanged in audit outputs; the legacy "
        "centrality-direction option is accepted for compatibility but does not alter the result."
    )
    return CentralityResult(result, "undirected", False, note, method="eigenvector")


def compute_centrality(
    graph: nx.DiGraph,
    *,
    method: str = "katz",
    direction: str = "incoming",
    katz_alpha_factor: float = 0.85,
    katz_beta: float = 1.0,
) -> CentralityResult:
    """Dispatch the configured SIGMA centrality method.

    ``direction`` is retained for configuration/API compatibility.  Canonical Katz
    uses both orientations and therefore does not depend on it.
    """
    method_value = str(method).strip().casefold()
    if method_value == "katz":
        return balanced_katz_centrality(
            graph,
            alpha_factor=katz_alpha_factor,
            beta=katz_beta,
        )
    if method_value == "eigenvector":
        return directed_eigenvector_centrality(graph, direction=direction)
    raise ValueError("centrality method must be 'katz' or 'eigenvector'")

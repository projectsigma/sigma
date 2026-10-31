"""Katz scores must not depend on the overall size of the X weights.

For a cyclic X this follows from alpha = 0.85 / rho(W). For an acyclic X, and
when the sparse eigenvalue solver fails, SIGMA divides by the largest weighted
row sum instead. That row sum must be used without a lower bound of 1;
otherwise every X whose weights are below 1 (the normal case for
coefficient / road distance) receives alpha = 0.85 and nearly equal scores.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pytest
from scipy.sparse.linalg import ArpackNoConvergence

import sigma.analysis.centrality as centrality_module
from sigma.analysis import balanced_katz_centrality

DAG_EDGES = [("A", "B", 0.20), ("B", "C", 0.10), ("A", "C", 0.05), ("D", "C", 0.30)]
# Four nodes, so the sparse eigs path (not dense eigvals) is used.
CYCLE_EDGES = [
    ("A", "B", 0.20), ("B", "A", 0.10), ("B", "C", 0.30), ("C", "D", 0.05), ("D", "A", 0.15),
]


def _graph(edges, scale: float) -> nx.DiGraph:
    graph = nx.DiGraph()
    for u, v, weight in edges:
        graph.add_edge(u, v, weight=weight * scale)
    return graph


def _max_row_sum(graph: nx.DiGraph) -> float:
    return max(sum(d["weight"] for _, _, d in graph.out_edges(n, data=True)) for n in graph)


def _assert_same_scores(result, reference):
    assert set(result.values) == set(reference.values)
    for node, value in reference.values.items():
        assert math.isclose(result.values[node], value, rel_tol=1e-8), node


@pytest.mark.parametrize("scale", [1e-6, 1e-3, 1e3])
def test_acyclic_katz_is_invariant_to_weight_scale(scale):
    reference = balanced_katz_centrality(_graph(DAG_EDGES, 1.0))
    graph = _graph(DAG_EDGES, scale)
    result = balanced_katz_centrality(graph)
    assert result.spectral_scale_kind == "weighted_row_sum_dag"
    assert math.isclose(result.alpha * _max_row_sum(graph), 0.85, rel_tol=1e-12)
    _assert_same_scores(result, reference)


def test_acyclic_katz_with_small_weights_is_not_flat():
    values = list(balanced_katz_centrality(_graph(DAG_EDGES, 1e-4)).values.values())
    assert max(values) - min(values) > 0.05


def test_solver_fallback_is_invariant_to_weight_scale(monkeypatch):
    def fail(*args, **kwargs):
        raise ArpackNoConvergence("forced for test", np.array([]), np.array([]))

    monkeypatch.setattr(centrality_module, "eigs", fail)
    reference = balanced_katz_centrality(_graph(CYCLE_EDGES, 1.0))
    result = balanced_katz_centrality(_graph(CYCLE_EDGES, 1e-4))
    assert result.spectral_scale_kind == "weighted_row_sum_bound"
    _assert_same_scores(result, reference)


def test_cyclic_katz_is_invariant_to_weight_scale():
    reference = balanced_katz_centrality(_graph(CYCLE_EDGES, 1.0))
    result = balanced_katz_centrality(_graph(CYCLE_EDGES, 1e-4))
    assert result.spectral_scale_kind == "spectral_radius"
    _assert_same_scores(result, reference)

@pytest.mark.parametrize("scale", [1e-6, 1e-14, 1e-20])
def test_cyclic_spectral_radius_is_scale_invariant_below_old_absolute_cutoff(scale):
    """Scaling W uniformly must not change which spectral scaling path is used."""
    reference = balanced_katz_centrality(_graph(CYCLE_EDGES, 1.0))
    result = balanced_katz_centrality(_graph(CYCLE_EDGES, scale))
    assert reference.spectral_scale_kind == "spectral_radius"
    assert result.spectral_scale_kind == "spectral_radius"
    assert result.spectral_radius is not None and result.spectral_radius > 0
    assert math.isclose(result.alpha * scale, reference.alpha, rel_tol=1e-8)
    _assert_same_scores(result, reference)


@pytest.mark.parametrize("scale", [1e-14, 1e-20])
def test_small_cyclic_dense_spectral_radius_is_scale_invariant(scale):
    """The dense eigenvalue code path (up to three nodes) must also normalize."""
    edges = [("A", "B", 0.2), ("B", "A", 0.1)]
    reference = balanced_katz_centrality(_graph(edges, 1.0))
    result = balanced_katz_centrality(_graph(edges, scale))
    assert result.spectral_scale_kind == "spectral_radius"
    _assert_same_scores(result, reference)


def test_katz_alpha_overflow_is_rejected_instead_of_returning_flat_scores():
    graph = _graph(CYCLE_EDGES, 1e-319)
    with pytest.raises(ValueError, match="Katz alpha is not finite"):
        balanced_katz_centrality(graph)

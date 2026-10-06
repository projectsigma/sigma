from __future__ import annotations

import math

import networkx as nx

from sigma.analysis import (
    balanced_katz_centrality,
    compute_centrality,
    directed_eigenvector_centrality,
    directed_katz_centrality,
)


def test_balanced_katz_uses_geometric_mean_then_final_l2_normalization():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", weight=1.0)
    graph.add_edge("B", "C", weight=1.0)

    result = balanced_katz_centrality(graph)

    assert result.method == "katz"
    assert result.direction == "balanced"
    assert result.combination == "geometric_mean"
    assert result.normalization == "l2_after_combination"
    assert result.katz_in_raw is not None
    assert result.katz_out_raw is not None
    assert result.katz_in_raw["C"] > result.katz_in_raw["B"] > result.katz_in_raw["A"]
    assert result.katz_out_raw["A"] > result.katz_out_raw["B"] > result.katz_out_raw["C"]
    # Pure source/sink endpoints are balanced symmetrically; the transit node wins.
    assert math.isclose(result.values["A"], result.values["C"], rel_tol=1e-12)
    assert result.values["B"] > result.values["A"]
    assert math.isclose(
        math.sqrt(sum(value * value for value in result.values.values())),
        1.0,
        rel_tol=1e-12,
    )
    assert result.degenerate_dag is True


def test_one_sided_directed_katz_helper_remains_available():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", weight=1.0)
    graph.add_edge("B", "C", weight=1.0)

    incoming = directed_katz_centrality(graph, "incoming")
    outgoing = directed_katz_centrality(graph, "outgoing")

    assert incoming.method == "katz"
    assert incoming.direction == "incoming"
    assert outgoing.direction == "outgoing"
    assert incoming.values["C"] > incoming.values["B"] > incoming.values["A"]
    assert outgoing.values["A"] > outgoing.values["B"] > outgoing.values["C"]


def test_katz_alpha_is_strictly_below_inverse_spectral_radius_for_cycle():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", weight=2.0)
    graph.add_edge("B", "A", weight=3.0)

    result = balanced_katz_centrality(graph, alpha_factor=0.85)

    assert result.spectral_radius is not None
    assert result.spectral_radius > 0
    assert result.alpha is not None
    assert result.alpha * result.spectral_radius < 1.0
    assert math.isclose(result.alpha * result.spectral_radius, 0.85, rel_tol=1e-8)


def test_eigenvector_remains_explicit_undirected_option():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", weight=1.0)
    graph.add_edge("B", "C", weight=1.0)

    incoming = directed_eigenvector_centrality(graph, "incoming")
    outgoing = directed_eigenvector_centrality(graph, "outgoing")

    assert incoming.method == "eigenvector"
    assert incoming.direction == "undirected"
    assert incoming.values == outgoing.values
    assert incoming.values["B"] > incoming.values["A"]
    assert math.isclose(incoming.values["A"], incoming.values["C"], rel_tol=1e-9)


def test_compute_centrality_defaults_to_balanced_katz():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", weight=1.0)
    result = compute_centrality(graph)
    assert result.method == "katz"
    assert result.direction == "balanced"
    assert result.combination == "geometric_mean"
    assert result.normalization == "l2_after_combination"


def test_zero_weight_edges_do_not_drive_either_method():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", weight=0.0)
    graph.add_edge("B", "C", weight=0.0)

    katz = balanced_katz_centrality(graph)
    eigen = directed_eigenvector_centrality(graph)

    expected = 1.0 / math.sqrt(3.0)
    assert all(math.isclose(value, expected, rel_tol=1e-12) for value in katz.values.values())
    assert all(math.isclose(value, expected, rel_tol=1e-12) for value in eigen.values.values())


def test_invalid_centrality_configuration_fails_closed():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", weight=1.0)

    for call in (
        lambda: directed_katz_centrality(graph, "sideways"),
        lambda: balanced_katz_centrality(graph, alpha_factor=1.0),
        lambda: balanced_katz_centrality(graph, beta=0.0),
        lambda: compute_centrality(graph, method="pagerank"),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid centrality configuration must fail")

    graph["A"]["B"]["weight"] = -1.0
    for call in (
        lambda: balanced_katz_centrality(graph),
        lambda: directed_katz_centrality(graph),
        lambda: directed_eigenvector_centrality(graph),
    ):
        try:
            call()
        except ValueError as exc:
            assert "invalid weight" in str(exc)
        else:
            raise AssertionError("negative X weight must fail")

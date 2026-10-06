"""Preserved maximum-weight acyclic-subgraph utilities from sigma-engine.

These functions remain available for compatibility/reproducibility.  In the new
canonical economic pipeline, fast MWAS is used only by the optional
``mwas_ras_fast`` transaction preprocessor as a sparse-support proposal; its
weights are never downstream economic weights.
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


@dataclass(frozen=True)
class MWASResult:
    """Acyclic IO subgraph plus optimization/audit metadata."""

    graph: nx.DiGraph
    method: str
    exact: bool
    optimal: bool
    solver_status: str | None
    source_weight: float
    retained_weight: float
    removed_weight: float
    self_loop_weight: float
    source_edge_count: int
    retained_edge_count: int
    removed_edge_count: int


def io_network(table: pd.DataFrame) -> nx.DiGraph:
    """Convert a validated transaction table into a weighted directed IO graph."""
    if list(table.index) != list(table.columns):
        raise ValueError("IO table axes must be aligned before graph construction")

    values = table.to_numpy(dtype=float, copy=False)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("IO table values must be finite and non-negative")

    graph = nx.DiGraph()
    graph.add_nodes_from(str(sector) for sector in table.index)

    sectors = [str(sector) for sector in table.index]
    for row, source in enumerate(sectors):
        for column, target in enumerate(sectors):
            weight = float(values[row, column])
            # Positive self-use remains in the source IO graph for faithful accounting.
            # No self-loop can belong to a DAG, so every MWAS method necessarily excludes
            # it from the retained acyclic subgraph while still counting its weight as removed.
            if weight <= 0:
                continue
            graph.add_edge(source, target, weight=weight)
    return graph


def _validate_weighted_digraph(graph: nx.DiGraph) -> None:
    """Validate the non-negative directed graph required by both MWAS methods."""
    if not graph.is_directed():
        raise ValueError("MWAS requires a directed graph")
    for source, target, data in graph.edges(data=True):
        if "weight" not in data:
            raise ValueError(f"IO edge {source!r}->{target!r} is missing weight")
        weight = float(data["weight"])
        if not np.isfinite(weight) or weight < 0:
            raise ValueError(
                f"IO edge {source!r}->{target!r} has invalid non-negative finite weight: "
                f"{data['weight']!r}"
            )


def _graph_weight(graph: nx.DiGraph) -> float:
    return float(sum(float(data["weight"]) for _, _, data in graph.edges(data=True)))


def _candidate_edges(graph: nx.DiGraph) -> list[tuple[object, object, float]]:
    """Return deterministic positive, non-self IO edges eligible for a DAG."""
    return sorted(
        (
            (source, target, float(data["weight"]))
            for source, target, data in graph.edges(data=True)
            if source != target and float(data["weight"]) > 0.0
        ),
        key=lambda edge: (str(edge[0]), str(edge[1])),
    )


def _result(
    source: nx.DiGraph,
    dag: nx.DiGraph,
    *,
    method: str,
    exact: bool,
    optimal: bool,
    solver_status: str | None,
) -> MWASResult:
    if not nx.is_directed_acyclic_graph(dag):
        raise RuntimeError(f"{method} MWAS produced a cyclic graph")
    source_weight = _graph_weight(source)
    retained_weight = _graph_weight(dag)
    removed_weight = source_weight - retained_weight
    scale = max(1.0, abs(source_weight))
    if removed_weight < -1e-10 * scale:
        raise RuntimeError("MWAS retained more total weight than exists in the source graph")
    self_loop_weight = float(
        sum(
            float(data["weight"])
            for source_node, target_node, data in source.edges(data=True)
            if source_node == target_node
        )
    )
    return MWASResult(
        graph=dag,
        method=method,
        exact=exact,
        optimal=optimal,
        solver_status=solver_status,
        source_weight=source_weight,
        retained_weight=retained_weight,
        removed_weight=max(0.0, float(removed_weight)),
        self_loop_weight=self_loop_weight,
        source_edge_count=int(source.number_of_edges()),
        retained_edge_count=int(dag.number_of_edges()),
        removed_edge_count=int(source.number_of_edges() - dag.number_of_edges()),
    )


def fast_mwas(graph: nx.DiGraph) -> MWASResult:
    """Return SIGMA's deterministic fast MWAS heuristic.

    Edges are considered in descending weight order, with source/target string
    order used only to make equal-weight ties deterministic.  An edge is accepted
    iff there is not already a path from its target back to its source.
    """
    _validate_weighted_digraph(graph)
    dag = nx.DiGraph()
    dag.add_nodes_from(graph.nodes(data=True))
    edges = sorted(
        _candidate_edges(graph),
        key=lambda edge: (-edge[2], str(edge[0]), str(edge[1])),
    )
    for source, target, weight in edges:
        if nx.has_path(dag, target, source):
            continue
        dag.add_edge(source, target, weight=weight)
    return _result(
        graph,
        dag,
        method="fast_greedy",
        exact=False,
        optimal=False,
        solver_status=None,
    )


def exact_mwas(graph: nx.DiGraph) -> MWASResult:
    """Solve weighted MWAS exactly with a topological-rank MILP."""
    _validate_weighted_digraph(graph)
    nodes = sorted(graph.nodes, key=str)
    edges = _candidate_edges(graph)
    n = len(nodes)
    m = len(edges)
    if m == 0:
        dag = nx.DiGraph()
        dag.add_nodes_from(graph.nodes(data=True))
        return _result(
            graph,
            dag,
            method="exact_milp",
            exact=True,
            optimal=True,
            solver_status="trivial",
        )

    node_index = {node: idx for idx, node in enumerate(nodes)}
    weights = np.asarray([edge[2] for edge in edges], dtype=float)
    weight_scale = float(max(1.0, np.max(weights)))
    objective = np.zeros(m + n, dtype=float)
    objective[:m] = -(weights / weight_scale)

    row = np.repeat(np.arange(m, dtype=np.int64), 3)
    col = np.empty(3 * m, dtype=np.int64)
    data = np.empty(3 * m, dtype=float)
    for edge_idx, (source, target, _weight) in enumerate(edges):
        base = 3 * edge_idx
        col[base] = edge_idx
        data[base] = float(n)
        col[base + 1] = m + node_index[source]
        data[base + 1] = 1.0
        col[base + 2] = m + node_index[target]
        data[base + 2] = -1.0
    matrix = coo_matrix((data, (row, col)), shape=(m, m + n)).tocsr()
    constraints = LinearConstraint(
        matrix,
        lb=np.full(m, -np.inf, dtype=float),
        ub=np.full(m, float(n - 1), dtype=float),
    )
    lower = np.zeros(m + n, dtype=float)
    upper = np.concatenate(
        [np.ones(m, dtype=float), np.full(n, float(max(0, n - 1)), dtype=float)]
    )
    result = milp(
        c=objective,
        integrality=np.ones(m + n, dtype=np.int8),
        bounds=Bounds(lower, upper),
        constraints=constraints,
        options={"mip_rel_gap": 0.0, "presolve": True},
    )
    if not bool(result.success) or int(result.status) != 0 or result.x is None:
        raise RuntimeError(
            "exact MWAS did not return a proven optimum: "
            f"status={result.status}, message={result.message}"
        )

    dag = nx.DiGraph()
    dag.add_nodes_from(graph.nodes(data=True))
    selected = np.asarray(result.x[:m]) > 0.5
    for keep, (source, target, weight) in zip(selected, edges, strict=True):
        if keep:
            dag.add_edge(source, target, weight=weight)
    return _result(
        graph,
        dag,
        method="exact_milp",
        exact=True,
        optimal=True,
        solver_status=str(result.message),
    )


def solve_mwas(graph: nx.DiGraph, *, method: str = "fast") -> MWASResult:
    """Solve/approximate MWAS with ``fast`` (default) or ``exact`` mode."""
    if method == "fast":
        return fast_mwas(graph)
    if method == "exact":
        return exact_mwas(graph)
    raise ValueError("MWAS method must be 'fast' or 'exact'")


def maximum_weight_acyclic_subgraph(
    graph: nx.DiGraph,
    *,
    exact: bool = False,
) -> nx.DiGraph:
    """Compatibility API returning only the MWAS graph."""
    return solve_mwas(graph, method="exact" if exact else "fast").graph

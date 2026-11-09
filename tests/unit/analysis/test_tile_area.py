"""Tile-perspective area-adjusted balanced Katz (stages 15-16)."""
from __future__ import annotations

import json
import math

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from scipy.sparse import csr_matrix, diags, identity
from scipy.sparse.linalg import spsolve
from shapely.geometry import box

import sigma.analysis.tile_area as tile_area
from sigma.analysis import balanced_katz_centrality, make_node_id


def _case(n=60, p=0.08, *, acyclic=False, equal_area=False, seed=3):
    """Nodes, edges (as read from CSV), partitions in an equal-area CRS, and the graph."""
    rng = np.random.default_rng(seed)
    types = [f"T{rng.integers(0, 6)}" for _ in range(n)]
    ids = [make_node_id(t, c) for t, c in zip(types, range(n), strict=True)]
    src, dst = np.nonzero(rng.random((n, n)) < p)
    keep = src != dst
    if acyclic:
        keep &= src < dst
    src, dst = src[keep], dst[keep]
    weight = rng.lognormal(-14.0, 1.5, len(src))
    nodes = pd.DataFrame({"node_id": ids, "type": types, "cluster": [str(c) for c in range(n)]})
    edges = pd.DataFrame({
        "source_type": [types[i] for i in src], "source_cluster": [str(i) for i in src],
        "target_type": [types[j] for j in dst], "target_cluster": [str(j) for j in dst],
        "edge_weight": [f"{w:.17g}" for w in weight],
    })
    side = np.full(n, 800.0) if equal_area else np.exp(rng.normal(6.5, 1.0, n))
    x0 = rng.uniform(0.0, 30_000.0, n)
    y0 = 1_600_000.0 + rng.uniform(0.0, 30_000.0, n)
    partitions = gpd.GeoDataFrame(
        {"type": types, "cluster": np.arange(n)},
        geometry=[box(a, b, a + s, b + s) for a, b, s in zip(x0, y0, side, strict=True)],
        crs="EPSG:6933",
    )
    graph = nx.DiGraph()
    graph.add_nodes_from(ids)
    for i, j, w in zip(src, dst, weight, strict=True):
        graph.add_edge(ids[i], ids[j], weight=float(w))
    return nodes, edges, partitions, graph


def _matrix(nodes, edges):
    index = tile_area._node_index(nodes, "type", "cluster")
    source, target, weight = tile_area._edge_arrays(index, edges)
    n = len(nodes)
    W = csr_matrix((weight, (source, target)), shape=(n, n))
    return W, W.transpose().tocsr()


def test_ppml_recovers_known_exponent_and_solves_score_equations():
    rng = np.random.default_rng(0)
    log_area = rng.normal(0.0, 1.5, 20_000)
    y = rng.poisson(np.exp(1.0 + 0.4 * log_area)).astype(float)
    fit = tile_area._ppml(y, log_area, "degree", required=True)
    assert fit["status"] == "ok"
    assert abs(fit["area_elasticity"] - 0.4) < 0.01
    mu = np.exp(fit["intercept_log_area_km2"] + fit["area_elasticity"] * log_area)
    X = np.column_stack((np.ones_like(log_area), log_area))
    assert np.max(np.abs(X.T @ (y - mu))) / y.sum() < 1e-6
    assert 0 < fit["robust_se_hc1"] < 0.01


def test_unit_factor_reproduces_existing_balanced_katz():
    nodes, edges, _, graph = _case()
    W, Wt = _matrix(nodes, edges)
    ones = np.ones(len(nodes))
    scale = tile_area._spectral_scale(W, Wt, ones, acyclic=False)
    alpha = 0.85 / scale["scale"]
    incoming, outgoing, _ = tile_area._tile_katz(W, Wt, ones, alpha, 1.0)
    reference = balanced_katz_centrality(graph)
    assert scale["method"] == "spectral_radius"
    # The existing solver starts ARPACK from a random vector: agreement is to ARPACK tolerance.
    assert math.isclose(alpha, reference.alpha, rel_tol=1e-9)
    ids = nodes["node_id"].tolist()
    np.testing.assert_allclose(incoming, [reference.katz_in_raw[i] for i in ids], rtol=1e-8)
    np.testing.assert_allclose(outgoing, [reference.katz_out_raw[i] for i in ids], rtol=1e-8)


def test_adjusted_katz_matches_direct_solve_and_shared_radius():
    nodes, edges, partitions, _ = _case()
    result, diagnostics, audit = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    W, _ = _matrix(nodes, edges)
    F = diags(audit["area_factor"].to_numpy())
    ids = nodes["node_id"].tolist()
    eye = identity(len(ids), format="csc")
    direct_out = spsolve((eye - result.alpha * (F @ W)).tocsc(), np.ones(len(ids)))
    direct_in = spsolve((eye - result.alpha * (F @ W.T)).tocsc(), np.ones(len(ids)))
    np.testing.assert_allclose([result.katz_out_raw[i] for i in ids], direct_out, rtol=1e-8)
    np.testing.assert_allclose([result.katz_in_raw[i] for i in ids], direct_in, rtol=1e-8)
    rho_out = np.max(np.abs(np.linalg.eigvals((F @ W).toarray())))
    rho_in = np.max(np.abs(np.linalg.eigvals((F @ W.T).toarray())))
    assert math.isclose(rho_out, rho_in, rel_tol=1e-9)
    assert math.isclose(diagnostics["spectral_radius"], rho_out, rel_tol=1e-8)
    assert diagnostics["regression"]["status"] == "ok"


def test_constant_area_is_exact_no_op_and_diagnostics_are_strict_json():
    nodes, edges, partitions, graph = _case(equal_area=True)
    messages = []
    result, diagnostics, audit = tile_area.calculate_tile_area_katz(
        nodes, edges, partitions, progress=messages.append,
    )
    assert diagnostics["gamma"] is None
    assert diagnostics["regression"]["status"] == "not_identified_constant_area"
    assert (audit["area_factor"] == 1.0).all()
    assert any("exact no-op" in message for message in messages)
    reference = balanced_katz_centrality(graph)
    for node, value in reference.values.items():
        assert math.isclose(result.values[node], value, rel_tol=1e-8)
    json.dumps(diagnostics, allow_nan=False)


def test_acyclic_x_uses_row_sum_scale_not_arpack():
    nodes, edges, partitions, _ = _case(acyclic=True, seed=5)
    result, diagnostics, audit = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    assert diagnostics["acyclic_x"] is True
    assert result.degenerate_dag is True
    assert diagnostics["spectral_scale_method"] == "weighted_row_sum_dag"
    assert diagnostics["spectral_radius"] == 0.0
    bound = diagnostics["outgoing_row_bound"]
    assert math.isclose(result.alpha, 0.85 / bound, rel_tol=1e-12)
    W, _ = _matrix(nodes, edges)
    F = diags(audit["area_factor"].to_numpy())
    eye = identity(len(nodes), format="csc")
    direct = spsolve((eye - result.alpha * (F @ W)).tocsc(), np.ones(len(nodes)))
    ids = nodes["node_id"].tolist()
    np.testing.assert_allclose([result.katz_out_raw[i] for i in ids], direct, rtol=1e-8)
    assert max(result.katz_out_raw.values()) < 10.0
    json.dumps(diagnostics, allow_nan=False)


def test_edgeless_x_is_exact_no_op_like_existing_solver():
    nodes, edges, partitions, graph = _case()
    edges = edges.iloc[0:0]
    graph.remove_edges_from(list(graph.edges))
    result, diagnostics, _ = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    reference = balanced_katz_centrality(graph)
    assert diagnostics["regression"]["status"] == "not_identified_no_edges"
    assert diagnostics["spectral_scale_method"] == reference.spectral_scale_kind == "unit_no_edges"
    assert math.isclose(result.alpha, reference.alpha, rel_tol=1e-15)
    for node, value in reference.values.items():
        assert math.isclose(result.values[node], value, rel_tol=1e-15)
    json.dumps(diagnostics, allow_nan=False)


def test_center_without_tile_stops_with_count_and_examples():
    nodes, edges, partitions, _ = _case()
    with pytest.raises(ValueError, match=r"1 X centers have edges but no final Voronoi tile"):
        tile_area.calculate_tile_area_katz(nodes, edges, partitions.iloc[1:])


def test_weights_parse_exactly_like_load_x():
    nodes, edges, _, _ = _case()
    index = tile_area._node_index(nodes, "type", "cluster")
    _, _, weight = tile_area._edge_arrays(index, edges)
    np.testing.assert_array_equal(weight, edges["edge_weight"].map(float).to_numpy())


def test_duplicate_edges_are_rejected_before_estimation(monkeypatch):
    nodes, edges, partitions, _ = _case()
    doubled = pd.concat([edges, edges.iloc[:1]], ignore_index=True)

    def no_fit(*args, **kwargs):
        raise AssertionError("the exponent must not be estimated on a corrupt X")

    monkeypatch.setattr(tile_area, "_ppml", no_fit)
    with pytest.raises(ValueError, match="Duplicate directed X edges"):
        tile_area.calculate_tile_area_katz(nodes, doubled, partitions)


def test_stored_degrees_are_cross_checked():
    nodes, edges, partitions, _ = _case()
    index = tile_area._node_index(nodes, "type", "cluster")
    source, target, _ = tile_area._edge_arrays(index, edges)
    nodes = nodes.assign(
        out_degree=np.bincount(source, minlength=len(nodes)).astype(str),
        in_degree=np.bincount(target, minlength=len(nodes)).astype(str),
    )
    tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    broken = nodes.copy()
    broken.loc[0, "out_degree"] = str(int(broken.loc[0, "out_degree"]) + 1)
    with pytest.raises(ValueError, match="out_degree disagrees"):
        tile_area.calculate_tile_area_katz(broken, edges, partitions)


def test_diagnostic_fit_failure_is_recorded_but_required_fit_raises(monkeypatch):
    class Failed:
        fun = float("nan")
        x = np.array([0.0, 0.0])
        message = "forced failure"

    monkeypatch.setattr(tile_area, "minimize", lambda *args, **kwargs: Failed())
    y = np.arange(1.0, 11.0)
    log_area = np.linspace(-1.0, 1.0, 10)
    assert tile_area._ppml(y, log_area, "strength")["status"] == "optimization_failed"
    with pytest.raises(RuntimeError, match="refusing a hardcoded"):
        tile_area._ppml(y, log_area, "degree", required=True)


def test_spectral_failure_falls_back_to_shared_bound_and_reports(monkeypatch):
    nodes, edges, partitions, _ = _case()

    def no_convergence(*args, **kwargs):
        raise RuntimeError("forced ARPACK failure")

    monkeypatch.setattr(tile_area, "eigs", no_convergence)
    messages = []
    result, diagnostics, _ = tile_area.calculate_tile_area_katz(
        nodes, edges, partitions, progress=messages.append,
    )
    assert diagnostics["spectral_scale_method"] == "weighted_row_sum_bound"
    assert diagnostics["spectral_radius"] is None
    assert "forced ARPACK failure" in diagnostics["spectral_error"]
    bound = diagnostics["outgoing_row_bound"]
    assert math.isclose(result.alpha, 0.85 / bound, rel_tol=1e-12)
    assert any("row-sum scale" in message for message in messages)
    json.dumps(diagnostics, allow_nan=False)


def test_isolated_center_without_tile_is_neutral_and_excluded_from_fit():
    nodes, edges, partitions, _ = _case(seed=14)
    isolated_id = nodes.loc[0, "node_id"]
    key_type = str(nodes.loc[0, "type"])
    key_cluster = str(nodes.loc[0, "cluster"])
    edges = edges.loc[~((edges["source_type"] == key_type)
                        & (edges["source_cluster"] == key_cluster))
                       & ~((edges["target_type"] == key_type)
                           & (edges["target_cluster"] == key_cluster))].reset_index(drop=True)
    partitions = partitions.iloc[1:].reset_index(drop=True)
    result, diagnostics, audit = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    assert diagnostics["excluded_isolated_without_tile"] == 1
    assert diagnostics["regression_node_count"] == len(nodes) - 1
    row = audit.set_index("node_id").loc[isolated_id]
    assert np.isnan(row["voronoi_area_km2"])
    assert row["area_factor"] == 1.0
    assert result.katz_in_raw[isolated_id] == 1.0
    assert result.katz_out_raw[isolated_id] == 1.0
    json.dumps(diagnostics, allow_nan=False)


def test_equal_areas_on_dag_match_existing_katz_fallback():
    nodes, edges, partitions, graph = _case(acyclic=True, equal_area=True)
    result, diagnostics, _ = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    reference = balanced_katz_centrality(graph)
    assert diagnostics["spectral_scale_method"] == "weighted_row_sum_dag"
    assert math.isclose(result.alpha, reference.alpha, rel_tol=1e-9)
    for node, value in reference.values.items():
        assert math.isclose(result.values[node], value, rel_tol=1e-8)


def test_no_edges_and_no_tiles_are_neutral():
    nodes, edges, partitions, _ = _case(n=8)
    result, diagnostics, audit = tile_area.calculate_tile_area_katz(
        nodes, edges.iloc[:0], partitions.iloc[:0],
    )
    assert diagnostics["gamma"] is None
    assert diagnostics["excluded_isolated_without_tile"] == len(nodes)
    assert diagnostics["area_km2_min_max"] is None
    assert all(v == 1.0 for v in result.katz_in_raw.values())
    assert audit["voronoi_area_km2"].isna().all()
    json.dumps(diagnostics, allow_nan=False)


def test_section97_comparison_matches_independent_unadjusted_katz():
    """Spec §9.7: before/after diagnostics use ordinary balanced Katz on the same X."""
    nodes, edges, partitions, graph = _case(n=140, p=0.05, seed=21)
    result, diagnostics, audit = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    comparison = diagnostics["unadjusted_comparison"]
    assert comparison["status"] == "ok"
    reference = balanced_katz_centrality(graph)
    ids = nodes["node_id"].tolist()
    before = np.array([reference.values[i] for i in ids])
    after = np.array([result.values[i] for i in ids])
    area = audit["voronoi_area_km2"].to_numpy()
    from scipy.stats import spearmanr
    assert math.isclose(comparison["area_katz_spearman_rho"],
                        spearmanr(np.log(area), before).statistic, abs_tol=1e-9)
    assert math.isclose(comparison["rank_correlation_with_adjusted"],
                        spearmanr(before, after).statistic, abs_tol=1e-9)
    top_before = set(np.argsort(-before, kind="stable")[:100])
    top_after = set(np.argsort(-after, kind="stable")[:100])
    assert comparison["top_k_retained_after_adjustment"] == len(top_before & top_after)
    ordered = np.sort(before)[::-1]
    assert math.isclose(comparison["concentration"]["top10_share"],
                        ordered[:10].sum() / ordered.sum(), rel_tol=1e-9)
    ordered = np.sort(after)[::-1]
    assert math.isclose(diagnostics["concentration"]["top100_share"],
                        ordered[:100].sum() / ordered.sum(), rel_tol=1e-9)
    json.dumps(diagnostics, allow_nan=False)


def test_section97_deciles_degree_balance_and_orientation_fits():
    nodes, edges, partitions, _ = _case(n=140, p=0.05, seed=22)
    _, diagnostics, audit = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    index = tile_area._node_index(nodes, "type", "cluster")
    source, target, _ = tile_area._edge_arrays(index, edges)
    k_out = np.bincount(source, minlength=len(nodes))
    k_in = np.bincount(target, minlength=len(nodes))
    balance = diagnostics["degree_balance"]
    assert balance["max_abs_in_minus_out"] == int(np.abs(k_in - k_out).max())
    assert balance["nodes_with_unequal_in_out"] == int(np.count_nonzero(k_in != k_out))
    assert balance["zero_degree_nodes"] == int(np.count_nonzero(k_in + k_out == 0))
    deciles = diagnostics["area_deciles"]
    assert [row["decile"] for row in deciles] == list(range(1, 11))
    assert sum(row["nodes"] for row in deciles) == len(nodes)
    assert all(a["area_km2_max"] <= b["area_km2_min"]
               for a, b in zip(deciles[:-1], deciles[1:], strict=True))
    adjusted = audit["area_factor"].to_numpy() * (k_in + k_out)
    weighted = sum(row["nodes"] * row["mean_adjusted_degree"] for row in deciles)
    assert math.isclose(weighted / len(nodes), adjusted.mean(), rel_tol=1e-12)
    for row in deciles:
        assert math.isclose(row["relative_mean_adjusted_degree"],
                            row["mean_adjusted_degree"] / adjusted.mean(), rel_tol=1e-12)
    fits = diagnostics["degree_orientation_regressions"]
    assert fits["in_degree"]["status"] == fits["out_degree"]["status"] == "ok"
    factor = audit["area_factor"].to_numpy()
    assert math.isclose(diagnostics["factor_max_min_ratio"], factor.max() / factor.min(),
                        rel_tol=1e-12)


def test_symmetric_x_has_equal_in_out_degree_and_equal_orientation_exponents():
    """Metro Manila had k_in = k_out for every node, so all three fits agree."""
    nodes, edges, partitions, _ = _case(n=120, p=0.06, seed=23)
    reverse = edges.rename(columns={
        "source_type": "target_type", "source_cluster": "target_cluster",
        "target_type": "source_type", "target_cluster": "source_cluster",
    })[edges.columns]
    both = pd.concat([edges, reverse], ignore_index=True).drop_duplicates(
        subset=["source_type", "source_cluster", "target_type", "target_cluster"])
    _, diagnostics, _ = tile_area.calculate_tile_area_katz(nodes, both, partitions)
    assert diagnostics["degree_balance"]["max_abs_in_minus_out"] == 0
    fits = diagnostics["degree_orientation_regressions"]
    gamma = diagnostics["gamma"]
    assert math.isclose(fits["in_degree"]["area_elasticity"], gamma, abs_tol=1e-6)
    assert math.isclose(fits["out_degree"]["area_elasticity"], gamma, abs_tol=1e-6)


def test_constant_area_comparison_is_identical_without_second_solve(monkeypatch):
    nodes, edges, partitions, _ = _case(equal_area=True)
    calls = []
    original = tile_area._tile_katz
    monkeypatch.setattr(tile_area, "_tile_katz",
                        lambda *a, **k: calls.append(1) or original(*a, **k))
    _, diagnostics, _ = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    comparison = diagnostics["unadjusted_comparison"]
    assert len(calls) == 1
    assert comparison["status"] == "identical_exact_no_op"
    assert math.isclose(comparison["rank_correlation_with_adjusted"], 1.0)
    assert comparison["top_k_retained_after_adjustment"] == comparison["top_k"]
    assert diagnostics["degree_orientation_regressions"]["status"] == "not_estimated_exact_no_op"


def test_failed_comparison_is_recorded_and_scores_are_unchanged(monkeypatch):
    nodes, edges, partitions, _ = _case(seed=24)
    expected, _, _ = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    original = tile_area._tile_katz
    calls = []

    def second_call_fails(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("forced comparison failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(tile_area, "_tile_katz", second_call_fails)
    result, diagnostics, _ = tile_area.calculate_tile_area_katz(nodes, edges, partitions)
    assert diagnostics["unadjusted_comparison"]["status"] == "failed"
    assert "forced comparison failure" in diagnostics["unadjusted_comparison"]["error"]
    assert result.values == expected.values
    json.dumps(diagnostics, allow_nan=False)

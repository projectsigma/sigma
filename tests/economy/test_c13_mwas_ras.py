from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from sigma import Economy, Sector, SectorCatalog, SigmaWorkspace
from sigma.economy import (
    EconomyPipeline,
    EconomyRunConfig,
    exact_mwas,
    fast_mwas,
    io_network,
    maximum_weight_acyclic_subgraph,
    preprocess_transactions,
    solve_mwas,
)
from sigma.errors import EconomyValidationError


def _workspace(tmp_path, name="ws"):
    return SigmaWorkspace.create(tmp_path / name, source_store=tmp_path / "sources")


def _repair_fixture() -> pd.DataFrame:
    # Fast MWAS + positive diagonal is infeasible for these raw margins.
    # Deterministic descending-weight restoration requires D->C (5) then A->C (4),
    # while D->B (4) remains excluded because feasibility has already been restored.
    return pd.DataFrame(
        [
            [0.0, 0.0, 4.0, 0.0],
            [2.0, 4.0, 11.0, 0.0],
            [6.0, 0.0, 0.0, 15.0],
            [8.0, 4.0, 5.0, 0.0],
        ],
        index=list("ABCD"),
        columns=list("ABCD"),
    )


def _assert_margins_within_policy(
    raw: pd.DataFrame,
    effective: pd.DataFrame,
    *,
    atol: float,
    rtol: float,
) -> None:
    raw_rows = raw.to_numpy(float).sum(axis=1)
    raw_cols = raw.to_numpy(float).sum(axis=0)
    eff_rows = effective.to_numpy(float).sum(axis=1)
    eff_cols = effective.to_numpy(float).sum(axis=0)
    assert np.all(np.abs(eff_rows - raw_rows) <= atol + rtol * np.abs(raw_rows))
    assert np.all(np.abs(eff_cols - raw_cols) <= atol + rtol * np.abs(raw_cols))


def test_preserved_fast_and_exact_mwas_match_c0_golden():
    golden = json.loads(Path("tests/golden/engine/mwas_fixture.json").read_text())
    graph = nx.DiGraph()
    graph.add_weighted_edges_from(
        [("A", "B", 20.0), ("B", "C", 30.0), ("C", "A", 10.0)]
    )
    fast = fast_mwas(graph)
    exact = exact_mwas(graph)

    assert solve_mwas(graph).method == golden["default_method"]
    assert maximum_weight_acyclic_subgraph(graph).has_edge("A", "B")
    assert sorted((u, v, float(d["weight"])) for u, v, d in fast.graph.edges(data=True)) == [
        tuple(row) for row in golden["fast"]["edges"]
    ]
    assert sorted((u, v, float(d["weight"])) for u, v, d in exact.graph.edges(data=True)) == [
        tuple(row) for row in golden["exact"]["edges"]
    ]
    assert fast.retained_weight == pytest.approx(golden["fast"]["retained_weight"])
    assert fast.removed_weight == pytest.approx(golden["fast"]["removed_weight"])
    assert exact.retained_weight == pytest.approx(golden["exact"]["retained_weight"])
    assert exact.removed_weight == pytest.approx(golden["exact"]["removed_weight"])


def test_preserved_mwas_self_loops_remain_removed_audit_weight():
    graph = nx.DiGraph()
    graph.add_edge("A", "A", weight=5.0)
    graph.add_edge("A", "B", weight=1.0)
    graph.add_edge("B", "B", weight=4.0)
    result = fast_mwas(graph)
    assert result.self_loop_weight == pytest.approx(9.0)
    assert result.retained_weight == pytest.approx(1.0)
    assert not any(u == v for u, v in result.graph.edges)


def test_support_repair_is_deterministic_preserves_diagonal_and_never_invents_cells():
    z = _repair_fixture()
    first = preprocess_transactions(z, mode="mwas_ras_fast")
    second = preprocess_transactions(z, mode="mwas_ras_fast")

    pd.testing.assert_frame_equal(first.table, second.table, check_exact=True)
    assert dict(first.diagnostics) == dict(second.diagnostics)
    assert first.diagnostics["mwas_method"] == "fast_greedy"
    assert first.diagnostics["support_repair_edge_count"] == 2
    assert first.diagnostics["ras_converged"] is True

    effective = first.table
    assert effective.loc["B", "B"] > 0  # original positive diagonal is admissible/preserved
    assert effective.loc["D", "C"] > 0  # first restored edge
    assert effective.loc["A", "C"] > 0  # second restored edge
    assert effective.loc["D", "B"] == 0  # equal-weight later tie is not restored unnecessarily
    assert not np.any((effective.to_numpy(float) > 0) & ~(z.to_numpy(float) > 0))
    _assert_margins_within_policy(z, effective, atol=1e-8, rtol=1e-10)


def test_mwas_ras_fast_builtin_io80_preserves_margins_and_recomputes_coefficients(tmp_path):
    economy = Economy.builtin("io80")
    config = EconomyRunConfig(transaction_preprocessing="mwas_ras_fast")
    pipe = EconomyPipeline(_workspace(tmp_path, "io80"), economy=economy, config=config)

    effective_ref = pipe.effective_transactions()
    coeff_ref = pipe.coefficients()
    graph_ref = pipe.graph()
    effective = pipe.load_transactions(effective_ref)
    coefficients = pipe.load_coefficients(coeff_ref)
    graph = pipe.load_graph(graph_ref)

    _assert_margins_within_policy(
        economy.Z_raw,
        effective,
        atol=config.ras_absolute_tolerance,
        rtol=config.ras_relative_tolerance,
    )
    assert np.count_nonzero(effective.to_numpy()) < np.count_nonzero(economy.Z_raw.to_numpy())
    assert not np.any(
        (effective.to_numpy(float) > 0) & ~(economy.Z_raw.to_numpy(float) > 0)
    )
    expected_a = effective.div(economy.x, axis="columns")
    pd.testing.assert_frame_equal(coefficients, expected_a, check_exact=True)
    assert graph.graph.number_of_edges() == int(np.count_nonzero(effective.to_numpy()))
    assert not nx.is_directed_acyclic_graph(graph.graph)  # diagonal/self-use is retained
    for row in graph.rows.itertuples(index=False):
        assert row.weight == row.technical_coefficient
        assert row.technical_coefficient == coefficients.loc[row.source_type, row.target_type]

    diagnostics = json.loads(
        (effective_ref.path / "preprocessing.json").read_text(encoding="utf-8")
    )
    assert diagnostics["ras_converged"] is True
    assert diagnostics["mwas_proposed_edge_count"] > 0
    assert diagnostics["final_nonzero_count"] <= diagnostics["raw_nonzero_count"]


def test_mwas_ras_fast_ignores_explicit_a_and_recomputes_from_effective_table(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[4.0, 2.0], [3.0, 5.0]], index=["A", "B"], columns=["A", "B"])
    x = pd.Series([10.0, 20.0], index=["A", "B"])
    explicit = pd.DataFrame([[9.0, 9.0], [9.0, 9.0]], index=["A", "B"], columns=["A", "B"])
    economy = Economy(
        economy_id="explicit-with-x",
        sectors=sectors,
        raw_transactions=z,
        total_output=x,
        explicit_technical_coefficients=explicit,
    )
    pipe = EconomyPipeline(
        _workspace(tmp_path),
        economy=economy,
        config=EconomyRunConfig(transaction_preprocessing="mwas_ras_fast"),
    )
    effective = pipe.load_transactions(pipe.effective_transactions())
    coefficients = pipe.load_coefficients(pipe.coefficients())
    expected = effective.div(x, axis="columns")
    pd.testing.assert_frame_equal(coefficients, expected, check_exact=True)
    assert not np.allclose(coefficients.to_numpy(), explicit.to_numpy())


def test_explicit_a_only_economy_is_rejected_for_mwas_ras_fast(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=["A", "B"], columns=["A", "B"])
    a = pd.DataFrame([[0.1, 0.2], [0.3, 0.4]], index=["A", "B"], columns=["A", "B"])
    economy = Economy(
        economy_id="explicit-only",
        sectors=sectors,
        raw_transactions=z,
        explicit_technical_coefficients=a,
    )
    with pytest.raises(EconomyValidationError, match="requires total output x"):
        EconomyPipeline(
            _workspace(tmp_path),
            economy=economy,
            config=EconomyRunConfig(transaction_preprocessing="mwas_ras_fast"),
        )


def test_switching_preprocessing_reuses_raw_only_and_invalidates_effective_descendants(tmp_path):
    economy = Economy.builtin("io16")
    ws = _workspace(tmp_path)
    none = EconomyPipeline(ws, economy=economy, config=EconomyRunConfig())
    refs_none = {
        "definition": none.definition(),
        "raw": none.raw_transactions(),
        "effective": none.effective_transactions(),
        "coefficients": none.coefficients(),
        "graph": none.graph(),
    }
    sparse = EconomyPipeline(
        ws,
        economy=economy,
        config=EconomyRunConfig(transaction_preprocessing="mwas_ras_fast"),
    )
    refs_sparse = {
        "definition": sparse.definition(),
        "raw": sparse.raw_transactions(),
        "effective": sparse.effective_transactions(),
        "coefficients": sparse.coefficients(),
        "graph": sparse.graph(),
    }
    assert refs_sparse["definition"].artifact_id == refs_none["definition"].artifact_id
    assert refs_sparse["raw"].artifact_id == refs_none["raw"].artifact_id
    for key in ("effective", "coefficients", "graph"):
        assert refs_sparse[key].artifact_id != refs_none[key].artifact_id


def test_ras_policy_change_invalidates_effective_onward_not_raw(tmp_path):
    economy = Economy.builtin("io16")
    ws = _workspace(tmp_path)
    p1 = EconomyPipeline(
        ws,
        economy=economy,
        config=EconomyRunConfig(
            transaction_preprocessing="mwas_ras_fast",
            ras_relative_tolerance=1e-9,
        ),
    )
    r1, e1, a1, g1 = p1.raw_transactions(), p1.effective_transactions(), p1.coefficients(), p1.graph()
    p2 = EconomyPipeline(
        ws,
        economy=economy,
        config=EconomyRunConfig(
            transaction_preprocessing="mwas_ras_fast",
            ras_relative_tolerance=1e-8,
        ),
    )
    r2, e2, a2, g2 = p2.raw_transactions(), p2.effective_transactions(), p2.coefficients(), p2.graph()
    assert r1.artifact_id == r2.artifact_id
    assert e1.artifact_id != e2.artifact_id
    assert a1.artifact_id != a2.artifact_id
    assert g1.artifact_id != g2.artifact_id


def test_nonconvergent_policy_fails_without_replacing_previous_complete_effective_artifact(tmp_path):
    sectors = SectorCatalog([Sector(code, code) for code in "ABCD"])
    z = _repair_fixture()
    x = pd.Series([30.0, 30.0, 30.0, 30.0], index=list("ABCD"))
    economy = Economy(economy_id="repair", sectors=sectors, raw_transactions=z, total_output=x)
    ws = _workspace(tmp_path)
    previous = EconomyPipeline(ws, economy=economy).effective_transactions()

    failing = EconomyPipeline(
        ws,
        economy=economy,
        config=EconomyRunConfig(
            transaction_preprocessing="mwas_ras_fast",
            ras_absolute_tolerance=1e-15,
            ras_relative_tolerance=1e-15,
            ras_max_iterations=1,
        ),
    )
    with pytest.raises(EconomyValidationError, match="did not converge"):
        failing.effective_transactions()
    assert ws.artifact("economy.transactions.effective").artifact_id == previous.artifact_id


def test_exact_mwas_is_not_a_ras_preprocessing_mode():
    z = pd.DataFrame([[0.0, 2.0], [1.0, 0.0]], index=["A", "B"], columns=["A", "B"])
    with pytest.raises(Exception, match="none.*mwas_ras_fast"):
        preprocess_transactions(z, mode="mwas_ras_exact")

def test_explicit_a_change_is_ignored_by_mwas_ras_fast_when_x_is_unchanged(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[4.0, 2.0], [3.0, 5.0]], index=["A", "B"], columns=["A", "B"])
    x = pd.Series([10.0, 20.0], index=["A", "B"])
    a1 = pd.DataFrame([[0.4, 0.1], [0.3, 0.25]], index=["A", "B"], columns=["A", "B"])
    a2 = pd.DataFrame([[7.0, 7.0], [7.0, 7.0]], index=["A", "B"], columns=["A", "B"])
    e1 = Economy(
        economy_id="e",
        sectors=sectors,
        raw_transactions=z,
        total_output=x,
        explicit_technical_coefficients=a1,
    )
    e2 = Economy(
        economy_id="e",
        sectors=sectors,
        raw_transactions=z,
        total_output=x,
        explicit_technical_coefficients=a2,
    )
    ws = _workspace(tmp_path)
    cfg = EconomyRunConfig(transaction_preprocessing="mwas_ras_fast")
    p1 = EconomyPipeline(ws, economy=e1, config=cfg)
    d1, r1, ef1, c1, g1 = (
        p1.definition(),
        p1.raw_transactions(),
        p1.effective_transactions(),
        p1.coefficients(),
        p1.graph(),
    )
    p2 = EconomyPipeline(ws, economy=e2, config=cfg)
    d2, r2, ef2, c2, g2 = (
        p2.definition(),
        p2.raw_transactions(),
        p2.effective_transactions(),
        p2.coefficients(),
        p2.graph(),
    )
    assert d1.artifact_id != d2.artifact_id  # Economy definition records the compatibility A identity.
    assert r1.artifact_id == r2.artifact_id
    assert ef1.artifact_id == ef2.artifact_id
    assert c1.artifact_id == c2.artifact_id
    assert g1.artifact_id == g2.artifact_id

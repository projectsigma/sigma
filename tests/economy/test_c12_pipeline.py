from __future__ import annotations

import json

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from sigma import Economy, Sector, SectorCatalog, SigmaWorkspace
from sigma.economy import EconomyPipeline, EconomyRunConfig, build_economic_graph
from sigma.errors import EconomyValidationError


def _workspace(tmp_path, name="ws"):
    return SigmaWorkspace.create(
        tmp_path / name,
        source_store=tmp_path / "sources",
    )


@pytest.mark.parametrize("builtin", ["io16", "io80"])
def test_builtin_none_pipeline_exact_z_and_a_parity(tmp_path, builtin):
    economy = Economy.builtin(builtin)
    pipe = EconomyPipeline(_workspace(tmp_path, builtin), economy=economy)

    raw_ref = pipe.raw_transactions()
    effective_ref = pipe.effective_transactions()
    coeff_ref = pipe.coefficients()
    graph_ref = pipe.graph()

    raw = pipe.load_transactions(raw_ref)
    effective = pipe.load_transactions(effective_ref)
    coefficients = pipe.load_coefficients(coeff_ref)
    result = pipe.load_graph(graph_ref)

    pd.testing.assert_frame_equal(raw, economy.Z_raw, check_exact=True)
    pd.testing.assert_frame_equal(effective, economy.Z_raw, check_exact=True)
    pd.testing.assert_frame_equal(coefficients, economy.A_raw, check_exact=True)
    assert result.graph.number_of_nodes() == len(economy.sectors)
    assert result.graph.number_of_edges() == int(np.count_nonzero(economy.Z_raw.to_numpy()))
    assert nx.number_of_selfloops(result.graph) > 0
    assert not nx.is_directed_acyclic_graph(result.graph)

    graph_meta = json.loads((graph_ref.path / "graph.json").read_text(encoding="utf-8"))
    assert graph_meta["edge_weight"] == "technical_coefficient"
    assert graph_meta["is_directed"] is True
    assert graph_meta["is_dag"] is False


def test_directed_graph_accepts_reciprocal_cycle_and_self_use():
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[4.0, 2.0], [3.0, 5.0]], index=["A", "B"], columns=["A", "B"])
    x = pd.Series([10.0, 20.0], index=["A", "B"])
    economy = Economy(economy_id="cyclic", sectors=sectors, raw_transactions=z, total_output=x)

    result = build_economic_graph(economy.Z_raw, economy.A_raw, sectors)

    assert set(result.graph.edges()) == {("A", "A"), ("A", "B"), ("B", "A"), ("B", "B")}
    assert result.graph["A"]["B"]["weight"] == pytest.approx(0.1)
    assert result.graph["B"]["A"]["weight"] == pytest.approx(0.3)
    assert not nx.is_directed_acyclic_graph(result.graph)
    assert list(result.rows.columns) == [
        "source_type",
        "target_type",
        "transaction_value",
        "technical_coefficient",
        "weight",
    ]


def test_none_explicit_a_only_compatibility_path(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=["A", "B"], columns=["A", "B"])
    a = pd.DataFrame([[0.2, 0.3], [0.4, 0.5]], index=["A", "B"], columns=["A", "B"])
    economy = Economy(
        economy_id="explicit-a",
        sectors=sectors,
        raw_transactions=z,
        explicit_technical_coefficients=a,
    )
    pipe = EconomyPipeline(_workspace(tmp_path), economy=economy)

    effective = pipe.load_transactions(pipe.effective_transactions())
    coefficients = pipe.load_coefficients(pipe.coefficients())
    result = pipe.load_graph(pipe.graph())

    pd.testing.assert_frame_equal(effective, z, check_exact=True)
    pd.testing.assert_frame_equal(coefficients, a, check_exact=True)
    assert result.graph["A"]["B"]["transaction_value"] == 2.0
    assert result.graph["A"]["B"]["technical_coefficient"] == 0.3


def test_positive_transaction_with_zero_explicit_coefficient_is_rejected(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[0.0, 2.0], [0.0, 0.0]], index=["A", "B"], columns=["A", "B"])
    a = pd.DataFrame([[0.0, 0.0], [0.0, 0.0]], index=["A", "B"], columns=["A", "B"])
    economy = Economy(
        economy_id="bad-explicit-a",
        sectors=sectors,
        raw_transactions=z,
        explicit_technical_coefficients=a,
    )
    pipe = EconomyPipeline(_workspace(tmp_path), economy=economy)

    with pytest.raises(EconomyValidationError, match="positive effective transaction"):
        pipe.graph()


def test_force_same_recipe_is_deterministic(tmp_path):
    pipe = EconomyPipeline(_workspace(tmp_path), economy=Economy.builtin("io16"))
    first = pipe.graph()
    second = pipe.graph(force=True)
    assert second.artifact_id == first.artifact_id
    assert second.recipe_fingerprint == first.recipe_fingerprint


def test_transaction_change_recomputes_numerical_branch_same_sector_identity(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z1 = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=["A", "B"], columns=["A", "B"])
    z2 = z1.copy(); z2.loc["A", "B"] = 7.0
    x = pd.Series([10.0, 20.0], index=["A", "B"])
    e1 = Economy(economy_id="e", sectors=sectors, raw_transactions=z1, total_output=x)
    e2 = Economy(economy_id="e", sectors=sectors, raw_transactions=z2, total_output=x)
    assert e1.sector_fingerprint == e2.sector_fingerprint

    ws = _workspace(tmp_path)
    p1 = EconomyPipeline(ws, economy=e1)
    refs1 = {
        "definition": p1.definition(),
        "raw": p1.raw_transactions(),
        "effective": p1.effective_transactions(),
        "coefficients": p1.coefficients(),
        "graph": p1.graph(),
    }
    p2 = EconomyPipeline(ws, economy=e2)
    refs2 = {
        "definition": p2.definition(),
        "raw": p2.raw_transactions(),
        "effective": p2.effective_transactions(),
        "coefficients": p2.coefficients(),
        "graph": p2.graph(),
    }
    for key in refs1:
        assert refs1[key].artifact_id != refs2[key].artifact_id, key


def test_output_change_reuses_raw_and_effective_but_changes_coefficients_and_graph(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=["A", "B"], columns=["A", "B"])
    e1 = Economy(
        economy_id="e",
        sectors=sectors,
        raw_transactions=z,
        total_output=pd.Series([10.0, 20.0], index=["A", "B"]),
    )
    e2 = Economy(
        economy_id="e",
        sectors=sectors,
        raw_transactions=z,
        total_output=pd.Series([11.0, 20.0], index=["A", "B"]),
    )
    ws = _workspace(tmp_path)
    p1 = EconomyPipeline(ws, economy=e1)
    d1, r1, efr1, a1, g1 = p1.definition(), p1.raw_transactions(), p1.effective_transactions(), p1.coefficients(), p1.graph()
    p2 = EconomyPipeline(ws, economy=e2)
    d2, r2, efr2, a2, g2 = p2.definition(), p2.raw_transactions(), p2.effective_transactions(), p2.coefficients(), p2.graph()

    assert d1.artifact_id != d2.artifact_id
    assert r1.artifact_id == r2.artifact_id
    assert efr1.artifact_id == efr2.artifact_id
    assert a1.artifact_id != a2.artifact_id
    assert g1.artifact_id != g2.artifact_id


def test_explicit_a_change_reuses_raw_effective_even_when_x_is_present(tmp_path):
    sectors = SectorCatalog([Sector("A", "Alpha"), Sector("B", "Beta")])
    z = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=["A", "B"], columns=["A", "B"])
    x = pd.Series([10.0, 20.0], index=["A", "B"])
    a1 = pd.DataFrame([[0.1, 0.1], [0.3, 0.2]], index=["A", "B"], columns=["A", "B"])
    a2 = a1.copy(); a2.loc["A", "B"] = 0.25
    e1 = Economy(economy_id="e", sectors=sectors, raw_transactions=z, total_output=x, explicit_technical_coefficients=a1)
    e2 = Economy(economy_id="e", sectors=sectors, raw_transactions=z, total_output=x, explicit_technical_coefficients=a2)
    ws = _workspace(tmp_path)
    p1 = EconomyPipeline(ws, economy=e1)
    r1, efr1, c1 = p1.raw_transactions(), p1.effective_transactions(), p1.coefficients()
    p2 = EconomyPipeline(ws, economy=e2)
    r2, efr2, c2 = p2.raw_transactions(), p2.effective_transactions(), p2.coefficients()

    assert r1.artifact_id == r2.artifact_id
    assert efr1.artifact_id == efr2.artifact_id
    assert c1.artifact_id != c2.artifact_id


def test_invalid_preprocessing_mode_is_rejected():
    with pytest.raises(ValueError, match="transaction_preprocessing"):
        EconomyRunConfig(transaction_preprocessing="other")  # type: ignore[arg-type]

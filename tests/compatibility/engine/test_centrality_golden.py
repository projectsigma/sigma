from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np

from sigma.analysis import directed_eigenvector_centrality, make_node_id

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "engine" / "x_score_output_fixture.json"


def test_c0_centrality_golden_is_preserved_exactly():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))["centrality"]
    graph = nx.DiGraph()
    a = make_node_id("A", 0)
    b = make_node_id("B", 0)
    graph.add_edge(a, b, weight=48.0)
    result = directed_eigenvector_centrality(graph, "incoming")

    assert result.direction == expected["direction"]
    assert result.degenerate_dag == expected["degenerate_dag"]
    assert result.note == expected["note"]
    assert set(result.values) == set(expected["values"])
    for node, value in expected["values"].items():
        assert np.isclose(result.values[node], value, rtol=0.0, atol=1e-15)

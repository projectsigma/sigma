from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from sigma.analysis.graph import make_node_id
from sigma.analysis.scoring import tempered_point_scores

GOLDEN = Path(__file__).resolve().parents[2] / "golden" / "engine" / "x_score_output_fixture.json"


def test_c0_scoring_golden_is_preserved():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    points = gpd.GeoDataFrame(
        {
            "canonical_id": [f"p{i}" for i in range(5)],
            "type": ["A"] * 5,
            "cluster": [0] * 5,
            "distance_to_cluster_median": [0.0, 10.0, 20.0, 30.0, 100.0],
        },
        geometry=[Point(i, 0) for i in range(5)],
        crs="EPSG:3857",
    )
    out = tempered_point_scores(
        points,
        {make_node_id("A", 0): 2.0},
        distance_tempering=0.15,
    )

    assert list(out.columns) == expected["score_columns"]
    actual = out.drop(columns="geometry").to_dict(orient="records")
    wanted = expected["scores"]
    assert len(actual) == len(wanted)
    for got, want in zip(actual, wanted, strict=True):
        assert got.keys() == want.keys()
        for key, value in want.items():
            if isinstance(value, float):
                assert np.isclose(float(got[key]), value, rtol=0.0, atol=1e-15)
            else:
                assert got[key] == value


def test_node_id_encoding_preserves_legacy_format():
    assert make_node_id("Food / drink::retail", 7) == "type=Food%20%2F%20drink%3A%3Aretail::cluster=7"

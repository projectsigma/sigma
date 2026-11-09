from __future__ import annotations

import json
import math

import numpy as np
import pytest

from sigma.analysis import (
    AnalysisPipeline,
    AnalysisRunConfig,
    balanced_katz_centrality,
    make_node_id,
)

from tests.integration.test_c14_analysis_x import _pipelines


def test_managed_centrality_defaults_to_balanced_directed_katz_on_cyclic_x(tmp_path):
    ws, spatial, economic, _ = _pipelines(tmp_path)
    analysis = AnalysisPipeline(ws, spatial_pipeline=spatial, economy_pipeline=economic)
    score_ref = analysis.scores()
    centrality = analysis.load_centrality()
    table = analysis.read_centrality_table()
    scores = analysis.read_scores(score_ref)

    a = make_node_id("A", 0)
    b = make_node_id("B", 0)
    assert centrality.method == "katz"
    assert centrality.direction == "balanced"
    assert centrality.combination == "geometric_mean"
    assert centrality.normalization == "l2_after_combination"
    assert centrality.katz_in_raw is not None
    assert centrality.katz_out_raw is not None
    assert centrality.alpha is not None and centrality.alpha > 0
    assert centrality.beta == 1.0
    assert centrality.values[a] > 0 and centrality.values[b] > 0
    assert list(table.columns) == [
        "node_id", "type", "cluster", "in_degree", "out_degree",
        "katz_in_raw", "katz_out_raw", "centrality",
        "voronoi_area_km2", "area_factor",
        "out_strength_original", "in_strength_original",
        "out_strength_adjusted", "in_strength_adjusted",
    ]
    assert table["katz_in_raw"].notna().all()
    assert table["katz_out_raw"].notna().all()
    assert set(scores["type"]) == {"A", "B"}
    assert set(scores["cluster"]) == {0}
    assert "distance_tempering" not in scores.columns
    distance = np.maximum(scores["distance_to_cluster_median"].to_numpy(float), 1.0)
    np.testing.assert_array_equal(
        scores["sigma_score"].to_numpy(float),
        scores["cluster_centrality"].to_numpy(float) / distance,
    )
    # Both fixture tiles cover the whole area, so the area factor is an exact no-op.
    metadata_path = ws.artifact("analysis.centrality").path / "centrality.json"
    adjustment = json.loads(metadata_path.read_text(encoding="utf-8"))["tile_area_adjustment"]
    assert adjustment["regression"]["status"] == "not_identified_constant_area"
    assert adjustment["gamma"] is None
    reference = balanced_katz_centrality(analysis.load_x(include_paths=False).graph)
    for node, value in reference.values.items():
        assert math.isclose(centrality.values[node], value, rel_tol=1e-10)


def test_x_distance_exponent_recomputes_x_centrality_and_scores_only(tmp_path):
    ws, spatial, economic, original = _pipelines(tmp_path)
    original.scores()
    saved = {
        stage: ws.artifact(stage).artifact_id
        for stage in (
            "spatial.clusters", "spatial.centers", "spatial.partitions",
            "spatial.point_distances", "economy.graph",
            "analysis.x", "analysis.centrality", "analysis.scores",
        )
    }
    modified = AnalysisPipeline(
        ws, spatial_pipeline=spatial, economy_pipeline=economic,
        config=AnalysisRunConfig(x_distance_decay_lambda=2.0),
    )
    modified.scores()
    unchanged = (
        "spatial.clusters", "spatial.centers", "spatial.partitions",
        "spatial.point_distances", "economy.graph",
    )
    changed = ("analysis.x", "analysis.centrality", "analysis.scores")
    assert all(ws.artifact(stage).artifact_id == saved[stage] for stage in unchanged)
    assert all(ws.artifact(stage).artifact_id != saved[stage] for stage in changed)


def test_katz_direction_compatibility_option_does_not_change_balanced_artifact(tmp_path):
    ws, spatial, economic, first = _pipelines(tmp_path)
    first.scores()
    first_values = dict(first.load_centrality().values)
    ids = {stage: ws.artifact(stage).artifact_id for stage in (
        "analysis.x", "analysis.centrality", "analysis.scores", "spatial.point_distances"
    )}

    changed = AnalysisPipeline(
        ws,
        spatial_pipeline=spatial,
        economy_pipeline=economic,
        config=AnalysisRunConfig(centrality_direction="outgoing", distance_tempering=0.15),
    )
    changed.scores()
    after = {stage: ws.artifact(stage).artifact_id for stage in ids}
    assert after == ids
    assert changed.load_centrality().values == first_values


def test_switching_to_eigenvector_invalidates_centrality_and_scores_only(tmp_path):
    ws, spatial, economic, first = _pipelines(tmp_path)
    first.scores()
    x_id = ws.artifact("analysis.x").artifact_id
    d_id = ws.artifact("spatial.point_distances").artifact_id
    c_id = ws.artifact("analysis.centrality").artifact_id
    s_id = ws.artifact("analysis.scores").artifact_id

    changed = AnalysisPipeline(
        ws,
        spatial_pipeline=spatial,
        economy_pipeline=economic,
        config=AnalysisRunConfig(centrality_method="eigenvector"),
    )
    changed.scores()
    assert ws.artifact("analysis.x").artifact_id == x_id
    assert ws.artifact("spatial.point_distances").artifact_id == d_id
    assert ws.artifact("analysis.centrality").artifact_id != c_id
    assert ws.artifact("analysis.scores").artifact_id != s_id
    assert changed.load_centrality().method == "eigenvector"
    assert changed.load_centrality().direction == "undirected"


def test_retired_tempering_is_rejected_by_canonical_analysis_config():
    with pytest.raises(ValueError, match="retired"):
        AnalysisRunConfig(distance_tempering=0.30)
    assert AnalysisRunConfig(centrality_method="eigenvector", distance_tempering=0.30)


def test_forced_centrality_and_scores_are_deterministic(tmp_path):
    _, _, _, analysis = _pipelines(tmp_path)
    c1 = analysis.centrality()
    c2 = analysis.centrality(force=True)
    s1 = analysis.scores()
    s2 = analysis.scores(force=True)
    assert c1.artifact_id == c2.artifact_id
    assert s1.artifact_id == s2.artifact_id


def test_analysis_run_config_validation():
    invalid = [
        lambda: AnalysisRunConfig(centrality_method="pagerank"),
        lambda: AnalysisRunConfig(centrality_direction="sideways"),
        lambda: AnalysisRunConfig(katz_alpha_factor=1.0),
        lambda: AnalysisRunConfig(katz_alpha_factor=0.0),
        lambda: AnalysisRunConfig(katz_beta=0.0),
    ]
    for constructor in invalid:
        try:
            constructor()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid analysis centrality configuration must fail")
    for value in (-1.0, float("nan"), float("inf")):
        try:
            AnalysisRunConfig(x_distance_decay_lambda=value)
        except ValueError as exc:
            assert "x_distance_decay_lambda" in str(exc)
        else:
            raise AssertionError("invalid X distance exponent must fail")
    for value in (-0.01, 1.01, float("nan")):
        try:
            AnalysisRunConfig(distance_tempering=value)
        except ValueError as exc:
            assert "distance_tempering" in str(exc)
        else:
            raise AssertionError("invalid distance tempering must fail")


def test_eigenvector_direction_is_ignored_and_reuses_artifact(tmp_path):
    ws, spatial, economic, _ = _pipelines(tmp_path)
    first = AnalysisPipeline(
        ws, spatial_pipeline=spatial, economy_pipeline=economic,
        config=AnalysisRunConfig(centrality_method="eigenvector", centrality_direction="incoming"),
    )
    ref = first.centrality()
    other = AnalysisPipeline(
        ws, spatial_pipeline=spatial, economy_pipeline=economic,
        config=AnalysisRunConfig(centrality_method="eigenvector", centrality_direction="outgoing"),
    )
    assert other.centrality(force=True).artifact_id == ref.artifact_id

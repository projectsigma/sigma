from __future__ import annotations

from sigma import Economy
from sigma.economy import EconomyPipeline, EconomyRunConfig


def test_preprocessing_change_does_not_invalidate_place_tagging_artifact(tmp_path):
    from tests.integration.test_c8_place_branch import (
        _services,
        _synthetic_builtin_taxonomy,
        _workspace,
    )
    from sigma.places.pipeline import PlacePipeline

    area, ws = _workspace(tmp_path)
    place = PlacePipeline(
        ws,
        area=area,
        economy=Economy.default(),
        services=_services(tmp_path, taxonomy=_synthetic_builtin_taxonomy()),
    )
    before = place.load()

    EconomyPipeline(ws, economy=Economy.default(), config=EconomyRunConfig()).graph()
    EconomyPipeline(
        ws,
        economy=Economy.default(),
        config=EconomyRunConfig(transaction_preprocessing="mwas_ras_fast"),
    ).graph()

    after = place.load()
    assert after.artifact_id == before.artifact_id


def test_preprocessing_change_does_not_invalidate_spatial_artifacts(tmp_path):
    from tests.integration.test_c9_spatial_branch import _pipeline, _workspace

    ws = _workspace(tmp_path)
    spatial = _pipeline(tmp_path, ws)
    before = spatial.prepare_clusters()

    economy = Economy.builtin("io16")
    EconomyPipeline(ws, economy=economy, config=EconomyRunConfig()).graph()
    EconomyPipeline(
        ws,
        economy=economy,
        config=EconomyRunConfig(transaction_preprocessing="mwas_ras_fast"),
    ).graph()

    after = spatial.prepare_clusters()
    assert after.artifact_id == before.artifact_id

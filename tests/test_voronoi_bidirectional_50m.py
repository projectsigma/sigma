"""Regression tests: 50m start; bidirectional budget repair; convergence."""
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from sigma.config import SpatialConfig
from sigma.spatial import voronoi


def _partition(resolution: float, cut: float = 1.0) -> gpd.GeoDataFrame:
    left, right = box(0, 0, cut, 1), box(cut, 0, 2, 1)
    return gpd.GeoDataFrame(
        {
            "type": ["sector", "sector"],
            "cluster": [1, 2],
            "surface_area": [left.area, right.area],
            "surface_resolution": [resolution, resolution],
            "surface_method": ["network_voronoi", "network_voronoi"],
            "surface_seed_method": ["cluster_member_network_sources"] * 2,
        }, geometry=[left, right], crs="EPSG:32651",
    )


def _run(monkeypatch, compute, *, boundary=None, max_cells=1_000_000, **kwargs):
    monkeypatch.setattr(voronoi, "surface_partition_for_type", compute)
    if boundary is None:
        boundary = gpd.GeoDataFrame(geometry=[box(0, 0, 2, 1)], crs="EPSG:32651")
    return voronoi.all_surface_partitions(
        SimpleNamespace(crs="EPSG:32651"),
        pd.DataFrame({"type": ["sector"], "cluster": [1]}),
        boundary, 50.0, max_cells,
        euclidean_fallback=False, **kwargs,
    )


def test_default_starts_at_50m():
    assert SpatialConfig().voronoi_resolution == 50.0


def test_budget_search_finds_intermediate_not_just_next_doubling():
    # 2000 x 2000 over 100 cells requires at least 200m.
    bounds = (0.0, 0.0, 2000.0, 2000.0)
    chosen, count, adjusted = voronoi._budgeted_start_resolution(bounds, 50.0, 100)
    assert adjusted
    assert 200 <= chosen < 201
    assert count <= 100
    assert voronoi._grid_cell_count(bounds, 50.0) > 100


def test_initial_50m_over_cap_recovers_by_coarsening(monkeypatch):
    events, calls = [], []

    def compute(_network, _points, _boundary, resolution, _cap, **_kwargs):
        calls.append(resolution)
        return _partition(resolution)

    big = gpd.GeoDataFrame(geometry=[box(0, 0, 2000, 2000)], crs="EPSG:32651")
    result = _run(monkeypatch, compute, boundary=big, max_cells=100, events=events)
    assert len(calls) == 1
    assert 200 <= calls[0] < 201
    assert float(result.surface_resolution.iloc[0]) == pytest.approx(calls[0])
    assert any(e["action"] == "coarsened_grid_budget" for e in events)
    assert any(e["action"] == "retain_last_valid_network_resolution" for e in events)
    assert not any(e["action"] == "fallback_euclidean_voronoi" for e in events)


def test_50m_success_does_not_stop_refinement(monkeypatch):
    calls, events = [], []

    def compute(_network, _points, _boundary, resolution, _cap, **_kwargs):
        calls.append(resolution)
        return _partition(resolution, 1.0 if resolution == 50.0 else 1.0001)

    result = _run(monkeypatch, compute, events=events)
    assert calls == [50.0, 25.0]
    assert set(result.surface_resolution) == {25.0}
    assert any(e["action"] == "converged_resolution" for e in events)


def test_missing_cluster_at_50m_refines_then_converges(monkeypatch):
    calls, events = [], []

    def compute(_network, _points, _boundary, resolution, _cap, **_kwargs):
        calls.append(resolution)
        if resolution == 50.0:
            raise ValueError("too coarse; cluster 2 received no grid cell")
        return _partition(resolution)

    result = _run(monkeypatch, compute, events=events)
    assert calls == [50.0, 25.0, 12.5]
    assert set(result.surface_resolution) == {12.5}
    assert any(e["action"] == "refined_resolution" for e in events)


def test_grid_cap_preserves_existing_successful_network_surface(monkeypatch):
    calls, events = [], []

    def compute(_network, _points, _boundary, resolution, _cap, **_kwargs):
        calls.append(resolution)
        return _partition(resolution)

    # 50m = 400 cells, 25m = 1600 cells, cap = 600.
    big = gpd.GeoDataFrame(geometry=[box(0, 0, 1000, 1000)], crs="EPSG:32651")
    result = _run(monkeypatch, compute, boundary=big, max_cells=600, events=events)
    assert calls == [50.0]
    assert set(result.surface_resolution) == {50.0}
    assert any(e["action"] == "retain_last_valid_network_resolution" for e in events)


def test_budget_vs_missing_cluster_reports_conflict_not_fake_success(monkeypatch):
    calls, events = [], []

    def compute(_network, _points, _boundary, resolution, _cap, **_kwargs):
        calls.append(resolution)
        raise ValueError("too coarse; cluster 2 received no grid cell")

    big = gpd.GeoDataFrame(geometry=[box(0, 0, 2000, 2000)], crs="EPSG:32651")
    result = _run(monkeypatch, compute, boundary=big, max_cells=100, events=events)
    assert result.empty
    assert len(calls) == 1
    assert any(e["action"] == "grid_budget_cluster_conflict" for e in events)
    assert any(e["status"] == "skipped" for e in events)


def test_auto_refine_disabled_makes_single_attempt(monkeypatch):
    calls = []

    def compute(_network, _points, _boundary, resolution, _cap, **_kwargs):
        calls.append(resolution)
        return _partition(resolution)

    result = _run(monkeypatch, compute, auto_refine=False)
    assert calls == [50.0]
    assert set(result.surface_resolution) == {50.0}


def test_change_fraction_detects_reassigned_area():
    a = _partition(50, 1.0)
    b = _partition(25, 1.2)
    assert voronoi._partition_change_fraction(a, b) == pytest.approx(0.1)
    assert voronoi._partition_change_fraction(a, a) == pytest.approx(0.0)

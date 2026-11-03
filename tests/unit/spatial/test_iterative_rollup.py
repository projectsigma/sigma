"""Conservative tests for residual-first economic coarsening."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sigma.economy.model import Economy, Sector, SectorCatalog
from sigma.spatial.iterative_rollup import (
    aggregate_economy, candidate_groups, nearest_residual,
    baseline_summary_discrepancies,
)


def _economy():
    codes = ('03:31:089', '03:o', '09:65:201', '09:65:o', '09:65:202', '10:68')
    table = np.arange(1.0, 37.0).reshape(6, 6)
    z = pd.DataFrame(table, index=codes, columns=codes)
    x = pd.Series(np.arange(101.0, 107.0), index=codes)
    return Economy(economy_id='fixture', sectors=SectorCatalog(
        Sector(code, f'sector {i}') for i, code in enumerate(codes)
    ), raw_transactions=z, total_output=x)


def test_nearest_residual_follows_ancestry():
    available = {'03:o', '09:65:o', '09:o', '09:65:202', '10:68'}
    assert nearest_residual('03:31:089', available) == '03:o'
    assert nearest_residual('09:65:201', available) == '09:65:o'
    assert nearest_residual('09:65:o', available) == '09:o'
    assert nearest_residual('10:68', available) is None
    assert nearest_residual('03:35:105', {'09:o'}) is None
    assert nearest_residual('anything', available) is None


def test_candidates_jointly_merge_siblings_at_one_destination():
    available = {'03:31:089', '03:35:105', '03:o', '10:68'}
    assert candidate_groups({'03:31:089', '03:35:105', '10:68'}, available) == {
        '03:o': ('03:31:089', '03:35:105')
    }


def test_rejected_nearest_residual_advances_to_next_existing_ancestor():
    available = {'09:65:201', '09:65:o', '09:o'}
    assert candidate_groups({'09:65:201'}, available) == {'09:65:o': ('09:65:201',)}
    assert candidate_groups({'09:65:201'}, available, {('09:65:201', '09:65:o')}) == {
        '09:o': ('09:65:201',)
    }
    assert candidate_groups({'09:65:201'}, available, {
        ('09:65:201', '09:65:o'), ('09:65:201', '09:o')
    }) == {}


def test_aggregated_economy_conserves_tables_and_removes_source_sectors():
    base = _economy()
    mapping = {'03:31:089': '03:o', '09:65:201': '09:65:o'}
    out = aggregate_economy(base, mapping)
    assert out.sectors.codes == ('03:o', '09:65:o', '09:65:202', '10:68')
    assert out.x.loc['03:o'] == base.x.loc['03:o'] + base.x.loc['03:31:089']
    assert out.Z_raw.loc['03:o', '09:65:o'] == (
        base.Z_raw.loc[['03:o', '03:31:089'], ['09:65:o', '09:65:201']].to_numpy().sum()
    )
    np.testing.assert_allclose(out.Z_raw.to_numpy().sum(), base.Z_raw.to_numpy().sum())
    np.testing.assert_allclose(out.x.sum(), base.x.sum())


def test_aggregated_economy_never_allows_missing_or_overlapping_targets():
    base = _economy()
    with pytest.raises(ValueError):
        aggregate_economy(base, {'03:31:089': 'nonexistent'})
    with pytest.raises(ValueError):
        aggregate_economy(base, {'03:31:089': '03:o', '03:o': '09:65:o'})
    with pytest.raises(ValueError):
        aggregate_economy(base, {'03:o': '03:o'})


def test_baseline_audit_mismatch_is_reported_without_replacing_saved_assignments():
    original = np.array(['10:68', '10:68', '10:69:208', '10:69:208'])
    assignments = np.array([-1, -1, 0, 0], dtype=np.int64)
    summaries = {
        '10:68': {'n_points': 2, 'n_clusters': 0},
        '10:69:208': {'n_points': 3, 'n_clusters': 2},  # intentionally stale
    }
    actual, mismatches = baseline_summary_discrepancies(original, assignments, summaries)
    assert actual == {'10:68': 0, '10:69:208': 1}
    assert mismatches == [{
        'type': '10:69:208', 'audit_points': 3, 'actual_points': 2,
        'audit_clusters': 2, 'actual_clusters': 1,
    }]


def test_baseline_audit_consistent_returns_no_discrepancies():
    original = np.array(['03:31:089', '03:o', '03:o'])
    assignments = np.array([-1, 0, 0], dtype=np.int64)
    actual, mismatches = baseline_summary_discrepancies(original, assignments, {
        '03:31:089': {'n_points': 1, 'n_clusters': 0},
        '03:o': {'n_points': 2, 'n_clusters': 1},
    })
    assert actual == {'03:31:089': 0, '03:o': 1}
    assert mismatches == []

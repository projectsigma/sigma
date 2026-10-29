"""Read-only comparison of genuine saved hierarchy artifacts (with synthetic fixtures)."""
import importlib.util
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[2] / 'scripts' / 'compare_hierarchical_tagging.py'
spec = importlib.util.spec_from_file_location('tagging_comparison', HERE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_comparator_detects_transitions_without_modifying_inputs(tmp_path, monkeypatch):
    # Exercise comparison logic even in a minimal test environment lacking pyarrow.
    monkeypatch.setattr(pd, "read_parquet", lambda path: pd.read_pickle(path))
    old = tmp_path / 'before' / 'hierarchical'
    new = tmp_path / 'after' / 'hierarchical'
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    pd.DataFrame({
        'canonical_id': ['a', 'b'], 'economy_code': ['', 'X'],
        'economy_status': ['UNASSIGNED_IO16_NO_RESIDUAL', 'IO240'],
    }).to_pickle(old / 'places.parquet')
    pd.DataFrame({
        'canonical_id': ['a', 'b'], 'economy_code': ['Y', ''],
        'economy_status': ['IO16_CANDIDATES', 'UNASSIGNED_CANDIDATE_CONFLICT'],
        'economy_evidence': ['coarse_or_candidate_contained', 'candidate_conflict'],
        'economy_review_required': [False, True],
    }).to_pickle(new / 'places.parquet')
    before_files = list(tmp_path.rglob('*'))
    report = module.compare(str(old), str(new))
    assert report['paired']['unassigned_to_assigned'] == 1
    assert report['paired']['assigned_to_unassigned'] == 1
    assert report['after']['candidate_conflicts'] == 1
    assert report['after']['review_required'] == 1
    assert before_files == list(tmp_path.rglob('*'))


def test_scored_output_comparator_detects_sector_cluster_and_score_differences(tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "read_parquet", lambda path: pd.read_pickle(path))
    before = tmp_path / 'before-output'
    after = tmp_path / 'after-output'
    before.mkdir()
    after.mkdir()
    pd.DataFrame({
        'canonical_id': ['a', 'b', 'c'], 'type': ['A', 'B', 'C'],
        'cluster': [1, 2, 3], 'sigma_score': [2.0, 4.0, 6.0],
    }).to_pickle(before / 'sigma_points.parquet')
    pd.DataFrame({
        'canonical_id': ['a', 'b', 'd'], 'type': ['A', 'D', 'E'],
        'cluster': [9, 2, 1], 'sigma_score': [2.5, 4.0, 1.0],
    }).to_pickle(after / 'sigma_points.parquet')
    out = module._spatial_changes(str(before), str(after))
    assert out['shared_scored'] == 2
    assert out['changed_sector_type'] == 1
    assert out['changed_cluster_within_same_sector'] == 1
    assert out['changed_score_for_shared_ids'] == 1
    assert out['newly_scored'] == out['no_longer_scored'] == 1

"""Regression tests for read-only roll-up UI provenance."""
from __future__ import annotations

import pandas as pd
import pytest

from sigma.web.rollup_hierarchy import build_rollup_children, original_label_map


def _cases():
    return pd.DataFrame({
        'economy_code': ['03:o', '03:o', '03:o', '03:o', '09:65:o', '09:65:o', '09:65:202', ''],
        'original_economy_code': ['03:o', '03:o', '03:31:089', '03:31:089', '09:65:o', '09:65:201', '09:65:202', ''],
    })


def _labels():
    return {'03:o': 'Manufacturing Other', '03:31:089': 'Tailoring',
            '09:65:o': 'Communications Other', '09:65:201': 'Telecommunications',
            '09:65:202': 'Computer programming'}


def test_children_preserve_original_code_and_counts():
    result = build_rollup_children(_cases(), _labels(), set(_labels()) - {'03:31:089', '09:65:201'})
    assert set(result) == {'03:o', '09:65:o'}
    assert result['03:o'] == [
        {'code': '03:o', 'label': 'Manufacturing Other', 'places': 2, 'rolled_up': False},
        {'code': '03:31:089', 'label': 'Tailoring', 'places': 2, 'rolled_up': True},
    ]
    assert result['09:65:o'][1]['code'] == '09:65:201'
    assert result['09:65:o'][1]['rolled_up'] is True
    # Successful independent sibling never gains fake child clusters.
    assert '09:65:202' not in result


def test_absent_provenance_leaves_baseline_unmodified():
    frame = pd.DataFrame({'economy_code': ['03:o', '03:o']})
    assert build_rollup_children(frame, _labels(), {'03:o'}) == {}


def test_no_moved_industry_means_no_expander():
    frame = pd.DataFrame({'economy_code': ['03:o'], 'original_economy_code': ['03:o']})
    assert build_rollup_children(frame, _labels(), {'03:o'}) == {}


@pytest.mark.parametrize('bad', [
    pd.DataFrame({'economy_code': ['03:o'], 'original_economy_code': ['BOGUS']}),
    pd.DataFrame({'economy_code': ['BOGUS'], 'original_economy_code': ['03:o']}),
    pd.DataFrame({'economy_code': ['03:o'], 'original_economy_code': ['']}),
])
def test_fail_closed_on_unknown_original_or_effective_tags(bad):
    with pytest.raises(ValueError):
        build_rollup_children(bad, _labels(), {'03:o'})


def test_catalog_labels_require_exact_hierarchy_ancestry(tmp_path):
    root = tmp_path / 'hierarchical'
    base = root / 'economy'
    rolled = root / 'iterative_rollup' / ('a' * 24) / 'economy'
    base.mkdir(parents=True)
    rolled.mkdir(parents=True)
    (base / 'economy.yml').write_text('id: psa-2018-io240-hierarchical-cafe\n', encoding='utf-8')
    (base / 'sectors.csv').write_text('code,label\n03:o,Other manufacturing\n03:31:089,Tailoring\n', encoding='utf-8')
    (rolled / 'sectors.csv').write_text('code,label\n03:o,Other manufacturing\n', encoding='utf-8')
    original = original_label_map(rolled / 'sectors.csv', 'psa-2018-io240-hierarchical-cafe-rollup-deadbeef')
    assert original['03:31:089'] == 'Tailoring'
    with pytest.raises(ValueError, match='does not descend'):
        original_label_map(rolled / 'sectors.csv', 'different-hierarchical-foo-rollup-deadbeef')

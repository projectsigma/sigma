"""Read-only before/after SIGMA hierarchical tagging comparison.

Usage:
    python scripts/compare_hierarchical_tagging.py \
        --before C:/.../qc-baseline/hierarchical \
        --after C:/.../workspaces/quezon_city/hierarchical

Never writes a file; prints aggregate JSON. Never exports establishment names/coordinates.
Neither policy yields ground-truth accuracy metrics without manual verification.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import numpy as np


def _root(path: str) -> Path:
    value = Path(path).expanduser().resolve()
    if (value / 'hierarchical' / 'places.parquet').is_file():
        value /= 'hierarchical'
    if not (value / 'places.parquet').is_file():
        raise FileNotFoundError(f'Expected hierarchical/places.parquet under {path}')
    return value


def _text_col(frame: pd.DataFrame, name: str) -> pd.Series:
    return (frame[name].astype('string').fillna('').str.strip() if name in frame
            else pd.Series([''] * len(frame), index=frame.index, dtype='string'))


def _count(frame: pd.DataFrame, col: str) -> dict[str, int]:
    return {str(k): int(v) for k, v in _text_col(frame, col).value_counts().sort_index().items()}


def _read(path: str) -> tuple[Path, pd.DataFrame, dict]:
    root = _root(path)
    frame = pd.read_parquet(root / 'places.parquet')
    audit = root / 'economy' / 'audit.json'
    data = json.loads(audit.read_text(encoding='utf-8')) if audit.is_file() else {}
    if 'economy_code' not in frame:
        raise ValueError(f'{root} lacks economy_code')
    return root, frame, data


def _summary(frame: pd.DataFrame, audit: dict) -> dict:
    status = _text_col(frame, 'economy_status')
    code = _text_col(frame, 'economy_code')
    provisional = _text_col(frame, 'io_mapping_provisional').str.casefold().eq('true')
    review = _text_col(frame, 'economy_review_required').str.casefold().eq('true')
    return {
        'places': int(len(frame)),
        'assigned': int(code.ne('').sum()),
        'unassigned': int(code.eq('').sum()),
        'final_sector_count': int(code[code.ne('')].nunique()),
        'model_sector_count': audit.get('final_sector_count'),
        'coarse_policy': audit.get('coarse_policy', 'legacy_unspecified'),
        'provisional_mappings': int(provisional.sum()),
        'provisional_assigned': int((provisional & code.ne('')).sum()),
        'review_required': int(review.sum()) if 'economy_review_required' in frame else None,
        'candidate_conflicts': int(status.eq('UNASSIGNED_CANDIDATE_CONFLICT').sum()),
        'residual_convention': int(status.isin(['IO80_RESIDUAL', 'IO16_RESIDUAL']).sum()),
        'straddling_unassigned': int(status.str.endswith('_STRADDLES').sum()),
        'ownership_resolved': int(_text_col(frame, 'ownership_side').ne('').sum()),
        'statuses': _count(frame, 'economy_status'),
        'evidence_categories': _count(frame, 'economy_evidence'),
        'by_io16': _count(frame.loc[code.ne('')], 'io16_code'),
    }


def _aligned_changes(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    key = 'canonical_id'
    for title, df in [('before', before), ('after', after)]:
        if key not in df or _text_col(df, key).eq('').any() or df[key].duplicated().any():
            return {'comparable': False, 'reason': f'{title} lacks unique nonblank {key}'}
    old = before.set_index(key, drop=False)
    new = after.set_index(key, drop=False)
    shared = old.index.intersection(new.index)
    a = _text_col(old.loc[shared], 'economy_code')
    b = _text_col(new.loc[shared], 'economy_code')
    # Sector identities can change legitimately if parents are merged; also
    # compare assigned/unassigned transitions separately from changed labels.
    moved = a.ne(b)
    return {
        'comparable': True, 'shared': int(len(shared)),
        'only_before': int(len(old) - len(shared)),
        'only_after': int(len(new) - len(shared)),
        'unassigned_to_assigned': int((a.eq('') & b.ne('')).sum()),
        'assigned_to_unassigned': int((a.ne('') & b.eq('')).sum()),
        'changed_sector_identity': int(moved.sum()),
        'same_sector_identity': int((~moved).sum()),
        'note': 'Sector-code changes need membership-based interpretation, not an assumed correction.',
    }


def _output_path(value: str) -> Path:
    source = Path(value).expanduser().resolve()
    if not (source / 'sigma_points.parquet').is_file():
        raise FileNotFoundError(f'Expected sigma_points.parquet in {source}')
    return source


def _spatial_changes(before_output: str, after_output: str) -> dict:
    """Compare unchanged establishment IDs across two published scored outputs."""
    a_root = _output_path(before_output)
    b_root = _output_path(after_output)
    old = pd.read_parquet(a_root / 'sigma_points.parquet')
    new = pd.read_parquet(b_root / 'sigma_points.parquet')
    for label, df in (('before', old), ('after', new)):
        if ('canonical_id' not in df or df['canonical_id'].duplicated().any()
                or _text_col(df, 'canonical_id').eq('').any()):
            raise ValueError(f'{label} scored output lacks unique canonical IDs')
    left = old.set_index('canonical_id')
    right = new.set_index('canonical_id')
    common = left.index.intersection(right.index)
    l, r = left.loc[common], right.loc[common]
    lt, rt = _text_col(l, 'type'), _text_col(r, 'type')
    lc, rc = _text_col(l, 'cluster'), _text_col(r, 'cluster')
    lx = pd.to_numeric(l.get('sigma_score', pd.Series(index=l.index, dtype=float)), errors='coerce')
    rx = pd.to_numeric(r.get('sigma_score', pd.Series(index=r.index, dtype=float)), errors='coerce')
    both = lx.notna() & rx.notna()
    score_changed = ~np.isclose(lx[both].to_numpy(dtype=float), rx[both].to_numpy(dtype=float), rtol=1e-8, atol=1e-10)
    return {
        'before_scored': int(len(left)), 'after_scored': int(len(right)),
        'shared_scored': int(len(common)),
        'newly_scored': int(len(right) - len(common)),
        'no_longer_scored': int(len(left) - len(common)),
        'changed_sector_type': int(lt.ne(rt).sum()),
        'changed_cluster_within_same_sector': int((lt.eq(rt) & lc.ne(rc)).sum()),
        'scores_present_both': int(both.sum()),
        'changed_score_for_shared_ids': int(score_changed.sum()),
        'comparison': 'IDs and numerical scores only; differing cluster labels are not evidence of worse clustering.',
    }


def compare(before: str, after: str, *,
            before_output: str | None = None, after_output: str | None = None) -> dict:
    old_root, old, old_audit = _read(before)
    new_root, new, new_audit = _read(after)
    result = {
        'before': {'path': str(old_root), **_summary(old, old_audit)},
        'after': {'path': str(new_root), **_summary(new, new_audit)},
        'paired': _aligned_changes(old, new),
        'limitations': [
            'These counts describe classifications, not independently verified establishment activity.',
            'Changes in sector count can be partition adaptations, not higher classification accuracy.',
            'Spatial cluster memberships and scores require separately preserved before/after output snapshots.',
        ],
    }
    if (before_output is None) != (after_output is None):
        raise ValueError('Specify both --before-output and --after-output or neither')
    if before_output is not None and after_output is not None:
        result['spatial_and_scores'] = _spatial_changes(before_output, after_output)
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', required=True, help='Preserved hierarchical snapshot or workspace')
    p.add_argument('--after', required=True, help='New hierarchical snapshot or workspace')
    p.add_argument('--before-output', help='Optional preserved published output directory for cluster/score comparison')
    p.add_argument('--after-output', help='Optional new published output directory for cluster/score comparison')
    args = p.parse_args()
    print(json.dumps(compare(args.before, args.after,
        before_output=args.before_output, after_output=args.after_output),
        indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()

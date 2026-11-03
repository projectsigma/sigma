"""Render-only provenance for sectors absorbed by SIGMA's iterative roll-up.

This does not retag establishments, recompute graph X, or invent child clusters.
The full classified POI handoff is authoritative for original sector membership.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def _text(value: object) -> str:
    return '' if value is None or pd.isna(value) else str(value).strip()


def original_label_map(derived_catalog_file: Path, economy_id: str) -> dict[str, str]:
    """Read the original catalog only within a verified derived package's ancestry.

    The caller first uses matching_catalog_files, which checks output ownership,
    the exact Economy ID, and derived roll-up file checksums. Never search by name.
    """
    file = Path(derived_catalog_file).resolve()
    if '-rollup-' not in economy_id or file.parent.name != 'economy':
        return {}
    # .../hierarchical/iterative_rollup/<sha24>/economy/sectors.csv
    if (file.parent.parent.parent.name != 'iterative_rollup'
            or file.parent.parent.parent.parent.name != 'hierarchical'):
        raise ValueError('roll-up sector catalog lies outside expected hierarchy')
    base = file.parent.parent.parent.parent / 'economy'
    base_spec = base / 'economy.yml'
    base_catalog = base / 'sectors.csv'
    if not base_spec.is_file() or not base_catalog.is_file():
        raise FileNotFoundError('original hierarchical economy catalog missing')
    data = yaml.safe_load(base_spec.read_text(encoding='utf-8')) or {}
    base_id = str(data.get('id', '')).strip()
    if not economy_id.startswith(base_id + '-rollup-'):
        raise ValueError('rolled-up economy does not descend from original catalog')
    table = pd.read_csv(base_catalog, dtype=str, keep_default_na=False)
    if not {'code', 'label'} <= set(table.columns) or table.code.duplicated().any():
        raise ValueError('original hierarchical sector catalog invalid')
    return dict(zip(table.code, table.label, strict=True))


def build_rollup_children(classified: pd.DataFrame | None, original_labels: dict[str, str],
                          effective_catalog: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Show genuine roll-up composition, including the destination's own places.

    Counts reflect **all classified POIs**, not only scored/clustered records.
    Non-roll-up datasets (no original_economy_code) get no expandable children.
    """
    if classified is None or 'original_economy_code' not in classified:
        return {}
    if not {'economy_code', 'original_economy_code'} <= set(classified.columns):
        raise ValueError('classified roll-up handoff has incomplete sector provenance')
    pairs: dict[str, dict[str, int]] = {}
    for effective, original in zip(classified['economy_code'], classified['original_economy_code'], strict=True):
        eff, orig = _text(effective), _text(original)
        if not eff:
            continue
        if eff not in effective_catalog:
            raise ValueError(f'roll-up POI has a sector absent from its Economy catalog: {eff}')
        if not orig or orig not in original_labels:
            raise ValueError(f'roll-up POI lacks a valid original sector: {orig!r}')
        bucket = pairs.setdefault(eff, {})
        bucket[orig] = bucket.get(orig, 0) + 1
    result: dict[str, list[dict[str, Any]]] = {}
    for parent, members in sorted(pairs.items()):
        if not any(original != parent for original in members):
            continue
        result[parent] = [{
            'code': code, 'label': original_labels[code],
            'places': int(count), 'rolled_up': code != parent,
        } for code, count in sorted(members.items(), key=lambda item: (item[0] != parent, item[0]))]
    return result


def validated_breakdown_for_run(source: Path, run: dict, classified: pd.DataFrame | None,
                                effective_catalog: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Resolve the same exact Economy catalog already required by local Explorer."""
    economy_id = str(run.get('economy_id', '')).strip()
    if '-rollup-' not in economy_id or classified is None:
        return {}
    from .unclustered import matching_catalog_files
    match = matching_catalog_files(source, run)
    if match is None:
        raise FileNotFoundError('validated roll-up catalog unavailable')
    original = original_label_map(match[0], economy_id)
    return build_rollup_children(classified, original, set(effective_catalog))

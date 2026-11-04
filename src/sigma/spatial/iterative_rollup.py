"""Optional, auditable residual-first hierarchical roll-up before a SIGMA analysis.

The baseline spatial.clusters immutable artifact must already be materialized from
an unmodified hierarchical Economy. This module never edits baseline artifacts.
A successful candidate creates a separate, content-addressed Economy/places
package; the normal Sigma analysis is then run with that package.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from sigma.economy.model import Economy, Sector, SectorCatalog
from sigma.places.frame_io import read_geoframe
from sigma.spatial.clustering import ClusteringConfig, SparseClusteringContext, cluster_by_type
from sigma.spatial.snap_context import load_sparse_context, validate_point_alignment

_SCHEME = 'sigma-iterative-residual-rollup-v1'
_SPARSE_CODE = re.compile(r'^\d+(?::(?:\d+|o)){0,2}$')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def nearest_residual(code: str, available: set[str]) -> str | None:
    """Nearest existing residual in valid sparse-code ancestry (no new buckets)."""
    if not _SPARSE_CODE.fullmatch(code):
        return None
    parts = code.split(':')
    candidates = []
    if len(parts) == 3 and parts[2] != 'o':
        candidates.append(f'{parts[0]}:{parts[1]}:o')
    if len(parts) >= 2:
        candidates.append(f'{parts[0]}:o')
    return next((c for c in candidates if c in available and c != code), None)


def candidate_groups(zero_codes: set[str], available: set[str],
                     attempted: set[tuple[str, str]] | None = None) -> dict[str, tuple[str, ...]]:
    """Next untried residual for each failed sector, closest ancestor first."""
    attempted = attempted or set()
    grouped: dict[str, set[str]] = defaultdict(set)
    for code in sorted(zero_codes):
        if not _SPARSE_CODE.fullmatch(code):
            continue
        parts = code.split(':')
        candidates = []
        if len(parts) == 3 and parts[-1] != 'o':
            candidates.append(f'{parts[0]}:{parts[1]}:o')
        if len(parts) >= 2:
            candidates.append(f'{parts[0]}:o')
        for target in candidates:
            if target != code and target in available and (code, target) not in attempted:
                grouped[target].add(code)
                break
    return {target: tuple(sorted(grouped[target])) for target in sorted(grouped)}


def config_from_manifest(manifest: dict[str, Any]) -> ClusteringConfig:
    p = manifest['recipe']['parameters']
    required = {'min_cluster_size', 'cluster_selection_method', 'hdbscan_max_distance',
                'hdbscan_distance_mode', 'hdbscan_distance_growth',
                'hdbscan_distance_steps', 'hdbscan_max_neighbor_pairs'}
    if not required.issubset(p):
        raise RuntimeError(f'clustering recipe missing parameters: {sorted(required - set(p))}')
    return ClusteringConfig(
        min_cluster_size=int(p['min_cluster_size']),
        min_samples=None if p.get('min_samples') is None else int(p['min_samples']),
        cluster_selection_method=str(p['cluster_selection_method']),
        allow_single_cluster=bool(p.get('allow_single_cluster', False)),
        max_distance=float(p['hdbscan_max_distance']),
        distance_mode=str(p['hdbscan_distance_mode']),
        min_distance=None if p.get('hdbscan_min_distance') is None else float(p['hdbscan_min_distance']),
        distance_growth=float(p['hdbscan_distance_growth']),
        distance_steps=int(p['hdbscan_distance_steps']),
        core_truncation_tolerance=float(p.get('hdbscan_core_truncation_tolerance', 0.01)),
        stability_tolerance=float(p.get('hdbscan_stability_tolerance', 1e-12)),
        max_neighbor_pairs=int(p['hdbscan_max_neighbor_pairs']),
    )



def baseline_summary_discrepancies(
    original_types: np.ndarray,
    assignments: np.ndarray,
    summaries: dict[str, dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Compare advisory audit counts with authoritative saved point assignments.

    Never use a possibly stale audit summary to decide zero-cluster eligibility.
    A disagreement MUST be independently replayed by the caller before accepting
    any roll-up; this helper deliberately does not suppress or modify it.
    """
    if len(original_types) != len(assignments):
        raise RuntimeError('baseline type/cluster arrays are not aligned')
    actual: dict[str, int] = {}
    mismatches: list[dict[str, Any]] = []
    for code in sorted(set(str(t) for t in original_types)):
        mask = original_types == code
        observed_n = int(np.count_nonzero(mask))
        retained = assignments[mask]
        observed_k = int(np.unique(retained[retained >= 0]).size)
        saved = summaries[code]
        audit_n = int(saved['n_points'])
        audit_k = int(saved['n_clusters'])
        actual[code] = observed_k
        if audit_n != observed_n or audit_k != observed_k:
            mismatches.append({
                'type': code,
                'audit_points': audit_n,
                'actual_points': observed_n,
                'audit_clusters': audit_k,
                'actual_clusters': observed_k,
            })
    return actual, mismatches


def _trial(points: gpd.GeoDataFrame, original_types: np.ndarray,
           positions: np.ndarray, destination: str, context: SparseClusteringContext,
           config: ClusteringConfig) -> tuple[np.ndarray, dict[str, Any]]:
    frame = points.iloc[positions].copy().reset_index(drop=True)
    frame['type'] = destination
    subset = SparseClusteringContext(
        graph=context.graph, snaps=context.snaps.subset(positions),
        edge_id=context.edge_id[positions],
    )
    events: list[dict[str, Any]] = []
    result = cluster_by_type(frame, subset, config, continue_on_error=True,
                             savepoints=None, events=events)
    summaries = result.attrs.get('clustering_summary', [])
    if len(summaries) != 1 or str(summaries[0].get('type')) != destination:
        raise RuntimeError(f'unexpected trial summary for {destination}')
    if any(str(row.get('status')) == 'skipped' for row in events) or summaries[0].get('clustering_method') == 'failed':
        raise RuntimeError(f'roll-up trial for {destination} failed; refusing silent fallback to noise')
    return result['cluster'].to_numpy(dtype=np.int64), dict(summaries[0])


def aggregate_economy(base: Economy, mappings: dict[str, str]) -> Economy:
    """Exact M Z M.T and M x aggregation, with unchanged surviving sector keys."""
    old_codes = list(base.sectors.codes)
    if base.x is None:
        raise ValueError('hierarchical iterative roll-up requires gross output')
    if any(source not in old_codes or target not in old_codes or source == target
           for source, target in mappings.items()):
        raise ValueError('roll-up source/target missing from base economic sector universe')
    if any(target in mappings for target in mappings.values()):
        raise ValueError('roll-up destinations cannot themselves be absorbed')
    new_codes = [c for c in old_codes if c not in mappings]
    m = np.zeros((len(new_codes), len(old_codes)), dtype=float)
    new_pos = {code: i for i, code in enumerate(new_codes)}
    for j, code in enumerate(old_codes):
        m[new_pos[mappings.get(code, code)], j] = 1.0
    old_z = base.Z_raw.to_numpy(dtype=float)
    old_x = base.x.to_numpy(dtype=float)
    new_z = m @ old_z @ m.T
    new_x = m @ old_x
    if not np.allclose(new_z.sum(), old_z.sum(), rtol=1e-12, atol=1e-7):
        raise ValueError('roll-up did not conserve total transactions')
    if not np.allclose(new_x.sum(), old_x.sum(), rtol=1e-12, atol=1e-7):
        raise ValueError('roll-up did not conserve total gross output')
    sector_labels = {s.code: s.label for s in base.sectors}
    digest = hashlib.sha256(json.dumps(sorted(mappings.items()), separators=(',', ':')).encode()).hexdigest()[:16]
    return Economy(
        economy_id=f'{base.economy_id}-rollup-{digest}',
        label=f'Residual-first iterative roll-up of {base.label}',
        version=base.version, reference_year=base.reference_year,
        sectors=SectorCatalog(Sector(code, sector_labels[code]) for code in new_codes),
        raw_transactions=pd.DataFrame(new_z, index=new_codes, columns=new_codes),
        total_output=pd.Series(new_x, index=new_codes, name='total_output'),
        provenance={'source_kind': 'hierarchical_io240_iterative_rollup',
                    'base_economy_fingerprint': base.economy_fingerprint,
                    'rollup_map': dict(sorted(mappings.items())),
                    'aggregation': 'M @ Z @ M.T; M @ x',
                    'rollup_scheme': _SCHEME},
    )


def _validate_membership(workspace: Path, base: Economy, mapping: dict[str, str]) -> pd.DataFrame:
    path = workspace / 'hierarchical' / 'economy' / 'membership.csv'
    if not path.is_file():
        raise RuntimeError('hierarchical membership.csv missing; refusing to infer sector ancestry')
    members = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {'economy_code', 'io240_code', 'io80_code', 'io16_code'}
    if not required.issubset(members.columns):
        raise RuntimeError('hierarchical membership.csv lacks validated ancestry columns')
    if len(members) != 240 or members.io240_code.duplicated().any() or set(members.economy_code) != set(base.sectors.codes):
        raise RuntimeError('hierarchical membership does not match base sector catalog')
    for source, target in mapping.items():
        ancestry = members.loc[members.economy_code == source]
        if ancestry.empty:
            raise RuntimeError(f'{source} has no IO240 members')
        parts = target.split(':')
        if parts[-1] != 'o':
            raise RuntimeError(f'{target} is not a residual destination')
        if len(parts) == 3:
            valid = ancestry.io80_code.eq(parts[1]) & ancestry.io16_code.eq(parts[0])
        elif len(parts) == 2:
            valid = ancestry.io16_code.eq(parts[0])
        else:
            raise RuntimeError(f'{target} is not a supported sparse residual code')
        if not valid.all():
            raise RuntimeError(f'{source} cannot be aggregated into non-ancestral {target}')
    out = members.copy()
    out['original_economy_code'] = out['economy_code']
    out['economy_code'] = out['economy_code'].replace(mapping)
    if out.io240_code.duplicated().any() or len(out) != len(members):
        raise RuntimeError('rolled membership is not an exclusive IO240 partition')
    return out


def _write_economy(directory: Path, economy: Economy, members: pd.DataFrame,
                   provenance: dict[str, Any], audit: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    e = economy
    e.sectors.to_frame().to_csv(directory / 'sectors.csv', index=False, lineterminator='\n')
    e.Z_raw.to_csv(directory / 'transactions.csv', index_label='sector', float_format='%.17g', lineterminator='\n')
    e.x.rename_axis('sector').reset_index().to_csv(
        directory / 'total_output.csv', index=False, float_format='%.17g', lineterminator='\n')
    meta: dict[str, Any] = {
        'id': e.economy_id, 'label': e.label, 'version': e.version,
        'reference_year': e.reference_year,
        'sectors': 'sectors.csv', 'transactions': 'transactions.csv',
        'total_output': 'total_output.csv', 'derivation': provenance,
    }
    (directory / 'economy.yml').write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding='utf-8')
    members.to_csv(directory / 'membership.csv', index=False, lineterminator='\n')
    (directory / 'rollup_audit.json').write_text(
        json.dumps(audit, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _validate_existing_package(directory: Path, fingerprint: str) -> Path:
    manifest = directory / 'rollup_manifest.json'
    if not manifest.is_file():
        raise RuntimeError(f'preexisting roll-up output lacks manifest: {directory}')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('recipe_sha256') != fingerprint:
        raise RuntimeError(f'preexisting roll-up output has different identity: {directory}')
    for rel, digest in data.get('file_hashes', {}).items():
        path = (directory / rel).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f'preexisting roll-up package altered: {rel}')
    if len(data.get('file_hashes', {})) < 5:
        raise RuntimeError('roll-up package manifest contains too few files')
    return directory


def prepare_iterative_rollup(
    *, workspace: Path, base_economy: Economy, base_places: Path, cluster_ref: Any,
    progress: Callable[[str], None] | None = None,
) -> Path | None:
    """Derive a new package, or return None when no acceptable residual merges.

    Assumes cluster_ref is from the baseline hierarchy. Reads the exact dependency
    points artifact and saved snap context; validates replay of every affected
    original sector before accepting any counterfactual.
    """
    workspace = Path(workspace).expanduser().resolve()
    base_places = Path(base_places).expanduser().resolve()
    expected_base = (workspace / 'hierarchical' / 'places.parquet').resolve()
    if base_places != expected_base:
        raise ValueError('iterative roll-up requires the original generated hierarchical places preview')
    if not base_places.is_file():
        raise FileNotFoundError(base_places)
    if cluster_ref.stage != 'spatial.clusters':
        raise ValueError('expected active baseline spatial.clusters artifact')
    manifest = json.loads((cluster_ref.path / 'artifact.json').read_text(encoding='utf-8'))
    dependency = manifest['recipe']['dependencies']['spatial.points']
    fingerprint = dependency['recipe_fingerprint']
    point_root = workspace / 'artifacts' / 'spatial.points' / str(fingerprint)
    points_manifest = json.loads((point_root / 'artifact.json').read_text(encoding='utf-8'))
    if points_manifest['artifact_id'] != dependency['artifact_id']:
        raise RuntimeError('spatial.points differs from baseline clustering dependency')
    cfg = config_from_manifest(manifest)
    cfg.validate()
    points = read_geoframe(point_root / 'points.parquet')
    clustered = read_geoframe(cluster_ref.path / 'clustered.parquet')
    if len(points) != len(clustered) or not points['canonical_id'].astype(str).equals(clustered['canonical_id'].astype(str)):
        raise RuntimeError('baseline clustering and input points are not positionally identical')
    if not points['type'].astype(str).equals(clustered['type'].astype(str)):
        raise RuntimeError('baseline sector assignments do not match input points')
    if points['canonical_id'].astype(str).duplicated().any():
        raise RuntimeError('duplicate canonical IDs in original clustering')
    original_type = points['type'].astype(str).to_numpy()
    available = set(original_type.tolist())
    if not all(_SPARSE_CODE.fullmatch(code) for code in available):
        raise ValueError('iterative roll-up supports only validated sparse hierarchical sector codes')
    if not available.issubset(set(base_economy.sectors.codes)):
        raise RuntimeError('baseline sector assignments not contained in economic sector catalog')
    audit_path = cluster_ref.path / 'clustering_audit.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    summary = {str(row['type']): row for row in audit.get('clustering_summary', [])}
    if set(summary) != available:
        raise RuntimeError('baseline audit sector set differs from input points')
    labels = clustered['cluster'].to_numpy(dtype=np.int64).copy()
    actual_cluster_counts, audit_mismatches = baseline_summary_discrepancies(
        original_type, labels, summary,
    )
    if audit_mismatches and progress:
        for item in audit_mismatches:
            progress(
                'iterative roll-up: WARNING saved clustering audit differs from '
                f"assignments for {item['type']} "
                f"(audit points={item['audit_points']}, actual={item['actual_points']}; "
                f"audit clusters={item['audit_clusters']}, actual={item['actual_clusters']}); "
                'exact replay required'
            )
    if not any(k == 0 for k in actual_cluster_counts.values()):
        if progress: progress('iterative roll-up: no zero-cluster sector; original hierarchy preserved')
        return None
    if progress: progress('iterative roll-up: loading saved sparse road graph and snaps')
    context, ctx_meta = load_sparse_context(cluster_ref.path / 'snap_context')
    validate_point_alignment(ctx_meta, points['canonical_id'].astype(str).tolist())
    replayed: set[str] = set()
    # Even an unrelated sector with stale audit metadata is verified against
    # the real saved assignments before any counterfactual can be published.
    for item in audit_mismatches:
        code = str(item['type'])
        original_positions = np.flatnonzero(original_type == code).astype(np.int64)
        replay_labels, _ = _trial(
            points, original_type, original_positions, code, context, cfg,
        )
        if not np.array_equal(replay_labels, labels[original_positions]):
            raise RuntimeError(
                f'baseline audit mismatch for {code} also fails exact clustering replay; '
                'saved assignments are incompatible with local code; no roll-ups published'
            )
        replayed.add(code)
        if progress:
            progress(f'iterative roll-up: baseline replay verified for {code}; ignoring only stale audit counts')
    working_type = original_type.copy()
    tested: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    attempted: set[tuple[str, str]] = set()
    # Each failed sector has at most two residual ancestors, so trials are finite.
    for iteration in range(1, 3 * len(available) + 1):
        live_types = set(working_type.tolist())
        zero_codes = {code for code in live_types if not np.any(labels[working_type == code] >= 0)}
        groups = candidate_groups(zero_codes, live_types, attempted)
        if not groups:
            break
        changed = False
        for target, sources in groups.items():
            participants = set(sources) | {target}
            positions = np.flatnonzero(np.isin(working_type, list(participants))).astype(np.int64)
            expected = int((labels[positions] >= 0).sum())
            # Replay affected sectors exactly once to exclude an incompatible
            # local SIGMA clustering implementation or stale saved result.
            for code in sorted(participants - replayed):
                if code not in available:
                    continue
                local_pos = np.flatnonzero(original_type == code).astype(np.int64)
                replay_labels, _ = _trial(points, original_type, local_pos, code, context, cfg)
                if not np.array_equal(replay_labels, clustered['cluster'].to_numpy(dtype=np.int64)[local_pos]):
                    raise RuntimeError(f'baseline replay differs for sector {code}; no roll-ups published')
                replayed.add(code)
            trial_labels, trial_summary = _trial(points, working_type, positions, target, context, cfg)
            recovered = sum(int(np.sum((working_type[positions] == src) & (trial_labels >= 0))) for src in sources)
            after = int(np.sum(trial_labels >= 0))
            event = {'iteration': iteration, 'destination': target, 'sources': list(sources),
                     'n_points': len(positions), 'before_retained': expected,
                     'after_retained': after, 'net_retained_gain': after - expected,
                     'gross_recovered': recovered,
                     'trial_clusters': int(trial_summary['n_clusters']),
                     'trial_clustering_method': trial_summary.get('clustering_method')}
            tested.append(event)
            attempted.update((src, target) for src in sources)
            if after <= expected:
                if progress: progress(f'iterative roll-up: rejected {sources} -> {target}: net {after-expected:+d}')
                continue
            labels[positions] = trial_labels
            for src in sources:
                working_type[working_type == src] = target
                mapping[src] = target
            accepted.append(event)
            changed = True
            if progress: progress(f'iterative roll-up: accepted {sources} -> {target}: net +{after-expected}, gross recovered {recovered}')
        # A rejected IO80 residual can be followed by an existing IO16 residual.
        # If any candidate remains untried, revisit failed sectors next round.
        if not changed and not candidate_groups(zero_codes, set(working_type.tolist()), attempted):
            break
    if not mapping:
        if progress: progress('iterative roll-up: no positive-net valid residual mergers; baseline preserved')
        return None
    # Validate economic membership before constructing any derived package.
    members = _validate_membership(workspace, base_economy, mapping)
    effective = aggregate_economy(base_economy, mapping)
    if set(members.economy_code) != set(effective.sectors.codes):
        raise RuntimeError('effective economic membership and sector catalog disagree')
    baseline_hash = sha256_file(base_places)
    receipt = {
        'scheme': _SCHEME, 'base_economy_fingerprint': base_economy.economy_fingerprint,
        'base_places_sha256': baseline_hash, 'cluster_artifact_id': cluster_ref.artifact_id,
        'cluster_recipe_fingerprint': cluster_ref.recipe_fingerprint,
        'rollup_map': dict(sorted(mapping.items())),
    }
    raw = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()
    recipe_hash = hashlib.sha256(raw).hexdigest()
    out = workspace / 'hierarchical' / 'iterative_rollup' / recipe_hash[:24]
    if out.exists():
        return _validate_existing_package(out, recipe_hash)
    # Use the unmodified generated hierarchical preview as the source of place
    # records and keep the original economic tag, PSIC and IO evidence intact.
    source_places = gpd.read_parquet(base_places)
    if 'economy_code' not in source_places or 'economy_label' not in source_places:
        raise RuntimeError('hierarchical preview lacks economy_code/economy_label')
    present = set(source_places.economy_code.astype('string').dropna().astype(str)) - {''}
    if not available.issubset(present):
        raise RuntimeError('baseline preview lacks sectors from original clustering')
    updated = source_places.copy()
    updated['original_economy_code'] = source_places['economy_code'].copy()
    updated['economy_code'] = source_places['economy_code'].replace(mapping)
    label_map = {s.code: s.label for s in effective.sectors}
    updated['economy_label'] = updated.economy_code.map(label_map).fillna('')
    updated['rollup_iteration'] = updated.original_economy_code.astype(str).map(
        {src: next(a['iteration'] for a in accepted if src in a['sources']) for src in mapping}
    ).astype('Int64')
    # Make sure tagged points have exactly the final effective sector values.
    if not set(updated.economy_code.astype('string').dropna().astype(str)) - {''} <= set(effective.sectors.codes):
        raise RuntimeError('some updated classified places refer to a missing effective sector')
    parent = out.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.rollup-tmp-', dir=parent))
    try:
        audit_data = {'scheme': _SCHEME, 'tested': tested, 'accepted': accepted,
                      'rolled_up_sectors': dict(sorted(mapping.items())),
                      'input_sector_count': len(base_economy.sectors),
                      'effective_sector_count': len(effective.sectors),
                      'point_count': len(points),
                      'baseline_cluster_count': int(clustered.loc[clustered.cluster >= 0, ['type', 'cluster']].drop_duplicates().shape[0]),
                      'predicted_cluster_count': int(pd.DataFrame({'type': working_type, 'cluster': labels})
                          .loc[lambda f: f.cluster >= 0, ['type', 'cluster']].drop_duplicates().shape[0])}
        provenance = dict(effective.provenance)
        provenance.update(receipt)
        provenance['recipe_sha256'] = recipe_hash
        _write_economy(tmp / 'economy', effective, members, provenance, audit_data)
        updated.to_parquet(tmp / 'places.parquet', index=False)
        file_hashes = {p.relative_to(tmp).as_posix(): sha256_file(p)
                       for p in sorted(tmp.rglob('*')) if p.is_file()}
        manifest_data = {'scheme': _SCHEME, 'recipe_sha256': recipe_hash,
                         'receipt': receipt, 'file_hashes': file_hashes}
        (tmp / 'rollup_manifest.json').write_text(
            json.dumps(manifest_data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        # Ensure same standard Economy.from_directory contract before publication.
        published = Economy.from_directory(tmp / 'economy')
        if published.sector_fingerprint != effective.sector_fingerprint:
            raise RuntimeError('serialized effective Economy sector fingerprint changed')
        if not np.allclose(published.Z_raw.to_numpy(), effective.Z_raw.to_numpy(), rtol=1e-12, atol=1e-8):
            raise RuntimeError('serialized effective Economy transactions changed')
        if out.exists():
            shutil.rmtree(tmp)
            return _validate_existing_package(out, recipe_hash)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    if progress: progress(f'iterative roll-up: generated validated alternative economic package {out}')
    return out

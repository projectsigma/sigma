"""Network-distance k-medoids refinement using a Gap-statistic adaptation.

HDBSCAN decides which observations belong to a density-based cluster. This module
can subdivide each *retained* HDBSCAN cluster into network-nearest-medoid cells;
it never assigns HDBSCAN noise, merges economic types, or invalidates clusters.

Methodology: Tibshirani, Walther & Hastie (2001) one-SE rule applied to the
weighted sum of road-network distances to observed demand-node medoids. Reference
samples are uniformly drawn from road *vertices* in each cluster's projected
axis-aligned bounding box and road connected component. This is a documented
network-specific null model, NOT the original Euclidean Gap statistic.

The medoid candidate restriction and capped demand subsample make optimization
approximate. Final child centers are independently recomputed by SIGMA's existing
exact network-vertex 1-median stage. Canonical SIGMA enables this single-pass
refinement by default with four workers; legacy `--equivalent` defaults off.
The module-level `NetworkGapConfig` defaults to serial for direct API callers.
Every run is audited; no recursive subdivision is performed.
"""
from __future__ import annotations

import hashlib
import math
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from sigma.transport._sparse_solver import SparseRoadSolver


@dataclass(frozen=True)
class NetworkGapConfig:
    max_k: int = 6
    replicates: int = 10
    max_sites: int = 64
    seed: int = 20261105
    min_members: int = 5
    workers: int = 1  # Python API retains serial behavior; CLI defaults to 4.

    def validate(self) -> None:
        if self.max_k < 2 or self.replicates < 2 or self.max_sites < 3:
            raise ValueError('network Gap requires max_k>=2, replicates>=2, max_sites>=3')
        if self.max_k >= self.max_sites:
            raise ValueError('network Gap max_k must be smaller than max_sites')
        if self.min_members < 2:
            raise ValueError('min_members must be >=2')
        if self.seed < 0:
            raise ValueError('network Gap seed must be non-negative')
        if isinstance(self.workers, bool) or not isinstance(self.workers, int) or not 1 <= self.workers <= 4:
            raise ValueError('network Gap workers must be an integer from 1 through 4')


def _bounded_distances(
    solver: SparseRoadSolver, sources: np.ndarray, targets: np.ndarray,
) -> np.ndarray:
    """Exact shortest road distances from a few source vertices to needed targets.

    SciPy's Dijkstra limit returns exact distances for reached vertices. Expand
    until every target has been reached. Multiple sources are processed in memory-
    bounded batches, and the component subgraph is cached by SparseRoadSolver.
    No road route is approximated or truncated by the radius.
    """
    sources = np.asarray(sources, dtype=np.int64)
    targets = np.asarray(targets, dtype=np.int64)
    if sources.ndim != 1 or targets.ndim != 1 or not len(sources) or not len(targets):
        raise ValueError('network Gap needs nonempty 1D source and destination arrays')
    comp = int(solver.component[sources[0]])
    if (np.any(solver.component[sources] != comp)
            or np.any(solver.component[targets] != comp)):
        raise ValueError('one candidate cluster crosses disconnected road components')
    component_nodes, sub = solver._component_graph(comp)
    src = np.searchsorted(component_nodes, sources)
    dst = np.searchsorted(component_nodes, targets)
    if (not np.array_equal(component_nodes[src], sources)
            or not np.array_equal(component_nodes[dst], targets)):
        raise RuntimeError('sampled nodes not found in road component')

    if solver.xy is None:
        first_limit = 2_000.0
    else:
        source_xy = np.asarray(solver.xy[sources], dtype=float)
        target_xy = np.asarray(solver.xy[targets], dtype=float)
        # 1.5x Euclidean diameter is a starting radius, NOT a distance proxy.
        span = source_xy[:, None, :] - target_xy[None, :, :]
        first_limit = max(1.0, 1.5 * float(np.hypot(span[..., 0], span[..., 1]).max(initial=0.0)))

    batch = max(1, 2_000_000 // max(len(component_nodes), 1))
    result = np.empty((len(sources), len(targets)), dtype=float)
    for start in range(0, len(sources), batch):
        stop = min(len(sources), start + batch)
        limit = first_limit
        while True:
            raw = np.atleast_2d(np.asarray(
                dijkstra(sub, directed=True, indices=src[start:stop], limit=limit),
                dtype=float,
            ))
            selected = raw[:, dst]
            if np.isfinite(selected).all():
                result[start:stop] = selected
                break
            if not np.isfinite(limit):
                raise RuntimeError('a within-component shortest-path matrix is not finite')
            limit = 2.0 * limit if limit < 1e12 else np.inf
    return result


def _matrix(solver: SparseRoadSolver, nodes: np.ndarray) -> np.ndarray:
    """Exact all-pairs shortest road distances between bounded candidate sites."""
    sites = np.asarray(nodes, dtype=np.int64)
    return _bounded_distances(solver, sites, sites)


def _medoid_curve(matrix: np.ndarray, weights: np.ndarray, maximum_k: int):
    """Deterministic PAM BUILD + SWAP, with vectorized cost evaluation.

    Retains the original candidate scan order and strict-improvement threshold,
    including first-wins behavior for numerically tied alternatives.
    """
    n = len(weights)
    chosen: list[int] = []
    objectives: list[float] = []
    site_sets: list[list[int]] = []
    for _ in range(min(maximum_k, n)):
        available = [j for j in range(n) if j not in chosen]
        if not available:
            break
        if chosen:
            current = matrix[:, chosen].min(axis=1)
            losses = np.minimum(current[:, None], matrix[:, available]).T @ weights
        else:
            losses = matrix[:, available].T @ weights
        added = available[int(np.argmin(losses))]
        chosen.append(added)
        chosen.sort()
        old = float(matrix[:, chosen].min(axis=1) @ weights)
        while True:
            move = None
            best = old
            owned = set(chosen)
            available = [j for j in range(n) if j not in owned]
            if not available:
                break
            # Removing one existing center leaves one nearest-distance vector.
            # For all replacement candidates, compute weighted costs together,
            # rather than rebuilding/reducing each candidate's k-column matrix.
            for position in range(len(chosen)):
                other = [v for j, v in enumerate(chosen) if j != position]
                if other:
                    nearest_other = matrix[:, other].min(axis=1)
                    costs = np.minimum(nearest_other[:, None], matrix[:, available]).T @ weights
                else:
                    costs = matrix[:, available].T @ weights
                for candidate, cost in zip(available, costs):
                    cost = float(cost)
                    if cost < best - max(1e-9, abs(best) * 1e-12):
                        best = cost
                        proposal = chosen.copy()
                        proposal[position] = int(candidate)
                        move = sorted(proposal)
            if move is None:
                break
            chosen = move
            old = best
        objectives.append(old)
        site_sets.append(chosen.copy())
    return np.asarray(objectives), site_sets


def _reference_pool(solver: SparseRoadSolver, tree: cKDTree, nodes: np.ndarray):
    """Network vertices inside the observed demand rectangle and component."""
    coords = np.asarray(solver.xy[nodes], dtype=float)
    lo, hi = coords.min(axis=0), coords.max(axis=0)
    mid = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0 + 1e-8
    close = np.asarray(tree.query_ball_point(mid, radius), dtype=np.int64)
    if len(close) == 0:
        return np.unique(nodes)
    xy = solver.xy[close]
    box = np.all((xy >= lo - 1e-8) & (xy <= hi + 1e-8), axis=1)
    comp = solver.component[close] == solver.component[nodes[0]]
    return np.unique(np.r_[close[box & comp], nodes])


def _seed(base: int, sector: str, cluster: int) -> int:
    raw = hashlib.sha256(f'{base}|{sector}|{cluster}'.encode('utf-8')).digest()
    return int.from_bytes(raw[:8], 'little')


def _selected_k(
    solver: SparseRoadSolver, original: np.ndarray, tree: cKDTree,
    config: NetworkGapConfig, rng: np.random.Generator,
):
    # Sample establishment observations (not unique sites) to preserve multiplicity.
    sample = original
    if len(sample) > config.max_sites:
        sample = original[np.sort(rng.choice(len(original), config.max_sites, replace=False))]
    sites, weights = np.unique(sample, return_counts=True)
    distinct = len(sites)
    if distinct < 3:
        return 1, [], 'insufficient_distinct_positions', [], len(sample), 0
    upper = min(config.max_k, distinct - 1)
    observed, site_sets = _medoid_curve(_matrix(solver, sites), weights.astype(float), upper)
    if observed[0] <= 1e-12:
        return 1, [], 'zero_one_median_loss', [], len(sample), 0
    pool = _reference_pool(solver, tree, sites)
    if len(pool) < 3:
        return 1, [], 'insufficient_reference_support', [], len(sample), len(pool)
    null_log = np.empty((config.replicates, upper), dtype=float)
    for b in range(config.replicates):
        ref = np.asarray(rng.choice(pool, size=len(sample), replace=True), dtype=np.int64)
        ref_sites, ref_weights = np.unique(ref, return_counts=True)
        rk = min(upper, len(ref_sites))
        ref_loss, _ = _medoid_curve(_matrix(solver, ref_sites), ref_weights.astype(float), rk)
        # Duplicates can reduce the null's distinct positions below upper.
        # With no new eligible sites, additional k has zero improvement.
        remaining = np.pad(ref_loss, (0, upper - len(ref_loss)), mode='edge')
        null_log[b] = np.log(np.maximum(remaining, 1e-12))
    gap = null_log.mean(axis=0) - np.log(np.maximum(observed, 1e-12))
    standard_error = null_log.std(axis=0, ddof=1) * math.sqrt(1.0 + 1.0 / config.replicates)
    selected = upper
    status = 'upper_bound_reached'
    for j in range(upper - 1):
        if gap[j] >= gap[j + 1] - standard_error[j + 1]:
            selected = j + 1
            status = 'one_se_stopping_rule'
            break
    return selected, gap.tolist(), status, [int(sites[j]) for j in site_sets[selected - 1]], len(sample), len(pool)


# A fixed process pool: each worker owns its own road adjacency, component labels,
# coordinate array, spatial index, and per-component Dijkstra cache. None of these
# objects is shared or sent with each cluster task.  Windows uses spawn explicitly.
_GAP_WORKER_STATE = None


def _init_gap_worker(adjacency, component, xy, config: NetworkGapConfig) -> None:
    global _GAP_WORKER_STATE
    # BLAS matrix-vector operations should not start a second thread pool per
    # process. threadpoolctl is optional; no additional runtime dependency.
    try:
        from threadpoolctl import threadpool_limits
        threadpool_limits(limits=1, user_api='blas')
    except ImportError:
        pass
    solver = SparseRoadSolver(adjacency, component, xy)
    _GAP_WORKER_STATE = (solver, cKDTree(xy), config)


def _compute_gap_cluster(solver, tree, config, sector, original_cluster, demand):
    """Pure per-cluster work. Cluster IDs are deliberately NOT allocated here."""
    selected = 1
    gap: list[float] = []
    medoids: list[int] = []
    status = 'one_site'
    sampled = len(demand)
    support = 0
    unique_count = int(len(np.unique(demand)))
    if len(demand) < 2 * config.min_members:
        status = 'insufficient_members_for_split'
    elif unique_count >= 3:
        rng = np.random.default_rng(_seed(config.seed, sector, original_cluster))
        selected, gap, status, medoids, sampled, support = _selected_k(
            solver, demand, tree, config, rng,
        )
    else:
        status = 'insufficient_distinct_positions'
    owners = None
    if selected > 1:
        # Same sorted medoid order, distance tie handling and min-members check as
        # the serial implementation. Distances are exact expanding-radius Dijkstra.
        medoids = sorted(medoids)
        distances = _bounded_distances(solver, np.asarray(medoids, dtype=np.int64), demand)
        if not np.isfinite(distances).all():
            raise RuntimeError(f'network Gap disconnected child in {sector}/{original_cluster}')
        owners = np.argmin(distances, axis=0)
        active = np.unique(owners)
        counts = np.bincount(owners, minlength=len(medoids))
        if len(active) <= 1 or not np.all(counts[active] >= config.min_members):
            selected, status, medoids, owners = 1, 'no_admissible_partition', [], None
    return {
        'selected': int(selected), 'gap': gap, 'status': status, 'medoids': medoids,
        'sampled': int(sampled), 'support': int(support), 'unique_count': unique_count,
        'owners': owners,
    }


def _run_gap_worker(task):
    if _GAP_WORKER_STATE is None:
        raise RuntimeError('network Gap worker was not initialized')
    solver, tree, config = _GAP_WORKER_STATE
    sector, original_cluster, demand = task
    return _compute_gap_cluster(solver, tree, config, sector, original_cluster, demand)


def refine_clusters_by_gap(
    retained: pd.DataFrame, network, config: NetworkGapConfig,
    *, progress=None,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    """Refine HDBSCAN clusters independently, with deterministic final labeling.

    Parallel workers return only per-cluster selection/assignment results.  The
    calling process assigns child IDs in the original sorted group order, keeping
    the output, audit ordering, and split-only progress identical to serial mode.
    """
    config.validate()
    required = {'type', 'cluster', 'canonical_id', 'network_node'}
    if not required <= set(retained.columns):
        raise ValueError(f'network Gap missing columns: {sorted(required - set(retained.columns))}')
    if retained.empty:
        return np.empty(0, dtype=np.int64), []
    solver = SparseRoadSolver.from_augmented(network)
    if solver.xy is None:
        raise ValueError('network Gap requires projected network-node geometry')
    new_labels = retained['cluster'].to_numpy(dtype=np.int64, copy=True)
    audit: list[dict[str, object]] = []
    maxima = retained.groupby('type', sort=False)['cluster'].max().astype(int).to_dict()
    jobs = []
    heavy_tasks = []
    for (sector, original_cluster), indices in retained.groupby(
        ['type', 'cluster'], sort=True,
    ).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        keys = retained.iloc[positions]['canonical_id'].astype(str).to_numpy()
        positions = positions[np.argsort(keys, kind='stable')]
        demand = retained.iloc[positions]['network_node'].to_numpy(np.int64)
        sector = str(sector)
        original_cluster = int(original_cluster)
        eligible = (len(demand) >= 2 * config.min_members and len(np.unique(demand)) >= 3)
        jobs.append((sector, original_cluster, positions, demand, eligible))
        if eligible:
            heavy_tasks.append((sector, original_cluster, demand))

    def assemble(results):
        for sector, original_cluster, positions, demand, eligible in jobs:
            if eligible:
                outcome = next(results)
            else:
                # No graph search or reference draws for infeasible clusters.
                outcome = {
                    'selected': 1, 'gap': [],
                    'status': ('insufficient_members_for_split'
                               if len(demand) < 2 * config.min_members else 'one_site'),
                    'medoids': [], 'sampled': len(demand), 'support': 0,
                    'unique_count': int(len(np.unique(demand))), 'owners': None,
                }
            selected = int(outcome['selected'])
            medoids = outcome['medoids']
            assigned_ids = [original_cluster]
            if selected > 1:
                owners = outcome['owners']
                if owners is None:
                    raise RuntimeError('split result is missing point-to-medoid assignments')
                active = np.unique(owners)
                primary = int(owners[0])
                mapping = {primary: original_cluster}
                for child in active:
                    if int(child) != primary:
                        maxima[sector] += 1
                        mapping[int(child)] = int(maxima[sector])
                new_labels[positions] = [mapping[int(x)] for x in owners]
                assigned_ids = sorted(mapping.values())
            audit.append({
                'type': sector, 'hdbscan_cluster': original_cluster,
                'observations': int(len(positions)),
                'distinct_demand_nodes': int(outcome['unique_count']),
                'sampled_observations': int(outcome['sampled']),
                'reference_vertex_pool': int(outcome['support']),
                'selected_k': selected, 'outcome': outcome['status'],
                'new_cluster_ids': assigned_ids,
                'selected_medoid_nodes': medoids,
                'gap_by_k': [float(x) for x in outcome['gap']],
                'sampled_approximation': bool(outcome['sampled'] < len(demand)),
            })
            if progress is not None and selected > 1:
                progress(f'network Gap: sector {sector} cluster {original_cluster} -> {selected} road-median cells')
        if len(new_labels) != len(retained) or np.any(new_labels < 0):
            raise RuntimeError('network Gap changed retained-point eligibility')
        return new_labels, audit

    if not heavy_tasks:
        return assemble(iter(()))
    if config.workers == 1 or len(heavy_tasks) == 1:
        tree = cKDTree(np.asarray(solver.xy, dtype=float))
        serial_results = (
            _compute_gap_cluster(solver, tree, config, *task) for task in heavy_tasks
        )
        return assemble(iter(serial_results))

    # Pass large road arrays only once at process initialization, not with every
    # cluster task.  Four isolated workers reuse their own subgraph caches.
    # Explicit spawn works from Windows conda CLI, not only from Unix fork mode.
    context = multiprocessing.get_context('spawn')
    with ProcessPoolExecutor(
        max_workers=min(config.workers, len(heavy_tasks)),
        mp_context=context,
        initializer=_init_gap_worker,
        initargs=(solver.adjacency, solver.component, np.asarray(solver.xy), config),
    ) as executor:
        ordered = executor.map(_run_gap_worker, heavy_tasks, chunksize=1)
        return assemble(iter(ordered))

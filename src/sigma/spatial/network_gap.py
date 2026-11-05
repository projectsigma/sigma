"""Optional network-distance k-medoids refinement using a Gap-statistic adaptation.

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
exact network-vertex 1-median stage.  The feature is opt-in and audited.
"""
from __future__ import annotations

import hashlib
import math
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

    def validate(self) -> None:
        if self.max_k < 2 or self.replicates < 2 or self.max_sites < 3:
            raise ValueError('network Gap requires max_k>=2, replicates>=2, max_sites>=3')
        if self.max_k >= self.max_sites:
            raise ValueError('network Gap max_k must be smaller than max_sites')
        if self.min_members < 2:
            raise ValueError('min_members must be >=2')
        if self.seed < 0:
            raise ValueError('network Gap seed must be non-negative')


def _matrix(solver: SparseRoadSolver, nodes: np.ndarray) -> np.ndarray:
    """All shortest road distances among bounded, unique demand network nodes."""
    sites = np.asarray(nodes, dtype=np.int64)
    if len(sites) == 0:
        raise ValueError('cannot compute an empty road distance matrix')
    if np.any(solver.component[sites] != solver.component[sites[0]]):
        raise ValueError('one candidate cluster crosses disconnected road components')
    component_nodes, sub = solver._component_graph(int(solver.component[sites[0]]))
    local = np.searchsorted(component_nodes, sites)
    if not np.array_equal(component_nodes[local], sites):
        raise RuntimeError('sampled nodes not found in road component')
    batch = max(1, 2_000_000 // max(len(component_nodes), 1))
    matrix = np.empty((len(sites), len(sites)), dtype=float)
    for start in range(0, len(sites), batch):
        end = min(len(sites), start + batch)
        raw = dijkstra(sub, directed=True, indices=local[start:end])
        raw = np.atleast_2d(np.asarray(raw, dtype=float))
        matrix[start:end] = raw[:, local]
    if not np.isfinite(matrix).all():
        raise RuntimeError('a within-component shortest-path matrix is not finite')
    return matrix


def _medoid_curve(matrix: np.ndarray, weights: np.ndarray, maximum_k: int):
    """Deterministic PAM-style greedy BUILD + improving SWAP for every candidate k."""
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
        # Strict improvements ensure termination (finite subsets of candidates).
        while True:
            move = None
            best = old
            owned = set(chosen)
            for position in range(len(chosen)):
                for candidate in range(n):
                    if candidate in owned:
                        continue
                    proposal = chosen.copy()
                    proposal[position] = candidate
                    cost = float(matrix[:, proposal].min(axis=1) @ weights)
                    if cost < best - max(1e-9, abs(best) * 1e-12):
                        best, move = cost, sorted(proposal)
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


def refine_clusters_by_gap(
    retained: pd.DataFrame, network, config: NetworkGapConfig,
    *, progress=None,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    """Return revised cluster labels for retained points; never discard observations.

    Caller must provide columns type, cluster, canonical_id, network_node.
    Labels remain unchanged for k=1; new children receive IDs above the
    largest original cluster index in their economic sector.
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
    tree = cKDTree(np.asarray(solver.xy, dtype=float))
    new_labels = retained['cluster'].to_numpy(dtype=np.int64, copy=True)
    audit: list[dict[str, object]] = []
    maxima = retained.groupby('type', sort=False)['cluster'].max().astype(int).to_dict()
    # A single cluster may contain many establishments but few distinct sites.
    for (sector, original_cluster), indices in retained.groupby(['type', 'cluster'], sort=True).indices.items():
        positions = np.asarray(indices, dtype=np.int64)
        sort_key = retained.iloc[positions]['canonical_id'].astype(str).to_numpy()
        positions = positions[np.argsort(sort_key, kind='stable')]
        demand = retained.iloc[positions]['network_node'].to_numpy(np.int64)
        selected = 1
        gap: list[float] = []
        medoids: list[int] = []
        status = 'one_site'
        sampled = len(demand)
        support = 0
        if len(np.unique(demand)) >= 3:
            rng = np.random.default_rng(_seed(config.seed, str(sector), int(original_cluster)))
            selected, gap, status, medoids, sampled, support = _selected_k(
                solver, demand, tree, config, rng,
            )
        assigned_ids = [int(original_cluster)]
        if selected > 1:
            # Assign *all* original observations by exact network distance, not
            # just sampled demand sites. Tie-break by lowest network node ID.
            medoids = sorted(medoids)
            distances = np.stack([
                np.asarray(dijkstra(solver.adjacency, directed=True, indices=int(medoid)), dtype=float)[demand]
                for medoid in medoids
            ])
            if not np.isfinite(distances).all():
                raise RuntimeError(f'network Gap disconnected child in {sector}/{original_cluster}')
            owners = np.argmin(distances, axis=0)
            active = np.unique(owners)
            counts = np.bincount(owners, minlength=len(medoids))
            if len(active) > 1 and np.all(counts[active] >= config.min_members):
                # Preserve parent's label for the child with smallest canonical ID.
                primary = int(owners[0])
                mapping = {primary: int(original_cluster)}
                for child in active:
                    if int(child) == primary:
                        continue
                    maxima[sector] += 1
                    mapping[int(child)] = int(maxima[sector])
                new_labels[positions] = [mapping[int(x)] for x in owners]
                assigned_ids = sorted(mapping.values())
            else:
                selected = 1
                status = 'no_admissible_partition'
                medoids = []
        audit.append({
            'type': str(sector), 'hdbscan_cluster': int(original_cluster),
            'observations': int(len(positions)), 'distinct_demand_nodes': int(len(np.unique(demand))),
            'sampled_observations': int(sampled), 'reference_vertex_pool': int(support),
            'selected_k': int(selected), 'outcome': status,
            'new_cluster_ids': assigned_ids,
            'selected_medoid_nodes': medoids,
            'gap_by_k': [float(x) for x in gap],
            'sampled_approximation': bool(sampled < len(demand)),
        })
        if progress is not None and selected > 1:
            progress(f'network Gap: sector {sector} cluster {original_cluster} -> {selected} road-median cells')
    if len(new_labels) != len(retained) or np.any(new_labels < 0):
        raise RuntimeError('network Gap changed retained-point eligibility')
    return new_labels, audit

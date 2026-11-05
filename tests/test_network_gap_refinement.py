import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sigma.spatial.network_gap import NetworkGapConfig, _matrix, _medoid_curve, refine_clusters_by_gap
from sigma.transport._sparse_solver import SparseRoadSolver


def chain_solver(n=25):
    weights = np.ones(n - 1, dtype=float)
    adjacency = csr_matrix((np.r_[weights, weights],
        (np.r_[np.arange(n-1), np.arange(1,n)],
         np.r_[np.arange(1,n), np.arange(n-1)])), shape=(n, n))
    return SparseRoadSolver(adjacency,
        np.zeros(n, dtype=np.int64), np.stack([np.arange(n), np.zeros(n)], axis=1))


def test_pam_reduces_network_objective_for_two_separated_groups():
    solver = chain_solver()
    distances = _matrix(solver, np.array([1, 2, 3, 18, 19, 20]))
    objective, centers = _medoid_curve(distances, np.ones(6), 3)
    assert objective[1] < objective[0]
    assert len(centers[1]) == 2


def test_refinement_never_changes_membership_or_economic_type(monkeypatch):
    from sigma.spatial import network_gap
    solver = chain_solver()
    monkeypatch.setattr(network_gap.SparseRoadSolver, 'from_augmented',
                        lambda network: solver)
    # Cluster with just two distinct road positions is kept intact.
    frame = pd.DataFrame({
        'type': ['01'] * 12,
        'cluster': [0] * 6 + [1] * 6,
        'canonical_id': [str(x).zfill(3) for x in range(12)],
        'network_node': [2] * 3 + [3] * 3 + [17] * 3 + [18] * 3,
    })
    labels, audit = refine_clusters_by_gap(frame, object(), NetworkGapConfig())
    assert len(labels) == 12
    assert np.array_equal(labels, frame.cluster.to_numpy())
    assert len(audit) == 2
    assert all(row['selected_k'] == 1 for row in audit)


def test_run_help_exposes_median_gap_options():
    from typer.testing import CliRunner
    from sigma.cli import app
    response = CliRunner().invoke(app, ["run", "--help"], env={"NO_COLOR":"1", "COLUMNS":"220"})
    assert response.exit_code == 0, response.output
    assert "--median-gap" in response.output
    assert "--median-gap-workers" in response.output


def test_configuration_rejects_missing_model_comparisons():
    import pytest
    with pytest.raises(ValueError):
        NetworkGapConfig(max_k=1).validate()
    with pytest.raises(ValueError):
        NetworkGapConfig(max_k=8, max_sites=8).validate()


def test_gap_fast_pam_matches_original_scalar_swap_on_metric_matrices():
    """Lock in the original strict-improvement and first-wins tie semantics."""
    def slow_curve(matrix, weights, maximum_k):
        n = len(weights)
        chosen, objectives, site_sets = [], [], []
        for _ in range(min(maximum_k, n)):
            available = [j for j in range(n) if j not in chosen]
            if not available:
                break
            if chosen:
                current = matrix[:, chosen].min(axis=1)
                losses = np.minimum(current[:, None], matrix[:, available]).T @ weights
            else:
                losses = matrix[:, available].T @ weights
            chosen.append(available[int(np.argmin(losses))])
            chosen.sort()
            old = float(matrix[:, chosen].min(axis=1) @ weights)
            while True:
                move, best, owned = None, old, set(chosen)
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
                chosen, old = move, best
            objectives.append(old)
            site_sets.append(chosen.copy())
        return np.asarray(objectives), site_sets

    for seed in range(20):
        rng = np.random.default_rng(seed)
        n = 5 + seed * 3
        xy = rng.integers(0, 90, size=(n, 2)).astype(float)
        metric = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2)
        weights = rng.integers(1, 8, size=n).astype(float)
        expected, original_medoids = slow_curve(metric, weights, 6)
        actual, optimized_medoids = _medoid_curve(metric, weights, 6)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-8)
        assert optimized_medoids == original_medoids


def test_gap_fast_bounded_distances_exact_with_detour_and_duplicate_targets():
    from sigma.spatial.network_gap import _bounded_distances
    from scipy.sparse.csgraph import dijkstra
    solver = chain_solver(100)
    # Geographic proximity must not be mistaken for network connectivity.
    solver = SparseRoadSolver(solver.adjacency, solver.component,
                              np.zeros((100, 2), dtype=float))
    src = np.array([1, 50, 80], dtype=np.int64)
    target = np.array([1, 3, 3, 72, 99], dtype=np.int64)
    expected = np.asarray(dijkstra(solver.adjacency, directed=True, indices=src))[:, target]
    np.testing.assert_allclose(_bounded_distances(solver, src, target), expected, rtol=0, atol=0)
    np.testing.assert_allclose(_matrix(solver, src),
                               np.asarray(dijkstra(solver.adjacency, directed=True, indices=src))[:, src],
                               rtol=0, atol=0)


def test_gap_fast_skips_clusters_too_small_for_two_admissible_children(monkeypatch):
    from sigma.spatial import network_gap
    solver = chain_solver(20)
    monkeypatch.setattr(network_gap.SparseRoadSolver, 'from_augmented', lambda network: solver)
    def forbidden(*args, **kwargs):
        raise AssertionError('Gap model must not run when two child clusters are impossible')
    monkeypatch.setattr(network_gap, '_selected_k', forbidden)
    frame = pd.DataFrame({
        'type': ['03'] * 9, 'cluster': [0] * 9,
        'canonical_id': [str(i) for i in range(9)],
        'network_node': list(range(9)),
    })
    messages = []
    labels, audit = refine_clusters_by_gap(frame, object(), NetworkGapConfig(min_members=5),
                                          progress=messages.append)
    np.testing.assert_array_equal(labels, np.zeros(9, dtype=np.int64))
    assert messages == []
    assert audit[0]['selected_k'] == 1
    assert audit[0]['outcome'] == 'insufficient_members_for_split'


def test_gap_multiprocess_matches_serial_end_to_end():
    """Spawn workers must preserve exact labels, order, audit and split messages."""
    from types import SimpleNamespace
    from sigma.spatial.network_gap import refine_clusters_by_gap
    solver = chain_solver(150)
    network = SimpleNamespace(
        nodes=pd.DataFrame({'network_node': np.arange(150, dtype=np.int64)}),
        sparse_adjacency=solver.adjacency,
        sparse_component=solver.component,
        _node_xy=solver.xy,
    )
    base = np.array([2, 3, 4, 6, 7, 9, 64, 65, 66, 70, 72, 75, 115, 116, 118, 123], dtype=np.int64)
    rows = []
    for sector, offset in [('04', 0), ('06', 1), ('08', 2)]:
        for i, node in enumerate(base + offset):
            rows.append((sector, 1, f'{sector}-{i:03d}', int(node)))
    frame = pd.DataFrame(rows, columns=['type', 'cluster', 'canonical_id', 'network_node'])
    cfg = NetworkGapConfig(max_k=4, replicates=3, max_sites=12, min_members=5)
    serial_logs, parallel_logs = [], []
    a, aa = refine_clusters_by_gap(frame, network,
        NetworkGapConfig(max_k=cfg.max_k, replicates=cfg.replicates,
                         max_sites=cfg.max_sites, seed=cfg.seed,
                         min_members=cfg.min_members, workers=1), progress=serial_logs.append)
    b, bb = refine_clusters_by_gap(frame, network,
        NetworkGapConfig(max_k=cfg.max_k, replicates=cfg.replicates,
                         max_sites=cfg.max_sites, seed=cfg.seed,
                         min_members=cfg.min_members, workers=4), progress=parallel_logs.append)
    np.testing.assert_array_equal(a, b)
    assert aa == bb
    assert serial_logs == parallel_logs



def test_gap_parallel_split_id_allocation_matches_serial():
    """Actual k>1 case: child IDs are allocated by the parent, not workers."""
    from types import SimpleNamespace
    solver = chain_solver(150)
    network = SimpleNamespace(
        nodes=pd.DataFrame({'network_node': np.arange(150, dtype=np.int64)}),
        sparse_adjacency=solver.adjacency,
        sparse_component=solver.component,
        _node_xy=solver.xy,
    )
    nodes = list(range(5, 15)) + list(range(125, 135))
    frame = pd.DataFrame({
        'type': ['A'] * 40,
        'cluster': [0] * 20 + [1] * 20,
        'canonical_id': [str(i) for i in range(40)],
        'network_node': nodes * 2,
    })
    kw = dict(max_k=4, replicates=6, max_sites=20, min_members=5)
    serial, sa = refine_clusters_by_gap(frame, network, NetworkGapConfig(workers=1, **kw))
    parallel, pa = refine_clusters_by_gap(frame, network, NetworkGapConfig(workers=4, **kw))
    np.testing.assert_array_equal(serial, parallel)
    assert sa == pa
    assert any(row['selected_k'] > 1 for row in sa)
    assert set(np.unique(serial)) == {0, 1, 2, 3}


def test_gap_worker_count_validation():
    import pytest
    for invalid in (0, -1, 5):
        with pytest.raises(ValueError):
            NetworkGapConfig(workers=invalid).validate()

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


def test_configuration_rejects_missing_model_comparisons():
    import pytest
    with pytest.raises(ValueError):
        NetworkGapConfig(max_k=1).validate()
    with pytest.raises(ValueError):
        NetworkGapConfig(max_k=8, max_sites=8).validate()

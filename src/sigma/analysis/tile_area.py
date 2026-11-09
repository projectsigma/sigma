"""Per-geography total-degree PPML and two tile-perspective Katz weight operators.

The original X weights W stay in ``analysis.x``. Katz uses two adjusted operators,
F W (outgoing) and F W.T (incoming), with F = diag(A_km2 ** -gamma). This is NOT
ordinary Katz on F W and its transpose.
"""
from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import ArpackNoConvergence, LinearOperator, eigs
from scipy.stats import norm, spearmanr

from .centrality import CentralityResult

METHOD_ID = "tile-perspective-total-degree-ppml-20261109-r3"
# Diagnostics only (spec §9.7); the scores of METHOD_ID are unchanged.
DIAGNOSTICS_VERSION = "spec-9.7-20261109-v2-consistent-deciles"
EDGE_COLUMNS = ("source_type", "source_cluster", "target_type", "target_cluster", "edge_weight")
ORIGINAL_X_EDGE_WEIGHT = (
    "technical_coefficient_times_both_clustered_sector_shares_times_inverse_mean_hub_distance"
)
AREA_CRS = "EPSG:6933"
AUDIT_COLUMNS = (
    "node_id", "voronoi_area_km2", "area_factor", "out_strength_original",
    "in_strength_original", "out_strength_adjusted", "in_strength_adjusted",
)


def _json_safe(value):
    """Return ``value`` with non-finite floats replaced by None (strict JSON manifests)."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _ppml(y: np.ndarray, log_area: np.ndarray, name: str, *, required: bool = False) -> dict:
    """PPML with log link, HC1 sandwich uncertainty, and retained zero outcomes.

    The response is rescaled by its mean only to condition the optimizer; it
    changes the intercept, not the area elasticity or robust standard error.
    When ``required`` is False, a failure is recorded in the returned status
    instead of raised, so a diagnostic fit cannot stop the stage.
    """
    y = np.asarray(y, dtype=float)
    log_area = np.asarray(log_area, dtype=float)
    n = len(y)
    if n != len(log_area) or not np.isfinite(y).all() or (y < 0).any():
        raise ValueError(f"{name}: response is invalid")
    if not np.isfinite(log_area).all():
        raise ValueError(f"{name}: invalid polygon areas")
    info = {"outcome": name, "observations": n, "zero_count": int((y == 0).sum())}
    if n < 5 or np.all(y == 0) or np.ptp(log_area) < 1e-12:
        if required:
            raise RuntimeError(f"Cannot estimate area scaling for {name}: too few nodes, "
                               "no positive connections, or no area variation")
        return {**info, "status": "not_estimable"}
    yn = y / float(np.mean(y))
    centered = log_area - float(log_area.mean())
    X = np.column_stack((np.ones(n), centered))

    def objective(parameters):
        eta = X @ parameters
        if (eta > 60).any() or (eta < -60).any():
            return float("inf"), np.full(2, np.nan)
        mu = np.exp(eta)
        return (float(np.mean(mu - yn * eta)), X.T @ (mu - yn) / n)

    fit = minimize(objective, np.zeros(2), method="L-BFGS-B", jac=True,
                   bounds=[(-40., 40.), (-25., 25.)],
                   options={"ftol": 1e-13, "gtol": 1e-10, "maxiter": 2000})
    if (not np.isfinite(fit.fun) or not np.isfinite(fit.x).all() or
            np.max(np.abs(objective(fit.x)[1])) > 2e-5):
        message = f"Area PPML optimization failed for {name}: {fit.message}"
        if required:
            raise RuntimeError(message + "; refusing a hardcoded or unvalidated exponent")
        return {**info, "status": "optimization_failed", "optimizer_message": str(fit.message)}
    mu = np.exp(X @ fit.x)
    errors = yn - mu
    H = X.T @ (mu[:, None] * X)
    meat = X.T @ ((errors ** 2)[:, None] * X)
    invH = np.linalg.pinv(H)
    cov = invH @ meat @ invH * (n / (n - 2))
    se = math.sqrt(max(float(cov[1, 1]), 0.0))
    gamma = float(fit.x[1])
    z = gamma / se if se > 0 else float("nan")
    correlation = spearmanr(log_area, y)
    return {
        **info, "status": "ok", "area_elasticity": gamma,
        "intercept_log_area_km2": float(fit.x[0] + math.log(np.mean(y)) -
                                         gamma * log_area.mean()),
        "robust_se_hc1": se,
        "ci95_low": gamma - 1.96 * se, "ci95_high": gamma + 1.96 * se,
        "p_value": float(2 * norm.sf(abs(z))) if math.isfinite(z) else None,
        "area_spearman_rho": float(correlation.statistic),
        "factor_if_area_doubles": float(2 ** gamma),
        "optimizer_message": str(fit.message),
    }


def _is_acyclic(W: csr_matrix) -> bool:
    """True when the directed support of W has no cycle.

    A positive diagonal F does not change the support, so F W and F W.T are
    acyclic exactly when W is. Decided from the edge table, not a manifest flag.
    """
    n = W.shape[0]
    if W.nnz == 0:
        return True
    if np.any(W.diagonal() != 0):
        return False
    count, _ = connected_components(W, directed=True, connection="strong")
    return int(count) == n


def _spectral_scale(W: csr_matrix, Wt: csr_matrix, factor: np.ndarray, *, acyclic: bool) -> dict:
    """One shared Katz scale for F W and F W.T; every fallback bounds both operators.

    Mirrors ``centrality._spectral_radius_or_safe_scale``: an acyclic X has
    spectral radius zero, so ARPACK is not called (it can return a spurious
    small positive radius on a nilpotent matrix, which would make alpha huge).
    """
    out_bound = float(np.max(factor * np.asarray(W.sum(axis=1)).ravel()))
    in_bound = float(np.max(factor * np.asarray(Wt.sum(axis=1)).ravel()))
    bound = out_bound  # Original SIGMA convention; safe for both equal-radius operators.
    if not math.isfinite(bound) or bound <= 0:
        raise ValueError("Area-adjusted Katz requires a positive finite row-sum bound")
    base = {"outgoing_row_bound": out_bound, "incoming_row_bound": in_bound,
            "spectral_error": None}
    if acyclic:
        return {**base, "scale": bound, "rho": 0.0, "method": "weighted_row_sum_dag"}
    n = len(factor)
    # Spectral radius of F W and F W.T is mathematically identical (F>0).
    # Normalize numerically before ARPACK, as in SIGMA's standard Katz solver.
    try:
        if n <= 3:
            eigenvalues = np.linalg.eigvals((factor[:, None] * W.toarray()) / out_bound)
        else:
            op = LinearOperator(
                (n, n), dtype=np.float64,
                matvec=lambda v: factor * (W @ v) / out_bound,
                rmatvec=lambda v: Wt @ (factor * v) / out_bound,
            )
            eigenvalues = eigs(op, k=1, which="LM", return_eigenvectors=False,
                               v0=np.ones(n, dtype=float) / math.sqrt(n),
                               tol=1e-10, maxiter=max(5000, 20 * n))
        normalized_rho = float(np.max(np.abs(eigenvalues)))
        if not math.isfinite(normalized_rho):
            raise RuntimeError("nonfinite spectral radius")
        if normalized_rho <= 1e-15:
            return {**base, "scale": bound, "rho": 0.0, "method": "weighted_row_sum_zero_radius"}
        rho = float(normalized_rho * out_bound)
        if not math.isfinite(rho) or rho <= 0:
            raise RuntimeError("invalid positive spectral radius")
        return {**base, "scale": rho, "rho": rho, "method": "spectral_radius"}
    except (ArpackNoConvergence, RuntimeError, ValueError, TypeError) as exc:
        return {**base, "scale": bound, "rho": None, "method": "weighted_row_sum_bound",
                "spectral_error": f"{type(exc).__name__}: {exc}"}


def _tile_katz(W: csr_matrix, Wt: csr_matrix, factor: np.ndarray, alpha: float, beta: float,
               *, max_iter: int = 10_000) -> tuple[np.ndarray, np.ndarray, dict]:
    """Raw incoming and outgoing Katz on F W.T and F W (NetworkX iteration and tolerance)."""
    n = len(factor)
    incoming = np.full(n, float(beta), dtype=float)
    outgoing = np.full(n, float(beta), dtype=float)
    tolerance = n * 1e-10  # Standard SIGMA/NetworkX L1 tolerance.
    for iteration in range(1, max_iter + 1):
        next_out = float(beta) + alpha * factor * (W @ outgoing)
        next_in = float(beta) + alpha * factor * (Wt @ incoming)
        if not np.isfinite(next_out).all() or not np.isfinite(next_in).all():
            raise RuntimeError("Area-adjusted Katz iteration produced nonfinite values")
        error_out = float(np.sum(np.abs(next_out - outgoing)))
        error_in = float(np.sum(np.abs(next_in - incoming)))
        outgoing, incoming = next_out, next_in
        if error_out < tolerance and error_in < tolerance:
            return incoming, outgoing, {"katz_iterations": iteration,
                                        "last_l1_error_in": error_in,
                                        "last_l1_error_out": error_out}
    raise RuntimeError(f"Area-adjusted Katz did not converge after {max_iter} iterations")


def _top_k(values: np.ndarray, k: int) -> np.ndarray:
    """Indices of the ``k`` largest values; ties keep node order (stable)."""
    return np.argsort(-np.asarray(values, dtype=float), kind="stable")[:min(int(k), len(values))]


def _concentration(values: np.ndarray) -> dict:
    """Shares of the summed normalized scores held by the top 10 and top 100 nodes."""
    values = np.asarray(values, dtype=float)
    total = float(values.sum())
    if not math.isfinite(total) or total <= 0:
        return {"top10_share": None, "top100_share": None}
    order = np.sort(values)[::-1]
    return {"top10_share": float(order[:10].sum() / total),
            "top100_share": float(order[:100].sum() / total)}


def _area_decile_labels(area: np.ndarray) -> np.ndarray:
    """Assign each tiled row to one equal-count, stable area-rank group.

    Group identities are reused for both area summaries and top-k diagnostics.
    A tied-area boundary is split deterministically by row order; it is not an
    economically meaningful distinction between tied observations.
    """
    area = np.asarray(area, dtype=float)
    if not np.isfinite(area).all() or (area <= 0).any():
        raise ValueError("Area-decile assignments require positive finite tile areas")
    n = len(area)
    labels = np.zeros(n, dtype=np.int64)
    if n:
        order = np.argsort(area, kind="stable")
        for number, members in enumerate(np.array_split(order, min(10, n)), start=1):
            labels[members] = number
    return labels


def _top_k_area_decile_counts(top: np.ndarray, decile_labels: np.ndarray) -> tuple[int, int]:
    """Count top-k members in the same lowest/highest groups as area_deciles."""
    labels = np.asarray(decile_labels, dtype=np.int64)
    positive = labels[labels > 0]
    if not len(positive):
        return 0, 0
    top_labels = labels[top]
    smallest = int(np.count_nonzero(top_labels == 1))
    # A single tiled observation has only one group, not two distinct deciles.
    largest = int(np.count_nonzero(top_labels == positive.max())) if positive.max() > 1 else 0
    return smallest, largest


def _area_deciles(area: np.ndarray, degree: np.ndarray, factor: np.ndarray) -> list[dict]:
    """Equal-count tile-area groups (smallest first) of degree and f_i k_i.

    Each mean is divided by the mean over every tiled node, so a value above 1
    means that area group has more than the average. Groups split the
    area-sorted nodes into ten equal-count parts (fewer when n < 10); ties keep
    node order. This is the spec's diagnostic for small-tile overcompensation.
    """
    n = len(area)
    if n == 0:
        return []
    adjusted = factor * degree
    mean_degree = float(degree.mean())
    mean_adjusted = float(adjusted.mean())
    labels = _area_decile_labels(area)
    rows = []
    for number in range(1, min(10, n) + 1):
        members = np.flatnonzero(labels == number)
        if len(members) == 0:
            continue
        rows.append({
            "decile": number,
            "nodes": int(len(members)),
            "area_km2_min": float(area[members].min()),
            "area_km2_max": float(area[members].max()),
            "mean_degree": float(degree[members].mean()),
            "mean_adjusted_degree": float(adjusted[members].mean()),
            "relative_mean_degree": (float(degree[members].mean()) / mean_degree
                                     if mean_degree > 0 else None),
            "relative_mean_adjusted_degree": (float(adjusted[members].mean()) / mean_adjusted
                                              if mean_adjusted > 0 else None),
        })
    return rows


def _rho(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or np.ptp(left) == 0 or np.ptp(right) == 0:
        return None  # a constant input has no rank correlation
    value = float(spearmanr(left, right).statistic)
    return value if math.isfinite(value) else None


def _area_katz_rho(log_area: np.ndarray, scores: np.ndarray) -> float | None:
    """Area–Katz rho is undefined when area is constant at PPML precision.

    Use the same log-area threshold as the not_identified_constant_area
    scoring branch. Tiny projected-polygon rounding noise has no rank meaning.
    Ordinary score-vs-score correlations continue to use _rho unchanged.
    """
    if len(log_area) < 2 or np.ptp(log_area) < 1e-12:
        return None
    return _rho(log_area, scores)


def _unadjusted_comparison(
    W: csr_matrix, Wt: csr_matrix, *, acyclic: bool, alpha_factor: float, beta: float,
    adjusted: np.ndarray, has_tile: np.ndarray, area: np.ndarray,
    area_decile_labels: np.ndarray, identical: bool,
) -> dict:
    """Ordinary balanced Katz on the same X, for the spec's before/after diagnostics.

    The comparison is diagnostic only: it never changes the published scores,
    and a failure is recorded instead of stopping the stage. When the area
    factor is an exact no-op, the unadjusted result equals the adjusted one.
    """
    n = W.shape[0]
    if identical:
        unadjusted, kin, kout = adjusted, None, None
        info = {"status": "identical_exact_no_op"}
    else:
        try:
            ones = np.ones(n, dtype=float)
            scale = _spectral_scale(W, Wt, ones, acyclic=acyclic)
            alpha = float(alpha_factor) / scale["scale"]
            kin, kout, _ = _tile_katz(W, Wt, ones, alpha, float(beta))
            combined = np.sqrt(np.maximum(kin, 0.0) * np.maximum(kout, 0.0))
            unadjusted = combined / float(np.linalg.norm(combined))
            if not np.isfinite(unadjusted).all():
                raise RuntimeError("non-finite unadjusted balanced Katz")
            info = {"status": "ok", "alpha": alpha, "spectral_scale_method": scale["method"]}
        except (RuntimeError, ValueError, ArpackNoConvergence, FloatingPointError,
                ZeroDivisionError, OverflowError, np.linalg.LinAlgError) as exc:
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    k = min(100, n)
    top_before, top_after = _top_k(unadjusted, k), _top_k(adjusted, k)
    tiled_area = area[has_tile]
    small_count, large_count = _top_k_area_decile_counts(top_before, area_decile_labels)
    result = {
        **info,
        "top_k": k,
        "area_katz_spearman_rho": _area_katz_rho(np.log(tiled_area), unadjusted[has_tile]),
        "rank_correlation_with_adjusted": _rho(unadjusted, adjusted),
        "top_k_retained_after_adjustment": int(len(np.intersect1d(top_before, top_after))),
        "top100_smallest_area_decile": small_count,
        "top100_largest_area_decile": large_count,
        "concentration": _concentration(unadjusted),
    }
    if kin is not None:
        result["area_katz_in_spearman_rho"] = _area_katz_rho(np.log(tiled_area), kin[has_tile])
        result["area_katz_out_spearman_rho"] = _area_katz_rho(np.log(tiled_area), kout[has_tile])
    return result


def _node_index(frame: pd.DataFrame, typ: str, cluster: str) -> pd.MultiIndex:
    if typ not in frame or cluster not in frame:
        raise ValueError(f"Expected node keys {typ!r} and {cluster!r}")
    code = frame[typ].astype(str)
    number = pd.to_numeric(frame[cluster], errors="raise")
    if code.eq("").any() or number.isna().any() or not np.all(number == np.floor(number)):
        raise ValueError("X node keys contain missing or fractional cluster identifiers")
    return pd.MultiIndex.from_arrays((code.to_numpy(), number.astype(np.int64).to_numpy()))


def _edge_arrays(nodes_index: pd.MultiIndex,
                 edges: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Source rows, target rows, and weights parsed exactly as ``load_x`` does."""
    source = nodes_index.get_indexer(_node_index(edges, "source_type", "source_cluster"))
    target = nodes_index.get_indexer(_node_index(edges, "target_type", "target_cluster"))
    if (source < 0).any() or (target < 0).any():
        raise ValueError("X edges reference an unknown X node")
    # Python float() round-trips SIGMA's %.17g serialization exactly; pandas'
    # fast numeric parser (pd.to_numeric) can select an adjacent IEEE-754 value.
    weight = np.fromiter((float(value) for value in edges["edge_weight"]),
                         dtype=float, count=len(edges))
    if not np.isfinite(weight).all() or (weight <= 0).any():
        raise ValueError("X must contain strictly positive finite ORIGINAL gravity weights")
    return source, target, weight


def calculate_tile_area_katz(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    partitions: gpd.GeoDataFrame,
    *,
    alpha_factor: float = 0.85,
    beta: float = 1.0,
    progress=None,
) -> tuple[CentralityResult, dict, pd.DataFrame]:
    """Use cached original X weights and current final polygons; never route.

    Returns the normal CentralityResult, strict-JSON aggregate metadata, and a
    per-cluster audit table containing area, area factor, and strengths.
    """
    if not 0 < float(alpha_factor) < 1 or not math.isfinite(float(beta)) or beta <= 0:
        raise ValueError("Area-adjusted Katz requires alpha_factor in (0,1) and beta > 0")
    if missing := set(EDGE_COLUMNS) - set(edges.columns):
        raise ValueError(f"Cached X edges are missing {sorted(missing)}")
    if missing := {"node_id", "type", "cluster"} - set(nodes.columns):
        raise ValueError(f"Cached X nodes are missing {sorted(missing)}")
    if not {"type", "cluster", "geometry"} <= set(partitions.columns) or partitions.crs is None:
        raise ValueError("Final Voronoi partitions or their CRS are unavailable")
    n = len(nodes)
    if n == 0:
        # Same behaviour as balanced_katz_centrality on an empty X.
        return (
            CentralityResult(
                {}, "balanced", False, "X is empty.", method="katz",
                alpha=float(alpha_factor), beta=float(beta), spectral_radius=0.0,
                spectral_scale_kind="unit_no_edges", katz_in_raw={}, katz_out_raw={},
                combination="geometric_mean", normalization="l2_after_combination",
            ),
            {"method": METHOD_ID, "regression": {"status": "empty_x"}, "gamma": None},
            pd.DataFrame(columns=list(AUDIT_COLUMNS)),
        )

    # 1. Topology and weights; all integrity checks happen before any estimation.
    nindex = _node_index(nodes, "type", "cluster")
    if nindex.has_duplicates:
        raise ValueError("X centers contain duplicate tile identities")
    identifiers = nodes["node_id"].astype(str).tolist()
    if len(set(identifiers)) != n:
        raise ValueError("Duplicate X node identifiers")
    source, target, weight = _edge_arrays(nindex, edges)
    W = csr_matrix((weight, (source, target)), shape=(n, n), dtype=float)
    if W.nnz != len(weight):
        raise ValueError("Duplicate directed X edges prevent an unambiguous adjusted matrix")
    Wt = W.transpose().tocsr()
    out_degree = np.bincount(source, minlength=n)
    in_degree = np.bincount(target, minlength=n)
    for column, computed in (("out_degree", out_degree), ("in_degree", in_degree)):
        if column in nodes.columns:
            stored = pd.to_numeric(nodes[column], errors="raise").to_numpy()
            if not np.array_equal(stored, computed):
                raise ValueError(
                    f"x_nodes.csv {column} disagrees with x_edges.csv for "
                    f"{int(np.sum(stored != computed))} nodes; the X artifact is inconsistent"
                )
    degree = out_degree + in_degree

    # 2. Final Voronoi tile areas in equal-area km².
    pindex = _node_index(partitions, "type", "cluster")
    if pindex.has_duplicates:
        raise ValueError("Final Voronoi partitions contain duplicate tile identities")
    positions = pindex.get_indexer(nindex)
    has_tile = positions >= 0
    without_tile = np.flatnonzero(~has_tile)
    if len(without_tile):
        nonisolated = without_tile[degree[without_tile] != 0]
        if len(nonisolated):
            examples = [identifiers[i] for i in nonisolated[:10]]
            raise ValueError(
                f"{len(nonisolated)} X centers have edges but no final Voronoi tile "
                f"(for example {examples}); inconsistent spatial/X artifacts"
            )
        if progress is not None:
            progress(
                f"area-adjusted Katz: {len(without_tile)} isolated X centers have no tile; "
                "excluding them from PPML, retaining them with neutral factor 1"
            )
    extra_tiles = len(pindex) - int(has_tile.sum())
    if extra_tiles:
        raise ValueError(f"{extra_tiles} final Voronoi tiles have no X center")
    area = np.full(n, np.nan, dtype=float)
    if has_tile.any():
        polygons = partitions.iloc[positions[has_tile]].geometry.to_crs(AREA_CRS)
        area[has_tile] = np.asarray(polygons.area, dtype=float) / 1e6
    if not np.isfinite(area[has_tile]).all() or (area[has_tile] <= 0).any():
        raise ValueError("Final Voronoi tiles must have positive finite equal-area km²")
    log_area = np.full(n, np.nan, dtype=float)
    log_area[has_tile] = np.log(area[has_tile])
    regression_area = log_area[has_tile]
    regression_degree = degree[has_tile]

    # 3. Per-geography exponent and tile factors.
    if W.nnz == 0:
        # No edges: every Katz value equals beta for every factor, so the area
        # factor has no effect (existing solver: scale 1, "unit_no_edges").
        gamma = None
        factor = np.ones(n, dtype=float)
        regression = {
            "outcome": "total_directed_degree", "observations": n,
            "status": "not_identified_no_edges", "adjustment": "exact_no_op",
        }
        if progress is not None:
            progress("area-adjusted Katz: X has no edges; the area factor is an exact no-op")
    elif np.ptp(regression_area) < 1e-12:
        # F = c*I for every gamma, and c cancels in alpha*F*W, so every exponent
        # gives the same scores as unadjusted Katz. Reported, not substituted.
        gamma = None
        factor = np.ones(n, dtype=float)
        regression = {
            "outcome": "total_directed_degree", "observations": n,
            "status": "not_identified_constant_area", "adjustment": "exact_no_op",
        }
        if progress is not None:
            progress("area-adjusted Katz: all tile areas are equal; the area factor is an "
                     "exact no-op and scores equal unadjusted balanced Katz")
    else:
        regression = _ppml(regression_degree, regression_area,
                           "total_directed_degree", required=True)
        gamma = float(regression["area_elasticity"])
        log_factor = -gamma * regression_area
        if not np.isfinite(log_factor).all() or np.max(np.abs(log_factor)) > 650:
            raise RuntimeError("Area factors are numerically extreme; "
                               "refusing the unbounded correction")
        factor = np.ones(n, dtype=float)
        factor[has_tile] = np.exp(log_factor)
        if not np.isfinite(factor).all() or (factor <= 0).any():
            raise RuntimeError("Area factors must be positive and finite")
        if progress is not None:
            progress(f"area-adjusted Katz: PPML total directed degree gamma={gamma:+.9f}, "
                     f"95% CI [{regression['ci95_low']:+.6f}, {regression['ci95_high']:+.6f}]")

    # 4. Shared alpha and the two perspective-specific Katz vectors.
    acyclic = _is_acyclic(W)
    if W.nnz == 0:
        scale = {"scale": 1.0, "rho": 0.0, "method": "unit_no_edges", "spectral_error": None,
                 "outgoing_row_bound": 0.0, "incoming_row_bound": 0.0}
    else:
        scale = _spectral_scale(W, Wt, factor, acyclic=acyclic)
    alpha = float(alpha_factor) / scale["scale"]
    if not math.isfinite(alpha) or alpha <= 0:
        raise RuntimeError("Invalid shared area-adjusted Katz alpha")
    if progress is not None and scale["method"] not in {"spectral_radius", "unit_no_edges"}:
        reason = scale["spectral_error"] or scale["method"]
        progress(f"area-adjusted Katz: using the conservative shared row-sum scale ({reason})")
    incoming, outgoing, katz_info = _tile_katz(W, Wt, factor, alpha, float(beta))
    combined = np.sqrt(np.maximum(incoming, 0.0) * np.maximum(outgoing, 0.0))
    l2 = float(np.linalg.norm(combined))
    if not math.isfinite(l2) or l2 <= 0:
        raise RuntimeError("Balanced Katz normalization is undefined")
    centrality = combined / l2

    # 5. Outputs and diagnostics.
    values = dict(zip(identifiers, centrality.tolist(), strict=True))
    katz_in = dict(zip(identifiers, incoming.tolist(), strict=True))
    katz_out = dict(zip(identifiers, outgoing.tolist(), strict=True))
    out_strength = np.bincount(source, weights=weight, minlength=n)
    in_strength = np.bincount(target, weights=weight, minlength=n)
    adjusted_out_strength = out_strength * factor
    adjusted_in_strength = in_strength * factor
    strength_fits = {
        "out_before": _ppml(out_strength[has_tile], regression_area,
                            "out_strength_before"),
        "in_before": _ppml(in_strength[has_tile], regression_area,
                           "in_strength_before"),
        "out_after": _ppml(adjusted_out_strength[has_tile], regression_area,
                           "out_strength_adjusted"),
        "in_after": _ppml(adjusted_in_strength[has_tile], regression_area,
                          "in_strength_adjusted"),
    }
    # Use the existing constant-safe rank-correlation helper for all three
    # area/Katz diagnostics. A constant input has no defined Spearman rho.
    area_correlation = _area_katz_rho(regression_area, centrality[has_tile])
    incoming_area_correlation = _area_katz_rho(regression_area, incoming[has_tile])
    outgoing_area_correlation = _area_katz_rho(regression_area, outgoing[has_tile])
    # One partition, shared by the decile table and both top-k comparisons.
    decile_labels = np.full(n, -1, dtype=np.int64)
    decile_labels[has_tile] = _area_decile_labels(area[has_tile])
    top100 = _top_k(centrality, 100)
    smallest_top100, largest_top100 = _top_k_area_decile_counts(top100, decile_labels)

    # 6. Spec §9.7 comparison diagnostics. They never change any score.
    if progress is not None and gamma is not None:
        progress("area-adjusted Katz: unadjusted balanced-Katz comparison (diagnostic only)")
    comparison = _unadjusted_comparison(
        W, Wt, acyclic=acyclic, alpha_factor=float(alpha_factor), beta=float(beta),
        adjusted=centrality, has_tile=has_tile, area=area,
        area_decile_labels=decile_labels, identical=gamma is None,
    )
    if gamma is not None:
        orientation_fits = {
            "in_degree": _ppml(in_degree[has_tile], regression_area, "in_degree"),
            "out_degree": _ppml(out_degree[has_tile], regression_area, "out_degree"),
        }
    else:
        orientation_fits = {"status": "not_estimated_exact_no_op"}
    degree_gap = np.abs(in_degree - out_degree)
    tiled_factor = factor[has_tile]
    diagnostics = _json_safe({
        "method": METHOD_ID,
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "input_edge_weights": "original_x_gravity_shares_coefficient_inverse_mean_hub_distance",
        "area_units": "km2",
        "area_projection": AREA_CRS,
        "degree_definition": "in_degree_plus_out_degree_including_zero_degree_nodes",
        "regression": regression,
        "regression_node_count": int(has_tile.sum()),
        "excluded_isolated_without_tile": int(len(without_tile)),
        "excluded_isolated_node_examples": [identifiers[i] for i in without_tile[:10]],
        "gamma": gamma,
        "weight_operators": {"out": "F W", "in": "F W.T", "f_i": "area_i_km2**(-gamma)"},
        "katz_alpha_factor": float(alpha_factor),
        "shared_alpha": alpha,
        "acyclic_x": acyclic,
        "spectral_radius": scale["rho"],
        "spectral_scale_method": scale["method"],
        "spectral_scale": scale["scale"],
        "spectral_error": scale["spectral_error"],
        "outgoing_row_bound": scale["outgoing_row_bound"],
        "incoming_row_bound": scale["incoming_row_bound"],
        **katz_info,
        "area_km2_min_max": ([float(area[has_tile].min()),
                              float(area[has_tile].max())] if has_tile.any() else None),
        "factor_min_max": [float(factor.min()), float(factor.max())],
        "factor_quantiles_p01_p50_p99": [float(v) for v in np.quantile(factor, [0.01, 0.5, 0.99])],
        "area_katz_spearman_rho": area_correlation,
        "area_katz_in_spearman_rho": incoming_area_correlation,
        "area_katz_out_spearman_rho": outgoing_area_correlation,
        "top100_smallest_area_decile": smallest_top100,
        "top100_largest_area_decile": largest_top100,
        "strength_area_regressions": strength_fits,
        "degree_orientation_regressions": orientation_fits,
        "degree_balance": {
            "max_abs_in_minus_out": int(degree_gap.max()) if n else 0,
            "nodes_with_unequal_in_out": int(np.count_nonzero(degree_gap)),
            "zero_degree_nodes": int(np.count_nonzero(degree == 0)),
            "zero_degree_nodes_in_regression": int(np.count_nonzero(regression_degree == 0)),
        },
        "factor_max_min_ratio": (float(tiled_factor.max() / tiled_factor.min())
                                 if len(tiled_factor) else None),
        "area_decile_definition": "stable_equal_count_area_rank; ties split by X-node order; untiled nodes excluded",
        "area_deciles": _area_deciles(area[has_tile], degree[has_tile].astype(float),
                                      tiled_factor),
        "concentration": _concentration(centrality),
        "unadjusted_comparison": comparison,
    })
    audit = pd.DataFrame({
        "node_id": identifiers,
        "voronoi_area_km2": area,
        "area_factor": factor,
        "out_strength_original": out_strength,
        "in_strength_original": in_strength,
        "out_strength_adjusted": adjusted_out_strength,
        "in_strength_adjusted": adjusted_in_strength,
    })
    if regression["status"] == "not_identified_no_edges":
        exponent_note = "X has no edges, so the area factor is an exact no-op"
    elif gamma is None:
        exponent_note = "all available tile areas equal; area factor is an exact no-op"
    else:
        exponent_note = f"per-geography total-degree PPML gamma={gamma:.9g}"
    result = CentralityResult(
        values=values, direction="balanced", degenerate_dag=bool(acyclic),
        note="Balanced Katz with two tile-perspective adjusted weight operators F W and F W.T; "
             f"{exponent_note}; shared alpha={alpha:.17g}.",
        method="katz", alpha=alpha, beta=float(beta), spectral_radius=scale["rho"],
        spectral_scale_kind=scale["method"], katz_in_raw=katz_in, katz_out_raw=katz_out,
        combination="geometric_mean", normalization="l2_after_combination",
    )
    return result, diagnostics, audit

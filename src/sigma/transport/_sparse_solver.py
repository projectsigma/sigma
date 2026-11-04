"""Shared SciPy shortest-path and network-median backend.

Shortest paths use Dijkstra's algorithm (Dijkstra, 1959) through SciPy
(Virtanen et al., 2020, https://doi.org/10.1038/s41592-019-0686-2).  The
vertex 1-median objective follows classical network-location theory: Hakimi
(1964), https://doi.org/10.1287/opre.12.3.450.  For vertex demand a median
optimum can be chosen at a network vertex; SIGMA evaluates that minisum
objective in bounded SciPy distance blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from .network import AugmentedNetwork

_MAX_MATRIX_VALUES = 8_000_000
# First search radius (map units) of a bounded search when node coordinates are not
# known; it doubles until every target is reached.  Any value gives the same distances;
# it only sets how much work is done.
_FIRST_SEARCH_LIMIT = 2_000.0


def _distances_until_reached(
    graph: csr_matrix, source: int, targets: np.ndarray, first_limit: float = _FIRST_SEARCH_LIMIT
) -> np.ndarray:
    """Exact shortest distances from ``source`` to ``targets`` with a growing search radius.

    SciPy's ``limit`` stops the search at that distance; every node within the limit
    gets exactly the distance a full search gives.  The limit doubles until all
    targets are reached, so callers should pass targets in the source's component
    (others end the loop only when the search becomes unbounded).
    """
    limit = float(first_limit)
    while True:
        values = np.asarray(
            dijkstra(graph, directed=True, indices=int(source), limit=limit), dtype=float
        )[targets]
        if np.isfinite(values).all() or not np.isfinite(limit):
            return values
        limit = limit * 2.0 if limit < 1e12 else np.inf


def _median_search_limit(
    graph: csr_matrix, demand: np.ndarray, weights: np.ndarray,
    first_limit: float = _FIRST_SEARCH_LIMIT,
) -> float:
    """Search radius, from every demand vertex, that still contains every possible median.

    Take one demand vertex ``p`` as a reference and let ``score(v)`` be the weighted sum
    of distances from the demand vertices to ``v``.  For every demand vertex ``i`` the
    triangle inequality gives ``d(i, v) >= d(p, v) - d(p, i)``.  Summing over the demand
    gives ``score(v) >= W * d(p, v) - score(p)``, where ``W`` is the total weight.  A
    vertex with ``d(p, v) > 2 * score(p) / W`` therefore scores worse than ``p`` itself and
    cannot be the median.  Every remaining vertex ``v`` satisfies
    ``d(i, v) <= d(p, i) + 2 * score(p) / W``, which is the returned radius.

    The small relative and absolute margins keep vertices that tie with the optimum within
    the tolerance used by ``one_median`` and absorb floating-point rounding.
    """
    to_demand = _distances_until_reached(graph, int(demand[0]), demand, first_limit)
    reference_score = float(weights.astype(float) @ to_demand)
    candidate_radius = 2.0 * reference_score / float(weights.sum())
    return (float(to_demand.max()) + candidate_radius) * (1.0 + 1e-9) + 1e-9


@dataclass(frozen=True)
class SparseRoadSolver:
    adjacency: csr_matrix
    component: np.ndarray
    # Node coordinates (map units), used only to choose the first search radius.
    xy: np.ndarray | None = field(default=None, repr=False, compare=False)
    # Per road component: its sorted node ids and its adjacency submatrix.  Every
    # cluster on the same component reuses one copy instead of slicing it again.
    # Components share no nodes, so all cached submatrices together are at most one
    # copy of the road adjacency matrix.
    _component_graphs: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def _first_limit(self, source: int, targets: np.ndarray) -> float:
        """1.5 x the largest straight-line distance from ``source`` to ``targets``.

        A straight line is never longer than the road route, so this is a cheap,
        data-driven start; :func:`_distances_until_reached` doubles it as needed.
        """
        if self.xy is None:
            return _FIRST_SEARCH_LIMIT
        span = np.hypot(*(self.xy[targets] - self.xy[int(source)]).T)
        return max(1.0, 1.5 * float(span.max(initial=0.0)))

    def _component_graph(self, comp: int) -> tuple[np.ndarray, csr_matrix]:
        cached = self._component_graphs.get(comp)
        if cached is None:
            candidates = np.flatnonzero(self.component == comp).astype(np.int64)
            cached = (candidates, self.adjacency[candidates][:, candidates])
            self._component_graphs[comp] = cached
        return cached

    @classmethod
    def from_augmented(cls, network: AugmentedNetwork) -> "SparseRoadSolver":
        n = len(network.nodes)
        node_ids = network.nodes["network_node"].to_numpy(np.int64, copy=False)
        if not np.array_equal(node_ids, np.arange(n, dtype=np.int64)):
            raise ValueError("optimized road solver requires contiguous network_node IDs")
        return cls(network.sparse_adjacency, network.sparse_component, network._node_xy)

    def distance(self, source: int, target: int) -> float:
        source, target = int(source), int(target)
        if not (0 <= source < self.adjacency.shape[0] and 0 <= target < self.adjacency.shape[0]):
            raise ValueError(f"unknown network node in distance query: {source}, {target}")
        if self.component[source] != self.component[target]:
            return float("inf")
        value = dijkstra(
            self.adjacency,
            directed=True,
            indices=source,
            min_only=False,
            limit=np.inf,
        )[target]
        return float(value)

    def distances_from(self, source: int, cutoff: float | None = None) -> dict[int, float]:
        source = int(source)
        if not 0 <= source < self.adjacency.shape[0]:
            raise ValueError(f"unknown network source node: {source}")
        limit = np.inf if cutoff is None else float(cutoff)
        values = np.asarray(
            dijkstra(self.adjacency, directed=True, indices=source, limit=limit), dtype=float
        )
        idx = np.flatnonzero(np.isfinite(values))
        return {int(i): float(values[i]) for i in idx}

    def one_median(self, demand_nodes: np.ndarray) -> tuple[int, float]:
        """Exact weighted vertex 1-median for repeated unit-weight demand nodes."""
        demand = np.asarray(demand_nodes, dtype=np.int64)
        if demand.ndim != 1 or len(demand) == 0:
            raise ValueError("network 1-median requires a non-empty one-dimensional demand array")
        if demand.min() < 0 or demand.max() >= self.adjacency.shape[0]:
            raise ValueError("network 1-median received an unknown demand node")
        comp = self.component[demand[0]]
        if np.any(self.component[demand] != comp):
            raise ValueError("one cluster spans disconnected road components")

        unique, weights = np.unique(demand, return_counts=True)
        candidates, sub = self._component_graph(int(comp))
        # ``candidates`` is sorted, so a search gives each node's local index.
        local_demand = np.searchsorted(candidates, unique)
        scores = np.zeros(len(candidates), dtype=float)

        # Vertices farther than ``limit`` from a demand vertex get an infinite score.  The
        # limit is chosen so that this never removes a vertex that could be the median.
        limit = _median_search_limit(
            sub, local_demand, weights, self._first_limit(int(unique[0]), unique)
        )
        batch = max(1, _MAX_MATRIX_VALUES // max(1, len(candidates)))
        for start in range(0, len(unique), batch):
            stop = min(len(unique), start + batch)
            dist = np.asarray(
                dijkstra(sub, directed=True, indices=local_demand[start:stop], limit=limit),
                dtype=float,
            )
            scores += weights[start:stop].astype(float) @ dist

        best = float(scores.min())
        tolerance = max(1e-9, abs(best) * 1e-12)
        tied = candidates[scores <= best + tolerance]
        best_node = int(tied.min())
        return best_node, float(scores[np.searchsorted(candidates, best_node)])

    def point_distances_from_centers(
        self, point_nodes: np.ndarray, center_for_point: np.ndarray
    ) -> np.ndarray:
        """Road distance from each point node to its assigned center, batched by center."""
        points = np.asarray(point_nodes, dtype=np.int64)
        centers = np.asarray(center_for_point, dtype=np.int64)
        if points.shape != centers.shape:
            raise ValueError("point and center node arrays must align")
        out = np.full(len(points), np.inf, dtype=float)
        for center in np.unique(centers):
            members = np.flatnonzero(centers == center)
            # Points on another road component stay infinite, as in a full search.
            members = members[self.component[points[members]] == self.component[center]]
            if members.size:
                out[members] = _distances_until_reached(
                    self.adjacency, int(center), points[members],
                    self._first_limit(int(center), points[members]),
                )
        return out

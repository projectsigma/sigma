"""Optional downstream, numerical-parity-checked SIGMA X route materialization.

This is ONLY invoked by the explicit precomputed export mode.  The numerical
analysis.x artifact is identical for browser and precomputed publication.
"""
from __future__ import annotations

from collections import defaultdict
import math

import geopandas as gpd
import numpy as np


def materialize_x_paths(analysis, graph, road, *, progress=None) -> gpd.GeoDataFrame:
    """Reconstruct all X geographic routes from already-committed numeric X edges.

    Uses a single SciPy predecessor search per distinct center road vertex.  Reuses
    the PR #27 batched ``route_geoseries`` method; does not recompute X weights.
    """
    by_source = defaultdict(list)
    for u, v, values in graph.edges(data=True):
        start = int(graph.nodes[u]["center_network_node"])
        dest = int(graph.nodes[v]["center_network_node"])
        by_source[start].append((u, v, dest, float(values["road_distance"])))
    for i, (source, edges) in enumerate(sorted(by_source.items()), 1):
        targets = np.asarray([e[2] for e in edges], dtype=np.int64)
        distances, routes = road.shortest_route_nodes_to_targets(source, targets)
        for (u, v, _, expected), actual, route in zip(edges, distances, routes, strict=True):
            if route is None or not math.isfinite(float(actual)):
                raise ValueError(f"Stored X edge {u}->{v} is disconnected in routing graph")
            tol = max(1e-6, abs(expected) * 1e-8)
            if abs(float(actual) - expected) > tol:
                raise ValueError(f"Published X distance differs from reconstructed route {u}->{v}")
            graph.edges[u, v]["route_nodes"] = route
        if progress is not None and (i % 200 == 0 or i == len(by_source)):
            progress(f"precomputed routes: {i:,}/{len(by_source):,} center-source searches")
    _, result = analysis._edge_outputs(graph, road)
    if len(result) != graph.number_of_edges():
        raise RuntimeError("Precomputed route count differs from numerical X edges")
    return result

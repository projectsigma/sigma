"""Privacy-minimized, exact-distance binary routing graph for SIGMA Explorer.

Never publish establishment-only split vertices. Each original straight road segment
(parent_edge_id) is a chain in SIGMA's augmented graph. Contract its interior
non-center vertices, retaining the original road endpoints and the publicly
visible cluster-center routing vertices. No X numerical calculation is changed.

Binary SIGRTE01: magic[8], uint32 n,m, n*(float64 lon,lat),
m*(uint32 u,v,float64 length). Node IDs in this file are NEW compact IDs.
"""
from __future__ import annotations

from pathlib import Path
import struct

import numpy as np
import shapely
from pyproj import Transformer

MAGIC = b"SIGRTE01"
HEADER = struct.Struct("<8sII")
EDGE_DTYPE = np.dtype([("u", "<u4"), ("v", "<u4"), ("weight", "<f8")])


def _contract_center_graph(road, center_nodes):
    """Return original-node-ID subset and distances without noncenter snap vertices.

    Every parent road edge must be an isolated, two-ended path of collinear
    segments. If any assumption fails, refuse export instead of leaking data or
    creating geometric shortcuts. Publicly visible center coordinates are kept.
    """
    nodes = road.nodes.sort_values("network_node", kind="stable")
    edges = road.edges.sort_values(["parent_edge_id", "aug_edge_id"], kind="stable")
    node_ids = nodes["network_node"].to_numpy(np.int64, copy=False)
    n, m = len(nodes), len(edges)
    if not n or not m or n > 0xFFFFFFFF or m > 0xFFFFFFFF:
        raise ValueError("Unsupported browser routing dimensions")
    if not np.array_equal(node_ids, np.arange(n, dtype=np.int64)):
        raise ValueError("Augmented routing vertices must have contiguous IDs")
    if not {"parent_edge_id", "aug_edge_id", "u", "v", "length"} <= set(edges):
        raise ValueError("Augmented routing edges must retain parent-edge lineage")
    geometries = edges.geometry.to_numpy()
    if not np.all(shapely.get_num_coordinates(geometries) == 2):
        raise ValueError("Cannot contract non-straight augmented road segments")
    xy = shapely.get_coordinates(nodes.geometry.to_numpy())
    if xy.shape != (n, 2) or not np.isfinite(xy).all():
        raise ValueError("Invalid augmented road vertex coordinates")
    u = edges["u"].to_numpy(np.int64, copy=False)
    v = edges["v"].to_numpy(np.int64, copy=False)
    w = edges["length"].to_numpy(float, copy=False)
    parent = edges["parent_edge_id"].to_numpy(np.int64, copy=False)
    if (np.any(u < 0) or np.any(v < 0) or np.any(u >= n) or np.any(v >= n)
            or np.any(u == v) or not np.isfinite(w).all() or np.any(w <= 0)
            or np.any(parent < 0)):
        raise ValueError("Invalid augmented road adjacency or weights")
    endpoint_xy = shapely.get_coordinates(geometries).reshape(m, 2, 2)
    if not (np.allclose(endpoint_xy[:, 0], xy[u], rtol=0, atol=1e-7)
            and np.allclose(endpoint_xy[:, 1], xy[v], rtol=0, atol=1e-7)):
        raise ValueError("Augmented road edge geometry disagrees with node positions")

    centers = {int(c) for c in center_nodes}
    if not centers or any(c < 0 or c >= n for c in centers):
        raise ValueError("Missing or invalid X cluster-center road nodes")
    kept = set(centers)
    contracted = []
    boundaries = np.r_[0, np.flatnonzero(parent[1:] != parent[:-1]) + 1, m]
    for left, right in zip(boundaries[:-1], boundaries[1:], strict=True):
        # The common case: an original road segment with no inserted snaps.
        if int(right - left) == 1:
            a, b = int(u[left]), int(v[left])
            kept.update((a, b))
            contracted.append((a, b, float(w[left])))
            continue
        # Each split parent road segment must be an undirected simple chain.
        neighbors = {}
        for i in range(int(left), int(right)):
            a, b, weight = int(u[i]), int(v[i]), float(w[i])
            neighbors.setdefault(a, []).append((b, weight))
            neighbors.setdefault(b, []).append((a, weight))
        ends = sorted(k for k, adj in neighbors.items() if len(adj) == 1)
        if len(ends) != 2 or any(len(adj) > 2 for adj in neighbors.values()):
            raise ValueError("Parent road segment is not a simple split chain")
        start, finish = ends
        span = xy[finish] - xy[start]
        length = float(np.hypot(*span))
        if length <= 0:
            raise ValueError("Parent road segment endpoints coincide")
        chain_nodes = np.asarray(list(neighbors), dtype=np.int64)
        offset = xy[chain_nodes] - xy[start]
        deviation = np.abs(offset[:, 0] * span[1] - offset[:, 1] * span[0]) / length
        projection = (offset @ span) / (length * length)
        if (np.any(deviation > 1e-6) or np.any(projection < -1e-9)
                or np.any(projection > 1 + 1e-9)):
            raise ValueError("Parent road segment is bent or leaves its original endpoints")
        kept.update(ends)
        previous, here = -1, start
        last_retained = start
        distance_since_retained = 0.0
        visited_edges = 0
        while here != finish:
            nexts = [(there, distance) for there, distance in neighbors[here]
                     if there != previous]
            if len(nexts) != 1:
                raise ValueError("Parent road chain contains a branch or cycle")
            there, distance = nexts[0]
            visited_edges += 1
            if visited_edges > int(right - left):
                raise ValueError("Parent road chain exceeds its edge count")
            distance_since_retained += distance
            if there in centers or there == finish:
                contracted.append((last_retained, there, distance_since_retained))
                last_retained, distance_since_retained = there, 0.0
                kept.add(there)
            previous, here = here, there
        if visited_edges != int(right - left) or distance_since_retained != 0.0:
            raise ValueError("Parent road chain did not traverse every split segment")

    retained = np.asarray(sorted(kept), dtype=np.int64)
    index = np.full(n, -1, dtype=np.int64)
    index[retained] = np.arange(len(retained), dtype=np.int64)
    packed = np.empty(len(contracted), dtype=EDGE_DTYPE)
    if contracted:
        a, b, weights = np.asarray(contracted, dtype=float).T
        packed["u"] = index[a.astype(np.int64)].astype(np.uint32)
        packed["v"] = index[b.astype(np.int64)].astype(np.uint32)
        packed["weight"] = weights
    if np.any(packed["u"] == packed["v"]) or not np.isfinite(packed["weight"]).all():
        raise ValueError("Contracted routing graph contains invalid edges")
    return xy[retained], packed, {center: int(index[center]) for center in centers}


def write_browser_routing_graph(road, destination: Path | str, *, center_nodes) -> dict[int, int]:
    """Write a privacy-minimized graph and return old->new center road-node IDs."""
    xy, packed, center_ids = _contract_center_graph(road, center_nodes)
    n, m = len(xy), len(packed)
    if n > 0xFFFFFFFF or m > 0xFFFFFFFF:
        raise ValueError("Contracted routing graph exceeds 32-bit IDs")
    transformer = Transformer.from_crs(road.crs, "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(xy[:, 0], xy[:, 1])
    if not np.isfinite(lon).all() or not np.isfinite(lat).all():
        raise ValueError("Nonfinite routing coordinates")
    coords = np.empty((n, 2), dtype="<f8")
    coords[:, 0], coords[:, 1] = lon, lat
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        handle.write(HEADER.pack(MAGIC, n, m))
        handle.write(coords.tobytes(order="C"))
        handle.write(packed.tobytes(order="C"))
    return center_ids

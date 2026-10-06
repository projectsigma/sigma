from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import shapely
from scipy.sparse import coo_matrix

from sigma.spatial.clustering import SparseClusteringContext
from sigma.transport._sparse_network import NetworkGraph, Snaps

_ARRAYS = (
    "vertex_xy",
    "arc_u",
    "arc_v",
    "arc_length",
    "component",
    "snap_u",
    "snap_v",
    "snap_offset",
    "snap_arc_length",
    "snap_distance",
    "snapped_xy",
    "edge_id",
)


def _save_array(root: Path, name: str, value: np.ndarray) -> None:
    with (root / f"{name}.npy").open("wb") as handle:
        np.save(handle, np.asarray(value), allow_pickle=False)


def _load_array(root: Path, name: str) -> np.ndarray:
    with (root / f"{name}.npy").open("rb") as handle:
        return np.load(handle, allow_pickle=False)


def save_sparse_context(
    context: SparseClusteringContext,
    root: Path,
    *,
    crs: object,
    vertex_digits: int | None,
    point_ids: list[str],
) -> Path:
    """Persist the exact Step-1 graph/snaps as deterministic NumPy arrays."""
    root.mkdir(parents=True, exist_ok=True)
    values = {
        "vertex_xy": context.graph.vertex_xy,
        "arc_u": context.graph.arc_u,
        "arc_v": context.graph.arc_v,
        "arc_length": context.graph.arc_length,
        "component": context.graph.component,
        "snap_u": context.snaps.u,
        "snap_v": context.snaps.v,
        "snap_offset": context.snaps.offset,
        "snap_arc_length": context.snaps.arc_length,
        "snap_distance": context.snaps.snap_distance,
        "snapped_xy": context.snaps.snapped_xy,
        "edge_id": context.edge_id,
    }
    for name in _ARRAYS:
        _save_array(root, name, values[name])
    metadata = {
        "schema_version": 1,
        "crs": str(crs),
        "vertex_digits": vertex_digits,
        "point_ids": [str(value) for value in point_ids],
        "n_vertices": int(context.graph.n_vertices),
        "n_arcs": int(context.graph.n_arcs),
        "n_components": int(context.graph.n_components),
        "n_points": int(len(context.snaps)),
    }
    (root / "context.json").write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return root


def load_sparse_context(root: Path) -> tuple[SparseClusteringContext, dict[str, object]]:
    """Restore the exact sparse graph and snap arrays persisted by C9."""
    root = Path(root)
    metadata = json.loads((root / "context.json").read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 1:
        raise ValueError("unsupported sparse snap-context schema")
    arrays = {name: _load_array(root, name) for name in _ARRAYS}

    vertex_xy = np.asarray(arrays["vertex_xy"], dtype=float)
    arc_u = np.asarray(arrays["arc_u"], dtype=np.int64)
    arc_v = np.asarray(arrays["arc_v"], dtype=np.int64)
    arc_length = np.asarray(arrays["arc_length"], dtype=float)
    n = len(vertex_xy)
    adjacency = coo_matrix(
        (
            np.concatenate([arc_length, arc_length]),
            (np.concatenate([arc_u, arc_v]), np.concatenate([arc_v, arc_u])),
        ),
        shape=(n, n),
    ).tocsr()
    adjacency.sort_indices()
    segments = shapely.linestrings(np.stack([vertex_xy[arc_u], vertex_xy[arc_v]], axis=1))
    graph = NetworkGraph(
        vertex_xy=vertex_xy,
        arc_u=arc_u,
        arc_v=arc_v,
        arc_length=arc_length,
        adjacency=adjacency,
        component=np.asarray(arrays["component"], dtype=np.int64),
        arc_tree=shapely.STRtree(segments),
        vertex_tree=shapely.STRtree(shapely.points(vertex_xy)),
    )
    snaps = Snaps(
        u=np.asarray(arrays["snap_u"], dtype=np.int64),
        v=np.asarray(arrays["snap_v"], dtype=np.int64),
        offset=np.asarray(arrays["snap_offset"], dtype=float),
        arc_length=np.asarray(arrays["snap_arc_length"], dtype=float),
        snap_distance=np.asarray(arrays["snap_distance"], dtype=float),
        snapped_xy=np.asarray(arrays["snapped_xy"], dtype=float),
    )
    context = SparseClusteringContext(
        graph=graph,
        snaps=snaps,
        edge_id=np.asarray(arrays["edge_id"], dtype=np.int64),
    )
    if int(metadata.get("n_points", -1)) != len(snaps):
        raise ValueError("sparse snap-context point count is inconsistent")
    return context, metadata


def validate_point_alignment(metadata: dict[str, object], point_ids) -> None:
    expected = [str(value) for value in metadata.get("point_ids", [])]
    actual = [str(value) for value in point_ids]
    if expected != actual:
        raise RuntimeError("saved Step-1 snap context is not aligned to the current point rows")

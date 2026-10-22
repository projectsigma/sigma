"""Create a static, browser-ready SIGMA Explorer from published SIGMA products.

Required inputs (all written by ``sigma run`` / ``sigma export``):
  sigma_points.parquet; sigma_spatial_outputs.gpkg (clusters, paths);
  sigma_X_nodes.csv; sigma_X_edges.csv.
Optional inputs: sigma_run_metadata.json, sigma_boundary.parquet, sigma_roads.parquet,
  sigma_manifest.json, ATTRIBUTION.txt, DATABASE_LICENSE.txt.

No analysis is re-run; this is a read-only post-publication transformation.  The
bundle is written to a staging directory and swapped in only after it is complete.
"""
from __future__ import annotations

import hashlib
import importlib.resources as resources
import json
import math
import shutil
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import mapping

REQUIRED_FILES = (
    "sigma_points.parquet",
    "sigma_spatial_outputs.gpkg",
    "sigma_X_nodes.csv",
    "sigma_X_edges.csv",
)
OPTIONAL_FILES = (
    "sigma_run_metadata.json",
    "sigma_boundary.parquet",
    "sigma_roads.parquet",
    "sigma_manifest.json",
)
BUNDLE_FORMAT = "sigma-explorer"
BUNDLE_VERSION = 3
OVERVIEW_ZOOM = 15  # aggregation grid for over-budget views: cells of about 1 km
MARKER = ".sigma-explorer"
TILE_ZOOM = 13
COORDINATE_DIGITS = 6  # about 0.1 m; published SIGMA geometry is unchanged
ROAD_VERTEX_BUDGET = 1_500_000  # automatic road inclusion limit (about 35 MB of GeoJSON)
POINT_BUDGET = 150_000  # the browser loads establishments only when the view holds fewer
STATIC_FILES = (
    "index.html",
    "tutorial.html",
    "tutorial-live.css",
    "tutorial-live.js",
    "app.js",
    "establishment-finder.js",
    "network-model.js",
    "style.css",
    "vendor/maplibre-gl.js",
    "vendor/maplibre-gl.css",
    "vendor/cytoscape.min.js",
    "vendor/LICENSE-maplibre-gl.txt",
    "vendor/LICENSE-cytoscape.txt",
    "vendor/README.txt",
)
FALLBACK_COLOR = "#657F78"


# --------------------------------------------------------------------------- locations


def resolve_output_directory(workspace: Path | str) -> Path:
    """Resolve SIGMA's saved output directory, including a custom --output-dir."""
    root = Path(workspace).expanduser().resolve()
    path = root / "workspace.json"
    if not path.is_file():
        raise FileNotFoundError(f"SIGMA workspace metadata not found: {path}. Run SIGMA first.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("output_dir")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing output_dir in workspace metadata: {path}")
    out = Path(value).expanduser()
    return (out if out.is_absolute() else root / out).resolve()


# --------------------------------------------------------------------------- freshness


def _static_file(name: str):  # noqa: ANN202 - importlib Traversable
    node = resources.files("sigma.web").joinpath("static")
    for part in name.split("/"):
        node = node.joinpath(part)
    return node


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_expectations(source: Path) -> dict[str, tuple[str, Any]]:
    """SHA-256 and size of each file listed in SIGMA's ``sigma_manifest.json``."""
    expected: dict[str, tuple[str, Any]] = {}
    manifest_path = source / "sigma_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("files", [])
        if not isinstance(entries, list):
            raise ValueError("sigma_manifest.json has invalid 'files' entries")
        for entry in entries:
            if not isinstance(entry, dict):
                # Older synthetic/test manifests may not list individual assets.
                continue
            name, sha = entry.get("name"), entry.get("sha256")
            if isinstance(name, str) and isinstance(sha, str):
                expected[name] = (sha.lower(), entry.get("size"))
    return expected


def _input_path(source: Path, name: str, expected: dict[str, tuple[str, Any]]) -> Path | None:
    """Path of an optional published input that belongs to the current SIGMA run.

    SIGMA's publish step overwrites files but never deletes old ones. When the manifest
    lists the run's files, an optional file it does not list (for example a boundary
    left from an earlier area-mode run) is ignored instead of being shown as current.
    """
    path = source / name
    if not path.is_file():
        return None
    if expected and name not in expected and name not in REQUIRED_FILES and name != "sigma_manifest.json":
        return None
    return path


def _source_digest(source: Path) -> bytes:
    """Verify published output integrity when SIGMA supplies a SHA256 manifest.

    Always hash actual input bytes; a copied/edited CSV must not be silently
    masked by an unchanged manifest. Metadata, boundary, and roads are included.
    """
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing published SIGMA outputs: " + ", ".join(missing))
    expected = _manifest_expectations(source)
    digest = hashlib.sha256()
    names = sorted(set(REQUIRED_FILES + OPTIONAL_FILES + ("ATTRIBUTION.txt", "DATABASE_LICENSE.txt")))
    for name in names:
        path = source / name
        if name in expected and not path.is_file():
            raise ValueError(f"Published manifest lists missing source file: {name}")
        if _input_path(source, name, expected) is None:
            digest.update((name + ":absent;").encode())
            continue
        actual = _sha256(path)
        if name in expected:
            sha, size = expected[name]
            if actual != sha or (size is not None and path.stat().st_size != int(size)):
                raise ValueError(f"SIGMA export integrity mismatch for {name}; re-export the run")
        digest.update(f"{name}:{actual};".encode())
    return digest.digest()


def source_fingerprint(
    source_dir: Path | str, *, include_roads: bool | None = None,
    profile: str = "local",
) -> str:
    """Hash actual published assets plus Explorer code, options, and profile."""
    if profile not in {"local", "public"}:
        raise ValueError("Explorer profile must be 'local' or 'public'")
    source = Path(source_dir).expanduser().resolve()
    digest = hashlib.sha256()
    digest.update(f"{BUNDLE_FORMAT}:{BUNDLE_VERSION}:roads={include_roads}:profile={profile}".encode())
    digest.update(resources.files("sigma.web").joinpath("builder.py").read_bytes())
    for name in STATIC_FILES:
        digest.update(_static_file(name).read_bytes())
    digest.update(_source_digest(source))
    return digest.hexdigest()


def read_marker(bundle_dir: Path | str) -> dict[str, Any] | None:
    """Read an Explorer ownership marker; reject malformed/unrecognized markers."""
    path = Path(bundle_dir) / MARKER
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text == "sigma-explorer-v1":
            return {"format": BUNDLE_FORMAT, "version": 1}
        value = json.loads(text)
    except (UnicodeError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("format") != BUNDLE_FORMAT:
        return None
    if type(value.get("version")) is not int or value["version"] not in {1, 2, 3}:
        return None
    return value


def bundle_profile(bundle_dir: Path | str) -> str | None:
    """Profile ("local" or "public") of an existing Explorer bundle, if any."""
    marker = read_marker(bundle_dir)
    if marker is None:
        return None
    return "public" if marker.get("profile") == "public" else "local"


def bundle_is_current(
    source_dir: Path | str, bundle_dir: Path | str, *, include_roads: bool | None = None,
    profile: str = "local",
) -> bool:
    """True when the bundle was built by this Explorer version from the same SIGMA run."""
    marker = read_marker(bundle_dir)
    if marker is None or not (Path(bundle_dir) / "index.html").is_file():
        return False
    return (
        marker.get("version") == BUNDLE_VERSION
        and marker.get("source_fingerprint")
        == source_fingerprint(source_dir, include_roads=include_roads, profile=profile)
    )


# --------------------------------------------------------------------------- value helpers


def _json_dump(path: Path, value: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return len(text)


def _clean(value: Any) -> Any:
    """Convert pandas/numpy scalars and missing data to safe JSON primitives."""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bool | int | str):
        return value
    if not isinstance(value, dict | list | tuple) and pd.isna(value):
        return None
    return str(value)


def _text(value: Any, default: str = "") -> str:
    v = _clean(value)
    return default if v is None else str(v).strip()


def _int(value: Any) -> int | None:
    v = _clean(value)
    if v is None or str(v).strip() == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if math.isfinite(f) and f.is_integer() else None


def _float(value: Any) -> float | None:
    v = _clean(value)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _key(sector: Any, cluster: Any) -> tuple[str, int | None]:
    return (_text(sector), _int(cluster))


def _slug(node_id: str) -> str:
    return hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:24]


def _sector_order(code: str) -> tuple[int, int | str]:
    return (0, int(code)) if code.isdigit() else (1, code)


def _to_wgs84(frame: gpd.GeoDataFrame, name: str) -> gpd.GeoDataFrame:
    if frame.crs is None:
        raise ValueError(f"{name} has no CRS")
    return frame if str(frame.crs).upper() == "EPSG:4326" else frame.to_crs("EPSG:4326")


def _rounded(geometries: Any) -> np.ndarray:
    """Round coordinates for transfer size; topology checks are not needed for display."""
    values = np.asarray(geometries, dtype=object)
    return shapely.transform(values, lambda xy: np.round(xy, COORDINATE_DIGITS))


def _tile_indices(lon: np.ndarray, lat: np.ndarray, zoom: int = TILE_ZOOM) -> tuple[np.ndarray, np.ndarray]:
    n = 1 << zoom
    lat = np.clip(lat, -85.051128, 85.051128)
    x = np.floor((lon + 180.0) / 360.0 * n).astype(np.int64)
    y = np.floor((1.0 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2.0 * n).astype(np.int64)
    return np.clip(x, 0, n - 1), np.clip(y, 0, n - 1)


def _tile(lon: float, lat: float, zoom: int = TILE_ZOOM) -> tuple[int, int]:
    x, y = _tile_indices(np.array([lon]), np.array([lat]), zoom)
    return int(x[0]), int(y[0])


def _column(frame: pd.DataFrame, *names: str) -> pd.Series:
    """First present column among ``names`` as text; empty text when none exists."""
    for name in names:
        if name in frame.columns:
            return frame[name].map(lambda v: _text(v))
    return pd.Series([""] * len(frame), index=frame.index, dtype=object)


# --------------------------------------------------------------------------- styling


def _sector_styles(
    codes: list[str], economy_id: str, label_hints: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Colors and labels identical to the QGIS project for SIGMA's built-in economies.

    ``Economy.builtin`` plus ``build_sector_styles`` is exactly what the QGIS exporter
    uses.  For a custom economy the catalog is not part of the published outputs, so
    labels come from the published ``type_display`` column and colors from SIGMA's
    deterministic fallback palette (ordered by the sectors present).
    """
    from sigma.export.qgis import _fallback_color

    colors: dict[str, str] = {}
    labels: dict[str, str] = dict(label_hints)
    styles = None
    key = economy_id.lower()
    for name in ("io80", "io16"):
        if key == f"psa-2018-{name}":
            try:
                from sigma import Economy
                from sigma.export.qgis import build_sector_styles

                styles = build_sector_styles(Economy.builtin(name).sectors)
            except Exception:  # noqa: BLE001 - styling must never block the Explorer
                styles = None
    for index, code in enumerate(codes):
        style = styles.get(code) if styles else None
        if style is not None:
            colors[code] = style.color_hex.upper()
            labels.setdefault(code, style.display)
        else:
            colors[code] = _fallback_color(index).upper()
            labels.setdefault(code, code)
    return colors, labels


def _distance_unit(run: dict[str, Any]) -> str:
    """Name the unit of SIGMA's road distances from the CRS that measured them."""
    crs_text = run.get("road_distance_crs")
    if not crs_text:
        return _text(run.get("road_distance_unit"), "CRS units")
    try:
        from pyproj import CRS

        unit = (CRS.from_user_input(crs_text).axis_info[0].unit_name or "").lower()
    except Exception:  # noqa: BLE001
        unit = ""
    if unit in {"metre", "meter"}:
        return "m"
    return _text(run.get("road_distance_unit"), "CRS units")


# --------------------------------------------------------------------------- bundle


def _build_unstaged_bundle(
    source_dir: Path | str,
    destination: Path | str,
    *,
    include_roads: bool | None = None,
    profile: str = "local",
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Write a complete Explorer bundle into an empty ``destination``.

    ``include_roads``: True always includes SIGMA's published roads, False never does,
    None includes them when they have at most ``ROAD_VERTEX_BUDGET`` vertices.
    """
    source = Path(source_dir).expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    if profile not in {"local", "public"}:
        raise ValueError("Explorer profile must be local or public")
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Incomplete SIGMA published outputs at {source}: {', '.join(missing)}. "
            "Run 'sigma export' or 'sigma run' first."
        )
    dest.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    expected = _manifest_expectations(source)
    for name in OPTIONAL_FILES + ("ATTRIBUTION.txt", "DATABASE_LICENSE.txt"):
        if (source / name).is_file() and _input_path(source, name, expected) is None:
            warnings.append(f"Ignored {name}: sigma_manifest.json does not list it, so it is left from an earlier run.")

    run_path = _input_path(source, "sigma_run_metadata.json", expected)
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path is not None else {}
    economy_id = _text(run.get("economy_id"))

    # ---- X nodes (authoritative cluster identities)
    node_table = pd.read_csv(
        source / "sigma_X_nodes.csv", dtype={"type": str, "node_id": str}, keep_default_na=False
    )
    edge_table = pd.read_csv(
        source / "sigma_X_edges.csv",
        dtype={"source_type": str, "target_type": str},
        keep_default_na=False,
    )
    for required in ("node_id", "type", "lat", "lon"):
        if required not in node_table:
            raise ValueError(f"sigma_X_nodes.csv is missing {required}")
    for required in ("source_type", "source_cluster", "target_type", "target_cluster"):
        if required not in edge_table:
            raise ValueError(f"sigma_X_edges.csv is missing {required}")
    cluster_field = "cluster" if "cluster" in node_table else "cluster_no"
    if cluster_field not in node_table:
        raise ValueError("sigma_X_nodes.csv must have cluster or cluster_no")

    lookup: dict[tuple[str, int | None], str] = {}
    nodes: list[dict[str, Any]] = []
    for row in node_table.to_dict("records"):
        key = _key(row["type"], row[cluster_field])
        nid = _text(row["node_id"])
        if key in lookup or not nid:
            raise ValueError(f"Duplicate or missing X node identifier for {key}")
        lookup[key] = nid
        nodes.append({
            "id": nid, "type": key[0], "cluster": key[1],
            "lon": _float(row["lon"]), "lat": _float(row["lat"]),
            "in_degree": _int(row.get("in_degree")), "out_degree": _int(row.get("out_degree")),
            "centrality": _float(row.get("centrality")),
            "members": 0, "route_file": None,
        })
    node_by_id = {n["id"]: n for n in nodes}

    # ---- X edges
    edges: list[dict[str, Any]] = []
    edge_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for row in edge_table.to_dict("records"):
        u = lookup.get(_key(row["source_type"], row["source_cluster"]))
        v = lookup.get(_key(row["target_type"], row["target_cluster"]))
        if u is None or v is None:
            raise ValueError("An X edge references an unknown node (type, cluster)")
        if (u, v) in edge_by_pair:
            raise ValueError("Duplicate directed X edge in published CSV")
        edge = {
            "from": u, "to": v,
            "coefficient": _float(row.get("technical_coefficient")),
            "distance": _float(row.get("road_distance")),
            "weight": _float(row.get("edge_weight")),
        }
        edges.append(edge)
        edge_by_pair[(u, v)] = edge

    # ---- exact road paths from SIGMA's GeoPackage, never inferred chords
    gpkg = source / "sigma_spatial_outputs.gpkg"
    paths = _to_wgs84(pyogrio.read_dataframe(gpkg, layer="paths"), "GeoPackage layer 'paths'")
    if len(paths) != len(edges):
        raise ValueError("X edge CSV and GeoPackage 'paths' counts differ; possibly stale exports")
    route_geometry: dict[tuple[str, str], Any] = {}
    path_geoms = _rounded(paths.geometry.values) if len(paths) else np.empty(0, dtype=object)
    for (u, v), geom in zip(
        zip(paths["from_id"].map(_text), paths["to_id"].map(_text), strict=True),
        path_geoms,
        strict=True,
    ):
        if (u, v) not in edge_by_pair:
            raise ValueError("GeoPackage paths and edge CSV refer to different X edges")
        if geom is None or shapely.is_empty(geom):
            raise ValueError("An X edge is missing exact route geometry")
        route_geometry[(u, v)] = geom
    if len(route_geometry) != len(edges):
        raise ValueError("Not all X edges have corresponding path features")

    # Preserve the exact independent path for EACH directed X edge. Shortest
    # distance symmetry does not imply unique equal-cost route geometry.
    related: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    for (u, v), edge in edge_by_pair.items():
        related[u].append((u, v, edge))
        if v != u:
            related[v].append((u, v, edge))
    route_bytes = 0
    for nid, connections in related.items():
        features: list[dict[str, Any]] = []
        position: dict[tuple[str, str], int] = {}
        # Outgoing edges first, so a reciprocal incoming edge can refer back to its partner.
        for u, v, edge in sorted(connections, key=lambda item: (item[0] != nid, item[0], item[1])):
            other = v if nid == u else u
            geom = route_geometry[(u, v)]
            properties = {
                "other": other, "other_type": node_by_id[other]["type"],
                "from": u, "to": v,
                "direction": "outgoing" if nid == u else "incoming",
                "coefficient": edge["coefficient"], "distance": edge["distance"],
                "weight": edge["weight"],
            }
            partner = position.get((v, u))
            # The reverse edge's path is stored only when it differs from the exact
            # reverse of the forward path; the browser rebuilds it with reverse_of.
            shared = (
                partner is not None
                and geom.geom_type == "LineString"
                and route_geometry[(v, u)].geom_type == "LineString"
                and shapely.equals_exact(geom, shapely.reverse(route_geometry[(v, u)]), tolerance=0)
            )
            if shared:
                properties["reverse_of"] = partner
            features.append({
                "type": "Feature",
                "properties": properties,
                "geometry": None if shared else mapping(geom),
            })
            position[(u, v)] = len(features) - 1
        node = node_by_id[nid]
        node["route_file"] = f"data/routes/{_slug(nid)}.geojson"
        route_bytes += _json_dump(dest / node["route_file"], {
            "type": "FeatureCollection", "features": features,
        })

    # ---- cluster partitions
    partitions = _to_wgs84(pyogrio.read_dataframe(gpkg, layer="clusters"), "GeoPackage layer 'clusters'")
    label_hints: dict[str, str] = {}
    partition_features = []
    partition_geoms = _rounded(partitions.geometry.values) if len(partitions) else []
    for row, geom in zip(partitions.drop(columns=partitions.geometry.name).to_dict("records"), partition_geoms, strict=True):
        key = _key(row.get("type"), row.get("cluster", row.get("cluster_no")))
        display = _text(row.get("type_display") or row.get("type_label"))
        if display:
            label_hints.setdefault(key[0], display)
        if key not in lookup:
            raise ValueError(f"Cluster partition {key} has no corresponding X node")
        if geom is None or shapely.is_empty(geom):
            raise ValueError(f"Cluster partition {key} has invalid geometry")
        partition_features.append({
            "type": "Feature",
            "properties": {"node_id": lookup[key], "type": key[0], "cluster": key[1]},
            "geometry": mapping(geom),
        })
    _json_dump(dest / "data/clusters.geojson", {"type": "FeatureCollection", "features": partition_features})

    # ---- establishments, tiled so a browser never needs the whole layer at once
    points = _to_wgs84(gpd.read_parquet(source / "sigma_points.parquet"), "sigma_points.parquet")
    geom = points.geometry
    is_point = (~geom.isna()) & (~geom.is_empty) & (geom.geom_type == "Point")
    points = points.loc[is_point.to_numpy()].copy()
    lon = points.geometry.x.to_numpy(dtype=float)
    lat = points.geometry.y.to_numpy(dtype=float)
    valid = np.isfinite(lon) & np.isfinite(lat) & (np.abs(lon) <= 180) & (np.abs(lat) <= 90)
    points, lon, lat = points.loc[valid].copy(), lon[valid], lat[valid]
    types = _column(points, "type")
    clusters = [_int(v) for v in points["cluster"]] if "cluster" in points else [None] * len(points)
    node_ids = [lookup.get((t, c), "") for t, c in zip(types, clusters, strict=True)]
    unassigned = sum(1 for n in node_ids if not n)
    for display, t in zip(_column(points, "type_display", "type_label"), types, strict=True):
        if display:
            label_hints.setdefault(t, display)
    names = _column(points, "canonical_name", "name").replace("", "Unnamed establishment")
    raw_ids = _column(points, "canonical_id", "point_id")
    seen: set[str] = set()
    ids = []
    for index, value in enumerate(raw_ids):
        candidate = value if value else f"row-{index}"
        if candidate in seen:
            candidate = f"explorer-row-{index}"
            suffix = 0
            while candidate in seen:
                suffix += 1
                candidate = f"explorer-row-{index}-{suffix}"
        seen.add(candidate)
        ids.append(candidate)
    scores = (
        pd.to_numeric(points["sigma_score"], errors="coerce").to_numpy(dtype=float)
        if "sigma_score" in points
        else np.full(len(points), np.nan)
    )
    psic = _column(points, "psic_code", "psic")
    sources_text = _column(points, "sources", "source")
    tiles: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    # Local-only name index: sector -> [name, tile key, position in tile, cluster].
    finder_rows: dict[str, list[list[Any]]] = defaultdict(list)
    overview: dict[tuple[int, int], int] = defaultdict(int)
    tx, ty = _tile_indices(lon, lat)
    ox, oy = _tile_indices(lon, lat, zoom=OVERVIEW_ZOOM)
    for i in range(len(points)):
        if node_ids[i]:
            node_by_id[node_ids[i]]["members"] += 1
        if profile == "public":
            continue  # never write individual IDs, names, locations or PSICs
        score = float(scores[i]) if math.isfinite(scores[i]) else None
        tile_key = (int(tx[i]), int(ty[i]))
        finder_rows[types.iat[i]].append([
            names.iat[i], f"{tile_key[0]}/{tile_key[1]}", len(tiles[tile_key]), clusters[i],
        ])
        tiles[tile_key].append({
            "type": "Feature",
            "properties": {
                "id": ids[i], "name": names.iat[i], "type": types.iat[i],
                "cluster": clusters[i], "node_id": node_ids[i], "score": score,
                "psic": psic.iat[i], "sources": sources_text.iat[i],
            },
            "geometry": {"type": "Point", "coordinates": [
                round(float(lon[i]), COORDINATE_DIGITS), round(float(lat[i]), COORDINATE_DIGITS)
            ]},
        })
        overview[(int(ox[i]), int(oy[i]))] += 1
    for (x, y), features in tiles.items():
        _json_dump(dest / f"data/tiles/{TILE_ZOOM}/{x}/{y}.geojson", {
            "type": "FeatureCollection", "features": features,
        })
    _json_dump(dest / "data/tiles.json", {
        "zoom": TILE_ZOOM, "tiles": {f"{x}/{y}": len(tiles[(x, y)]) for x, y in sorted(tiles)},
    })
    # The index contains names and tile-feature locators, so NEVER generate it
    # in public-profile bundles. Shard by sector and count to bound file size.
    if profile == "local":
        index: dict[str, list[str]] = {}
        for sector_n, code in enumerate(sorted(finder_rows, key=_sector_order)):
            filenames: list[str] = []
            rows = finder_rows[code]
            for start in range(0, len(rows), 4000):
                filename = f"data/search/s{sector_n:04d}-{start // 4000:04d}.json"
                _json_dump(dest / filename, rows[start:start + 4000])
                filenames.append(filename)
            index[code] = filenames
        _json_dump(dest / "data/search/index.json", {"version": 1, "sectors": index})
    # Counts per grid cell, placed at the cell center (not at any establishment).
    cells = 1 << OVERVIEW_ZOOM
    _json_dump(dest / "data/overview.geojson", {
        "type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"count": count}, "geometry": {"type": "Point", "coordinates": [
                round((x + 0.5) / cells * 360.0 - 180.0, COORDINATE_DIGITS),
                round(math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / cells)))), COORDINATE_DIGITS),
            ]}}
            for (x, y), count in sorted(overview.items())
        ],
    })

    # ---- roads (context only; routes above already follow SIGMA's own paths)
    road_count = 0
    roads_file = _input_path(source, "sigma_roads.parquet", expected)
    if include_roads is not False and roads_file is not None:
        roads = _to_wgs84(gpd.read_parquet(roads_file), "sigma_roads.parquet")
        roads = roads[~roads.geometry.isna() & ~roads.geometry.is_empty]
        simplified = roads.geometry.simplify(0.00001, preserve_topology=True)
        vertices = int(shapely.get_num_coordinates(simplified.values).sum()) if len(roads) else 0
        if include_roads is None and vertices > ROAD_VERTEX_BUDGET:
            warnings.append(
                f"Roads omitted: {vertices:,} vertices exceed the automatic limit of "
                f"{ROAD_VERTEX_BUDGET:,}. Use --roads to include them anyway."
            )
        else:
            road_geoms = _rounded(simplified.values)
            _json_dump(dest / "data/roads.geojson", {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": mapping(g)} for g in road_geoms
            ]})
            road_count = len(roads)

    # ---- boundary and cluster centers
    boundary_file = _input_path(source, "sigma_boundary.parquet", expected)
    boundary = (
        _to_wgs84(gpd.read_parquet(boundary_file), "sigma_boundary.parquet")
        if boundary_file is not None
        else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    )
    if len(boundary):
        _json_dump(dest / "data/boundary.geojson", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": mapping(g)}
            for g in _rounded(boundary.geometry.values) if g is not None and not shapely.is_empty(g)
        ]})
    _json_dump(dest / "data/nodes.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"id": n["id"], "type": n["type"], "cluster": n["cluster"]},
         "geometry": {"type": "Point", "coordinates": [round(n["lon"], COORDINATE_DIGITS), round(n["lat"], COORDINATE_DIGITS)]}}
        for n in nodes if n["lon"] is not None and n["lat"] is not None
    ]})

    # ---- metadata
    codes = sorted({n["type"] for n in nodes} | set(types), key=_sector_order)
    colors, labels = _sector_styles(codes, economy_id, label_hints)
    point_counts = types.value_counts().to_dict()
    cluster_counts = pd.Series([n["type"] for n in nodes], dtype=object).value_counts().to_dict()
    sectors = [{
        "code": code, "label": labels.get(code, code), "color": colors[code],
        "points": int(point_counts.get(code, 0)), "clusters": int(cluster_counts.get(code, 0)),
    } for code in codes]
    finite = scores[np.isfinite(scores)]
    bounds = None
    for frame in (boundary, points, partitions):
        if len(frame):
            b = [float(v) for v in frame.total_bounds]
            if all(math.isfinite(v) for v in b):
                bounds = b
                break
    if bounds is None:
        bounds = [120.9, 14.4, 121.2, 14.8]
    if bounds[0] == bounds[2]:
        bounds[0], bounds[2] = bounds[0] - 0.005, bounds[2] + 0.005
    if bounds[1] == bounds[3]:
        bounds[1], bounds[3] = bounds[1] - 0.005, bounds[3] + 0.005
    linked_pairs = len({tuple(sorted(pair)) for pair in edge_by_pair})
    metadata = {
        "schema_version": BUNDLE_VERSION,
        "profile": profile,
        "has_points": profile == "local" and bool(len(points)),
        "has_establishment_finder": profile == "local" and bool(len(points)),
        "overview_grid_zoom": OVERVIEW_ZOOM,
        "area": _text(run.get("area_name") or run.get("area_slug") or source.name),
        "economy_id": economy_id,
        "bounds": bounds,
        "counts": {
            "points": len(points), "unassigned_points": unassigned, "clusters": len(nodes),
            "edges": len(edges), "linked_pairs": linked_pairs,
            "partitions": len(partition_features), "roads": road_count,
        },
        "sectors": sectors,
        "tile_zoom": TILE_ZOOM,
        "point_budget": POINT_BUDGET,
        "has_roads": bool(road_count),
        "has_boundary": bool(len(boundary)),
        "score_range": [float(finite.min()), float(finite.max())] if len(finite) else [None, None],
        "distance_unit": _distance_unit(run),
        "created_at": _text(run.get("created_at")),
        "sigma_version": _text(run.get("sigma_version")),
        "warnings": warnings,
        "note": "X edges are modeled cluster-level spatial-economic relationships, not verified firm-to-firm trade.",
    }
    _json_dump(dest / "data/metadata.json", metadata)
    _json_dump(dest / "data/graph.json", {"nodes": nodes, "edges": edges})

    for name in ("ATTRIBUTION.txt", "DATABASE_LICENSE.txt"):
        licence_file = _input_path(source, name, expected)
        if licence_file is not None:
            shutil.copy2(licence_file, dest / name)
    (dest / "DATA_NOTICE.txt").write_text(
        "SIGMA Explorer uses derived SIGMA exports.\n"
        "Network X represents modeled spatial-economic links between clusters, not observed transactions.\n"
        "Establishment-level links are cluster membership only; the dataset does not establish transactions between firms.\n"
        "Before public hosting, inspect ATTRIBUTION.txt, DATABASE_LICENSE.txt and the source data terms.\n",
        encoding="utf-8",
    )
    for name in STATIC_FILES:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_static_file(name).read_bytes())
    (dest / MARKER).write_text(json.dumps({
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "source_fingerprint": fingerprint or source_fingerprint(source, include_roads=include_roads, profile=profile),
        "include_roads": include_roads,
        "profile": profile,
    }, indent=2) + "\n", encoding="utf-8")
    return {"destination": str(dest), "source": str(source), "warnings": warnings,
            "route_bytes": route_bytes, **metadata["counts"]}


def build_web_bundle(
    source_dir: Path | str,
    destination: Path | str,
    *,
    include_roads: bool | None = None,
    force: bool = False,
    profile: str = "local",
) -> dict[str, Any]:
    """Publish a complete Explorer atomically; a failed refresh keeps the last good bundle."""
    source = Path(source_dir).expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Incomplete SIGMA published outputs at {source}: {', '.join(missing)}. "
            "Run 'sigma export' or 'sigma run' first."
        )
    if profile not in {"local", "public"}:
        raise ValueError("Explorer profile must be 'local' or 'public'")
    if dest == source or dest in source.parents:
        raise ValueError("Explorer destination must not contain SIGMA source outputs")
    if source in dest.parents and dest not in {source / "explorer", source / "explorer-public"}:
        raise ValueError("Explorer inside source outputs must use its dedicated explorer/ child")
    if profile == "local" and (dest.name == "explorer-public" or bundle_profile(dest) == "public"):
        raise ValueError(
            f"{dest} is reserved for a public-profile Explorer; refusing to write establishment-level "
            "data there. Use the 'explorer' folder or another --output-dir for the full local bundle."
        )
    if dest.exists() and any(dest.iterdir()):
        if not force:
            raise FileExistsError(f"Explorer directory already exists and is not empty: {dest}. Use --force.")
        if read_marker(dest) is None or not (dest / "index.html").is_file():
            raise ValueError(f"Refusing to overwrite a non-Explorer directory: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.staging-", dir=dest.parent))
    backup = dest.with_name(f".{dest.name}.backup-{uuid.uuid4().hex}")
    moved_old = False
    try:
        initial_fingerprint = source_fingerprint(source, include_roads=include_roads, profile=profile)
        result = _build_unstaged_bundle(source, staging, include_roads=include_roads, profile=profile,
                                        fingerprint=initial_fingerprint)
        if source_fingerprint(source, include_roads=include_roads, profile=profile) != initial_fingerprint:
            raise ValueError("SIGMA outputs changed during the Explorer build; the previous bundle is kept. Run the command again.")
        if dest.exists():
            dest.rename(backup)
            moved_old = True
        try:
            staging.rename(dest)
        except Exception:
            if moved_old:
                backup.rename(dest)
                moved_old = False
            raise
        result["destination"] = str(dest)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if moved_old and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

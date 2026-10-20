"""SIGMA Explorer contract tests.

The first group uses small hand-made published outputs.  The last test runs SIGMA's own
area pipeline on a synthetic city and builds the Explorer from the real export, so a
change in SIGMA's published schema fails here rather than in the browser.
"""
from __future__ import annotations

import json
import re
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import LineString, Point, box

pytest.importorskip("pyarrow")

from sigma.web import build_web_bundle, bundle_is_current, resolve_output_directory
from sigma.web import builder as web_builder
from sigma.web import server as web_server

A, B, C = "type=54::cluster=1", "type=55::cluster=2", "type=63::cluster=3"
A_END, B_END, C_END = (121.060, 14.600), (121.065, 14.605), (121.055, 14.596)


@pytest.fixture
def published(tmp_path: Path) -> Path:
    """Published outputs with one reciprocal pair (A<->B) and one one-way edge (C->A)."""
    p = tmp_path / "output"
    p.mkdir()
    (p / "sigma_X_nodes.csv").write_text(
        "node_id,type,cluster,cluster_no,lat,lon,in_degree,out_degree,centrality\n"
        f"{A},54,1,1,{A_END[1]},{A_END[0]},2,1,0.6\n"
        f"{B},55,2,2,{B_END[1]},{B_END[0]},1,1,0.4\n"
        f"{C},63,3,3,{C_END[1]},{C_END[0]},0,1,0.1\n", encoding="utf-8")
    (p / "sigma_X_edges.csv").write_text(
        "source_type,source_cluster,target_type,target_cluster,technical_coefficient,road_distance,edge_weight\n"
        "54,1,55,2,0.25,1200,300\n"
        "55,2,54,1,0.05,1200,60\n"
        "63,3,54,1,0.01,900,9\n", encoding="utf-8")
    (p / "sigma_run_metadata.json").write_text(json.dumps({
        "economy_id": "psa-2018-io80", "area_name": "Synthetic Pasig",
        "road_distance_unit": "CRS units", "road_distance_crs": "EPSG:32651"}), encoding="utf-8")
    (p / "sigma_manifest.json").write_text('{"files": ["first run"]}', encoding="utf-8")
    gpkg = p / "sigma_spatial_outputs.gpkg"
    clusters = gpd.GeoDataFrame(
        {"type": ["54", "55", "63"], "cluster": [1, 2, 3],
         "type_display": ["54 - Wholesale trade", "55 - Retail trade", "63 - Food and beverage service"]},
        geometry=[box(121.059, 14.599, 121.063, 14.604), box(121.062, 14.604, 121.068, 14.609),
                  box(121.053, 14.594, 121.058, 14.598)], crs="EPSG:4326")
    ab = LineString([A_END, (121.0641234567, 14.6031234567), B_END])
    paths = gpd.GeoDataFrame(
        {"from_id": [A, B, C], "to_id": [B, A, A], "technical_coefficient": [0.25, 0.05, 0.01],
         "road_distance": [1200.0, 1200.0, 900.0], "edge_weight": [300.0, 60.0, 9.0]},
        geometry=[ab, ab.reverse(), LineString([C_END, (121.058, 14.598), A_END])], crs="EPSG:4326")
    pyogrio.write_dataframe(clusters, gpkg, layer="clusters", driver="GPKG")
    pyogrio.write_dataframe(paths, gpkg, layer="paths", driver="GPKG", append=True)
    gpd.GeoDataFrame(
        {"canonical_id": ["p1", "p2", "p3"], "canonical_name": ["Test Shop", "Another shop", "Eatery"],
         "type": ["54", "55", "63"], "cluster": [1, 2, 3], "sigma_score": [0.9, 0.2, 0.5],
         "psic_code": ["4610", "4711", "5610"],
         "customer_account_number": ["NEVER_EXPORTED", "ALSO_SECRET", "SECRET_TOO"]},
        geometry=[Point(121.0601, 14.6001), Point(121.0651, 14.6051), Point(121.0551, 14.5961)],
        crs="EPSG:4326").to_parquet(p / "sigma_points.parquet", index=False)
    gpd.GeoDataFrame({"highway": ["primary"]}, geometry=[LineString([(121.05, 14.59), (121.07, 14.61)])],
                     crs="EPSG:4326").to_parquet(p / "sigma_roads.parquet", index=False)
    gpd.GeoDataFrame({"area_slug": ["synthetic"]}, geometry=[box(121.05, 14.59, 121.07, 14.61)],
                     crs="EPSG:4326").to_parquet(p / "sigma_boundary.parquet", index=False)
    return p


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _expanded(features: list[dict]) -> list[dict]:
    """Python mirror of SigmaGraph.expandRoutes: rebuild exact-reverse paths."""
    out = []
    for feature in features:
        ref = feature["properties"].get("reverse_of")
        if feature["geometry"] is None and ref is not None:
            base = features[ref]["geometry"]
            assert base["type"] == "LineString"
            feature = {**feature, "geometry": {"type": "LineString", "coordinates": base["coordinates"][::-1]}}
        out.append(feature)
    return out


def _routes(dest: Path, node_id: str) -> dict[str, dict]:
    graph = _json(dest / "data/graph.json")
    node = next(n for n in graph["nodes"] if n["id"] == node_id)
    features = _json(dest / node["route_file"])["features"]
    return {f["properties"]["other"]: f for f in features}


def test_bundle_has_directed_pairs_exact_paths_and_tiled_points(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    report = build_web_bundle(published, dest)
    assert (report["points"], report["edges"], report["linked_pairs"]) == (3, 3, 2)

    graph = _json(dest / "data/graph.json")
    assert {(e["from"], e["to"]) for e in graph["edges"]} == {(A, B), (B, A), (C, A)}
    assert next(n for n in graph["nodes"] if n["id"] == A)["members"] == 1

    # Each directed X edge keeps its OWN SIGMA-computed route, even for reciprocal links.
    node_a = next(n for n in graph["nodes"] if n["id"] == A)
    stored = _json(dest / node_a["route_file"])["features"]
    assert len(stored) == 3  # A->B, B->A, C->A (not two unordered pairs)
    # B->A uses exactly the reversed A->B path, so it is stored once and referenced.
    stored_ba = next(f for f in stored if (f["properties"]["from"], f["properties"]["to"]) == (B, A))
    assert stored_ba["geometry"] is None
    assert stored[stored_ba["properties"]["reverse_of"]]["properties"]["from"] == A
    a_features = _expanded(stored)
    ab = next(f for f in a_features if (f["properties"]["from"], f["properties"]["to"]) == (A, B))
    ba = next(f for f in a_features if (f["properties"]["from"], f["properties"]["to"]) == (B, A))
    ca = next(f for f in a_features if (f["properties"]["from"], f["properties"]["to"]) == (C, A))
    assert (ab["properties"]["direction"], ba["properties"]["direction"]) == ("outgoing", "incoming")
    assert ab["properties"]["coefficient"] == .25
    assert ba["properties"]["coefficient"] == .05
    assert ab["geometry"]["coordinates"][0] == list(A_END)
    assert ba["geometry"]["coordinates"][0] == list(B_END)
    assert ca["geometry"]["coordinates"][0] == list(C_END)
    assert len(ab["geometry"]["coordinates"]) == 3  # exact path, not a chord
    assert ab["geometry"]["coordinates"][1] == [121.064123, 14.603123]

    tiles = _json(dest / "data/tiles.json")
    assert sum(tiles["tiles"].values()) == 3
    text = " ".join(f.read_text(encoding="utf-8") for f in (dest / "data/tiles/13").rglob("*.geojson"))
    assert "Test Shop" in text and A in text
    overview = _json(dest / "data/overview.geojson")["features"]
    assert sum(f["properties"]["count"] for f in overview) == 3
    # Overview cells sit at grid-cell centers, never at an establishment's own position.
    places = {(121.0601, 14.6001), (121.0651, 14.6051), (121.0551, 14.5961)}
    assert not {tuple(f["geometry"]["coordinates"]) for f in overview} & places
    assert "NEVER_EXPORTED" not in text

    meta = _json(dest / "data/metadata.json")
    sectors = {s["code"]: s for s in meta["sectors"]}
    assert sectors["54"]["color"] == "#AE2B64"  # same IO80 color as the QGIS project
    assert sectors["54"]["label"] == "54 - Wholesale trade"
    assert meta["distance_unit"] == "m"
    assert meta["has_roads"] and meta["has_boundary"]
    assert meta["score_range"] == [0.2, 0.9]


def test_bundle_is_self_contained(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    build_web_bundle(published, dest)
    html = (dest / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"""(src|href)=["']?(https?:)?//""", html)  # no CDN; works offline
    for name in ("maplibre-gl.js", "maplibre-gl.css", "cytoscape.min.js", "LICENSE-maplibre-gl.txt"):
        assert (dest / "vendor" / name).is_file()


def test_road_inclusion_options(published: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert not _json(Path(build_web_bundle(published, tmp_path / "a", include_roads=False)["destination"])
                     / "data/metadata.json")["has_roads"]
    monkeypatch.setattr(web_builder, "ROAD_VERTEX_BUDGET", 1)
    report = build_web_bundle(published, tmp_path / "b")
    assert report["roads"] == 0 and "Roads omitted" in report["warnings"][0]
    assert build_web_bundle(published, tmp_path / "c", include_roads=True)["roads"] == 1


def test_explorer_is_readonly_and_refuses_unsafe_overwrite(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    before = (published / "sigma_X_edges.csv").read_bytes()
    build_web_bundle(published, dest)
    with pytest.raises(FileExistsError):
        build_web_bundle(published, dest)
    (dest / "data" / "junk.txt").write_text("temporary")
    build_web_bundle(published, dest, force=True)
    assert not (dest / "data" / "junk.txt").exists()
    assert (published / "sigma_X_edges.csv").read_bytes() == before
    hostile = tmp_path / "user-files"
    hostile.mkdir()
    (hostile / "important.txt").write_text("do not delete")
    with pytest.raises(ValueError, match="non-Explorer"):
        build_web_bundle(published, hostile, force=True)
    assert (hostile / "important.txt").is_file()


def test_bundle_freshness_tracks_sigma_runs_and_options(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    assert not bundle_is_current(published, dest)
    build_web_bundle(published, dest)
    assert bundle_is_current(published, dest)
    assert not bundle_is_current(published, dest, include_roads=False)
    (published / "sigma_manifest.json").write_text('{"files": ["second run"]}', encoding="utf-8")
    assert not bundle_is_current(published, dest)
    build_web_bundle(published, dest, force=True)
    (dest / ".sigma-explorer").write_text("sigma-explorer-v1\n", encoding="utf-8")  # first overlay
    assert not bundle_is_current(published, dest)
    build_web_bundle(published, dest, force=True)  # v1 bundles may be replaced
    assert bundle_is_current(published, dest)


def test_workspace_output_location_is_read_from_metadata(tmp_path: Path):
    workspace = tmp_path / "custom-ws"
    workspace.mkdir()
    output = tmp_path / "custom-outputs"
    (workspace / "workspace.json").write_text(json.dumps({"output_dir": str(output)}))
    assert resolve_output_directory(workspace) == output
    with pytest.raises(FileNotFoundError):
        resolve_output_directory(tmp_path / "missing")


def test_incomplete_output_is_reported_without_adding_a_directory(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    dest = tmp_path / "destination"
    with pytest.raises(FileNotFoundError, match="sigma_points.parquet"):
        build_web_bundle(empty, dest)
    assert not dest.exists()


def test_bad_new_inputs_do_not_destroy_previous_good_bundle(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    build_web_bundle(published, dest)
    old_graph = (dest / "data/graph.json").read_bytes()
    csv_file = published / "sigma_X_edges.csv"
    csv_file.write_text(csv_file.read_text(encoding="utf-8").replace("54,1,55,2", "54,99,55,2"), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown node"):
        build_web_bundle(published, dest, force=True)
    assert (dest / "data/graph.json").read_bytes() == old_graph
    assert (dest / ".sigma-explorer").exists()


def test_server_sends_executable_types_and_hides_listings(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    build_web_bundle(published, dest)
    server = web_server._bind(dest, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base}/app.js") as response:
            assert response.headers["Content-Type"].startswith("text/javascript")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        with urllib.request.urlopen(f"{base}/data/metadata.json") as response:
            assert response.headers["Content-Type"] == "application/json"
        with pytest.raises(urllib.error.HTTPError) as listing:
            urllib.request.urlopen(f"{base}/data/")
        assert listing.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_server_moves_to_a_free_port(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    build_web_bundle(published, dest)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        server = web_server._bind(dest, taken)
        try:
            assert server.server_port != taken
        finally:
            server.server_close()


def test_cli_view_rebuilds_only_after_new_outputs(published: Path, monkeypatch: pytest.MonkeyPatch):
    from typer.testing import CliRunner

    import sigma.web
    from sigma.cli import app

    served: list[Path] = []
    monkeypatch.setattr(sigma.web, "serve_bundle", lambda d, **kw: served.append(Path(d)))
    runner = CliRunner()
    args = ["view", "anything", "--source-dir", str(published), "--no-browser"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "built from the latest SIGMA outputs" in first.output
    second = runner.invoke(app, args)
    assert "already match" in second.output
    (published / "sigma_manifest.json").write_text('{"files": ["new run"]}', encoding="utf-8")
    third = runner.invoke(app, args)
    assert "built from the latest SIGMA outputs" in third.output
    assert served == [published / "explorer"] * 3


def test_stale_csv_invalidates_even_unchanged_manifest(published: Path, tmp_path: Path):
    dest = tmp_path / "web"
    build_web_bundle(published, dest)
    assert bundle_is_current(published, dest)
    csv = published / "sigma_X_edges.csv"
    csv.write_text(csv.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert not bundle_is_current(published, dest)


def test_source_ancestor_and_bad_marker_cannot_be_overwritten(published: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="must not contain"):
        build_web_bundle(published, tmp_path, force=True)
    dest = tmp_path / "other"
    build_web_bundle(published, dest)
    (dest / ".sigma-explorer").write_text('{"format":"some-other-application","version":3}')
    with pytest.raises(ValueError, match="non-Explorer"):
        build_web_bundle(published, dest, force=True)
    assert (dest / "data/graph.json").is_file()


def test_public_profile_omits_individual_points_and_local_path(published: Path, tmp_path: Path):
    dest = tmp_path / "public"
    build_web_bundle(published, dest, profile="public")
    meta = _json(dest / "data/metadata.json")
    assert meta["profile"] == "public" and not meta["has_points"]
    assert list((dest / "data").rglob("*.geojson"))  # cluster & network layers retained
    assert _json(dest / "data/tiles.json")["tiles"] == {}
    all_text = " ".join(x.read_text(encoding="utf-8") for x in dest.rglob("*.json"))
    assert "Test Shop" not in all_text and '"p1"' not in all_text
    assert str(published) not in (dest / ".sigma-explorer").read_text(encoding="utf-8")
    assert not bundle_is_current(published, dest, profile="local")
    assert bundle_is_current(published, dest, profile="public")


def test_independent_reciprocal_routes_are_not_merged(published: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original = pyogrio.read_dataframe
    def read_with_alternative_reverse(path, *args, **kwargs):
        layer = kwargs.get("layer")
        result = original(path, *args, **kwargs)
        if layer == "paths":
            result.loc[result["from_id"] == B, "geometry"] = [LineString([
                B_END, (121.066543, 14.607654), A_END,
            ])]
        return result
    monkeypatch.setattr(web_builder.pyogrio, "read_dataframe", read_with_alternative_reverse)
    dest = tmp_path / "web"
    build_web_bundle(published, dest)
    node = next(n for n in _json(dest / "data/graph.json")["nodes"] if n["id"] == A)
    features = _json(dest / node["route_file"])["features"]
    assert all(f["geometry"] is not None for f in features)  # different paths are both stored
    ab = next(f for f in features if f["properties"]["from"] == A and f["properties"]["to"] == B)
    ba = next(f for f in features if f["properties"]["from"] == B and f["properties"]["to"] == A)
    assert ab["geometry"]["coordinates"][1] == [121.064123, 14.603123]
    assert ba["geometry"]["coordinates"][1] == [121.066543, 14.607654]


def test_unmatched_partition_is_rejected(published: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original = pyogrio.read_dataframe
    def bad_cluster(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if kwargs.get("layer") == "clusters":
            result.loc[0, "cluster"] = 999
        return result
    monkeypatch.setattr(web_builder.pyogrio, "read_dataframe", bad_cluster)
    with pytest.raises(ValueError, match="no corresponding X node"):
        build_web_bundle(published, tmp_path / "web")


def test_generated_point_ids_avoid_collisions(published: Path, tmp_path: Path):
    path = published / "sigma_points.parquet"
    frame = gpd.read_parquet(path)
    frame["canonical_id"] = ["row-1", "row-1", "explorer-row-1"]
    frame.to_parquet(path, index=False)
    dest = tmp_path / "web"
    build_web_bundle(published, dest)
    files = list((dest / "data/tiles/13").rglob("*.geojson"))
    ids = [f["properties"]["id"] for path in files for f in _json(path)["features"]]
    assert len(ids) == len(set(ids)) == 3


def test_publication_integrity_manifest_hash_mismatch_fails(published: Path, tmp_path: Path):
    import hashlib
    target = published / "sigma_X_edges.csv"
    correct = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {"files": [{"name": "sigma_X_edges.csv", "sha256": correct, "size": target.stat().st_size}]}
    (published / "sigma_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    build_web_bundle(published, tmp_path / "good")
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity mismatch"):
        build_web_bundle(published, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_public_bundle_is_never_replaced_with_establishment_data(published: Path, tmp_path: Path):
    public = tmp_path / "shared"
    build_web_bundle(published, public, profile="public")
    with pytest.raises(ValueError, match="public-profile"):
        build_web_bundle(published, public, force=True)  # local profile into a public bundle
    with pytest.raises(ValueError, match="public-profile"):
        build_web_bundle(published, published / "explorer-public")  # reserved name
    assert _json(public / "data/metadata.json")["profile"] == "public"
    build_web_bundle(published, public, force=True, profile="public")  # public refresh is fine


def test_cli_view_keeps_a_public_bundle_public(published: Path, monkeypatch: pytest.MonkeyPatch):
    from typer.testing import CliRunner

    import sigma.web
    from sigma.cli import app

    monkeypatch.setattr(sigma.web, "serve_bundle", lambda d, **kw: None)
    runner = CliRunner()
    made = runner.invoke(app, ["export-web", "x", "--source-dir", str(published), "--public"])
    assert made.exit_code == 0, made.output
    assert "sigma view x --public" in made.output
    target = published / "explorer-public"
    (published / "sigma_manifest.json").write_text('{"files": ["newer run"]}', encoding="utf-8")
    for args in (["--public"], ["--output-dir", str(target)]):
        result = runner.invoke(app, ["view", "x", "--source-dir", str(published), "--no-browser", *args])
        assert result.exit_code == 0, result.output
        meta = _json(target / "data/metadata.json")
        assert meta["profile"] == "public" and not meta["has_points"]
    assert _json(target / "data/tiles.json")["tiles"] == {}


def test_optional_files_left_from_an_earlier_run_are_ignored(published: Path, tmp_path: Path):
    import hashlib

    listed = ["sigma_points.parquet", "sigma_spatial_outputs.gpkg", "sigma_X_nodes.csv",
              "sigma_X_edges.csv", "sigma_run_metadata.json", "sigma_roads.parquet"]
    files = [{"name": n, "sha256": hashlib.sha256((published / n).read_bytes()).hexdigest(),
              "size": (published / n).stat().st_size} for n in listed]
    (published / "sigma_manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    report = build_web_bundle(published, tmp_path / "web")  # sigma_boundary.parquet is not listed
    meta = _json(tmp_path / "web/data/metadata.json")
    assert not meta["has_boundary"] and meta["has_roads"]
    assert any("sigma_boundary.parquet" in w for w in report["warnings"])
    assert bundle_is_current(published, tmp_path / "web")
    (published / "sigma_boundary.parquet").write_bytes(b"changed but not part of the run")
    assert bundle_is_current(published, tmp_path / "web")


# --------------------------------------------------------------------------- real export


def _synthetic_city(root: Path):
    """A small street grid with four business hot spots, run through SIGMA's area pipeline."""
    from sigma import Area, Sigma, SigmaConfig, SourceConfig, SpatialConfig
    from sigma.places.pipeline import PlaceServices

    rng = np.random.default_rng(11)
    west, south, east, north = 121.060, 14.560, 121.080, 14.580
    step = 0.0015
    xs, ys = np.arange(west - 0.003, east + 0.003, step), np.arange(south - 0.003, north + 0.003, step)
    lines = [LineString([(x, ys[j]), (x, ys[j + 1])]) for x in xs for j in range(len(ys) - 1)]
    lines += [LineString([(xs[i], y), (xs[i + 1], y)]) for y in ys for i in range(len(xs) - 1)]
    roads = root / "roads.gpkg"
    gpd.GeoDataFrame(geometry=lines, crs="EPSG:4326").to_crs("EPSG:32651").to_file(roads, layer="roads", driver="GPKG")
    spots = [(121.064, 14.564), (121.076, 14.566), (121.066, 14.576), (121.075, 14.577)]
    categories = ["amenity=restaurant", "shop=supermarket", "amenity=bank", "shop=car_repair"]
    rows = []
    for k in range(260):
        x, y = spots[k % 4]
        rows.append((x + rng.normal(0, 0.0008), y + rng.normal(0, 0.0008), categories[(k // 4) % 4]))

    def frame(source: str) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(pd.DataFrame({
            "source": source, "source_id": [f"{source}/{i}" for i in range(len(rows))],
            "name": [f"Place {i}" for i in range(len(rows))], "category": [c for _, _, c in rows],
            "lon": [x for x, _, _ in rows], "lat": [y for _, y, _ in rows], "provenance": source,
            "upstream_license": "ODbL-1.0" if source == "osm" else "CDLA-Permissive-2.0",
            "overture_providers": "" if source == "osm" else "meta",
        }), geometry=[Point(x, y) for x, y, _ in rows], crs="EPSG:4326")

    pbf, snapshot = root / "ph.osm.pbf", root / "overture.parquet"
    pbf.write_bytes(b"fixture")
    snapshot.write_bytes(b"fixture")
    services = PlaceServices(
        geofabrik=lambda store, config, progress: store.register_path(
            pbf, kind="provider-snapshot", provider="geofabrik", name="philippines-osm-pbf", version="fixture"),
        overture=lambda store, bbox, config, progress: store.register_path(
            snapshot, kind="query-snapshot", provider="overture", name="places",
            selection={"bbox": list(bbox)}, metadata={"bbox": list(bbox)}),
        load_overture=lambda ref: frame("overture").iloc[::13],
        load_prepared_osm=lambda cache_base, ref, area_slug, areas_file, progress: (frame("osm"), "fixture", False),
    )
    job = Sigma(
        Area("explorer_fixture", "Explorer Fixture", "city", (west, south, east, north)),
        workspace=root / "workspace", source_store=root / "sources", output_dir=root / "output",
        roads=roads, roads_layer="roads", place_services=services,
        config=SigmaConfig(sources=SourceConfig(), spatial=SpatialConfig(min_cluster_size=5, voronoi_resolution=500.0)),
    )
    job.load()
    job.run()
    return root / "output"


def test_explorer_builds_from_a_genuine_sigma_export(tmp_path: Path):
    output = _synthetic_city(tmp_path)
    run = _json(output / "sigma_run_metadata.json")
    report = build_web_bundle(output, output / "explorer")
    assert report["points"] == run["scored_points"]
    assert report["edges"] == run["x_edges"] > 0
    assert report["clusters"] == run["x_nodes"]
    assert report["unassigned_points"] == 0
    dest = output / "explorer"
    graph = _json(dest / "data/graph.json")
    ids = {n["id"] for n in graph["nodes"]}
    pairs = {(e["from"], e["to"]) for e in graph["edges"]}
    for node in graph["nodes"]:
        if node["route_file"] is None:
            continue
        for feature in _json(dest / node["route_file"])["features"]:
            attr = feature["properties"]
            if feature["geometry"] is None:  # exact reverse of an edge stored in the same file
                partner = _json(dest / node["route_file"])["features"][attr["reverse_of"]]["properties"]
                assert (partner["from"], partner["to"]) == (attr["to"], attr["from"])
            assert attr["other"] in ids
            assert (attr["from"], attr["to"]) in pairs
            assert attr["direction"] == ("outgoing" if attr["from"] == node["id"] else "incoming")
    meta = _json(dest / "data/metadata.json")
    assert meta["distance_unit"] == "m"
    assert meta["has_roads"] and meta["has_boundary"]
    assert sum(n["members"] for n in graph["nodes"]) == run["scored_points"]
    assert bundle_is_current(output, dest)


def test_local_finder_index_and_public_privacy(published: Path, tmp_path: Path):
    local = tmp_path / "local-finder"
    public = tmp_path / "public-finder"
    build_web_bundle(published, local)
    meta = _json(local / "data/metadata.json")
    assert meta["has_establishment_finder"]
    manifest = _json(local / "data/search/index.json")
    assert manifest["version"] == 1
    assert set(manifest["sectors"]) == {"54", "55", "63"}
    seen_names = set()
    for sector, filenames in manifest["sectors"].items():
        for filename in filenames:
            assert filename.startswith("data/search/")
            assert (local / filename).stat().st_size < 2_000_000
            for name, tile_key, offset, cluster in _json(local / filename):
                seen_names.add(name)
                fc = _json(local / "data/tiles/13" / (tile_key + ".geojson"))
                point = fc["features"][offset]
                assert point["properties"]["name"] == name
                assert point["properties"]["type"] == sector
                assert point["properties"]["cluster"] == cluster
    assert seen_names == {"Test Shop", "Another shop", "Eatery"}
    build_web_bundle(published, public, profile="public")
    assert not _json(public / "data/metadata.json")["has_establishment_finder"]
    assert not (public / "data/search").exists()
    assert "Test Shop" not in " ".join(p.read_text(encoding="utf-8") for p in public.rglob("*.json"))

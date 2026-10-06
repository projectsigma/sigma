from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from sigma import Area, Economy, GeofabrikRoadSource
from sigma.places.pipeline import PlacePipeline, PlaceServices
from sigma.spatial import SpatialPipeline, SpatialRunConfig
from sigma.sources import SourceStore
from sigma.transport import roads as roads_module
from sigma.workspace import SigmaWorkspace


def _area() -> Area:
    return Area("fixture", "Fixture City", "city", (120.99, 13.99, 121.01, 14.01))


def _workspace(tmp_path: Path, area: Area) -> SigmaWorkspace:
    return SigmaWorkspace.create(
        tmp_path / "workspace",
        area=area,
        source_store=tmp_path / "sources",
        output_dir=tmp_path / "output",
    )


def _services(tmp_path: Path, calls: dict[str, object]) -> PlaceServices:
    pbf = tmp_path / "philippines.osm.pbf"
    pbf.write_bytes(b"one-shared-pbf")

    def geofabrik(store: SourceStore, config, progress):
        calls["geofabrik"] = int(calls.get("geofabrik", 0)) + 1
        return store.register_path(
            pbf,
            kind="provider-snapshot",
            provider="geofabrik",
            name="philippines-osm-pbf",
            version="fixture-v1",
            managed=False,
        )

    def load_prepared(cache_base, ref, area_slug, areas_file, progress):
        calls["poi_source_id"] = ref.source_id
        frame = gpd.GeoDataFrame(
            {"osm_id": ["node/1"], "name": ["Fixture"]},
            geometry=[Point(121.0, 14.0)],
            crs="EPSG:4326",
        )
        return frame, "fixture-v1", False

    return PlaceServices(geofabrik=geofabrik, load_prepared_osm=load_prepared)


def _patch_road_candidates(monkeypatch):
    candidates = gpd.GeoDataFrame(
        {
            "osm_way_id": [100],
            "highway": ["primary"],
            "access": [None],
            "name": ["Fixture Road"],
            "oneway": ["yes"],
            "bridge": [None],
            "tunnel": [None],
            "layer": [None],
        },
        geometry=[LineString([(120.995, 14.0), (121.005, 14.0)])],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(roads_module, "_extract_pbf_road_candidates", lambda path, bbox, **kwargs: candidates)


def test_one_geofabrik_snapshot_feeds_poi_and_managed_road_consumers_independently(tmp_path, monkeypatch):
    _patch_road_candidates(monkeypatch)
    area = _area()
    ws = _workspace(tmp_path, area)
    calls: dict[str, object] = {}
    place = PlacePipeline(ws, area=area, services=_services(tmp_path, calls))
    spatial = SpatialPipeline(
        ws,
        roads=GeofabrikRoadSource(buffer_m=0),
        place_pipeline=place,
        economy=Economy.default(),
        config=SpatialRunConfig(min_cluster_size=2, min_samples=2),
    )

    road_ref = spatial.planner.ensure("transport.roads")
    poi_ref = spatial.planner.ensure("source.osm_national_pois")
    gf_artifact = ws.artifact("source.geofabrik_pbf")
    assert gf_artifact is not None
    source_payload = __import__("json").loads((gf_artifact.path / "source.json").read_text())
    source_id = source_payload["source_id"]

    assert calls["geofabrik"] == 1
    assert calls["poi_source_id"] == source_id
    assert ws.manifest("transport.roads").metadata["source_id"] == source_id
    assert ws.manifest("transport.roads").metadata["road_source_mode"] == "geofabrik"
    assert (road_ref.path / "roads.json").is_file()
    assert (poi_ref.path / "osm-area.json").is_file()

    # Transport depends only on the shared PBF pointer + boundary, not on POI extraction.
    assert spatial.planner.stages["transport.roads"].dependencies == (
        "source.geofabrik_pbf",
        "area.boundary",
    )
    assert "source.osm_national_pois" not in spatial.planner.stages["transport.roads"].dependencies


def test_managed_road_policy_change_invalidates_transport_not_shared_pbf(tmp_path, monkeypatch):
    _patch_road_candidates(monkeypatch)
    area = _area()
    ws = _workspace(tmp_path, area)
    calls: dict[str, object] = {}
    place = PlacePipeline(ws, area=area, services=_services(tmp_path, calls))

    first = SpatialPipeline(
        ws,
        roads=GeofabrikRoadSource(buffer_m=0),
        place_pipeline=place,
        economy=Economy.default(),
    )
    first_road = first.planner.ensure("transport.roads")
    first_pbf = ws.artifact("source.geofabrik_pbf")
    assert first_pbf is not None

    second = SpatialPipeline(
        ws,
        roads=GeofabrikRoadSource(buffer_m=1000),
        place_pipeline=place,
        economy=Economy.default(),
    )
    second_road = second.planner.ensure("transport.roads")
    second_pbf = ws.artifact("source.geofabrik_pbf")
    assert second_pbf is not None

    assert second_pbf.artifact_id == first_pbf.artifact_id
    assert second_road.artifact_id != first_road.artifact_id
    assert calls["geofabrik"] == 2  # two independent planners resolve the same SourceStore identity
    assert ws.manifest("transport.roads").metadata["clip_buffer_m"] == 1000.0


def test_public_sigma_facade_accepts_opt_in_managed_roads(tmp_path, monkeypatch):
    from sigma import Sigma

    _patch_road_candidates(monkeypatch)
    area = _area()
    calls: dict[str, object] = {}
    job = Sigma(
        area,
        workspace=tmp_path / "facade-workspace",
        source_store=tmp_path / "facade-sources",
        roads=GeofabrikRoadSource(buffer_m=0),
        place_services=_services(tmp_path, calls),
    )
    result = job.prepare_network()
    manifest = job.workspace.manifest("transport.roads")
    assert manifest is not None
    assert manifest.metadata["road_source_mode"] == "geofabrik"
    assert result.roads == job.workspace.artifact("transport.roads")
    assert calls["geofabrik"] == 1


def test_sigma_facade_shares_source_runtime_across_domain_planners(tmp_path):
    from sigma import Sigma

    area = _area()
    calls: dict[str, object] = {}
    job = Sigma(
        area,
        workspace=tmp_path / "runtime-workspace",
        source_store=tmp_path / "runtime-sources",
        place_services=_services(tmp_path, calls),
    )
    place = job._place_pipeline()
    assert place is not None
    spatial = SpatialPipeline(
        job.workspace, roads=GeofabrikRoadSource(), economy=job.economy, place_pipeline=place
    )
    spatial.planner.runtime = job._runtime_cache

    first = place.planner.ensure("source.geofabrik_pbf")
    second = spatial.planner.ensure("source.geofabrik_pbf")
    assert second.artifact_id == first.artifact_id
    assert calls["geofabrik"] == 1

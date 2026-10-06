from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from sigma import Economy, SigmaWorkspace
from sigma.area import resolve_area
from sigma.classification import TaggingReferences
from sigma.classification.crosswalk import CrosswalkIndex
from sigma.classification.reference import PsicNode, PsicTaxonomy, load_builtin_io_reference
from sigma.economy import Sector, SectorCatalog
from sigma.places.pipeline import PlacePipeline, PlaceRunConfig, PlaceServices


def _source(source: str, sid: str, name: str, category: str):
    frame = pd.DataFrame(
        {
            "source": [source],
            "source_id": [sid],
            "name": [name],
            "category": [category],
            "lon": [121.0],
            "lat": [14.5],
            "provenance": [source],
            "upstream_license": ["ODbL-1.0" if source == "osm" else "CDLA-Permissive-2.0"],
            "overture_providers": ["" if source == "osm" else "meta"],
        }
    )
    return gpd.GeoDataFrame(frame, geometry=[Point(121.0, 14.5)], crs="EPSG:4326")


def _synthetic_builtin_taxonomy() -> PsicTaxonomy:
    ref = load_builtin_io_reference()
    nodes = [PsicNode(row.rev5_code, row.rev5_level, row.rev5_title) for row in ref.bridge]
    known = {node.code for node in nodes}
    level_for_length = {1: "section", 2: "division", 3: "group", 4: "class", 5: "subclass"}
    for rule in CrosswalkIndex.load_builtin().entries:
        for code in rule.codes:
            if code in known:
                continue
            nodes.append(PsicNode(code, level_for_length[len(code)], f"Synthetic {code}"))
            known.add(code)
    taxonomy = PsicTaxonomy(nodes)
    taxonomy.origin = "builtin:psic_rev5"
    raw = resources.files("sigma.resources.classification").joinpath("psic_rev5", "nodes.parquet").read_bytes()
    taxonomy.asset_sha256 = hashlib.sha256(raw).hexdigest()
    return taxonomy


def _services(tmp_path: Path, taxonomy=None):
    osm = _source("osm", "node/1", "Sample Bank", "amenity=bank")
    overture = _source("overture", "ov-1", "Sample Bank", "bank")
    pbf = tmp_path / "philippines.osm.pbf"
    pbf.write_bytes(b"pbf-fixture")
    overture_bytes = tmp_path / "overture.parquet"
    overture_bytes.write_bytes(b"overture-fixture")

    def geofabrik(store, config, progress):
        return store.register_path(
            pbf, kind="provider-snapshot", provider="geofabrik", name="philippines-osm-pbf", version="test-v1"
        )

    def overture_ref(store, bbox, config, progress):
        return store.register_path(
            overture_bytes, kind="query-snapshot", provider="overture", name="places",
            selection={"bbox": list(bbox)}, metadata={"bbox": list(bbox)}
        )

    def prepared(cache_base, gf, area_slug, areas_file, progress):
        return osm.copy(), "test-v1", False

    return PlaceServices(
        geofabrik=geofabrik,
        overture=overture_ref,
        load_overture=lambda ref: overture.copy(),
        load_prepared_osm=prepared,
        taxonomy=(lambda: taxonomy) if taxonomy is not None else None,
    )


def _workspace(tmp_path: Path):
    area = resolve_area("metro_manila")
    ws = SigmaWorkspace.create(
        tmp_path / "workspace", area=area, source_store=tmp_path / "sources", output_dir=tmp_path / "output"
    )
    return area, ws


def test_place_branch_reproduces_siphon_fixture_and_reuses_all_stages(tmp_path):
    area, ws = _workspace(tmp_path)
    taxonomy = _synthetic_builtin_taxonomy()
    pipeline = PlacePipeline(ws, area=area, services=_services(tmp_path, taxonomy=taxonomy))
    ref = pipeline.load()
    result = pipeline.read_classified(ref)

    assert len(result) == 1
    assert result.loc[0, "osm_name"] == "Sample Bank"
    assert result.loc[0, "osm_category"] == "amenity=bank"
    assert result.loc[0, "overture_name"] == "Sample Bank"
    assert result.loc[0, "overture_category"] == "bank"
    assert result.loc[0, "psic_code"]
    assert result.loc[0, "direct_io80_code"] == "66"
    assert result.loc[0, "io80_code"] == "66"
    assert result.loc[0, "economy_code"] == "66"
    assert result.loc[0, "economy_label"] == Economy.default().sectors.label_for("66")
    assert "ODbL-1.0" in result.loc[0, "source_licenses"]

    first = {stage: ws.artifact(stage).artifact_id for stage in pipeline.planner.stages}
    second_ref = pipeline.load()
    second = {stage: ws.artifact(stage).artifact_id for stage in pipeline.planner.stages}
    assert second_ref.artifact_id == ref.artifact_id
    assert second == first
    assert all(step.action == "reuse" for step in pipeline.planner.plan("places.classified"))


def test_taxonomy_change_recomputes_only_classification_descendants(tmp_path):
    area, ws = _workspace(tmp_path)
    builtin = _synthetic_builtin_taxonomy()
    first = PlacePipeline(ws, area=area, services=_services(tmp_path, taxonomy=builtin))
    first.load()
    ids_before = {stage: ws.artifact(stage).artifact_id for stage in first.planner.stages}

    custom = PsicTaxonomy.from_frame(pd.DataFrame([
        {"scheme": "custom", "version": "1", "code": "A", "level": "section", "title": "Bank", "parent_code": ""},
    ]))
    economy = Economy(
        economy_id="custom-econ",
        sectors=SectorCatalog([Sector("E1", "Banking")]),
        raw_transactions=pd.DataFrame([[1.0]], index=["E1"], columns=["E1"]),
        total_output=pd.Series([2.0], index=["E1"]),
    )
    custom_services = _services(tmp_path, taxonomy=custom)
    custom_services.references = lambda t, e: TaggingReferences.custom(
        taxonomy=t, economy=e, source_to_psic=CrosswalkIndex([]), psic_to_economy={"A": "E1"}
    )
    second = PlacePipeline(ws, area=area, economy=economy, services=custom_services)
    second.load()
    ids_after = {stage: ws.artifact(stage).artifact_id for stage in second.planner.stages}

    for stage in (
        "area.definition", "area.boundary", "source.geofabrik_pbf", "source.osm_national_pois",
        "source.osm_area_index", "source.overture_snapshot", "places.osm_area", "places.overture_area",
        "places.canonical",
    ):
        assert ids_after[stage] == ids_before[stage]
    assert ids_after["classification.taxonomy"] != ids_before["classification.taxonomy"]
    assert ids_after["classification.tagging_references"] != ids_before["classification.tagging_references"]
    assert ids_after["places.psic"] != ids_before["places.psic"]
    assert ids_after["places.classified"] != ids_before["places.classified"]


def test_transaction_value_change_with_same_sector_identity_reuses_place_tags(tmp_path):
    area, ws = _workspace(tmp_path)
    custom = PsicTaxonomy.from_frame(pd.DataFrame([
        {"scheme": "custom", "version": "1", "code": "A", "level": "section", "title": "Bank", "parent_code": ""},
    ]))
    services = _services(tmp_path, taxonomy=custom)
    services.references = lambda t, e: TaggingReferences.custom(
        taxonomy=t, economy=e, source_to_psic=CrosswalkIndex([]), psic_to_economy={"A": "E1"}
    )
    sectors = SectorCatalog([Sector("E1", "Banking")])
    e1 = Economy(economy_id="e1", sectors=sectors, raw_transactions=pd.DataFrame([[1.0]], index=["E1"], columns=["E1"]), total_output=pd.Series([2.0], index=["E1"]))
    first = PlacePipeline(ws, area=area, economy=e1, services=services)
    first.load()
    classified_before = ws.artifact("places.classified").artifact_id

    e2 = Economy(economy_id="e2", sectors=sectors, raw_transactions=pd.DataFrame([[9.0]], index=["E1"], columns=["E1"]), total_output=pd.Series([10.0], index=["E1"]))
    second = PlacePipeline(ws, area=area, economy=e2, services=services)
    second.load()
    assert ws.artifact("places.classified").artifact_id == classified_before


def test_compatibility_publication_preserves_siphon_surface(monkeypatch, tmp_path):
    area, ws = _workspace(tmp_path)
    taxonomy = _synthetic_builtin_taxonomy()
    pipeline = PlacePipeline(ws, area=area, services=_services(tmp_path, taxonomy=taxonomy))
    ref = pipeline.load()

    written = {}
    def fake_to_parquet(self, path, index=False):
        written["frame"] = self.copy()
        Path(path).touch()
    monkeypatch.setattr(gpd.GeoDataFrame, "to_parquet", fake_to_parquet)

    target, report = pipeline.publish_compatibility(ref)
    assert target.name == "pois.parquet"
    assert target.exists()
    assert (target.parent / "run.json").exists()
    assert (target.parent / "ATTRIBUTION.txt").exists()
    assert (target.parent / "DATABASE_LICENSE.txt").exists()
    result = written["frame"]
    assert result.loc[0, "io80_code"] == "66"
    assert report["counts"]["matched_two_source"] == 1
    assert report["counts"]["psic_coded"] == 1
    assert report["counts"]["io80_coded"] == 1
    assert report["classification"]["architecture"] == "psic-primary-hybrid-io"
    assert report["classification"]["psic_canonical"] is True
    assert report["licensing"]["database_license"] == "ODbL-1.0"
    assert report["licensing"]["software"] == "Proprietary"
    assert report["boundary"]["mode"] == "gpkg"
    assert len(str(report["boundary"]["geometry_sha256"])) == 64
    assert len(str(report["boundary"]["fingerprint"])) == 64
    assert report["classified_places_artifact_id"] == ref.artifact_id


def test_geofabrik_source_change_invalidates_only_osm_and_downstream_branch(tmp_path):
    area, ws = _workspace(tmp_path)
    taxonomy = _synthetic_builtin_taxonomy()
    services = _services(tmp_path, taxonomy=taxonomy)
    first = PlacePipeline(ws, area=area, services=services)
    first.load()
    before = {stage: ws.artifact(stage).artifact_id for stage in first.planner.stages}

    # Same logical local source path, different bytes/version: source identity must change.
    pbf = tmp_path / "philippines.osm.pbf"
    pbf.write_bytes(b"pbf-fixture-v2")
    def geofabrik_v2(store, config, progress):
        return store.register_path(
            pbf, kind="provider-snapshot", provider="geofabrik", name="philippines-osm-pbf", version="test-v2"
        )
    services2 = _services(tmp_path, taxonomy=taxonomy)
    services2.geofabrik = geofabrik_v2
    second = PlacePipeline(ws, area=area, services=services2)
    second.load()
    after = {stage: ws.artifact(stage).artifact_id for stage in second.planner.stages}

    assert after["source.geofabrik_pbf"] != before["source.geofabrik_pbf"]
    assert after["source.osm_national_pois"] != before["source.osm_national_pois"]
    assert after["source.osm_area_index"] != before["source.osm_area_index"]
    assert after["places.osm_area"] != before["places.osm_area"]
    assert after["places.canonical"] != before["places.canonical"]
    assert after["places.psic"] != before["places.psic"]
    assert after["places.classified"] != before["places.classified"]
    # Overture snapshot/branch is independent of the Geofabrik source identity.
    assert after["source.overture_snapshot"] == before["source.overture_snapshot"]
    assert after["places.overture_area"] == before["places.overture_area"]


def test_status_never_calls_provider_acquisition_for_missing_sources(tmp_path):
    area, ws = _workspace(tmp_path)
    taxonomy = _synthetic_builtin_taxonomy()
    services = PlaceServices(
        geofabrik=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network acquisition called")),
        overture=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network acquisition called")),
        taxonomy=lambda: taxonomy,
    )
    pipeline = PlacePipeline(ws, area=area, services=services)
    status = pipeline.planner.status()
    assert status["source.geofabrik_pbf"].status == "missing"
    assert status["source.overture_snapshot"].status == "missing"


def test_osm_preparation_namespace_preserves_cross_version_fallback(tmp_path):
    area, ws = _workspace(tmp_path)
    taxonomy = _synthetic_builtin_taxonomy()
    osm = _source("osm", "node/1", "Sample Bank", "amenity=bank")
    overture = _source("overture", "ov-1", "Sample Bank", "bank")
    pbf = tmp_path / "fallback-pbf.osm.pbf"
    ov = tmp_path / "fallback-overture.parquet"
    ov.write_bytes(b"ov")
    seen_cache_bases = []

    def overture_ref(store, bbox, config, progress):
        return store.register_path(ov, kind="query-snapshot", provider="overture", name="places", selection={"bbox": list(bbox)})

    def loader(cache_base, gf, area_slug, areas_file, progress):
        seen_cache_bases.append(cache_base)
        if gf.version == "v2":
            return osm.copy(), "v1", True
        return osm.copy(), "v1", False

    pbf.write_bytes(b"v1")
    services1 = PlaceServices(
        geofabrik=lambda store, config, progress: store.register_path(pbf, kind="provider-snapshot", provider="geofabrik", name="philippines-osm-pbf", version="v1"),
        overture=overture_ref, load_overture=lambda ref: overture.copy(), load_prepared_osm=loader,
        taxonomy=lambda: taxonomy,
    )
    PlacePipeline(ws, area=area, services=services1).load()

    pbf.write_bytes(b"v2")
    services2 = PlaceServices(
        geofabrik=lambda store, config, progress: store.register_path(pbf, kind="provider-snapshot", provider="geofabrik", name="philippines-osm-pbf", version="v2"),
        overture=overture_ref, load_overture=lambda ref: overture.copy(), load_prepared_osm=loader,
        taxonomy=lambda: taxonomy,
    )
    PlacePipeline(ws, area=area, services=services2).load()
    assert len(seen_cache_bases) == 2
    assert seen_cache_bases[0] == seen_cache_bases[1]
    fallback_ref = ws.artifact("source.osm_national_pois")
    assert fallback_ref is not None
    meta = ws.manifest("source.osm_national_pois").metadata
    assert meta["fallback"] is True
    assert meta["prepared_source_version"] == "v1"
    assert meta["cache_reusable"] is False

    # The same requested v2 source must retry preparation rather than permanently reusing
    # the fallback artifact. A successful retry supersedes only that provisional artifact.
    def loader_v2(cache_base, gf, area_slug, areas_file, progress):
        seen_cache_bases.append(cache_base)
        return osm.copy(), "v2", False

    services3 = PlaceServices(
        geofabrik=lambda store, config, progress: store.register_path(
            pbf, kind="provider-snapshot", provider="geofabrik",
            name="philippines-osm-pbf", version="v2"
        ),
        overture=overture_ref, load_overture=lambda ref: overture.copy(),
        load_prepared_osm=loader_v2, taxonomy=lambda: taxonomy,
    )
    PlacePipeline(ws, area=area, services=services3).load()
    fresh_ref = ws.artifact("source.osm_national_pois")
    assert fresh_ref is not None
    assert fresh_ref.artifact_id != fallback_ref.artifact_id
    fresh_meta = ws.manifest("source.osm_national_pois").metadata
    assert fresh_meta["fallback"] is False
    assert fresh_meta["prepared_source_version"] == "v2"
    assert fresh_meta["cache_reusable"] is True
    assert len(seen_cache_bases) == 3

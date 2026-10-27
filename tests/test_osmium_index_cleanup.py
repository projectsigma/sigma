"""Regression tests for disk-backed libosmium index lifecycle."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from sigma._cache_cleanup import remove_temporary_node_index
from sigma.sources import osm_prepare
from sigma.spatial import pipeline as spatial_pipeline
from sigma.transport.roads import GeofabrikRoadSource


def test_temporary_node_index_cleanup_is_idempotent(tmp_path):
    index = tmp_path / "nodes.cache"
    index.write_bytes(b"temporary index")

    remove_temporary_node_index(index, progress=None, label="test")
    remove_temporary_node_index(index, progress=None, label="test")

    assert not index.exists()


def test_locked_node_index_does_not_fail_completed_stage(tmp_path, monkeypatch):
    index = tmp_path / "nodes.cache"
    index.write_bytes(b"temporary index")
    messages = []
    original_unlink = Path.unlink

    def locked_unlink(self, *args, **kwargs):
        if self == index:
            raise PermissionError("file in use")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    remove_temporary_node_index(index, progress=messages.append, label="roads")

    assert index.exists()
    assert messages and "file in use" in messages[0]


@pytest.mark.parametrize("write_fails", [False, True])
def test_national_poi_index_is_removed_after_extraction(tmp_path, monkeypatch, write_fails):
    index = tmp_path / "sources" / "geofabrik" / "node-locations.cache"
    output = tmp_path / "work" / "national-pois.parquet"
    monkeypatch.setattr(osm_prepare, "_parquet_ok", lambda path: False)
    monkeypatch.setattr(osm_prepare, "_set_stage", lambda *args, **kwargs: None)

    def fake_extract(pbf_file, *, node_cache, progress):
        assert node_cache == index
        node_cache.parent.mkdir(parents=True, exist_ok=True)
        node_cache.write_bytes(b"temporary index")
        return ["POI"]

    def fake_save(frame, path):
        assert path == output
        assert not index.exists(), "index is no longer needed after extraction"
        if write_fails:
            raise OSError("output write failed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"saved POIs")

    monkeypatch.setattr(osm_prepare, "extract_national_osm_pois", fake_extract)
    monkeypatch.setattr(osm_prepare, "_atomic_parquet", fake_save)

    def run():
        return osm_prepare._prepare_national_stage(
            directory=output.parent,
            state={},
            cache_base=tmp_path / "sources",
            pbf_file=tmp_path / "philippines.osm.pbf",
            progress=None,
        )
    if write_fails:
        with pytest.raises(OSError, match="output write failed"):
            run()
        assert not index.exists()  # Failed saves must not retain huge indexes.
    else:
        assert run() == ["POI"]
        assert output.exists()
        assert not index.exists()


@pytest.mark.parametrize("write_fails", [False, True])
def test_road_node_index_is_removed_after_extraction(tmp_path, monkeypatch, write_fails):
    ref = SimpleNamespace(sha256="test-sha256", path=tmp_path / "source.pbf", source_id="osm")
    index = tmp_path / "geofabrik" / "road-node-index" / "test-sha256.nodes.cache"
    output = tmp_path / "roads.json"

    class FakeRoads:
        crs = "EPSG:32651"
        geometry = SimpleNamespace(
            geom_type=SimpleNamespace(astype=lambda dtype: ["LineString"])
        )

        def __len__(self):
            return 1

    def fake_load(self, pbf_path, *, area, boundary, node_cache, progress):
        assert node_cache == index
        node_cache.parent.mkdir(parents=True, exist_ok=True)
        node_cache.write_bytes(b"temporary index")
        return FakeRoads()

    def fake_save(roads, path):
        assert path == output
        assert not index.exists(), "index is no longer needed after extraction"
        if write_fails:
            raise OSError("output write failed")
        path.write_text("saved roads", encoding="utf-8")

    monkeypatch.setattr(GeofabrikRoadSource, "load", fake_load)
    monkeypatch.setattr(GeofabrikRoadSource, "recipe_parameters", lambda self, area, boundary: {})
    monkeypatch.setattr(spatial_pipeline, "write_geoframe", fake_save)

    stage = SimpleNamespace(
        roads=GeofabrikRoadSource(),
        place_pipeline=SimpleNamespace(area="pasig"),
        workspace=SimpleNamespace(
            sources=SimpleNamespace(root=tmp_path, validate=lambda ref: SimpleNamespace(valid=True))
        ),
        _source_ref_from_artifact=lambda planner, source: ref,
        _boundary_from_artifact=lambda boundary: "boundary",
        progress=None,
    )
    deps = {"source.geofabrik_pbf": object(), "area.boundary": object()}
    write = SimpleNamespace(output=lambda name: tmp_path / name)
    def run():
        return spatial_pipeline.SpatialPipeline._exec_roads(stage, None, None, deps, write)

    if write_fails:
        with pytest.raises(OSError, match="output write failed"):
            run()
        assert not index.exists()
    else:
        metadata, _ = run()
        assert metadata["rows"] == 1
        assert output.exists()
        assert not index.exists()

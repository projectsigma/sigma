from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sigma.errors import SourceError
from sigma.places.overture import OVERTURE_NORMALIZATION_VERSION
from sigma.sources import SourceStore
from sigma.sources.cache import write_cache_identity


def _write_policy_marker(path: Path, bbox, *, raw=10, accepted=8):
    path.with_suffix(path.suffix + ".overture.json").write_text(
        json.dumps(
            {
                "normalization_version": OVERTURE_NORMALIZATION_VERSION,
                "bbox": [float(v) for v in bbox],
                "raw_rows": raw,
                "accepted_rows": accepted,
            }
        ),
        encoding="utf-8",
    )


def test_user_file_identity_is_content_addressed_and_selector_sensitive(tmp_path):
    source = tmp_path / "roads.gpkg"
    source.write_bytes(b"roads-v1")
    store = SourceStore(tmp_path / "store")

    first = store.register_user_file(source, layer="roads")
    again = store.register_user_file(source, layer="roads")
    other_layer = store.register_user_file(source, layer="roads_alt")

    assert first.source_id == again.source_id
    assert first.sha256 == hashlib.sha256(b"roads-v1").hexdigest()
    assert first.source_id != other_layer.source_id
    assert store.validate(first).valid
    assert not first.managed


def test_changed_external_source_invalidates_old_ref_and_gets_new_identity(tmp_path):
    source = tmp_path / "points.parquet"
    source.write_bytes(b"points-v1")
    store = SourceStore(tmp_path / "store")
    old = store.register_user_file(source)

    source.write_bytes(b"points-version-two")
    validation = store.validate(old)
    assert not validation.valid
    assert validation.reason in {"size_changed", "hash_mismatch"}

    new = store.register_user_file(source)
    assert new.source_id != old.source_id
    assert store.validate(new).valid


def test_packaged_reference_can_be_a_directory_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "a.csv").write_text("a\n1\n", encoding="utf-8")
    (bundle / "b.yml").write_text("x: 1\n", encoding="utf-8")
    store = SourceStore(tmp_path / "store")

    ref = store.register_packaged_reference("fixture-bundle", bundle, version="1")
    assert ref.is_directory
    assert ref.size == (bundle / "a.csv").stat().st_size + (bundle / "b.yml").stat().st_size
    assert store.validate(ref).valid
    assert len(ref.metadata["members"]) == 2


def test_legacy_geofabrik_adoption_records_hash_without_mutating_bytes(tmp_path):
    cache = tmp_path / ".sigma-cache"
    geofabrik = cache / "geofabrik"
    geofabrik.mkdir(parents=True)
    pbf = geofabrik / "philippines-latest.osm.pbf"
    payload = b"fake-pbf-bytes"
    pbf.write_bytes(payload)
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    (geofabrik / "philippines-latest.meta.json").write_text(
        json.dumps(
            {
                "source_version": "261003",
                "source_date": "2026-10-03T00:00:00+00:00",
                "source_url": "https://download.geofabrik.de/asia/philippines-261003.osm.pbf",
                "md5": md5,
                "md5_verified": True,
            }
        ),
        encoding="utf-8",
    )
    before = pbf.read_bytes()

    store = SourceStore(tmp_path / "source-store")
    ref = store.adopt_legacy_geofabrik(cache)

    assert pbf.read_bytes() == before
    assert ref.path == pbf.resolve()
    assert not ref.managed
    assert ref.version == "261003"
    assert ref.sha256 == hashlib.sha256(payload).hexdigest()
    assert store.current_geofabrik().source_id == ref.source_id
    assert store.validate(ref).valid


def test_legacy_geofabrik_adoption_rejects_bad_recorded_md5(tmp_path):
    cache = tmp_path / ".sigma-cache"
    geofabrik = cache / "geofabrik"
    geofabrik.mkdir(parents=True)
    (geofabrik / "philippines-latest.osm.pbf").write_bytes(b"bad")
    (geofabrik / "philippines-latest.meta.json").write_text(
        json.dumps({"source_version": "261003", "md5": "0" * 32}),
        encoding="utf-8",
    )
    store = SourceStore(tmp_path / "source-store")
    with pytest.raises(SourceError, match="MD5"):
        store.adopt_legacy_geofabrik(cache)


def test_repeated_geofabrik_consumers_resolve_same_canonical_snapshot(tmp_path):
    store = SourceStore(tmp_path / "source-store")
    calls = []

    def fake_downloader(cache_root, *, refresh, progress=None):
        calls.append((Path(cache_root), refresh))
        directory = Path(cache_root) / "geofabrik"
        directory.mkdir(parents=True, exist_ok=True)
        pbf = directory / "philippines-latest.osm.pbf"
        pbf.write_bytes(b"snapshot-one")
        (directory / "philippines-latest.meta.json").write_text(
            json.dumps(
                {
                    "source_version": "261003",
                    "source_date": "2026-10-03T00:00:00+00:00",
                    "source_url": "https://example.test/philippines-261003.osm.pbf",
                    "content_length": len(b"snapshot-one"),
                }
            ),
            encoding="utf-8",
        )
        return pbf

    first = store.ensure_geofabrik(downloader=fake_downloader)
    second = store.ensure_geofabrik(downloader=fake_downloader)

    assert len(calls) == 1
    assert first.source_id == second.source_id
    assert first.path == second.path
    assert first.managed
    assert first.path.parent.parent == store.root / "geofabrik" / "philippines"


def test_geofabrik_refresh_promotes_new_immutable_snapshot(tmp_path):
    store = SourceStore(tmp_path / "source-store")
    counter = {"n": 0}

    def fake_downloader(cache_root, *, refresh, progress=None):
        counter["n"] += 1
        version = f"26100{counter['n']}"
        payload = f"snapshot-{counter['n']}".encode()
        directory = Path(cache_root) / "geofabrik"
        directory.mkdir(parents=True, exist_ok=True)
        pbf = directory / "philippines-latest.osm.pbf"
        pbf.write_bytes(payload)
        (directory / "philippines-latest.meta.json").write_text(
            json.dumps({"source_version": version, "content_length": len(payload)}),
            encoding="utf-8",
        )
        return pbf

    old = store.ensure_geofabrik(downloader=fake_downloader)
    new = store.ensure_geofabrik(refresh=True, downloader=fake_downloader)

    assert old.source_id != new.source_id
    assert old.path.exists()
    assert new.path.exists()
    assert old.path != new.path
    assert store.current_geofabrik().source_id == new.source_id


def test_overture_snapshot_requires_compatible_sidecars_and_is_query_addressable(tmp_path):
    bbox = (120.0, 14.0, 121.0, 15.0)
    cache = tmp_path / "overture.parquet"
    cache.write_bytes(b"normalized-overture")
    write_cache_identity(cache, bbox)
    _write_policy_marker(cache, bbox)
    store = SourceStore(tmp_path / "store")

    ref = store.register_overture_snapshot(cache, bbox=bbox)
    assert ref.selection["bbox"] == list(bbox)
    assert ref.metadata["normalization_version"] == OVERTURE_NORMALIZATION_VERSION
    assert store.current_overture(bbox).source_id == ref.source_id
    assert store.validate(ref).valid


def test_overture_snapshot_rejects_wrong_policy_bbox(tmp_path):
    bbox = (120.0, 14.0, 121.0, 15.0)
    cache = tmp_path / "overture.parquet"
    cache.write_bytes(b"normalized-overture")
    write_cache_identity(cache, bbox)
    _write_policy_marker(cache, (120.0, 14.0, 121.1, 15.0))
    store = SourceStore(tmp_path / "store")
    with pytest.raises(SourceError, match="bbox"):
        store.register_overture_snapshot(cache, bbox=bbox)


def test_fetch_overture_snapshot_reuses_current_snapshot(tmp_path):
    bbox = (120.0, 14.0, 121.0, 15.0)
    store = SourceStore(tmp_path / "store")
    calls = []

    def fake_fetcher(value, cache_file, *, refresh, progress=None):
        calls.append((value, refresh))
        cache_file.write_bytes(b"query-result")
        write_cache_identity(cache_file, value)
        _write_policy_marker(cache_file, value, raw=5, accepted=4)
        return object()

    first = store.fetch_overture_snapshot(bbox, fetcher=fake_fetcher)
    second = store.fetch_overture_snapshot(bbox, fetcher=fake_fetcher)
    assert len(calls) == 1
    assert first.source_id == second.source_id
    assert first.path == second.path
    assert first.managed
    assert first.path.with_suffix(first.path.suffix + ".meta.json").exists()
    assert first.path.with_suffix(first.path.suffix + ".overture.json").exists()


def test_adopt_legacy_cache_discovers_geofabrik_overture_and_prepared_state(tmp_path):
    cache = tmp_path / ".sigma-cache"
    geofabrik = cache / "geofabrik"
    geofabrik.mkdir(parents=True)
    pbf = geofabrik / "philippines-latest.osm.pbf"
    pbf.write_bytes(b"pbf")
    md5 = hashlib.md5(b"pbf", usedforsecurity=False).hexdigest()
    (geofabrik / "philippines-latest.meta.json").write_text(
        json.dumps({"source_version": "261003", "md5": md5}), encoding="utf-8"
    )

    prepared = geofabrik / "prepared" / "261003"
    (prepared / "areas").mkdir(parents=True)
    (prepared / "national-pois.parquet").write_bytes(b"placeholder")
    (prepared / "manifest.json").write_text(
        json.dumps({"status": "complete", "source_version": "261003"}), encoding="utf-8"
    )
    (prepared / "state.json").write_text(
        json.dumps({"status": "complete", "source_version": "261003"}), encoding="utf-8"
    )
    (geofabrik / "prepared" / "current.json").write_text(
        json.dumps({"source_version": "261003"}), encoding="utf-8"
    )

    area = cache / "quezon_city"
    area.mkdir()
    ov = area / "overture.parquet"
    bbox = (120.9, 14.5, 121.1, 14.8)
    ov.write_bytes(b"overture")
    write_cache_identity(ov, bbox)
    _write_policy_marker(ov, bbox)

    store = SourceStore(tmp_path / "store")
    adopted = store.adopt_legacy_cache(cache)
    assert adopted.geofabrik is not None
    assert len(adopted.overture) == 1
    assert adopted.prepared_osm is not None
    assert adopted.prepared_osm["source_version"] == "261003"
    assert adopted.prepared_osm["structurally_complete"] is True
    assert (store.root / "legacy-cache-adoption.json").exists()


def test_builtin_reference_bundles_are_registered_and_valid(tmp_path):
    store = SourceStore(tmp_path / "store")
    refs = store.register_builtin_references()
    assert set(refs) == {
        "areas",
        "classification",
        "economy-io80",
        "economy-io16",
        "tagging-compatibility",
    }
    assert all(ref.is_directory for ref in refs.values())
    assert all(store.validate(ref).valid for ref in refs.values())
    assert all(
        not str(member["path"]).endswith((".py", ".pyc"))
        for ref in refs.values()
        for member in ref.metadata.get("members", [])
    )


def test_shared_osm_preparation_wrapper_reuses_same_cache_root(tmp_path):
    store = SourceStore(tmp_path / "store")
    pbf = tmp_path / "legacy" / "geofabrik" / "philippines-latest.osm.pbf"
    pbf.parent.mkdir(parents=True)
    pbf.write_bytes(b"pbf")
    md5 = hashlib.md5(b"pbf", usedforsecurity=False).hexdigest()
    (pbf.parent / "philippines-latest.meta.json").write_text(
        json.dumps({"source_version": "261003", "md5": md5}), encoding="utf-8"
    )
    ref = store.adopt_legacy_geofabrik(tmp_path / "legacy")
    calls = []

    def fake_loader(*, cache_base, pbf_file, area_slug, areas_file, progress):
        calls.append((Path(cache_base), Path(pbf_file), area_slug))
        return f"frame:{area_slug}", "261003", False

    first = store.load_prepared_osm_area(ref, area_slug="quezon_city", loader=fake_loader)
    second = store.load_prepared_osm_area(ref, area_slug="pasig", loader=fake_loader)

    assert first == ("frame:quezon_city", "261003", False)
    assert second == ("frame:pasig", "261003", False)
    assert calls[0][0] == calls[1][0] == store.prepared_osm_cache_root
    assert calls[0][1] == calls[1][1] == ref.path
    metadata = json.loads(
        (store.prepared_osm_cache_root / "geofabrik" / "philippines-latest.meta.json").read_text()
    )
    assert metadata["source_id"] == ref.source_id
    assert metadata["sha256"] == ref.sha256


def test_adopted_prepared_osm_cache_is_reused_by_wrapper(tmp_path):
    cache = tmp_path / ".sigma-cache"
    geofabrik = cache / "geofabrik"
    geofabrik.mkdir(parents=True)
    pbf = geofabrik / "philippines-latest.osm.pbf"
    pbf.write_bytes(b"pbf")
    md5 = hashlib.md5(b"pbf", usedforsecurity=False).hexdigest()
    (geofabrik / "philippines-latest.meta.json").write_text(
        json.dumps({"source_version": "261003", "md5": md5}), encoding="utf-8"
    )
    prepared = geofabrik / "prepared" / "261003"
    (prepared / "areas").mkdir(parents=True)
    (prepared / "national-pois.parquet").write_bytes(b"placeholder")
    (prepared / "manifest.json").write_text(
        json.dumps({"status": "complete", "source_version": "261003"}), encoding="utf-8"
    )
    (geofabrik / "prepared" / "current.json").write_text(
        json.dumps({"source_version": "261003"}), encoding="utf-8"
    )

    store = SourceStore(tmp_path / "store")
    adoption = store.adopt_legacy_cache(cache)
    assert adoption.geofabrik is not None
    seen = {}

    def fake_loader(*, cache_base, pbf_file, area_slug, areas_file, progress):
        seen["cache_base"] = Path(cache_base)
        seen["pbf_file"] = Path(pbf_file)
        return "frame", "261003", False

    store.load_prepared_osm_area(
        adoption.geofabrik,
        area_slug="quezon_city",
        loader=fake_loader,
    )
    assert seen["cache_base"] == cache.resolve()
    assert seen["pbf_file"] == pbf.resolve()


def test_managed_geofabrik_pbf_is_content_hashed_once_on_promotion(tmp_path, monkeypatch):
    import sigma.sources.store as store_module

    original = store_module._file_sha256
    hashed = []

    def counting_hash(path):
        hashed.append(Path(path).name)
        return original(Path(path))

    monkeypatch.setattr(store_module, "_file_sha256", counting_hash)
    store = SourceStore(tmp_path / "store")

    def fake_downloader(cache_root, *, refresh, progress=None):
        directory = Path(cache_root) / "geofabrik"
        directory.mkdir(parents=True, exist_ok=True)
        pbf = directory / "philippines-latest.osm.pbf"
        pbf.write_bytes(b"large-source-placeholder")
        (directory / "philippines-latest.meta.json").write_text(
            json.dumps({"source_version": "261003"}), encoding="utf-8"
        )
        return pbf

    store.ensure_geofabrik(downloader=fake_downloader)
    assert hashed.count("philippines-latest.osm.pbf") == 1
    assert "philippines.osm.pbf" not in hashed


def test_sigma_home_selects_default_shared_source_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_HOME", str(tmp_path / "sigma-home"))
    store = SourceStore()
    assert store.root == (tmp_path / "sigma-home" / "sources").resolve()

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import yaml
from shapely.geometry import box

from sigma import Area, AreaCatalog, BoundaryResolver, BoundarySpec
from sigma.area.boundary import materialize_area_boundary as materialize_canonical_boundary


ROOT = Path(__file__).resolve().parents[3]


def test_public_area_surface_is_canonical() -> None:
    catalog = AreaCatalog()
    area = catalog.resolve("1381300000")
    assert isinstance(area, Area)
    assert area.slug == "quezon_city"
    assert area.boundary is not None
    assert area.boundary.layer == "areas"
    assert area.boundary.field == "psgc_code"
    assert area.boundary.value == "1381300000"


def test_packaged_area_resources_are_byte_preserved() -> None:
    source_hashes = {
        "areas.yml": "659af513e79bf305acafcb39332eac8459d0a48eb61a81c0008c590cb90427d7",
        "areas.gpkg": "3b6b7de34445bd761185b3fddf4cf9dac89c8f5032e4ee9861a902bf260ef5fc",
    }
    catalog = AreaCatalog()
    identity = catalog.identity()
    assert identity["catalog_sha256"] == source_hashes["areas.yml"]
    assert len(identity["boundaries"]) == 1
    assert identity["boundaries"][0]["sha256"] == source_hashes["areas.gpkg"]


def test_c0_quezon_city_boundary_identity_is_exact() -> None:
    golden = json.loads(
        (ROOT / "tests/golden/siphon/area_boundary_fixture.json").read_text(encoding="utf-8")
    )
    area = AreaCatalog().resolve(golden["fixture"]["query"])
    geometry = BoundaryResolver().load(area)
    identity = BoundaryResolver().identity(area, geometry)
    assert area.slug == golden["fixture"]["slug"]
    assert area.psgc_code == golden["fixture"]["psgc_code"]
    assert list(geometry.bounds) == golden["fixture"]["geometry_bounds"]
    assert identity["geometry_sha256"] == golden["fixture"]["boundary_identity"]["geometry_sha256"]
    assert identity["fingerprint"] == golden["fixture"]["boundary_identity"]["fingerprint"]


def test_custom_catalog_uses_canonical_parser_and_materializer(tmp_path: Path) -> None:
    data = tmp_path / "data" / "boundaries"
    data.mkdir(parents=True)
    gpkg = data / "areas.gpkg"
    gpd.GeoDataFrame(
        {"psgc_code": ["0123456789", "9999999999"]},
        geometry=[box(0, 0, 1, 1), box(10, 10, 11, 11)],
        crs="EPSG:4326",
    ).to_file(gpkg, layer="areas", driver="GPKG")
    config = tmp_path / "config"
    config.mkdir()
    areas_file = config / "areas.yml"
    areas_file.write_text(
        yaml.safe_dump(
            {
                "areas": {
                    "sample": {
                        "name": "Sample",
                        "kind": "city",
                        "aliases": ["0123456789"],
                        "bbox": [0, 0, 1, 1],
                        "boundary": {
                            "gpkg": "../data/boundaries/areas.gpkg",
                            "layer": "areas",
                            "field": "psgc_code",
                            "value": "0123456789",
                        },
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    area = AreaCatalog(areas_file).resolve("0123456789")
    assert area.slug == "sample"
    assert area.boundary is not None
    assert area.boundary.value == "0123456789"
    boundary_path = materialize_canonical_boundary(area, tmp_path / "selected.gpkg")
    selected = gpd.read_file(boundary_path, layer="boundary")
    assert len(selected) == 1
    assert selected.loc[0, "area_slug"] == "sample"
    assert selected.crs.to_string() == "EPSG:4326"
    assert selected.geometry.iloc[0].equals(box(0, 0, 1, 1))


def test_canonical_materialization_uses_canonical_geometry_for_bbox(tmp_path: Path) -> None:
    area = Area("bbox", "BBox", "custom", (120.0, 14.0, 121.0, 15.0))
    resolver = BoundaryResolver()
    expected = resolver.load(area)
    output = resolver.materialize(area, tmp_path / "bbox.gpkg")
    actual = gpd.read_file(output, layer="boundary").geometry.iloc[0]
    assert actual.equals(expected)


def test_catalog_list_wrapper_does_not_reparse_or_redefine_area_identity() -> None:
    catalog = AreaCatalog()
    matches = catalog.list(kind="city", search="Quezon")
    assert any(area.slug == "quezon_city" for area in matches)
    assert all(area.kind == "city" for area in matches)


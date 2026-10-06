import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from sigma.area.catalog import Area, BoundarySpec
from sigma.area.boundary import boundary_identity, clip_points, load_boundary


def test_bbox_is_default_boundary():
    area = Area("x", "X", "test", (120.0, 14.0, 121.0, 15.0))
    boundary = load_boundary(area)
    frame = gpd.GeoDataFrame(
        pd.DataFrame({"name": ["in", "out"]}),
        geometry=[Point(120.5, 14.5), Point(122.0, 14.5)],
        crs="EPSG:4326",
    )
    clipped = clip_points(frame, boundary)
    assert clipped["name"].tolist() == ["in"]


def test_boundary_identity_is_content_addressed(tmp_path):
    gpkg = tmp_path / "areas.gpkg"
    frame = gpd.GeoDataFrame(
        {"psgc_code": ["0000000001"]},
        geometry=[box(120.0, 14.0, 121.0, 15.0)],
        crs="EPSG:4326",
    )
    frame.to_file(gpkg, layer="areas", driver="GPKG")
    area = Area(
        "x",
        "X",
        "city",
        (120.0, 14.0, 121.0, 15.0),
        boundary=BoundarySpec(
            gpkg=gpkg,
            layer="areas",
            field="psgc_code",
            value="0000000001",
        ),
    )
    identity = boundary_identity(area)
    assert identity["mode"] == "gpkg"
    assert identity["values"] == ["0000000001"]
    assert len(str(identity["geometry_sha256"])) == 64
    assert len(str(identity["fingerprint"])) == 64


def test_boundary_read_is_spatially_prefiltered(monkeypatch, tmp_path):
    gpkg = tmp_path / "areas.gpkg"
    frame = gpd.GeoDataFrame(
        {"psgc_code": ["0000000001", "0000000002"]},
        geometry=[
            box(120.0, 14.0, 120.5, 14.5),
            box(125.0, 10.0, 126.0, 11.0),
        ],
        crs="EPSG:4326",
    )
    frame.to_file(gpkg, layer="areas", driver="GPKG")
    area = Area(
        "x",
        "X",
        "city",
        (120.0, 14.0, 120.5, 14.5),
        boundary=BoundarySpec(
            gpkg=gpkg,
            layer="areas",
            field="psgc_code",
            value="0000000001",
        ),
    )
    original = gpd.read_file
    seen = {}

    def wrapped(*args, **kwargs):
        seen.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(gpd, "read_file", wrapped)
    geometry = load_boundary(area)
    assert geometry.bounds == (120.0, 14.0, 120.5, 14.5)
    assert seen["bbox"] == area.bbox


def test_composite_boundary_unions_multiple_psgc_rows(tmp_path):
    gpkg = tmp_path / "areas.gpkg"
    frame = gpd.GeoDataFrame(
        {"psgc_code": ["0000000001", "0000000002"]},
        geometry=[box(120.0, 14.0, 120.5, 14.5), box(120.5, 14.0, 121.0, 14.5)],
        crs="EPSG:4326",
    )
    frame.to_file(gpkg, layer="areas", driver="GPKG")
    area = Area(
        "metro_test",
        "Metro Test",
        "composite",
        (120.0, 14.0, 121.0, 14.5),
        members=("0000000001", "0000000002"),
        boundary=BoundarySpec(
            gpkg=gpkg,
            layer="areas",
            field="psgc_code",
            value=("0000000001", "0000000002"),
        ),
    )
    geometry = load_boundary(area)
    assert geometry.bounds == (120.0, 14.0, 121.0, 14.5)

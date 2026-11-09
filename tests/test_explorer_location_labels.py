
"""Source-backed administrative and named-road labels are presentation-only."""
from types import SimpleNamespace

import geopandas as gpd
from shapely.geometry import LineString

from sigma.web.builder import _context_label_features


def test_catalog_towns_and_named_roads(monkeypatch, tmp_path):
    import sigma.area.catalog as catalog
    import sigma.paths as paths

    city = SimpleNamespace(kind="city", name="Example City", psgc_code="1234567890",
                           bbox=(120.97, 14.47, 121.04, 14.56), boundary=None)
    monkeypatch.setattr(catalog, "load_areas", lambda: {"example_city": city})
    monkeypatch.setattr(paths, "initialization_path", lambda: tmp_path / "no-pbf.json")
    roads = gpd.GeoDataFrame({
        "name": ["Example Avenue", None, "Outside Road"],
        "highway": ["primary", "primary", "secondary"],
    }, geometry=[LineString([(120.99, 14.50), (121.01, 14.50)]),
                 LineString([(121.01, 14.51), (121.02, 14.52)]),
                 LineString([(124.00, 14.50), (124.01, 14.50)])], crs="EPSG:4326")
    features = _context_label_features((120.95, 14.45, 121.05, 14.58), roads)
    observed = [(f["properties"]["kind"], f["properties"]["name"]) for f in features]
    assert ("town", "Example City") in observed
    assert ("road", "Example Avenue") in observed
    assert not any(name == "Outside Road" for _, name in observed)
    assert not any(name == "None" for _, name in observed)
    assert all(f["geometry"]["type"] == "Point" for f in features)
    assert all(120.95 <= f["geometry"]["coordinates"][0] <= 121.05 for f in features)


def test_missing_road_metadata_does_not_fabricate_names(monkeypatch, tmp_path):
    import sigma.area.catalog as catalog
    import sigma.paths as paths
    monkeypatch.setattr(catalog, "load_areas", lambda: {})
    monkeypatch.setattr(paths, "initialization_path", lambda: tmp_path / "no-pbf.json")
    roads = gpd.GeoDataFrame(geometry=[LineString([(121, 14), (121.1, 14.1)])], crs="EPSG:4326")
    assert _context_label_features((120.9, 13.9, 121.2, 14.2), roads) == []


def test_polygon_interior_point_is_used_even_when_first_town_has_no_boundary(monkeypatch, tmp_path):
    import sigma.area.catalog as catalog
    import sigma.paths as paths
    from shapely.geometry import box

    gpkg = tmp_path / "areas.gpkg"
    gpd.GeoDataFrame({"psgc_code": ["0100101000"]},
        geometry=[box(120.96, 14.50, 120.98, 14.52)], crs="EPSG:4326"
    ).to_file(gpkg, layer="areas", driver="GPKG")
    no_boundary = SimpleNamespace(kind="city", name="Other Town", psgc_code="2222222222",
        bbox=(120.97, 14.53, 121.01, 14.57), boundary=None)
    boundary = SimpleNamespace(gpkg=gpkg, layer="areas", field="psgc_code", value="0100101000")
    target = SimpleNamespace(kind="municipality", name="Polygon Town", psgc_code="0100101000",
        bbox=(120.95, 14.48, 121.05, 14.58), boundary=boundary)
    monkeypatch.setattr(catalog, "load_areas", lambda: {"other": no_boundary, "polygon": target})
    monkeypatch.setattr(paths, "initialization_path", lambda: tmp_path / "no-pbf.json")
    features = _context_label_features((120.94, 14.47, 121.06, 14.59), None)
    polygon = next(f for f in features if f["properties"]["name"] == "Polygon Town")
    lon, lat = polygon["geometry"]["coordinates"]
    assert 120.96 <= lon <= 120.98
    assert 14.50 <= lat <= 14.52

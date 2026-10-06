from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

import geopandas as gpd
from shapely.geometry import LineString, Point

from sigma.economy.model import Sector, SectorCatalog
from sigma.export.qgis import WGS84, annotate_types, as_wgs84, build_sector_styles, write_qgis_project


def _catalog() -> SectorCatalog:
    return SectorCatalog(Sector(str(i), f"Catalog label {i}") for i in range(1, 81))


def test_canonical_io80_palette_is_fixed_unique_and_uses_requested_labels():
    styles = build_sector_styles(_catalog())
    assert len(styles) == 80
    assert len({style.color_hex for style in styles.values()}) == 80
    assert styles["1"].color_hex == "#A0BF43"
    assert styles["1"].display == "01 - Palay"
    assert styles["21"].color_hex == "#262626"
    assert styles["35"].color_hex == "#00B4EC"
    assert styles["53"].color_hex == "#EE7815"
    assert styles["53"].display == "53 - Construction"
    assert styles["80"].color_hex == "#77697B"
    assert styles["80"].display == "80 - Other services"


def test_as_wgs84_reprojects_export_copy_without_mutating_input():
    original = gpd.GeoDataFrame(
        {"id": [1]}, geometry=[Point(13500000, 1600000)], crs="EPSG:3857"
    )
    exported = as_wgs84(original)
    assert str(exported.crs).upper() == WGS84
    assert str(original.crs).upper() == "EPSG:3857"




def test_as_wgs84_reprojects_secondary_geometry_columns():
    original = gpd.GeoDataFrame(
        {
            "id": [1],
            "network_position": gpd.GeoSeries([Point(13501000, 1600000)], crs="EPSG:3857"),
        },
        geometry=[Point(13500000, 1600000)],
        crs="EPSG:3857",
    )
    exported = as_wgs84(original)
    assert str(exported.crs).upper() == WGS84
    assert str(exported["network_position"].crs).upper() == WGS84
    assert -180 <= float(exported.geometry.x.iloc[0]) <= 180
    assert -180 <= float(exported["network_position"].x.iloc[0]) <= 180
    assert str(original.crs).upper() == "EPSG:3857"
    assert str(original["network_position"].crs).upper() == "EPSG:3857"


def test_write_qgis_project_uses_wgs84_fixed_palette_labels_and_requested_order(tmp_path):
    styles = build_sector_styles(_catalog())
    types = ["1", "53"]

    boundary = gpd.GeoDataFrame(
        {"area_slug": ["fixture"], "area_name": ["Fixture City"]},
        geometry=[Point(13500000, 1600000).buffer(5000)],
        crs="EPSG:3857",
    )
    roads = gpd.GeoDataFrame(
        {"road_id": [1]},
        geometry=[LineString([(13495000, 1600000), (13505000, 1600000)])],
        crs="EPSG:3857",
    )
    partitions = annotate_types(
        gpd.GeoDataFrame(
            {"type": types, "cluster": [0, 0]},
            geometry=[Point(13499000, 1600000).buffer(1000), Point(13502000, 1600000).buffer(1000)],
            crs="EPSG:3857",
        ),
        styles,
    )
    centers = annotate_types(
        gpd.GeoDataFrame(
            {"type": types, "cluster": [0, 0]},
            geometry=[Point(13499000, 1600000), Point(13502000, 1600000)],
            crs="EPSG:3857",
        ),
        styles,
    )
    scores = annotate_types(
        gpd.GeoDataFrame(
            {
                "type": types,
                "cluster": [0, 0],
                "sigma_score": [0.25, 0.75],
                "canonical_name": ["Rice Shop", "Builder"],
            },
            geometry=[Point(13499000, 1600000), Point(13502000, 1600000)],
            crs="EPSG:3857",
        ),
        styles,
    )

    target = tmp_path / "fixture.qgz"
    write_qgis_project(
        target,
        area_name="Fixture City",
        area_slug="fixture",
        boundary=boundary,
        roads=roads,
        partitions=partitions,
        centers=centers,
        points=scores,
        styles=styles,
    )

    with zipfile.ZipFile(target) as archive:
        root = ET.fromstring(archive.read("fixture.qgs"))

    assert root.attrib["version"] == "3.44.6-Solothurn"
    assert root.findtext("projectCrs/spatialrefsys/authid") == WGS84
    project_srs = root.find("projectCrs/spatialrefsys")
    assert project_srs is not None
    assert project_srs.attrib["nativeFormat"] == "Wkt"
    assert project_srs.findtext("srid") == "4326"
    assert project_srs.findtext("srsid") == "3452"
    assert project_srs.findtext("wkt").startswith('GEOGCRS["WGS 84",ENSEMBLE[')

    canvas = root.find("mapcanvas[@name='theMapCanvas']")
    assert canvas is not None
    assert canvas.findtext("units") == "degrees"
    assert canvas.findtext("destinationsrs/spatialrefsys/authid") == WGS84
    assert canvas.findtext("destinationsrs/spatialrefsys/srid") == "4326"
    assert canvas.findtext("destinationsrs/spatialrefsys/srsid") == "3452"
    assert canvas.findtext("destinationsrs/spatialrefsys/wkt").startswith(
        'GEOGCRS["WGS 84",ENSEMBLE['
    )
    canvas_extent = canvas.find("extent")
    assert canvas_extent is not None
    canvas_bounds = tuple(float(canvas_extent.findtext(tag)) for tag in ("xmin", "ymin", "xmax", "ymax"))
    expected_bounds = tuple(float(value) for value in as_wgs84(boundary).total_bounds)
    assert all(abs(actual - expected) < 1e-9 for actual, expected in zip(canvas_bounds, expected_bounds))
    for layer in root.findall(".//projectlayers/maplayer"):
        layer_srs = layer.find("srs/spatialrefsys")
        assert layer_srs is not None
        assert layer_srs.attrib["nativeFormat"] == "Wkt"
        assert layer_srs.findtext("authid") == WGS84
        assert layer_srs.findtext("srid") == "4326"
        assert layer_srs.findtext("wkt").startswith('GEOGCRS["WGS 84",ENSEMBLE[')

    tree = root.find("layer-tree-group")
    assert tree is not None
    visible_order = [child.attrib.get("name") for child in list(tree) if child.tag.startswith("layer-tree")]
    assert visible_order == [
        "sigma_points",
        "Partitions",
        "sigma_network_centers",
        "sigma_roads",
        "sigma_boundary",
    ]
    partitions_group = next(child for child in tree if child.tag == "layer-tree-group")
    assert [child.attrib["name"] for child in partitions_group.findall("layer-tree-layer")] == [
        "01 - Palay",
        "53 - Construction",
    ]

    points = next(layer for layer in root.findall(".//projectlayers/maplayer") if layer.findtext("layername") == "sigma_points")
    text_style = points.find("labeling/settings/text-style")
    assert text_style is not None
    assert text_style.attrib["isExpression"] == "1"
    assert text_style.attrib["fieldName"] == 'concat("canonical_name", \'-\', round(100 * "sigma_score", 2))'
    categories = points.find("renderer-v2/categories")
    assert categories is not None
    labels = [category.attrib["label"] for category in categories.findall("category")]
    assert labels == ["01 - Palay", "53 - Construction"]
    colors = []
    for symbol in points.findall("renderer-v2/symbols/symbol"):
        assert symbol.attrib["alpha"] == "0.5"
        option = symbol.find("layer/Option/Option[@name='color']")
        assert option is not None
        colors.append(option.attrib["value"])
    assert colors[0].startswith("160,191,67,255")  # #A0BF43
    assert colors[1].startswith("238,120,21,255")  # #EE7815

    partition_layers = [
        layer for layer in root.findall(".//projectlayers/maplayer")
        if (layer.findtext("datasource") or "").startswith("./sigma_partitions.parquet")
    ]
    assert [layer.findtext("layername") for layer in partition_layers] == ["01 - Palay", "53 - Construction"]
    for layer in partition_layers:
        symbol = layer.find("renderer-v2/symbols/symbol")
        assert symbol is not None and symbol.attrib["alpha"] == "1"

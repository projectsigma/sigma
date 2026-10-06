"""QGIS project generation for SIGMA export bundles."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import uuid
import zipfile
import xml.etree.ElementTree as ET

import geopandas as gpd
from geopandas.array import GeometryDtype
import pandas as pd

from sigma.economy.model import SectorCatalog


_RESOURCE_INDUSTRIES = Path(__file__).resolve().parents[1] / "resources" / "tagging" / "compatibility" / "industries.csv"
WGS84 = "EPSG:4326"
_WGS84_WKT = (
    'GEOGCRS["WGS 84",ENSEMBLE["World Geodetic System 1984 ensemble",'
    'MEMBER["World Geodetic System 1984 (Transit)"],MEMBER["World Geodetic System 1984 (G730)"],'
    'MEMBER["World Geodetic System 1984 (G873)"],MEMBER["World Geodetic System 1984 (G1150)"],'
    'MEMBER["World Geodetic System 1984 (G1674)"],MEMBER["World Geodetic System 1984 (G1762)"],'
    'MEMBER["World Geodetic System 1984 (G2139)"],MEMBER["World Geodetic System 1984 (G2296)"],'
    'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]],ENSEMBLEACCURACY[2.0]],'
    'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],CS[ellipsoidal,2],'
    'AXIS["geodetic latitude (Lat)",north,ORDER[1],ANGLEUNIT["degree",0.0174532925199433]],'
    'AXIS["geodetic longitude (Lon)",east,ORDER[2],ANGLEUNIT["degree",0.0174532925199433]],'
    'USAGE[SCOPE["Horizontal component of 3D system."],AREA["World."],BBOX[-90,-180,90,180]],'
    'ID["EPSG",4326]]'
)


@dataclass(frozen=True, slots=True)
class SectorStyle:
    code: str
    label: str
    display: str
    family: str
    color_hex: str


# Canonical PSA 2018 IO80 presentation palette supplied for SIGMA mapping.
# Codes 1-80 are intentionally unique and stable; do not auto-generate or rotate them.
_IO80_PRESENTATION: dict[int, tuple[str, str]] = {
    1: ("#A0BF43", "Palay"),
    2: ("#E7AD00", "Corn"),
    3: ("#935802", "Coconut incl. copra"),
    4: ("#ABE79C", "Sugarcane"),
    5: ("#FCED64", "Banana"),
    6: ("#FFA62B", "Mango"),
    7: ("#CCD100", "Pineapple"),
    8: ("#724F3E", "Coffee"),
    9: ("#BEA978", "Cassava"),
    10: ("#474337", "Rubber"),
    11: ("#6D3200", "Cacao"),
    12: ("#CAC779", "Abaca"),
    13: ("#A37D00", "Tobacco"),
    14: ("#58B555", "Other crops"),
    15: ("#E39B98", "Livestock"),
    16: ("#FFC8A2", "Poultry and eggs"),
    17: ("#C48396", "Other animal production"),
    18: ("#005819", "Forestry and logging"),
    19: ("#008DA9", "Fishing and aquaculture"),
    20: ("#759535", "Support to agriculture"),
    21: ("#262626", "Coal"),
    22: ("#004556", "Crude petroleum and gas"),
    23: ("#BC9900", "Gold and precious metals"),
    24: ("#7AA67D", "Nickel"),
    25: ("#C56317", "Copper"),
    26: ("#948C88", "Stone and other quarrying"),
    27: ("#E6412E", "Food products"),
    28: ("#8F1741", "Beverages"),
    29: ("#585200", "Tobacco products"),
    30: ("#554DA4", "Textiles"),
    31: ("#E346A4", "Wearing apparel"),
    32: ("#9B6F58", "Leather and footwear"),
    33: ("#C08658", "Wood bamboo rattan"),
    34: ("#EFE7D9", "Paper"),
    35: ("#00B4EC", "Printing"),
    36: ("#3F2147", "Refined petroleum and coke"),
    37: ("#7E2DB1", "Chemicals"),
    38: ("#DE97EC", "Pharmaceuticals"),
    39: ("#C16CC1", "Rubber and plastic products"),
    40: ("#CDBDB2", "Non-metallic minerals"),
    41: ("#4F5269", "Basic metals"),
    42: ("#9BA4BA", "Fabricated metal"),
    43: ("#00914B", "Electronics"),
    44: ("#3B6DFF", "Electrical equipment"),
    45: ("#5E8375", "Machinery"),
    46: ("#4A71AE", "Transport equipment"),
    47: ("#9D3D36", "Furniture"),
    48: ("#A56B93", "Other manufacturing"),
    49: ("#FFD248", "Electricity"),
    50: ("#C4D5ED", "Steam"),
    51: ("#4394DB", "Water supply"),
    52: ("#737530", "Sewerage and waste"),
    53: ("#EE7815", "Construction"),
    54: ("#AE2B64", "Wholesale trade"),
    55: ("#FA4674", "Retail trade"),
    56: ("#7C446B", "Motor vehicle sale and repair"),
    57: ("#425B87", "Land transport"),
    58: ("#162C64", "Water transport"),
    59: ("#7FCCF8", "Air transport"),
    60: ("#B9B3E9", "Warehousing and transport support"),
    61: ("#7B77E2", "Postal and courier"),
    62: ("#1EB9B4", "Accommodation"),
    63: ("#52E9EF", "Food and beverage service"),
    64: ("#5635DA", "Information and publishing"),
    65: ("#A28CFF", "Communication"),
    66: ("#045F56", "Banking"),
    67: ("#009F89", "Non-banks"),
    68: ("#30D7B8", "Insurance and pensions"),
    69: ("#AAF5E2", "Auxiliary financial"),
    70: ("#621F30", "Real estate"),
    71: ("#BB5359", "Ownership of dwellings"),
    72: ("#7D82B2", "Professional and business services"),
    73: ("#0047B7", "Public administration"),
    74: ("#297651", "Public education"),
    75: ("#8EBEAA", "Private education"),
    76: ("#C81B1D", "Public health"),
    77: ("#EF7572", "Private health"),
    78: ("#F2B3DE", "Social work"),
    79: ("#E420D0", "Arts and entertainment"),
    80: ("#77697B", "Other services"),
}


def _pad_code(code: str) -> str:
    text = str(code).strip()
    return text.zfill(2) if text.isdigit() and len(text) < 2 else text


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid hex color: {hex_color!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _qgis_rgba(hex_color: str, *, alpha: int = 255) -> str:
    r, g, b = _rgb(hex_color)
    return f"{r},{g},{b},{alpha}"


def _family_map_for_catalog(catalog: SectorCatalog) -> dict[str, str]:
    if _RESOURCE_INDUSTRIES.exists():
        frame = pd.read_csv(_RESOURCE_INDUSTRIES, dtype={"io80_code": str, "io16_code": str})
        io80 = {str(row.io80_code).strip(): str(row.io16_label).strip() for row in frame.itertuples(index=False)}
        io16 = {str(row.io16_code).strip(): str(row.io16_label).strip() for row in frame.itertuples(index=False)}
        codes = {str(item.code).strip() for item in catalog}
        if codes and codes <= set(io80):
            return {code: io80.get(code, "Other services") for code in codes}
        if codes and codes <= set(io16):
            return {code: io16.get(code, "Other services") for code in codes}
    return {str(item.code).strip(): str(item.label).strip() for item in catalog}


def _fallback_color(index: int) -> str:
    # Deterministic custom-economy fallback; canonical IO80 never reaches this path.
    import colorsys
    hue = (index * 137.50776405) % 360.0
    r, g, b = colorsys.hsv_to_rgb(hue / 360.0, 0.62, 0.78)
    return f"#{int(round(r * 255)):02X}{int(round(g * 255)):02X}{int(round(b * 255)):02X}"


def build_sector_styles(catalog: SectorCatalog) -> dict[str, SectorStyle]:
    family_map = _family_map_for_catalog(catalog)
    styles: dict[str, SectorStyle] = {}
    for index, sector in enumerate(catalog):
        code = str(sector.code).strip()
        family = family_map.get(code, "Other services")
        numeric_code = int(code) if code.isdigit() else None
        if numeric_code in _IO80_PRESENTATION and len(catalog) == 80:
            color, label = _IO80_PRESENTATION[numeric_code]
        else:
            color, label = _fallback_color(index), str(sector.label).strip()
        display = f"{_pad_code(code)} - {label}"
        styles[code] = SectorStyle(
            code=code,
            label=label,
            display=display,
            family=family,
            color_hex=color,
        )
    return styles


def as_wgs84(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a published copy with every geometry column normalized to WGS 84.

    GeoPandas ``to_crs`` transforms only the active geometry column. SIGMA export
    frames can also carry secondary geometry columns (for example
    ``network_position``), so normalize those explicitly as well.
    """
    if frame.crs is None:
        raise ValueError("geospatial export requires a declared CRS")
    out = frame.to_crs(WGS84) if str(frame.crs).upper() != WGS84 else frame.copy()
    active = frame.geometry.name
    for column in frame.columns:
        if column == active or not isinstance(frame[column].dtype, GeometryDtype):
            continue
        source = frame[column]
        source_crs = getattr(source, "crs", None) or frame.crs
        if source_crs is None:
            raise ValueError(f"geometry export column {column!r} has no declared CRS")
        transformed = gpd.GeoSeries(source, index=frame.index, crs=source_crs)
        if str(transformed.crs).upper() != WGS84:
            transformed = transformed.to_crs(WGS84)
        out[column] = transformed
    return out


def _append_wgs84_spatialrefsys(parent: ET.Element) -> ET.Element:
    """Write the complete CRS block QGIS itself persists for EPSG:4326."""
    spatial = ET.SubElement(parent, "spatialrefsys", {"nativeFormat": "Wkt"})
    ET.SubElement(spatial, "wkt").text = _WGS84_WKT
    ET.SubElement(spatial, "proj4").text = "+proj=longlat +datum=WGS84 +no_defs"
    ET.SubElement(spatial, "srsid").text = "3452"
    ET.SubElement(spatial, "srid").text = "4326"
    ET.SubElement(spatial, "authid").text = WGS84
    ET.SubElement(spatial, "description").text = "WGS 84"
    ET.SubElement(spatial, "projectionacronym").text = "longlat"
    ET.SubElement(spatial, "ellipsoidacronym").text = "EPSG:7030"
    ET.SubElement(spatial, "geographicflag").text = "true"
    return spatial


def _append_wgs84_mapcanvas(
    root: ET.Element,
    bounds: tuple[float, float, float, float],
) -> ET.Element:
    """Persist the actual QGIS map-canvas destination CRS and initial extent.

    ``projectCrs`` alone is not sufficient for a hand-written QGS project to
    reproduce QGIS' own saved-project state reliably.  QGIS 3.44 also stores
    the canvas destination CRS explicitly under ``mapcanvas/destinationsrs``.
    """
    canvas = ET.SubElement(
        root,
        "mapcanvas",
        {"name": "theMapCanvas", "annotationsVisible": "1"},
    )
    ET.SubElement(canvas, "units").text = "degrees"
    extent = ET.SubElement(canvas, "extent")
    minx, miny, maxx, maxy = bounds
    for tag, value in (("xmin", minx), ("ymin", miny), ("xmax", maxx), ("ymax", maxy)):
        ET.SubElement(extent, tag).text = f"{value:.15g}"
    ET.SubElement(canvas, "rotation").text = "0"
    destination = ET.SubElement(canvas, "destinationsrs")
    _append_wgs84_spatialrefsys(destination)
    ET.SubElement(canvas, "rendermaptile").text = "0"
    ET.SubElement(canvas, "expressionContextScope")
    return canvas


def annotate_types(frame: gpd.GeoDataFrame, styles: Mapping[str, SectorStyle]) -> gpd.GeoDataFrame:
    out = frame.copy()
    if "type" not in out.columns:
        return out
    values = out["type"].astype(str)
    out["type_label"] = [styles.get(v, SectorStyle(v, v, v, "Other services", "#607D8B")).label for v in values]
    out["type_display"] = [styles.get(v, SectorStyle(v, v, v, "Other services", "#607D8B")).display for v in values]
    out["type_family"] = [styles.get(v, SectorStyle(v, v, v, "Other services", "#607D8B")).family for v in values]
    return out


def _bounds(frame: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = frame.total_bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def _authid(frame: gpd.GeoDataFrame) -> str:
    if frame.crs is None:
        return "EPSG:4326"
    return str(frame.crs.to_authority()[0] + ":" + frame.crs.to_authority()[1]) if frame.crs.to_authority() else str(frame.crs)


def _new_maplayer_base(layer_type: str, layername: str, datasource: str, geometry: str, crs_authid: str, bounds: tuple[float, float, float, float], labels_enabled: bool = False) -> ET.Element:
    maplayer = ET.Element(
        "maplayer",
        {
            "type": "vector",
            "geometry": geometry,
            "labelsEnabled": "1" if labels_enabled else "0",
            "readOnly": "0",
            "styleCategories": "AllStyleCategories",
            "autoRefreshTime": "0",
            "simplifyLocal": "1",
            "minScale": "100000000",
            "maxScale": "0",
        },
    )
    extent = ET.SubElement(maplayer, "extent")
    minx, miny, maxx, maxy = bounds
    for tag, value in (("xmin", minx), ("ymin", miny), ("xmax", maxx), ("ymax", maxy)):
        ET.SubElement(extent, tag).text = f"{value:.15g}"
    ET.SubElement(maplayer, "id").text = f"{layername}_{uuid.uuid4()}"
    ET.SubElement(maplayer, "datasource").text = datasource
    ET.SubElement(maplayer, "layername").text = layername
    srs = ET.SubElement(maplayer, "srs")
    if crs_authid == WGS84:
        _append_wgs84_spatialrefsys(srs)
    else:
        sref = ET.SubElement(srs, "spatialrefsys")
        ET.SubElement(sref, "authid").text = crs_authid
        ET.SubElement(sref, "description").text = crs_authid
    ET.SubElement(maplayer, "provider", {"encoding": "UTF-8"}).text = "ogr"
    ET.SubElement(maplayer, "subsetString")
    ET.SubElement(maplayer, "vectorjoins")
    ET.SubElement(maplayer, "layerDependencies")
    ET.SubElement(maplayer, "dataDependencies")
    ET.SubElement(maplayer, "expressionfields")
    ET.SubElement(maplayer, "map-layer-style-manager", {"current": "default"})
    ET.SubElement(maplayer, "auxiliaryLayer")
    flags = ET.SubElement(maplayer, "flags")
    for name, value in (("Identifiable", "1"), ("Removable", "1"), ("Searchable", "1"), ("Private", "0")):
        ET.SubElement(flags, name).text = value
    ET.SubElement(maplayer, "layerOpacity").text = "1"
    ET.SubElement(maplayer, "blendMode").text = "0"
    ET.SubElement(maplayer, "paintEffect")
    return maplayer


def _simple_fill_symbol(color_hex: str, *, alpha: int = 255, outline_hex: str = "#232323", outline_width: str = "0.2") -> ET.Element:
    symbol = ET.Element("symbol", {"type": "fill", "name": "0", "alpha": "1", "clip_to_extent": "1"})
    layer = ET.SubElement(symbol, "layer", {"class": "SimpleFill", "enabled": "1", "pass": "0", "locked": "0", "id": str(uuid.uuid4())})
    option = ET.SubElement(layer, "Option", {"type": "Map"})
    opts = {
        "color": _qgis_rgba(color_hex, alpha=alpha),
        "outline_color": _qgis_rgba(outline_hex),
        "outline_style": "solid",
        "outline_width": outline_width,
        "outline_width_unit": "MM",
        "style": "solid",
        "joinstyle": "bevel",
    }
    for key, value in opts.items():
        ET.SubElement(option, "Option", {"type": "QString", "name": key, "value": value})
    return symbol


def _simple_line_symbol(color_hex: str, *, width: str = "0.35") -> ET.Element:
    symbol = ET.Element("symbol", {"type": "line", "name": "0", "alpha": "1", "clip_to_extent": "1"})
    layer = ET.SubElement(symbol, "layer", {"class": "SimpleLine", "enabled": "1", "pass": "0", "locked": "0", "id": str(uuid.uuid4())})
    option = ET.SubElement(layer, "Option", {"type": "Map"})
    opts = {
        "line_color": _qgis_rgba(color_hex),
        "line_style": "solid",
        "line_width": width,
        "line_width_unit": "MM",
        "joinstyle": "bevel",
        "capstyle": "square",
    }
    for key, value in opts.items():
        ET.SubElement(option, "Option", {"type": "QString", "name": key, "value": value})
    return symbol


def _simple_marker_symbol(color_hex: str, *, size: str = "2.8", alpha: str = "1", shape: str = "circle", outline_hex: str = "#232323") -> ET.Element:
    symbol = ET.Element("symbol", {"type": "marker", "name": "0", "alpha": alpha, "clip_to_extent": "1"})
    layer = ET.SubElement(symbol, "layer", {"class": "SimpleMarker", "enabled": "1", "pass": "0", "locked": "0", "id": str(uuid.uuid4())})
    option = ET.SubElement(layer, "Option", {"type": "Map"})
    opts = {
        "name": shape,
        "color": _qgis_rgba(color_hex),
        "outline_color": _qgis_rgba(outline_hex),
        "outline_style": "solid",
        "outline_width": "0",
        "outline_width_unit": "MM",
        "size": size,
        "size_unit": "MM",
        "scale_method": "diameter",
        "horizontal_anchor_point": "1",
        "vertical_anchor_point": "1",
    }
    for key, value in opts.items():
        ET.SubElement(option, "Option", {"type": "QString", "name": key, "value": value})
    return symbol


def _add_data_defined_size(symbol: ET.Element, field: str, *, min_value: float, max_value: float, min_size: float, max_size: float) -> None:
    layer = symbol.find("layer")
    if layer is None:
        return
    dd = ET.SubElement(layer, "data_defined_properties")
    top = ET.SubElement(dd, "Option", {"type": "Map"})
    ET.SubElement(top, "Option", {"type": "QString", "name": "name", "value": ""})
    props = ET.SubElement(top, "Option", {"type": "Map", "name": "properties"})
    size = ET.SubElement(props, "Option", {"type": "Map", "name": "size"})
    ET.SubElement(size, "Option", {"type": "bool", "name": "active", "value": "true"})
    ET.SubElement(size, "Option", {"type": "QString", "name": "field", "value": field})
    transformer = ET.SubElement(size, "Option", {"type": "Map", "name": "transformer"})
    d = ET.SubElement(transformer, "Option", {"type": "Map", "name": "d"})
    for name, value in {
        "exponent": 1.0,
        "maxSize": max_size,
        "maxValue": max_value,
        "minSize": min_size,
        "minValue": min_value,
        "nullSize": 0.0,
        "scaleType": 2,
    }.items():
        typ = "double" if isinstance(value, float) else "int"
        ET.SubElement(d, "Option", {"type": typ, "name": name, "value": str(value)})
    ET.SubElement(transformer, "Option", {"type": "int", "name": "t", "value": "1"})
    ET.SubElement(size, "Option", {"type": "int", "name": "type", "value": "2"})
    ET.SubElement(top, "Option", {"type": "QString", "name": "type", "value": "collection"})


def _categorized_point_renderer(type_order: list[str], styles: Mapping[str, SectorStyle], *, score_min: float, score_max: float) -> ET.Element:
    renderer = ET.Element("renderer-v2", {"type": "categorizedSymbol", "attr": "type", "symbollevels": "0", "forceraster": "0", "enableorderby": "0", "referencescale": "-1"})
    categories = ET.SubElement(renderer, "categories")
    symbols = ET.SubElement(renderer, "symbols")
    for idx, code in enumerate(type_order):
        style = styles[code]
        ET.SubElement(categories, "category", {
            "symbol": str(idx),
            "label": style.display,
            "value": code,
            "type": "string",
            "render": "true",
            "uuid": "{" + str(uuid.uuid4()) + "}",
        })
        symbol = _simple_marker_symbol(style.color_hex, size="1", alpha="0.5", shape="circle")
        symbol.attrib["name"] = str(idx)
        _add_data_defined_size(symbol, "sigma_score", min_value=score_min, max_value=score_max, min_size=1.5, max_size=10.0)
        symbols.append(symbol)
    return renderer


def _single_symbol_renderer(symbol: ET.Element) -> ET.Element:
    renderer = ET.Element("renderer-v2", {"type": "singleSymbol", "symbollevels": "0", "forceraster": "0", "enableorderby": "0", "referencescale": "-1"})
    symbols = ET.SubElement(renderer, "symbols")
    symbols.append(symbol)
    return renderer


def _add_simple_labeling(maplayer: ET.Element, *, score_min: float, score_max: float) -> None:
    labeling = ET.SubElement(maplayer, "labeling", {"type": "simple"})
    settings = ET.SubElement(labeling, "settings")
    ET.SubElement(settings, "text-style", {
        "fieldName": "concat(\"canonical_name\", '-', round(100 * \"sigma_score\", 2))",
        "fontSize": "9",
        "fontSizeUnit": "Point",
        "isExpression": "1",
        "textColor": "35,35,35,255",
        "fontFamily": "Arial",
        "multilineHeight": "1",
    })
    ET.SubElement(settings, "text-format")
    ET.SubElement(settings, "placement", {"placement": "6", "dist": "0", "offsetUnits": "MM", "quadOffset": "4"})
    ET.SubElement(settings, "rendering", {"drawLabels": "1", "maxNumLabels": "2000", "obstacle": "1"})
    dd = ET.SubElement(settings, "dd_properties")
    top = ET.SubElement(dd, "Option", {"type": "Map"})
    ET.SubElement(top, "Option", {"type": "QString", "name": "name", "value": ""})
    props = ET.SubElement(top, "Option", {"type": "Map", "name": "properties"})
    for prop_name, out_min, out_max in (("Size", 5.0, 20.0), ("FontOpacity", 50.0, 100.0)):
        prop = ET.SubElement(props, "Option", {"type": "Map", "name": prop_name})
        ET.SubElement(prop, "Option", {"type": "bool", "name": "active", "value": "true"})
        ET.SubElement(prop, "Option", {"type": "QString", "name": "field", "value": "sigma_score"})
        transformer = ET.SubElement(prop, "Option", {"type": "Map", "name": "transformer"})
        d = ET.SubElement(transformer, "Option", {"type": "Map", "name": "d"})
        for name, value in {
            "exponent": 1.0,
            "maxOutput": out_max,
            "maxValue": score_max,
            "minOutput": out_min,
            "minValue": score_min,
            "nullOutput": 0.0,
        }.items():
            ET.SubElement(d, "Option", {"type": "double", "name": name, "value": str(value)})
        ET.SubElement(transformer, "Option", {"type": "int", "name": "t", "value": "0"})
        ET.SubElement(prop, "Option", {"type": "int", "name": "type", "value": "2"})
    ET.SubElement(top, "Option", {"type": "QString", "name": "type", "value": "collection"})


def write_qgis_project(
    target: Path,
    *,
    area_name: str,
    area_slug: str,
    boundary: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    partitions: gpd.GeoDataFrame,
    centers: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    styles: Mapping[str, SectorStyle],
) -> None:
    boundary = as_wgs84(boundary)
    roads = as_wgs84(roads)
    partitions = as_wgs84(partitions)
    centers = as_wgs84(centers)
    points = as_wgs84(points)

    root = ET.Element("qgis", {"projectname": area_name, "version": "3.44.6-Solothurn"})
    ET.SubElement(root, "homePath", {"path": "."})
    ET.SubElement(root, "title").text = f"SIGMA – {area_name}"
    ET.SubElement(root, "autotransaction").text = "0"
    project_crs = ET.SubElement(root, "projectCrs")
    _append_wgs84_spatialrefsys(project_crs)
    canvas_bounds = _bounds(boundary if len(boundary) else points)
    _append_wgs84_mapcanvas(root, canvas_bounds)

    layer_tree = ET.SubElement(root, "layer-tree-group", {"name": "", "checked": "Qt::Checked", "expanded": "1"})
    partitions_group = ET.Element("layer-tree-group", {"name": "Partitions", "checked": "Qt::Checked", "expanded": "1"})

    projectlayers = ET.SubElement(root, "projectlayers")
    layer_ids: list[str] = []

    crs_authid = WGS84
    score_series = pd.to_numeric(points["sigma_score"], errors="coerce") if len(points) else pd.Series([0.0])
    finite_scores = score_series[score_series.notna()]
    score_min = float(finite_scores.min()) if len(finite_scores) else 0.0
    score_max = float(finite_scores.max()) if len(finite_scores) else 1.0
    if score_max <= score_min:
        score_max = score_min + 1.0

    def add_tree_entry(parent: ET.Element, maplayer: ET.Element, *, checked: str = "Qt::Checked") -> None:
        layer_id = maplayer.findtext("id") or ""
        ET.SubElement(parent, "layer-tree-layer", {"id": layer_id, "name": maplayer.findtext("layername") or "", "checked": checked, "expanded": "1", "providerKey": "ogr"})
        layer_ids.append(layer_id)
        projectlayers.append(maplayer)

    # Build all map layers first, then insert them in the requested top-to-bottom order.
    boundary_layer = _new_maplayer_base(
        "vector", "sigma_boundary",
        "./sigma_boundary.parquet",
        "Polygon", crs_authid, _bounds(boundary),
    )
    boundary_layer.append(
        _single_symbol_renderer(
            _simple_fill_symbol("#FFFFFF", alpha=255, outline_hex="#232323", outline_width="0.26")
        )
    )

    roads_layer = _new_maplayer_base(
        "vector", "sigma_roads",
        "./sigma_roads.parquet",
        "Line", crs_authid, _bounds(roads),
    )
    roads_layer.append(_single_symbol_renderer(_simple_line_symbol("#F3A6B2", width="0.16")))

    centers_layer = _new_maplayer_base(
        "vector", "sigma_network_centers",
        "./sigma_network_centers.parquet",
        "Point", crs_authid, _bounds(centers),
    )
    centers_layer.append(
        _single_symbol_renderer(_simple_marker_symbol("#C43C39", size="2", alpha="1", shape="circle"))
    )

    partition_type_order = sorted(
        {str(v) for v in partitions.get("type", pd.Series(dtype=str)).astype(str)},
        key=lambda v: (0, int(v)) if v.isdigit() else (1, v),
    )
    point_type_order = sorted(
        {str(v) for v in points.get("type", pd.Series(dtype=str)).astype(str)},
        key=lambda v: (0, int(v)) if v.isdigit() else (1, v),
    )
    partition_layers: list[ET.Element] = []
    for code in partition_type_order:
        style = styles.get(code, SectorStyle(code, code, code, "Other services", "#90A4AE"))
        maplayer = _new_maplayer_base(
            "vector",
            f"partition_{code}",
            "./sigma_partitions.parquet",
            "Polygon",
            crs_authid,
            _bounds(partitions),
        )
        subset = maplayer.find("subsetString")
        if subset is not None:
            subset.text = f'"type" = \'{code}\''
        maplayer.find("layername").text = style.display
        maplayer.append(
            _single_symbol_renderer(
                _simple_fill_symbol(style.color_hex, alpha=255, outline_hex="#232323", outline_width="0.26")
            )
        )
        partition_layers.append(maplayer)

    points_layer = _new_maplayer_base(
        "vector", "sigma_points",
        "./sigma_points.parquet",
        "Point", crs_authid, _bounds(points), labels_enabled=True,
    )
    points_layer.append(
        _categorized_point_renderer(point_type_order, styles, score_min=score_min, score_max=score_max)
    )
    _add_simple_labeling(points_layer, score_min=score_min, score_max=score_max)

    # One canonical establishment layer; sector categories are mutually exclusive.
    add_tree_entry(layer_tree, points_layer, checked="Qt::Checked")
    layer_tree.append(partitions_group)
    for maplayer in partition_layers:  # Sector order itself remains ascending.
        add_tree_entry(partitions_group, maplayer, checked="Qt::Unchecked")
    add_tree_entry(layer_tree, centers_layer, checked="Qt::Unchecked")
    add_tree_entry(layer_tree, roads_layer, checked="Qt::Checked")
    add_tree_entry(layer_tree, boundary_layer, checked="Qt::Checked")

    # Layer order.
    layerorder = ET.SubElement(root, "layerorder")
    for layer_id in layer_ids:
        ET.SubElement(layerorder, "layer", {"id": layer_id})

    # Canvas extent.
    props = ET.SubElement(root, "properties")
    view = ET.SubElement(props, "Gui")
    extent = ET.SubElement(view, "CanvasExtent")
    minx, miny, maxx, maxy = canvas_bounds
    for tag, value in (("xmin", minx), ("ymin", miny), ("xmax", maxx), ("ymax", maxy)):
        ET.SubElement(extent, tag).text = f"{value:.15g}"

    ET.indent(root)
    qgs_name = f"{area_slug}.qgs"
    qgs_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(qgs_name, qgs_bytes)

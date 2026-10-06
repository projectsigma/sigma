from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from sigma.sources import SourceStore
from sigma.transport import FileRoadSource
from sigma.transport.roads import validate_road_frame


def test_file_road_source_registers_selection_and_loads_projected_lines(tmp_path):
    path = tmp_path / "roads.gpkg"
    roads = gpd.GeoDataFrame({"road_id": [1]}, geometry=[LineString([(0, 0), (10, 0)])], crs="EPSG:3857")
    roads.to_file(path, layer="roads", driver="GPKG")
    store = SourceStore(tmp_path / "sources")
    source = FileRoadSource(path, "roads")
    ref = source.register(store)
    assert ref.selection["layer"] == "roads"
    loaded = source.load()
    assert len(loaded) == 1
    assert str(loaded.crs).upper() == "EPSG:3857"


def test_road_source_rejects_geographic_or_non_line_geometry():
    geographic = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 0)])], crs="EPSG:4326")
    with pytest.raises(ValueError, match="projected CRS"):
        validate_road_frame(geographic)
    points = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:3857")
    with pytest.raises(ValueError, match="only line geometry"):
        validate_road_frame(points)


def test_managed_road_selection_and_projection_policy_are_pinned():
    from sigma.area import Area
    from sigma.transport.roads import (
        GeofabrikRoadSource,
        MANAGED_ACCESS_EXCLUDED,
        MANAGED_HIGHWAY_VALUES,
        _selected_osm_road,
    )

    assert "primary" in MANAGED_HIGHWAY_VALUES
    assert "footway" not in MANAGED_HIGHWAY_VALUES
    assert "private" in MANAGED_ACCESS_EXCLUDED
    assert _selected_osm_road("primary", None)
    assert _selected_osm_road("residential", "destination")
    assert not _selected_osm_road("footway", None)
    assert not _selected_osm_road("primary", "private")

    area = Area("qc", "Quezon City", "city", (120.9, 14.5, 121.2, 14.8))
    source = GeofabrikRoadSource()
    assert source.resolve_target_crs(area, LineString([(120.9, 14.5), (121.2, 14.8)]).envelope) == "EPSG:32651"
    params = source.recipe_parameters(area, LineString([(120.9, 14.5), (121.2, 14.8)]).envelope)
    assert params["simplification"] == "none"
    assert params["directionality"] == "undirected-linework-retain-osm-oneway-metadata"
    assert params["clip_buffer_m"] == 5000.0


def test_managed_extraction_clips_projects_and_preserves_osm_audit_fields(tmp_path, monkeypatch):
    from sigma.area import Area
    from sigma.transport import roads as roads_module
    from sigma.transport.roads import GeofabrikRoadSource

    pbf = tmp_path / "philippines.osm.pbf"
    pbf.write_bytes(b"fixture")
    area = Area("fixture", "Fixture", "city", (120.99, 13.99, 121.01, 14.01))
    boundary = gpd.GeoSeries.from_wkt(
        ["POLYGON ((120.99 13.99, 121.01 13.99, 121.01 14.01, 120.99 14.01, 120.99 13.99))"],
        crs="EPSG:4326",
    ).iloc[0]

    candidates = gpd.GeoDataFrame(
        {
            "osm_way_id": [2, 1],
            "highway": ["primary", "residential"],
            "access": [None, "destination"],
            "name": ["Outside-to-inside", "Inside"],
            "oneway": ["yes", None],
            "bridge": [None, None],
            "tunnel": [None, None],
            "layer": [None, None],
        },
        geometry=[
            LineString([(120.95, 14.0), (121.0, 14.0)]),
            LineString([(120.995, 14.0), (121.005, 14.0)]),
        ],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(roads_module, "_extract_pbf_road_candidates", lambda path, bbox, **kwargs: candidates)

    result = GeofabrikRoadSource(buffer_m=0).load(pbf, area=area, boundary=boundary)
    assert str(result.crs).upper() == "EPSG:32651"
    assert result["osm_way_id"].tolist() == [1, 2]
    assert result.loc[result["osm_way_id"] == 2, "oneway"].iloc[0] == "yes"
    assert result.geometry.length.gt(0).all()
    # The crossing feature is clipped to the exact boundary when buffer_m=0.
    wgs = result.to_crs("EPSG:4326")
    assert float(wgs.total_bounds[0]) >= 120.99 - 1e-9

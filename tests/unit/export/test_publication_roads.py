from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from sigma.export.compatibility import _clip_roads_to_boundary
from sigma.export.qgis import WGS84


def test_publication_roads_are_clipped_to_exact_area_boundary():
    boundary = gpd.GeoDataFrame(
        {"area": ["fixture"]},
        geometry=[
            Polygon(
                [
                    (121.00, 14.50),
                    (121.10, 14.50),
                    (121.10, 14.60),
                    (121.00, 14.60),
                ]
            )
        ],
        crs=WGS84,
    )
    roads = gpd.GeoDataFrame(
        {"road_id": ["crossing", "outside"]},
        geometry=[
            LineString([(120.95, 14.55), (121.15, 14.55)]),
            LineString([(120.90, 14.52), (120.95, 14.52)]),
        ],
        crs=WGS84,
    )

    clipped = _clip_roads_to_boundary(roads, boundary)

    assert list(clipped["road_id"]) == ["crossing"]
    assert str(clipped.crs).upper() == WGS84
    minx, miny, maxx, maxy = clipped.total_bounds
    assert abs(minx - 121.00) < 1e-12
    assert abs(maxx - 121.10) < 1e-12
    assert 14.50 <= miny <= maxy <= 14.60
    assert boundary.geometry.iloc[0].covers(clipped.geometry.iloc[0])

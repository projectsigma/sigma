import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon

from sigma.places.reconcile import reconcile


def layer(source, rows):
    frame = pd.DataFrame(rows)
    frame["source"] = source
    frame["upstream_license"] = "ODbL-1.0" if source == "osm" else "CDLA-Permissive-2.0"
    frame["overture_providers"] = "" if source == "osm" else "meta"
    return gpd.GeoDataFrame(
        frame,
        geometry=[Point(xy) for xy in zip(frame.lon, frame.lat, strict=True)],
        crs="EPSG:4326",
    )


def test_near_same_name_is_reconciled():
    a = layer(
        "osm",
        [
            {
                "source_id": "node/1",
                "name": "Alpha Coffee",
                "category": "amenity=cafe",
                "lon": 121.0,
                "lat": 14.5,
            }
        ],
    )
    b = layer(
        "overture",
        [
            {
                "source_id": "ov-1",
                "name": "Alpha Coffee",
                "category": "coffee shop",
                "lon": 121.00005,
                "lat": 14.5,
            }
        ],
    )
    out = reconcile(a, b)
    assert len(out) == 1
    assert out.loc[0, "source_count"] == 2
    assert out.loc[0, "osm_id"] == "node/1"
    assert out.loc[0, "overture_id"] == "ov-1"
    assert out.loc[0, "source_licenses"] == "CDLA-Permissive-2.0|ODbL-1.0"
    assert out.loc[0, "overture_providers"] == "meta"


def test_midpoint_outside_boundary_falls_back_to_source_coordinate():
    a = layer(
        "osm",
        [{
            "source_id": "node/1",
            "name": "Alpha Coffee",
            "category": "amenity=cafe",
            "lon": 120.9997,
            "lat": 14.5,
        }],
    )
    b = layer(
        "overture",
        [{
            "source_id": "ov-1",
            "name": "Alpha Coffee",
            "category": "coffee shop",
            "lon": 121.0003,
            "lat": 14.5,
        }],
    )
    boundary = Polygon(
        [
            (120.9990, 14.4990),
            (121.0010, 14.4990),
            (121.0010, 14.5010),
            (120.9990, 14.5010),
        ],
        holes=[[
            (120.9999, 14.4999),
            (121.0001, 14.4999),
            (121.0001, 14.5001),
            (120.9999, 14.5001),
        ]],
    )
    out = reconcile(a, b, boundary=boundary)
    assert len(out) == 1
    assert out.loc[0, "source_count"] == 2
    assert boundary.covers(out.geometry.iloc[0])
    assert (out.loc[0, "lon"], out.loc[0, "lat"]) == (120.9997, 14.5)


def test_distant_observations_stay_separate():
    a = layer(
        "osm",
        [
            {
                "source_id": "node/1",
                "name": "Alpha Coffee",
                "category": "amenity=cafe",
                "lon": 121.0,
                "lat": 14.5,
            }
        ],
    )
    b = layer(
        "overture",
        [
            {
                "source_id": "ov-1",
                "name": "Alpha Coffee",
                "category": "coffee shop",
                "lon": 121.01,
                "lat": 14.5,
            }
        ],
    )
    out = reconcile(a, b)
    assert len(out) == 2
    assert set(out["source_count"]) == {1}


def test_reconciliation_preserves_source_specific_semantics():
    a = layer(
        "osm",
        [{
            "source_id": "node/1",
            "name": "Alpha Coffee",
            "category": "amenity=cafe | cuisine=coffee_shop",
            "lon": 121.0,
            "lat": 14.5,
        }],
    )
    b = layer(
        "overture",
        [{
            "source_id": "ov-1",
            "name": "Alpha Coffee Cafe",
            "category": "coffee_shop",
            "lon": 121.00005,
            "lat": 14.5,
        }],
    )
    out = reconcile(a, b)
    assert out.loc[0, "osm_name"] == "Alpha Coffee"
    assert out.loc[0, "osm_category"] == "amenity=cafe | cuisine=coffee_shop"
    assert out.loc[0, "overture_name"] == "Alpha Coffee Cafe"
    assert out.loc[0, "overture_category"] == "coffee_shop"

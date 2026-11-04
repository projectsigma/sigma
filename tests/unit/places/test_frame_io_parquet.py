"""Managed geoframes read back identically from Parquet and from the legacy JSON."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from sigma.places.frame_io import read_geoframe, write_geoframe


def _frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "int": [1, 2, 3, 4],
            "int_missing": [1, None, 3, 4],
            "float": [0.1, -0.0, float("inf"), np.float64(2.5)],
            "float_nan": [np.nan, 1.5, None, 2.0],
            "numpy_int": np.asarray([7, 8, 9, 2**40], dtype=np.int64),
            "text": ["a", "ñandú", None, ""],
            "bool": [True, False, np.bool_(True), None],
            "mixed_number": [1, 2.5, None, 3],
            "mixed_type": ["1", 1, None, True],
            "big_int": [2**70, 1, None, 2],
            "lists": [["x", 1], [], None, np.asarray([1.5, 2.0])],
            "dicts": [{"a": 1}, {"b": [1, {"c": None}]}, None, {}],
            "time": [pd.Timestamp("2026-11-02T01:02:03"), None, pd.Timestamp("2020-01-01"), None],
            "all_none": [None, None, None, None],
        },
        geometry=[Point(1, 2), None, LineString([(0, 0), (1, 1)]), Point(3, 4)],
        crs="EPSG:32651",
    )


def _assert_identical(a: gpd.GeoDataFrame, b: gpd.GeoDataFrame) -> None:
    pd.testing.assert_frame_equal(
        a.drop(columns="geometry"), b.drop(columns="geometry"), check_dtype=True, check_exact=True
    )
    for column in a.columns.drop("geometry"):
        for x, y in zip(a[column], b[column], strict=True):
            assert type(x) is type(y), column
    assert [g is None for g in a.geometry] == [g is None for g in b.geometry]
    assert [None if g is None else g.wkb for g in a.geometry] == [
        None if g is None else g.wkb for g in b.geometry
    ]
    assert str(a.crs) == str(b.crs)


@pytest.mark.parametrize("rows", [slice(None), slice(0, 0)])
def test_parquet_reads_back_exactly_like_legacy_json(tmp_path, rows):
    frame = _frame().iloc[rows]
    write_geoframe(frame, tmp_path / "t.json")
    write_geoframe(frame, tmp_path / "t.parquet")
    _assert_identical(read_geoframe(tmp_path / "t.json"), read_geoframe(tmp_path / "t.parquet"))


def test_parquet_name_falls_back_to_legacy_json_artifact(tmp_path):
    frame = _frame()
    write_geoframe(frame, tmp_path / "places.json")
    restored = read_geoframe(tmp_path / "places.parquet")
    _assert_identical(read_geoframe(tmp_path / "places.json"), restored)

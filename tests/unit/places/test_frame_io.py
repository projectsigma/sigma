from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from sigma.places.frame_io import read_geoframe, write_geoframe


def test_write_geoframe_serializes_ndarray_cells_from_parquet_style_roundtrip(tmp_path):
    frame = gpd.GeoDataFrame(
        {
            "canonical_id": ["p1", "p2"],
            "audit_values": [
                np.asarray([], dtype=object),
                np.asarray(["a", np.int64(2), np.float64(3.5)], dtype=object),
            ],
        },
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
    )

    path = tmp_path / "frame.json"
    write_geoframe(frame, path)
    restored = read_geoframe(path)

    assert restored["audit_values"].tolist() == [[], ["a", 2, 3.5]]
    assert restored.geometry.to_wkt().tolist() == ["POINT (0 0)", "POINT (1 1)"]

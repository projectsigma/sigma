from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely.wkb
from shapely.geometry import Point

from .licensing import OSM_LICENSE
from .text import clean_text, combine

ProgressCallback = Callable[[str], None]

POI_KEYS = (
    "amenity",
    "shop",
    "office",
    "craft",
    "tourism",
    "leisure",
    "healthcare",
    "industrial",
    "man_made",
    "club",
    "emergency",
    "public_transport",
)

VALUE_SELECTORS = {
    "aeroway": ("aerodrome", "terminal"),
    "railway": ("station", "halt", "tram_stop", "subway_entrance"),
}
CATEGORY_KEYS = (*POI_KEYS, *VALUE_SELECTORS)

OSM_COLUMNS = [
    "source",
    "source_id",
    "name",
    "category",
    "lon",
    "lat",
    "provenance",
    "upstream_license",
    "overture_providers",
    "geometry",
]


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _has_poi(tags) -> bool:
    if not combine(tags.get("name"), tags.get("name:en")):
        return False
    for key in POI_KEYS:
        if clean_text(tags.get(key)):
            return True
    for key, values in VALUE_SELECTORS.items():
        value = clean_text(tags.get(key))
        if value in values:
            return True
    return False


def _category(tags) -> str:
    parts = []
    for key in CATEGORY_KEYS:
        value = clean_text(tags.get(key))
        if value:
            parts.append(f"{key}={value}")
    for key in ("cuisine", "brand", "operator"):
        value = clean_text(tags.get(key))
        if value:
            parts.append(f"{key}={value}")
    return " | ".join(parts)


def _empty_osm() -> gpd.GeoDataFrame:
    frame = pd.DataFrame(columns=OSM_COLUMNS)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs="EPSG:4326")


def extract_national_osm_pois(
    pbf_file: Path,
    *,
    node_cache: Path,
    progress: ProgressCallback | None = None,
) -> gpd.GeoDataFrame:
    """Scan the Philippines PBF once and return all named POI candidates."""
    try:
        import osmium
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Local OSM extraction requires the 'osmium' Python package. "
            "Run: python -m pip install -e ."
        ) from exc

    node_cache.parent.mkdir(parents=True, exist_ok=True)
    index_spec = f"sparse_file_array,{node_cache}"
    wkbfab = osmium.geom.WKBFactory()

    _emit(
        progress,
        "OSM preparation: scanning the Philippines PBF once for nationwide named POIs",
    )

    class POIHandler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.rows: dict[str, dict[str, object]] = {}
            self.objects_seen = 0
            self.next_report = 1_000_000

        def _tick(self) -> None:
            self.objects_seen += 1
            if self.objects_seen >= self.next_report:
                _emit(
                    progress,
                    f"OSM preparation: {self.objects_seen:,} objects examined; "
                    f"{len(self.rows):,} nationwide POI candidates retained",
                )
                self.next_report += 1_000_000

        def _add(self, source_id: str, tags, lon: float, lat: float) -> None:
            name = combine(tags.get("name"), tags.get("name:en"))
            if not name:
                return
            self.rows[source_id] = {
                "source": "osm",
                "source_id": source_id,
                "name": name,
                "category": _category(tags),
                "lon": lon,
                "lat": lat,
                "provenance": "OpenStreetMap contributors via Geofabrik",
                "upstream_license": OSM_LICENSE,
                "overture_providers": "",
            }

        def node(self, node) -> None:
            self._tick()
            if not _has_poi(node.tags) or not node.location.valid():
                return
            self._add(
                f"node/{node.id}",
                node.tags,
                float(node.location.lon),
                float(node.location.lat),
            )

        def way(self, way) -> None:
            self._tick()
            if not _has_poi(way.tags):
                return

            # Closed ways are handled by area(), which also covers multipolygons.
            if way.is_closed():
                return

            try:
                wkb = wkbfab.create_linestring(way)
                geometry = shapely.wkb.loads(wkb, hex=True)
            except (RuntimeError, ValueError):
                return
            if geometry.is_empty:
                return

            point = geometry.interpolate(0.5, normalized=True)
            self._add(
                f"way/{way.id}",
                way.tags,
                float(point.x),
                float(point.y),
            )

        def area(self, area) -> None:
            self._tick()
            if not _has_poi(area.tags):
                return
            try:
                wkb = wkbfab.create_multipolygon(area)
                geometry = shapely.wkb.loads(wkb, hex=True)
            except (RuntimeError, ValueError):
                return
            if geometry.is_empty:
                return

            point = geometry.representative_point()
            prefix = "way" if area.from_way() else "relation"
            self._add(
                f"{prefix}/{area.orig_id()}",
                area.tags,
                float(point.x),
                float(point.y),
            )

    handler = POIHandler()
    try:
        handler.apply_file(
            str(pbf_file),
            locations=True,
            idx=index_spec,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"National Geofabrik OSM extraction failed: {exc}") from exc

    if not handler.rows:
        return _empty_osm()

    frame = pd.DataFrame(handler.rows.values())
    gdf = gpd.GeoDataFrame(
        frame,
        geometry=[
            Point(xy)
            for xy in zip(frame["lon"], frame["lat"], strict=False)
        ],
        crs="EPSG:4326",
    )
    _emit(
        progress,
        f"OSM preparation: national scan complete — {len(gdf):,} POI candidates",
    )
    return gdf


def read_osm_cache(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Prepared OSM cache is missing: {path}")
    return gpd.read_parquet(path)

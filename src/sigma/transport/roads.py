from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from collections.abc import Callable
from typing import TypeAlias

import geopandas as gpd
from shapely.geometry import GeometryCollection, LineString, MultiLineString
import shapely.wkb

from sigma.area import Area
from sigma.economy.io_utils import read_vector
from sigma.sources import SourceRef, SourceStore

# C20 managed-road policy. These values are part of the artifact recipe and therefore
# intentionally versioned rather than inferred from whatever an OSM library happens to
# expose at runtime.
MANAGED_ROAD_SCHEMA_VERSION = 1
MANAGED_ROAD_SELECTION_VERSION = "osm-highway-motor-access-v1"
MANAGED_ROAD_PROJECTION_VERSION = "wgs84-bbox-centroid-utm-v1"
MANAGED_ROAD_DEFAULT_BUFFER_M = 5_000.0

# The default area-mode profile is deliberately a motor-road network rather than every
# OSM ``highway=*`` feature. FileRoadSource remains available as an explicit override
# when a different network semantics is required.
MANAGED_HIGHWAY_VALUES = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "road",
    }
)
MANAGED_ACCESS_EXCLUDED = frozenset({"no", "private", "agricultural", "forestry"})


@dataclass(frozen=True, slots=True)
class FileRoadSource:
    """Explicit projected road-line input, preserving current Engine semantics."""

    path: Path | str
    layer: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())

    def register(self, store: SourceStore) -> SourceRef:
        return store.register_user_file(self.path, name="roads", layer=self.layer)

    def load(self) -> gpd.GeoDataFrame:
        frame = read_vector(self.path, self.layer)
        return validate_road_frame(frame)


@dataclass(frozen=True, slots=True)
class GeofabrikRoadSource:
    """Managed OSM motor-road extraction from SIGMA's shared Geofabrik PBF.

    This source is intentionally *not* equivalent to ``FileRoadSource``. It is the
    canonical area-mode default; its selection, clipping, directionality and projection
    policies are pinned by versioned constants in this module.

    Directionality policy: OSM ``oneway`` is retained as audit metadata, while the
    emitted linework is direction-neutral because SIGMA's current ``RoadNetwork`` is
    undirected. No geometry simplification is applied.
    """

    buffer_m: float = MANAGED_ROAD_DEFAULT_BUFFER_M
    target_crs: str | int | None = None

    def __post_init__(self) -> None:
        value = float(self.buffer_m)
        if not math.isfinite(value) or value < 0:
            raise ValueError("managed road buffer_m must be a finite nonnegative distance")

    @property
    def layer(self) -> None:
        """Compatibility surface: managed roads are not read from a vector layer."""
        return None

    def resolve_target_crs(self, area: Area, boundary) -> str:
        if self.target_crs is not None:
            crs = gpd.GeoSeries([], crs=self.target_crs).crs
            if crs is None or getattr(crs, "is_geographic", False):
                raise ValueError("managed road target_crs must be a projected CRS")
            units = {str(axis.unit_name or "").casefold() for axis in crs.axis_info}
            if not units or not units <= {"metre", "meter"}:
                raise ValueError("managed road target_crs must use metre linear units")
            return crs.to_string()
        west, south, east, north = boundary.bounds
        lon = (float(west) + float(east)) / 2.0
        lat = (float(south) + float(north)) / 2.0
        zone = max(1, min(60, int((lon + 180.0) // 6.0) + 1))
        epsg = (32600 if lat >= 0 else 32700) + zone
        return f"EPSG:{epsg}"

    def recipe_parameters(self, area: Area, boundary) -> dict[str, object]:
        return {
            "road_schema_version": MANAGED_ROAD_SCHEMA_VERSION,
            "selection_version": MANAGED_ROAD_SELECTION_VERSION,
            "projection_version": MANAGED_ROAD_PROJECTION_VERSION,
            "included_highway_values": sorted(MANAGED_HIGHWAY_VALUES),
            "excluded_access_values": sorted(MANAGED_ACCESS_EXCLUDED),
            "simplification": "none",
            "directionality": "undirected-linework-retain-osm-oneway-metadata",
            "clip_buffer_m": float(self.buffer_m),
            "target_crs": self.resolve_target_crs(area, boundary),
            "area_slug": area.slug,
        }

    def load(
        self,
        pbf_path: Path | str,
        *,
        area: Area,
        boundary,
        node_cache: Path | str | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> gpd.GeoDataFrame:
        target_crs = self.resolve_target_crs(area, boundary)
        return extract_geofabrik_roads(
            Path(pbf_path).expanduser().resolve(),
            boundary=boundary,
            target_crs=target_crs,
            buffer_m=float(self.buffer_m),
            node_cache=Path(node_cache).expanduser().resolve() if node_cache is not None else None,
            progress=progress,
        )


RoadSource: TypeAlias = FileRoadSource | GeofabrikRoadSource


def _selected_osm_road(highway: str | None, access: str | None) -> bool:
    highway_value = str(highway or "").strip().casefold()
    access_value = str(access or "").strip().casefold()
    return highway_value in MANAGED_HIGHWAY_VALUES and access_value not in MANAGED_ACCESS_EXCLUDED


def _line_parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, LineString):
        if geometry.length > 0:
            yield geometry
        return
    if isinstance(geometry, MultiLineString | GeometryCollection):
        for part in geometry.geoms:
            yield from _line_parts(part)


def _extract_pbf_road_candidates(
    pbf_path: Path,
    bbox: tuple[float, float, float, float],
    *,
    node_cache: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> gpd.GeoDataFrame:
    """Scan one PBF and return selected candidate ways intersecting a WGS84 bbox.

    The import stays local so the rest of SIGMA remains importable in environments
    where the optional-at-execution OSM parser is not installed yet.
    """
    try:
        import osmium
    except ImportError as exc:  # pragma: no cover - exercised in runtime preflight
        raise RuntimeError("managed Geofabrik roads require the declared 'osmium' dependency") from exc

    west, south, east, north = (float(value) for value in bbox)
    rows: list[dict[str, object]] = []
    wkbfab = osmium.geom.WKBFactory()

    class RoadHandler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways_seen = 0
            self.next_report = 1_000_000

        def way(self, way):
            self.ways_seen += 1
            if progress is not None and self.ways_seen >= self.next_report:
                progress(
                    f"managed roads: {self.ways_seen:,} OSM ways examined; "
                    f"{len(rows):,} candidate ways retained"
                )
                self.next_report += 1_000_000
            highway = way.tags.get("highway")
            access = way.tags.get("access")
            if not _selected_osm_road(highway, access):
                return
            try:
                geometry = shapely.wkb.loads(wkbfab.create_linestring(way), hex=True)
            except (RuntimeError, ValueError):
                return
            if geometry.is_empty or not isinstance(geometry, LineString):
                return
            minx, miny, maxx, maxy = geometry.bounds
            if maxx < west or minx > east or maxy < south or miny > north:
                return
            rows.append(
                {
                    "osm_way_id": int(way.id),
                    "highway": str(highway),
                    "access": str(access) if access is not None else None,
                    "name": str(way.tags.get("name")) if way.tags.get("name") is not None else None,
                    "oneway": str(way.tags.get("oneway")) if way.tags.get("oneway") is not None else None,
                    "bridge": str(way.tags.get("bridge")) if way.tags.get("bridge") is not None else None,
                    "tunnel": str(way.tags.get("tunnel")) if way.tags.get("tunnel") is not None else None,
                    "layer": str(way.tags.get("layer")) if way.tags.get("layer") is not None else None,
                    "geometry": geometry,
                }
            )

    handler = RoadHandler()
    if node_cache is None:
        index_spec = "flex_mem"
    else:
        node_cache.parent.mkdir(parents=True, exist_ok=True)
        index_spec = f"sparse_file_array,{node_cache}"
    if progress is not None:
        progress(f"managed roads: scanning shared Geofabrik PBF {pbf_path.name}")
    try:
        handler.apply_file(str(pbf_path), locations=True, idx=index_spec)
    except RuntimeError as exc:
        raise RuntimeError(f"managed Geofabrik road extraction failed: {exc}") from exc
    if progress is not None:
        progress(
            f"managed roads: PBF scan complete; {len(rows):,} candidate ways retained"
        )
    columns = [
        "osm_way_id", "highway", "access", "name", "oneway", "bridge", "tunnel", "layer"
    ]
    if not rows:
        return gpd.GeoDataFrame(
            {column: [] for column in columns},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
            crs="EPSG:4326",
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def extract_geofabrik_roads(
    pbf_path: Path,
    *,
    boundary,
    target_crs: str,
    buffer_m: float = MANAGED_ROAD_DEFAULT_BUFFER_M,
    node_cache: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> gpd.GeoDataFrame:
    """Extract, clip and project the pinned managed-road profile from one PBF."""
    if not pbf_path.is_file():
        raise FileNotFoundError(pbf_path)

    boundary_wgs84 = gpd.GeoSeries([boundary], crs="EPSG:4326")
    projected_boundary = boundary_wgs84.to_crs(target_crs)
    clip_geometry = projected_boundary.iloc[0].buffer(float(buffer_m))
    query_geometry = gpd.GeoSeries([clip_geometry], crs=target_crs).to_crs("EPSG:4326").iloc[0]
    candidates = _extract_pbf_road_candidates(
        pbf_path, tuple(query_geometry.bounds), node_cache=node_cache, progress=progress
    )
    if candidates.empty:
        raise ValueError("managed Geofabrik road selection produced no features for the area")

    projected = candidates.to_crs(target_crs)
    records: list[dict[str, object]] = []
    geometry_name = projected.geometry.name
    value_columns = [column for column in projected.columns if column != geometry_name]
    for _, row in projected.iterrows():
        clipped = row[geometry_name].intersection(clip_geometry)
        for part in _line_parts(clipped):
            record = {column: row[column] for column in value_columns}
            record["geometry"] = part
            records.append(record)
    if not records:
        raise ValueError("managed Geofabrik roads do not intersect the buffered area boundary")

    frame = gpd.GeoDataFrame(records, geometry="geometry", crs=target_crs)
    frame["_geometry_wkb"] = frame.geometry.apply(lambda geometry: geometry.wkb_hex)
    frame = (
        frame.sort_values(["osm_way_id", "_geometry_wkb"], kind="stable")
        .drop(columns="_geometry_wkb")
        .reset_index(drop=True)
    )
    return validate_road_frame(frame)


def validate_road_frame(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Validate the road-source contract without changing its geometry."""
    if frame.crs is None:
        raise ValueError("road network CRS is missing")
    if getattr(frame.crs, "is_geographic", False):
        raise ValueError("road network must use a projected CRS with linear units")
    if frame.empty:
        raise ValueError("road network contains no features")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("road network contains missing or empty geometry")
    allowed = {"LineString", "MultiLineString"}
    kinds = set(frame.geometry.geom_type.astype(str))
    invalid = sorted(kinds - allowed)
    if invalid:
        raise ValueError(f"road network must contain only line geometry; found {invalid}")
    return frame.copy()

"""Canonical SIGMA area and boundary model."""
from .boundary import (
    BoundaryResolver,
    boundary_identity,
    clip_points,
    load_boundary,
    materialize_area_boundary,
)
from .catalog import (
    Area,
    AreaCatalog,
    BoundarySpec,
    default_areas_path,
    list_areas,
    load_area_catalog,
    load_areas,
    resolve_area,
)

__all__ = [
    "Area",
    "BoundarySpec",
    "AreaCatalog",
    "BoundaryResolver",
    "default_areas_path",
    "load_areas",
    "load_area_catalog",
    "list_areas",
    "resolve_area",
    "load_boundary",
    "boundary_identity",
    "clip_points",
    "materialize_area_boundary",
]

"""Unified SIGMA place, network-spatial, and economic analysis package."""

from ._version import __version__
from .area import Area, AreaCatalog, BoundaryResolver, BoundarySpec
from .config import (
    AnalysisConfig, EconomicConfig, ExportConfig, PlaceConfig, SigmaConfig,
    SourceConfig, SpatialConfig, TransportConfig,
)
from .classification import PsicTaxonomy, TaggingReferences
from .economy import Economy, Sector, SectorCatalog
from .workspace import SigmaWorkspace
from .transport import FileRoadSource, GeofabrikRoadSource, RoadSource
from .export import ExportBundle
from .facade import (
    AnalysisArtifacts, EconomicArtifacts, PlaceArtifacts, Sigma, SigmaResult,
    SpatialArtifacts, TransportArtifacts, WorkflowStatus,
)
from .errors import (
    AreaValidationError,
    ArtifactValidationError,
    CompatibilityError,
    ConfigurationError,
    EconomyValidationError,
    SigmaError,
    SourceError,
    StageExecutionError,
    TaxonomyValidationError,
    ValidationError,
)

__all__ = [
    "__version__",
    "SigmaConfig",
    "SourceConfig",
    "PlaceConfig",
    "TransportConfig",
    "SpatialConfig",
    "EconomicConfig",
    "AnalysisConfig",
    "ExportConfig",
    "Sigma",
    "SigmaResult",
    "WorkflowStatus",
    "PlaceArtifacts",
    "TransportArtifacts",
    "SpatialArtifacts",
    "EconomicArtifacts",
    "AnalysisArtifacts",
    "ExportBundle",
    "SigmaWorkspace",
    "RoadSource",
    "FileRoadSource",
    "GeofabrikRoadSource",
    "Area",
    "BoundarySpec",
    "AreaCatalog",
    "BoundaryResolver",
    "PsicTaxonomy",
    "TaggingReferences",
    "Economy",
    "Sector",
    "SectorCatalog",
    "SigmaError",
    "ConfigurationError",
    "ValidationError",
    "AreaValidationError",
    "EconomyValidationError",
    "TaxonomyValidationError",
    "ArtifactValidationError",
    "SourceError",
    "StageExecutionError",
    "CompatibilityError",
]

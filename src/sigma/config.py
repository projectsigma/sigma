"""Immutable public configuration values for the unified SIGMA facade.

The facade owns only configuration composition. Domain pipelines continue to own
execution and translate these value objects into their proven run-config types.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Literal

from ._version import __version__


@dataclass(frozen=True, slots=True)
class SourceConfig:
    source_store: Path | str | None = None
    refresh_geofabrik: bool = False
    refresh_overture: bool = False


@dataclass(frozen=True, slots=True)
class PlaceConfig:
    clip: bool = True
    use_llm: bool = False
    top_n: int = 5
    min_score: float = 0.45
    min_margin: float = 0.12
    llm_retrieval_top_n: int = 20


@dataclass(frozen=True, slots=True)
class TransportConfig:
    roads_layer: str | None = None


@dataclass(frozen=True, slots=True)
class SpatialConfig:
    economy_column: str = "economy_code"
    classification: Literal["io80", "io16"] | None = None
    classification_column: str | None = None
    io80_column: str | None = None
    io16_column: str | None = None
    vertex_digits: int = 11
    max_snap_distance: float | None = None
    min_cluster_size: int = 5
    min_samples: int | None = None
    cluster_selection_method: Literal["eom", "leaf"] = "eom"
    allow_single_cluster: bool = False
    hdbscan_max_distance: float = 5_000.0
    hdbscan_distance_mode: Literal["adaptive", "fixed"] = "adaptive"
    hdbscan_min_distance: float | None = None
    hdbscan_distance_growth: float = 1.5
    hdbscan_distance_steps: int = 4
    hdbscan_core_truncation_tolerance: float = 0.01
    hdbscan_stability_tolerance: float = 1e-12
    hdbscan_max_neighbor_pairs: int = 20_000_000
    voronoi_resolution: float = 500.0
    voronoi_max_cells: int = 1_000_000
    voronoi_refine_factor: float = 0.5
    voronoi_max_refinements: int = 5


@dataclass(frozen=True, slots=True)
class EconomicConfig:
    transaction_preprocessing: Literal["none", "mwas_ras_fast"] = "none"
    legacy_mwas_method: Literal["fast", "exact"] | None = None
    ras_absolute_tolerance: float = 1e-8
    ras_relative_tolerance: float = 1e-10
    ras_max_iterations: int = 10_000


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    centrality_method: Literal["katz", "eigenvector"] = "katz"
    # Compatibility-only for direct one-sided callers; canonical Katz uses both directions.
    centrality_direction: Literal["incoming", "outgoing"] = "incoming"
    katz_alpha_factor: float = 0.85
    katz_beta: float = 1.0
    distance_tempering: float = 0.15


@dataclass(frozen=True, slots=True)
class ExportConfig:
    compatibility: bool = True
    unified: bool = True


@dataclass(frozen=True)
class SigmaConfig:
    """Small immutable aggregate aligned with real SIGMA domain boundaries."""

    sources: SourceConfig = field(default_factory=SourceConfig)
    places: PlaceConfig = field(default_factory=PlaceConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    spatial: SpatialConfig = field(default_factory=SpatialConfig)
    economic: EconomicConfig = field(default_factory=EconomicConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    export: ExportConfig = field(default_factory=ExportConfig)

    @classmethod
    def default(cls) -> "SigmaConfig":
        return cls()

    @classmethod
    def equivalent(cls, *, mwas_method: Literal["fast", "exact"] = "fast") -> "SigmaConfig":
        """Legacy Engine regression profile; distinct from the canonical default."""
        if mwas_method not in {"fast", "exact"}:
            raise ValueError("mwas_method must be 'fast' or 'exact'")
        return cls(
            spatial=SpatialConfig(classification="io80"),
            economic=EconomicConfig(
                transaction_preprocessing="none",
                legacy_mwas_method=mwas_method,
            ),
            analysis=AnalysisConfig(centrality_method="eigenvector"),
        )

    @property
    def fingerprint(self) -> str:
        def normalize(value, *, key: str | None = None):
            if isinstance(value, Path):
                return str(value.expanduser().resolve())
            if key == "source_store" and isinstance(value, str) and value.strip():
                return str(Path(value).expanduser().resolve())
            if isinstance(value, dict):
                return {str(k): normalize(v, key=str(k)) for k, v in sorted(value.items())}
            if isinstance(value, (list, tuple)):
                return [normalize(v) for v in value]
            return value

        payload = normalize(asdict(self))
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()


# Preserved Siphon model-backend defaults.
DEFAULT_LLM_MODEL = "gpt-5.6-luna"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"

# Preserved Siphon source defaults.
DEFAULT_GEOFABRIK_PAGE_URL = "https://download.geofabrik.de/asia/philippines.html"
DEFAULT_GEOFABRIK_MAX_AGE_DAYS = 7.0
DEFAULT_DOWNLOAD_USER_AGENT = f"SIGMA/{__version__}"

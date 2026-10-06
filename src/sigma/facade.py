"""Public SIGMA facade.

C16 deliberately keeps this module orchestration-only: it selects domain pipelines,
asks their existing ExecutionPlanner instances for targets, and packages ArtifactRefs.
No numerical, classification, source-acquisition, or export algorithm lives here.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .analysis import AnalysisPipeline, AnalysisRunConfig
from .area import Area, AreaCatalog
from .artifacts import ArtifactRef, ArtifactValidation
from .classification import PsicTaxonomy, TaggingReferences
from .config import SigmaConfig
from .economy import Economy, EconomyPipeline, EconomyRunConfig
from .export import ExportBundle, ExportPipeline
from .errors import CompatibilityError, ConfigurationError
from .places.pipeline import PlacePipeline, PlaceRunConfig, PlaceServices
from .spatial import RestartRunConfig, RestartSpatialPipeline, SpatialPipeline, SpatialRunConfig
from .transport import FileRoadSource, GeofabrikRoadSource, RoadSource
from .workspace import SigmaWorkspace


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


_SHAPEFILE_EXTENSIONS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx")


def _dataset_sha256(path: Path) -> str:
    """Hash one file, or the complete same-stem Shapefile dataset when applicable."""
    path = path.expanduser().resolve()
    if path.suffix.casefold() != ".shp":
        return _file_sha256(path)
    members = []
    for suffix in _SHAPEFILE_EXTENSIONS:
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            members.append((candidate.name.casefold(), _file_sha256(candidate)))
    if not members:
        raise FileNotFoundError(path)
    raw = json.dumps(sorted(members), separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _validate_existing_workspace_paths(
    workspace: SigmaWorkspace,
    *,
    output_dir: Path | str | None,
    source_store: Path | str | None,
) -> None:
    """Reject explicit path arguments that conflict with durable workspace configuration."""
    if output_dir is not None:
        requested_output = Path(output_dir).expanduser().resolve()
        if requested_output != workspace.output_dir.expanduser().resolve():
            raise ConfigurationError(
                f"existing workspace output_dir is {workspace.output_dir}; "
                f"requested {requested_output}"
            )
    if source_store is not None:
        requested_store = Path(source_store).expanduser().resolve()
        if requested_store != workspace.sources.root.expanduser().resolve():
            raise ConfigurationError(
                f"existing workspace source_store is {workspace.sources.root}; "
                f"requested {requested_store}"
            )


def _custom_area_identity(boundary: Path, layer: str | None, label: str | None) -> str:
    payload = {
        "kind": "custom-boundary",
        "sha256": _dataset_sha256(boundary),
        "layer": layer,
        "label": label,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PlaceArtifacts:
    canonical: ArtifactRef
    psic_classified: ArtifactRef
    classified_places: ArtifactRef

    @property
    def classified(self) -> ArtifactRef:
        return self.classified_places


@dataclass(frozen=True, slots=True)
class TransportArtifacts:
    roads: ArtifactRef


@dataclass(frozen=True, slots=True)
class SpatialArtifacts:
    normalized_points: ArtifactRef | None
    clustered_points: ArtifactRef | None
    centers: ArtifactRef
    points_with_center_distance: ArtifactRef
    partitions: ArtifactRef

    @property
    def points(self) -> ArtifactRef:
        return self.normalized_points

    @property
    def clusters(self) -> ArtifactRef:
        return self.clustered_points

    @property
    def point_distances(self) -> ArtifactRef:
        return self.points_with_center_distance


@dataclass(frozen=True, slots=True)
class EconomicArtifacts:
    economy_definition: ArtifactRef
    transactions_raw: ArtifactRef
    transactions_effective: ArtifactRef
    technical_coefficients: ArtifactRef
    graph: ArtifactRef

    @property
    def definition(self) -> ArtifactRef:
        return self.economy_definition

    @property
    def coefficients(self) -> ArtifactRef:
        return self.technical_coefficients


@dataclass(frozen=True, slots=True)
class AnalysisArtifacts:
    x_graph: ArtifactRef
    centrality: ArtifactRef
    scored_points: ArtifactRef


@dataclass(frozen=True, slots=True)
class SigmaResult:
    places: PlaceArtifacts | None
    transport: TransportArtifacts
    spatial: SpatialArtifacts
    economic: EconomicArtifacts
    analysis: AnalysisArtifacts
    outputs: Mapping[str, Path]
    run_manifest: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))


@dataclass(frozen=True, slots=True)
class WorkflowStatus:
    stages: Mapping[str, ArtifactValidation]

    def __post_init__(self) -> None:
        object.__setattr__(self, "stages", MappingProxyType(dict(self.stages)))

    def __getitem__(self, stage: str) -> ArtifactValidation:
        return self.stages[stage]

    def stage(self, stage: str) -> ArtifactValidation:
        return self.stages[stage]


class _TransportComponent:
    """Advanced direct access to the managed ``transport.roads`` target."""

    def __init__(self, owner: "Sigma"):
        self._owner = owner

    @property
    def source(self) -> RoadSource | None:
        return self._owner._roads

    def prepare(self, *, force: bool = False) -> ArtifactRef:
        return self._owner.prepare_network(force=force).roads


class _ComponentView:
    def __init__(self, owner: "Sigma"):
        self._owner = owner

    @property
    def places(self) -> PlacePipeline | None:
        return self._owner._place_pipeline()

    @property
    def transport(self) -> _TransportComponent:
        return _TransportComponent(self._owner)

    @property
    def spatial(self) -> SpatialPipeline | None:
        return self._owner._spatial_pipeline()

    @property
    def economy(self) -> EconomyPipeline:
        return self._owner._economy_pipeline()

    @property
    def analysis(self) -> AnalysisPipeline | None:
        return self._owner._analysis_pipeline()

    @property
    def exports(self) -> ExportPipeline | None:
        return self._owner._export_pipeline()


class Sigma:
    """Thin public orchestration facade over the proven managed stage pipelines."""

    def __init__(
        self,
        area: str | Area,
        *,
        workspace: Path | str,
        roads: Path | str | RoadSource | None = None,
        roads_layer: str | None = None,
        output_dir: Path | str | None = None,
        source_store: Path | str | None = None,
        economy: Economy | None = None,
        psic: PsicTaxonomy | None = None,
        tagging_references: TaggingReferences | None = None,
        config: SigmaConfig | None = None,
        areas_file: Path | str | None = None,
        progress=None,
        place_services: PlaceServices | None = None,
    ):
        self.config = config or SigmaConfig.default()
        self.economy = economy or Economy.default()
        self._psic = psic
        self._tagging_references = tagging_references
        if psic is not None and tagging_references is not None:
            tagging_references.validate_for(psic, self.economy)
        self.progress = progress
        # All planners created by one Sigma facade share transient run state. This keeps
        # refresh/acquisition identities stable across analysis and export in one run().
        self._runtime_cache: dict[str, object] = {}
        self._runtime_depth = 0
        self.areas_file = Path(areas_file).expanduser().resolve() if areas_file is not None else None
        catalog = AreaCatalog(self.areas_file)
        self.area = area if isinstance(area, Area) else catalog.resolve(str(area))
        self._mode = "area"
        self._points_path: Path | None = None
        self._points_layer: str | None = None
        self._boundary_path: Path | None = None
        self._boundary_layer: str | None = None
        self._roads: RoadSource | None = self._coerce_roads(roads, roads_layer)
        self._place_services_input = place_services
        root = Path(workspace).expanduser().resolve()
        store = source_store if source_store is not None else self.config.sources.source_store
        if (root / "workspace.json").exists():
            self.workspace = SigmaWorkspace.open(root, area=self.area)
            _validate_existing_workspace_paths(
                self.workspace, output_dir=output_dir, source_store=store
            )
        else:
            self.workspace = SigmaWorkspace.create(
                root,
                area=self.area,
                source_store=store,
                output_dir=output_dir,
                economy_fingerprint=self.economy.economy_fingerprint,
                taxonomy_fingerprint=psic.fingerprint if psic is not None else None,
                tagging_fingerprint=tagging_references.fingerprint if tagging_references is not None else None,
                config_fingerprint=self.config.fingerprint,
            )
        self._places: PlacePipeline | None = None
        self._spatial: SpatialPipeline | None = None
        self._economic: EconomyPipeline | None = None
        self._analysis: AnalysisPipeline | None = None
        self._exports: ExportPipeline | None = None
        self.components = _ComponentView(self)

    @classmethod
    def from_inputs(
        cls,
        *,
        workspace: Path | str,
        points: Path | str,
        roads: Path | str,
        boundary: Path | str,
        points_layer: str | None = None,
        roads_layer: str | None = None,
        boundary_layer: str | None = None,
        economy: Economy | None = None,
        classification: str | None = None,
        output_dir: Path | str | None = None,
        source_store: Path | str | None = None,
        config: SigmaConfig | None = None,
        label: str | None = None,
        progress=None,
    ) -> "Sigma":
        if classification is not None:
            normalized = str(classification).strip().casefold()
            if normalized not in {"io80", "io16"}:
                raise ConfigurationError("legacy classification must be 'io80' or 'io16'")
            if economy is not None:
                raise ConfigurationError("pass either economy or legacy classification, not both")
            economy = Economy.builtin(normalized)
        economy = economy or Economy.default()
        config = config or SigmaConfig.default()
        boundary_path = Path(boundary).expanduser().resolve()
        if not boundary_path.is_file():
            raise FileNotFoundError(boundary_path)
        root = Path(workspace).expanduser().resolve()
        identity = _custom_area_identity(boundary_path, boundary_layer, label)

        self = cls.__new__(cls)
        self.config = config
        self.economy = economy
        self._psic = None
        self._tagging_references = None
        self.progress = progress
        self._runtime_cache = {}
        self._runtime_depth = 0
        self.areas_file = None
        self.area = None
        self._mode = "inputs"
        self._points_path = Path(points).expanduser().resolve()
        self._points_layer = points_layer
        self._boundary_path = boundary_path
        self._boundary_layer = boundary_layer
        self._roads = FileRoadSource(roads, roads_layer or config.transport.roads_layer)
        self._place_services_input = None
        store = source_store if source_store is not None else config.sources.source_store
        if (root / "workspace.json").exists():
            self.workspace = SigmaWorkspace.open(root, area_identity=identity)
            _validate_existing_workspace_paths(
                self.workspace, output_dir=output_dir, source_store=store
            )
        else:
            self.workspace = SigmaWorkspace.create(
                root,
                area_identity=identity,
                source_store=store,
                output_dir=output_dir,
                economy_fingerprint=economy.economy_fingerprint,
                config_fingerprint=config.fingerprint,
            )
        self._places = None
        self._spatial = None
        self._economic = None
        self._analysis = None
        self._exports = None
        self.components = _ComponentView(self)
        return self

    @classmethod
    def from_partitions(
        cls,
        *,
        workspace: Path | str,
        partitions: Path | str,
        centers: Path | str,
        points_with_center_distance: Path | str,
        roads: Path | str,
        roads_layer: str | None = None,
        economy: Economy | None = None,
        output_dir: Path | str | None = None,
        source_store: Path | str | None = None,
        config: SigmaConfig | None = None,
        progress=None,
    ) -> "Sigma":
        economy = economy or Economy.default()
        config = config or SigmaConfig.equivalent()
        paths = [Path(value).expanduser().resolve() for value in (partitions, centers, points_with_center_distance, roads)]
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(path)
        root = Path(workspace).expanduser().resolve()
        identity_payload = {
            "kind": "legacy-from-partitions",
            "files": {path.name: _dataset_sha256(path) for path in paths},
            "roads_layer": roads_layer,
        }
        identity = hashlib.sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self = cls.__new__(cls)
        self.config = config
        self.economy = economy
        self._psic = None
        self._tagging_references = None
        self.progress = progress
        self._runtime_cache = {}
        self._runtime_depth = 0
        self.areas_file = None
        self.area = None
        self._mode = "restart"
        self._points_path = None
        self._points_layer = None
        self._boundary_path = None
        self._boundary_layer = None
        self._roads = FileRoadSource(roads, roads_layer or config.transport.roads_layer)
        self._place_services_input = None
        store = source_store if source_store is not None else config.sources.source_store
        if (root / "workspace.json").exists():
            self.workspace = SigmaWorkspace.open(root, area_identity=identity)
            _validate_existing_workspace_paths(
                self.workspace, output_dir=output_dir, source_store=store
            )
        else:
            self.workspace = SigmaWorkspace.create(
                root, area_identity=identity, source_store=store, output_dir=output_dir,
                economy_fingerprint=economy.economy_fingerprint, config_fingerprint=config.fingerprint,
            )
        self._restart_paths = {
            "partitions": paths[0], "centers": paths[1],
            "points": paths[2], "roads": paths[3],
        }
        self._places = None
        self._spatial = None
        self._economic = None
        self._analysis = None
        self._exports = None
        self.components = _ComponentView(self)
        return self

    def _coerce_roads(
        self, roads: Path | str | RoadSource | None, roads_layer: str | None
    ) -> RoadSource | None:
        if roads is None:
            if self._mode == "area":
                if roads_layer is not None or self.config.transport.roads_layer is not None:
                    raise ConfigurationError(
                        "roads_layer requires an explicit file road source; "
                        "managed Geofabrik roads are the area-mode default"
                    )
                return GeofabrikRoadSource()
            return None
        if isinstance(roads, FileRoadSource):
            if roads_layer is not None and roads.layer != roads_layer:
                raise ConfigurationError("roads_layer conflicts with the supplied FileRoadSource")
            return roads
        if isinstance(roads, GeofabrikRoadSource):
            if roads_layer is not None:
                raise ConfigurationError("roads_layer is not applicable to GeofabrikRoadSource")
            if self.config.transport.roads_layer is not None:
                raise ConfigurationError(
                    "config.transport.roads_layer is not applicable to GeofabrikRoadSource"
                )
            return roads
        return FileRoadSource(roads, roads_layer or self.config.transport.roads_layer)

    def _place_services(self) -> PlaceServices:
        base = self._place_services_input or PlaceServices()
        # Copy so caller-owned test/provider seams are never mutated.
        services = PlaceServices(
            geofabrik=base.geofabrik,
            overture=base.overture,
            load_overture=base.load_overture,
            load_prepared_osm=base.load_prepared_osm,
            taxonomy=base.taxonomy,
            references=base.references,
        )
        if self._psic is not None:
            services.taxonomy = lambda: self._psic
        if self._tagging_references is not None:
            services.references = lambda taxonomy, economy: self._tagging_references
        return services

    def _place_run_config(self) -> PlaceRunConfig:
        p, s = self.config.places, self.config.sources
        return PlaceRunConfig(
            clip=p.clip,
            refresh_geofabrik=s.refresh_geofabrik,
            refresh_overture=s.refresh_overture,
            use_llm=p.use_llm,
            top_n=p.top_n,
            min_score=p.min_score,
            min_margin=p.min_margin,
            llm_retrieval_top_n=p.llm_retrieval_top_n,
        )

    def _spatial_run_config(self) -> SpatialRunConfig:
        s = self.config.spatial
        return SpatialRunConfig(**{name: getattr(s, name) for name in s.__dataclass_fields__})

    def _economy_run_config(self) -> EconomyRunConfig:
        e = self.config.economic
        return EconomyRunConfig(
            transaction_preprocessing=e.transaction_preprocessing,
            ras_absolute_tolerance=e.ras_absolute_tolerance,
            ras_relative_tolerance=e.ras_relative_tolerance,
            ras_max_iterations=e.ras_max_iterations,
            legacy_mwas_method=e.legacy_mwas_method,
        )

    def _analysis_run_config(self) -> AnalysisRunConfig:
        a = self.config.analysis
        return AnalysisRunConfig(
            centrality_method=a.centrality_method,
            centrality_direction=a.centrality_direction,
            katz_alpha_factor=a.katz_alpha_factor,
            katz_beta=a.katz_beta,
            distance_tempering=a.distance_tempering,
        )

    def _place_pipeline(self) -> PlacePipeline | None:
        if self._mode != "area":
            return None
        if self._places is None:
            assert self.area is not None
            self._places = PlacePipeline(
                self.workspace,
                area=self.area,
                economy=self.economy,
                config=self._place_run_config(),
                areas_file=self.areas_file,
                services=self._place_services(),
                progress=self.progress,
            )
            self._places.planner.runtime = self._runtime_cache
        return self._places

    @property
    def places_path(self) -> Path:
        if self._mode != "area":
            raise ConfigurationError("places handoff is available only in area mode")
        return self.workspace.root / "places" / "places.parquet"

    def _require_loaded_places(self) -> Path:
        path = self.places_path
        if not path.is_file():
            slug = self.area.slug if self.area is not None else "<area>"
            raise ConfigurationError(
                "analysis requires a loaded places GeoParquet. Run "
                f"'sigma load {slug}' first (or pass --workspace if using a custom workspace). "
                f"You may inspect or filter {path} before running the analysis."
            )
        return path

    def _publish_places_handoff(self, ref: ArtifactRef) -> Path:
        pipeline = self._place_pipeline()
        assert pipeline is not None
        frame = pipeline.read_classified(ref)
        if "canonical_id" not in frame.columns and "poi_id" in frame.columns:
            frame = frame.copy()
            frame["canonical_id"] = frame["poi_id"]
        target = self.places_path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp.parquet")
        frame.to_parquet(tmp, index=False)
        tmp.replace(target)
        metadata = {
            "schema_version": 1,
            "area_slug": self.area.slug if self.area is not None else None,
            "rows": int(len(frame)),
            "economy_id": self.economy.economy_id,
            "classified_places_artifact_id": ref.artifact_id,
            "editable_handoff": True,
            "path": str(target),
        }
        (target.parent / "places.meta.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if self.progress is not None:
            self.progress(
                f"loaded places handoff: {target} ({len(frame):,} rows); "
                "this GeoParquet may be filtered before analysis"
            )
        return target

    def _require_roads(self) -> RoadSource:
        if self._roads is None:
            raise ConfigurationError(
                "a projected road source is required for custom-input/restart mode"
            )
        return self._roads

    def _spatial_pipeline(self) -> SpatialPipeline | None:
        if self._roads is None:
            return None
        if self._spatial is None:
            roads = self._require_roads()
            if self._mode == "restart":
                rp = self._restart_paths
                self._spatial = RestartSpatialPipeline(
                    self.workspace, roads=roads, partitions=rp["partitions"],
                    centers=rp["centers"], points_with_center_distance=rp["points"],
                    config=RestartRunConfig(vertex_digits=self.config.spatial.vertex_digits),
                    economy=self.economy, progress=self.progress,
                )
            elif self._mode == "area":
                self._spatial = SpatialPipeline(
                    self.workspace,
                    roads=roads,
                    economy=self.economy,
                    config=self._spatial_run_config(),
                    place_pipeline=self._place_pipeline(),
                    points_path=self._require_loaded_places(),
                    progress=self.progress,
                )
            else:
                assert self._points_path is not None and self._boundary_path is not None
                self._spatial = SpatialPipeline(
                    self.workspace,
                    roads=roads,
                    economy=self.economy,
                    config=self._spatial_run_config(),
                    points_path=self._points_path,
                    points_layer=self._points_layer,
                    boundary_path=self._boundary_path,
                    boundary_layer=self._boundary_layer,
                    progress=self.progress,
                )
            self._spatial.planner.runtime = self._runtime_cache
        return self._spatial

    def _economy_pipeline(self) -> EconomyPipeline:
        if self._economic is None:
            self._economic = EconomyPipeline(
                self.workspace,
                economy=self.economy,
                config=self._economy_run_config(),
                progress=self.progress,
            )
            self._economic.planner.runtime = self._runtime_cache
        return self._economic

    def _analysis_pipeline(self) -> AnalysisPipeline | None:
        spatial = self._spatial_pipeline()
        if spatial is None:
            return None
        if self._analysis is None:
            self._analysis = AnalysisPipeline(
                self.workspace,
                spatial_pipeline=spatial,
                economy_pipeline=self._economy_pipeline(),
                config=self._analysis_run_config(),
                progress=self.progress,
            )
            self._analysis.planner.runtime = self._runtime_cache
        return self._analysis

    @property
    def psic(self) -> PsicTaxonomy | None:
        if self._mode != "area":
            return self._psic
        pipeline = self._place_pipeline()
        assert pipeline is not None
        if self._psic is None:
            self._psic = pipeline._taxonomy_obj()
        return self._psic

    @property
    def tagging_references(self) -> TaggingReferences | None:
        if self._mode != "area":
            return self._tagging_references
        pipeline = self._place_pipeline()
        assert pipeline is not None
        if self._tagging_references is None:
            self._tagging_references = pipeline._reference_obj()
        return self._tagging_references

    def _export_pipeline(self) -> ExportPipeline | None:
        analysis = self._analysis_pipeline()
        spatial = self._spatial_pipeline()
        if analysis is None or spatial is None:
            return None
        if self._exports is None:
            self._exports = ExportPipeline(
                self.workspace, analysis_pipeline=analysis, spatial_pipeline=spatial,
                economy_pipeline=self._economy_pipeline(), place_pipeline=self._place_pipeline(),
                compatibility=self.config.export.compatibility, unified=self.config.export.unified,
                progress=self.progress,
            )
            self._exports.planner.runtime = self._runtime_cache
        return self._exports

    @contextmanager
    def _execution_scope(self):
        """Give one public execution operation a fresh shared planner runtime.

        Pipelines are cached on the facade, so their planners outlive an individual
        ``run()`` call.  Runtime entries such as refreshed source references and
        provisional-artifact identities must not: they are shared only among the
        nested planner calls that make up one public operation.
        """
        outermost = self._runtime_depth == 0
        if outermost:
            self._runtime_cache.clear()
        self._runtime_depth += 1
        try:
            yield
        finally:
            self._runtime_depth -= 1

    def _planner_for(self, stage: str):
        # Independent place/economy targets must remain usable before the loaded-place
        # handoff exists.  Only spatial/analysis/export targets require that handoff.
        place = self._place_pipeline()
        if place is not None and stage in place.planner.stages:
            return place.planner
        economy = self._economy_pipeline()
        if stage in economy.planner.stages:
            return economy.planner
        analysis = self._analysis_pipeline()
        if analysis is not None and stage in analysis.planner.stages:
            return analysis.planner
        exports = self._export_pipeline()
        if exports is not None and stage in exports.planner.stages:
            return exports.planner
        raise KeyError(f"unknown or unavailable SIGMA stage: {stage}")

    def ensure(self, stage: str, *, force: bool = False) -> ArtifactRef:
        with self._execution_scope():
            if stage == "export.bundle":
                exports = self._export_pipeline()
                if exports is None:
                    raise ConfigurationError("export.bundle is unavailable without spatial inputs")
                return exports.ensure_bundle()
            return self._planner_for(stage).ensure(stage, force=force)

    def recompute(self, stage: str) -> ArtifactRef:
        return self.ensure(stage, force=True)

    def load(self, *, force: bool = False) -> PlaceArtifacts:
        with self._execution_scope():
            pipeline = self._place_pipeline()
            if pipeline is None:
                raise ConfigurationError("load() is unavailable for Sigma.from_inputs()")
            classified = pipeline.load(force=force)
            self._publish_places_handoff(classified)
            canonical = self.workspace.artifact("places.canonical")
            psic = self.workspace.artifact("places.psic")
            assert canonical is not None and psic is not None
            return PlaceArtifacts(canonical, psic, classified)

    def prepare_network(
        self,
        roads: Path | str | RoadSource | None = None,
        *,
        layer: str | None = None,
        force: bool = False,
    ) -> TransportArtifacts:
        with self._execution_scope():
            if roads is not None:
                proposed = self._coerce_roads(roads, layer)
                if self._spatial is not None and proposed != self._roads:
                    raise ConfigurationError(
                        "road source cannot be changed after spatial components are initialized"
                    )
                self._roads = proposed
            if self._mode == "area":
                roads_source = self._require_roads()
                spatial = SpatialPipeline(
                    self.workspace,
                    roads=roads_source,
                    economy=self.economy,
                    config=self._spatial_run_config(),
                    place_pipeline=self._place_pipeline(),
                    progress=self.progress,
                )
                spatial.planner.runtime = self._runtime_cache
            else:
                spatial = self._spatial_pipeline()
                if spatial is None:
                    self._require_roads()
                    raise AssertionError("unreachable")
            return TransportArtifacts(spatial.planner.ensure("transport.roads", force=force))

    def run_spatial(self, *, force: bool = False) -> SpatialArtifacts:
        with self._execution_scope():
            spatial = self._spatial_pipeline()
            if spatial is None:
                self._require_roads()
                raise AssertionError("unreachable")
            if self._mode == "restart":
                centers, partitions, point_distances = spatial.prepare_imports(force=force)
                return SpatialArtifacts(None, None, centers, point_distances, partitions)
            # Partitions and point distances are siblings downstream of clustering/centers.
            point_distances = spatial.prepare_point_distances(force=force)
            partitions = spatial.prepare_partitions(force=force)
            return self._spatial_artifacts(
                point_distances=point_distances, partitions=partitions
            )

    def _spatial_artifacts(
        self,
        *,
        point_distances: ArtifactRef | None = None,
        partitions: ArtifactRef | None = None,
    ) -> SpatialArtifacts:
        required = {
            "normalized_points": self.workspace.artifact("spatial.points"),
            "clustered_points": self.workspace.artifact("spatial.clusters"),
            "centers": self.workspace.artifact("spatial.centers"),
            "points_with_center_distance": point_distances or self.workspace.artifact("spatial.point_distances"),
            "partitions": partitions or self.workspace.artifact("spatial.partitions"),
        }
        missing = [name for name, ref in required.items() if ref is None]
        if missing:
            raise RuntimeError(f"spatial branch is incomplete: {', '.join(missing)}")
        return SpatialArtifacts(**required)  # type: ignore[arg-type]

    def run_economy(self, *, force: bool = False) -> EconomicArtifacts:
        with self._execution_scope():
            pipeline = self._economy_pipeline()
            graph = pipeline.graph(force=force)
            return self._economic_artifacts(graph=graph)

    def _economic_artifacts(self, *, graph: ArtifactRef | None = None) -> EconomicArtifacts:
        required = {
            "economy_definition": self.workspace.artifact("economy.definition"),
            "transactions_raw": self.workspace.artifact("economy.transactions.raw"),
            "transactions_effective": self.workspace.artifact("economy.transactions.effective"),
            "technical_coefficients": self.workspace.artifact("economy.coefficients"),
            "graph": graph or self.workspace.artifact(self._economy_pipeline().analysis_graph_stage),
        }
        missing = [name for name, ref in required.items() if ref is None]
        if missing:
            raise RuntimeError(f"economic branch is incomplete: {', '.join(missing)}")
        return EconomicArtifacts(**required)  # type: ignore[arg-type]

    def run_analysis(self, *, force: bool = False) -> AnalysisArtifacts:
        with self._execution_scope():
            analysis = self._analysis_pipeline()
            if analysis is None:
                self._require_roads()
                raise AssertionError("unreachable")
            score = analysis.scores(force=force)
            x = self.workspace.artifact("analysis.x")
            centrality = self.workspace.artifact("analysis.centrality")
            assert x is not None and centrality is not None
            return AnalysisArtifacts(x, centrality, score)

    def run(self, *, force: bool = False) -> SigmaResult:
        with self._execution_scope():
            analysis = self.run_analysis(force=force)
            spatial = (
                self.run_spatial(force=False)
                if self._mode == "restart"
                else self._spatial_artifacts()
            )
            economic = self._economic_artifacts()
            roads = self.workspace.artifact("transport.roads")
            if roads is None:
                raise RuntimeError("transport branch is incomplete")
            places_ref = self.workspace.artifact("places.classified")
            places = None
            if places_ref is not None:
                canonical = self.workspace.artifact("places.canonical")
                psic = self.workspace.artifact("places.psic")
                assert canonical is not None and psic is not None
                places = PlaceArtifacts(canonical, psic, places_ref)
            bundle = self.export()
            return SigmaResult(
                places=places,
                transport=TransportArtifacts(roads),
                spatial=spatial,
                economic=economic,
                analysis=analysis,
                outputs=bundle.files,
                run_manifest=bundle.run_manifest,
            )

    def export(self, *, force: bool = False) -> ExportBundle:
        with self._execution_scope():
            exports = self._export_pipeline()
            if exports is None:
                raise ConfigurationError("export requires configured spatial inputs")
            # ``force`` means republish the valid immutable bundle; container formats such
            # as GeoPackage are not regenerated under an identical recipe.
            ref = exports.ensure_bundle()
            return exports.publish(ref)

    def status(self) -> WorkflowStatus:
        # Prefer the maximal combined planner when roads are configured. Its inspection
        # mode never refreshes/acquires sources merely to answer status().
        exports = self._export_pipeline()
        if exports is not None:
            return WorkflowStatus(exports.planner.status())
        analysis = self._analysis_pipeline()
        if analysis is not None:
            return WorkflowStatus(analysis.planner.status())
        stages: dict[str, ArtifactValidation] = {}
        place = self._place_pipeline()
        if place is not None:
            stages.update(place.planner.status())
        stages.update(self._economy_pipeline().planner.status())
        return WorkflowStatus(stages)

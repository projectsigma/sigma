"""Thin Typer CLI for the unified SIGMA Python API.

C18 keeps orchestration in :class:`sigma.Sigma`: commands parse user-facing
arguments, build immutable public config/domain objects, invoke one public API
operation, and render the result.  No stage ordering or analytical algorithm
lives in this module.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import importlib.util
from importlib import resources
import json
import time
from pathlib import Path
from typing import Any

import typer

from . import __version__
from .area import AreaCatalog
from .classification import PsicTaxonomy, TaggingReferences
from .classification.reference import _canonical_manifest_bytes
from .config import (
    AnalysisConfig,
    EconomicConfig,
    ExportConfig,
    PlaceConfig,
    SigmaConfig,
    SourceConfig,
    SpatialConfig,
    TransportConfig,
)
from .economy import Economy
from .errors import SigmaError
from .facade import Sigma
from .initialization import initialize, load_initialization, require_initialization
from .paths import sigma_home, source_store_root
from .transport import GeofabrikRoadSource, RoadSource

app = typer.Typer(help="Unified SIGMA place, spatial-network, and economic analysis.", no_args_is_help=True, invoke_without_command=True)
network_app = typer.Typer(help="Road/network preparation.", no_args_is_help=True)
spatial_app = typer.Typer(help="Spatial clustering/centers/partitions.", no_args_is_help=True)
economy_app = typer.Typer(help="Economic-table and directed-graph stages.", no_args_is_help=True)
analysis_app = typer.Typer(help="X, centrality, and point-score stages.", no_args_is_help=True)
areas_app = typer.Typer(help="Inspect the canonical area catalog.", no_args_is_help=True)
app.add_typer(network_app, name="network")
app.add_typer(spatial_app, name="spatial")
app.add_typer(economy_app, name="economy")
app.add_typer(analysis_app, name="analysis")
app.add_typer(areas_app, name="areas")

_CLI_QUIET = False


def _elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class _TimedProgress:
    def __init__(self) -> None:
        self.started = time.monotonic()

    def __call__(self, message: str) -> None:
        if _CLI_QUIET:
            return
        typer.echo(f"[{_elapsed(time.monotonic() - self.started)}] {message}", err=True)


def _progress() -> _TimedProgress | None:
    return None if _CLI_QUIET else _TimedProgress()


def _initialized_source_store(explicit: Path | None = None) -> Path:
    state = require_initialization()
    if explicit is not None and explicit.expanduser().resolve() != state.source_store:
        raise typer.BadParameter(
            f"SIGMA is initialized with shared source store {state.source_store}; "
            "change SIGMA_HOME and run 'sigma init' again rather than overriding --source-store",
            param_hint="--source-store",
        )
    return state.source_store


def _workspace_for(
    area: str,
    workspace: Path | None,
    areas_file: Path | None = None,
) -> Path:
    """Return the explicit workspace or the predictable initialized default."""
    if workspace is not None:
        return workspace
    state = require_initialization()
    resolved = AreaCatalog(areas_file).resolve(area)
    return state.home / "workspaces" / resolved.slug


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str))


def _economy(spec: str | None) -> Economy:
    if spec is None:
        return Economy.default()
    value = spec.strip()
    low = value.casefold()
    aliases = {
        "io80": "io80", "builtin:io80": "io80", "psa-2018-io80": "io80",
        "io16": "io16", "builtin:io16": "io16", "psa-2018-io16": "io16",
    }
    if low in aliases:
        return Economy.builtin(aliases[low])
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise typer.BadParameter(
            "economy must be builtin:io80, builtin:io16, or a custom economy directory",
            param_hint="--economy",
        )
    return Economy.from_directory(path)


def _road_source(
    roads: Path | None,
    managed_roads: bool,
    roads_layer: str | None,
    *,
    required: bool,
) -> Path | RoadSource | None:
    """Translate CLI road options; managed Geofabrik roads are the area-mode default."""
    if managed_roads and roads is not None:
        raise typer.BadParameter("choose either --roads FILE or --managed-roads, not both")
    if roads is None:
        if roads_layer is not None:
            raise typer.BadParameter("--roads-layer requires --roads FILE")
        return GeofabrikRoadSource() if required else None
    return roads


def _config(
    *,
    equivalent: bool = False,
    mwas_method: str = "fast",
    transaction_preprocessing: str = "none",
    refresh_geofabrik: bool = False,
    refresh_overture: bool = False,
    source_store: Path | None = None,
    clip: bool = True,
    use_llm: bool = False,
    top_n: int = 5,
    min_score: float = 0.45,
    min_margin: float = 0.12,
    roads_layer: str | None = None,
    classification: str | None = None,
    classification_column: str | None = None,
    io80_column: str | None = None,
    io16_column: str | None = None,
    vertex_digits: int = 11,
    max_snap_distance: float | None = None,
    min_cluster_size: int = 5,
    min_samples: int | None = None,
    cluster_selection_method: str = "eom",
    allow_single_cluster: bool = False,
    hdbscan_max_distance: float = 5000.0,
    voronoi_resolution: float = 500.0,
    voronoi_max_cells: int = 1_000_000,
    centrality_method: str | None = None,
    centrality_direction: str = "incoming",
    distance_tempering: float = 0.15,
    compatibility_export: bool = True,
    unified_export: bool = True,
) -> SigmaConfig:
    if equivalent:
        if transaction_preprocessing != "none":
            raise typer.BadParameter("--equivalent cannot be combined with --transaction-preprocessing other than none")
        base = SigmaConfig.equivalent(mwas_method=mwas_method)  # type: ignore[arg-type]
    else:
        if mwas_method != "fast":
            raise typer.BadParameter("--mwas-method applies only with --equivalent")
        if transaction_preprocessing not in {"none", "mwas_ras_fast"}:
            raise typer.BadParameter("transaction preprocessing must be none or mwas_ras_fast")
        base = SigmaConfig.default()

    if classification not in {None, "io80", "io16"}:
        raise typer.BadParameter("classification must be io80 or io16")
    if cluster_selection_method not in {"eom", "leaf"}:
        raise typer.BadParameter("cluster selection method must be eom or leaf")
    if centrality_method not in {None, "katz", "eigenvector"}:
        raise typer.BadParameter("centrality method must be katz or eigenvector")
    if centrality_direction not in {"incoming", "outgoing"}:
        raise typer.BadParameter("centrality direction must be incoming or outgoing")

    spatial = replace(
        base.spatial,
        classification=classification if classification is not None else base.spatial.classification,
        classification_column=classification_column,
        io80_column=io80_column,
        io16_column=io16_column,
        vertex_digits=vertex_digits,
        max_snap_distance=max_snap_distance,
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method=cluster_selection_method,  # type: ignore[arg-type]
        allow_single_cluster=allow_single_cluster,
        hdbscan_max_distance=hdbscan_max_distance,
        voronoi_resolution=voronoi_resolution,
        voronoi_max_cells=voronoi_max_cells,
    )
    economic = replace(
        base.economic,
        transaction_preprocessing=transaction_preprocessing,  # type: ignore[arg-type]
    )
    return SigmaConfig(
        sources=SourceConfig(
            source_store=source_store,
            refresh_geofabrik=refresh_geofabrik,
            refresh_overture=refresh_overture,
        ),
        places=PlaceConfig(
            clip=clip,
            use_llm=use_llm,
            top_n=top_n,
            min_score=min_score,
            min_margin=min_margin,
        ),
        transport=TransportConfig(roads_layer=roads_layer),
        spatial=spatial,
        economic=economic,
        analysis=AnalysisConfig(
            centrality_method=(centrality_method or base.analysis.centrality_method),  # type: ignore[arg-type]
            centrality_direction=centrality_direction,  # type: ignore[arg-type]
            katz_alpha_factor=base.analysis.katz_alpha_factor,
            katz_beta=base.analysis.katz_beta,
            distance_tempering=distance_tempering,
        ),
        export=ExportConfig(compatibility=compatibility_export, unified=unified_export),
    )


def _job(
    *, area: str, workspace: Path, roads: Path | RoadSource | None, roads_layer: str | None,
    output_dir: Path | None, source_store: Path | None, economy: str | None,
    areas_file: Path | None, config: SigmaConfig, progress=None,
) -> Sigma:
    return Sigma(
        area,
        workspace=workspace,
        roads=roads,
        roads_layer=roads_layer,
        output_dir=output_dir,
        source_store=source_store,
        economy=_economy(economy),
        config=config,
        areas_file=areas_file,
        progress=progress,
    )


def _artifact_payload(ref) -> dict[str, Any]:
    return {"stage": ref.stage, "artifact_id": ref.artifact_id, "path": str(ref.path)}


def _handle_error(exc: Exception) -> None:
    typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=2)


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show SIGMA version and exit."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress normal progress output; warnings and errors remain."),
) -> None:
    global _CLI_QUIET
    _CLI_QUIET = bool(quiet)
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command("init")
def init_command(
    yes: bool = typer.Option(False, "--yes", "-y", help="Initialize without an interactive confirmation."),
    refresh: bool = typer.Option(False, "--refresh", help="Download/check a fresh Philippines Geofabrik PBF."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Set up the visible shared SIGMA data directory and national OSM source."""
    try:
        existing = load_initialization()
        progress = _progress()
        if existing is not None and not refresh:
            payload = {
                "status": "already_initialized",
                "home": str(existing.home),
                "source_store": str(existing.source_store),
                "geofabrik_path": str(existing.geofabrik.path),
                "geofabrik_version": existing.geofabrik.version,
                "geofabrik_size_bytes": existing.geofabrik.size,
            }
            if json_output:
                _echo_json(payload)
            else:
                typer.echo("SIGMA is already initialized.")
                typer.echo(f"Shared data: {existing.home}")
                typer.echo(f"Philippines OSM PBF: {existing.geofabrik.path}")
            return

        if not yes:
            typer.echo("SIGMA initialization")
            typer.echo("")
            typer.echo(f"Shared data directory: {sigma_home()}")
            typer.echo(f"Shared source store:   {source_store_root()}")
            typer.echo("")
            typer.echo("SIGMA will download the Philippines OpenStreetMap PBF from Geofabrik.")
            typer.echo("This is a large national file (typically hundreds of MiB); progress and size are shown.")
            typer.echo("The same national file supplies both OSM places and roads.")
            typer.echo("Area-specific Overture Places are downloaded later by 'sigma load <area>'.")
            if not typer.confirm("Continue?"):
                raise typer.Abort()
        state = initialize(refresh=refresh, progress=progress)
        payload = {
            "status": "initialized",
            "home": str(state.home),
            "source_store": str(state.source_store),
            "geofabrik_path": str(state.geofabrik.path),
            "geofabrik_version": state.geofabrik.version,
            "geofabrik_size_bytes": state.geofabrik.size,
        }
        if json_output:
            _echo_json(payload)
        elif not _CLI_QUIET:
            typer.echo("")
            typer.echo("SIGMA is ready.")
            typer.echo(f"Shared data: {state.home}")
            typer.echo(f"Philippines OSM PBF: {state.geofabrik.path}")
            typer.echo("Next: sigma load <area>")
    except typer.Abort:
        raise
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("run")
def run_command(
    area: str,
    workspace: Path | None = typer.Option(
        None, "--workspace", file_okay=False,
        help="Workspace directory. Defaults to <SIGMA home>/workspaces/<area>.",
    ),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default initialized Geofabrik road source."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False),
    source_store: Path | None = typer.Option(None, "--source-store", file_okay=False, hidden=True),
    areas_file: Path | None = typer.Option(None, "--areas-file", exists=True, dir_okay=False),
    economy: str | None = typer.Option(None, "--economy"),
    transaction_preprocessing: str = typer.Option("none", "--transaction-preprocessing"),
    equivalent: bool = typer.Option(False, "--equivalent", help="Use legacy Engine-equivalent profile."),
    mwas_method: str = typer.Option("fast", "--mwas-method"),
    min_cluster_size: int = typer.Option(5, "--min-cluster-size"),
    min_samples: int | None = typer.Option(None, "--min-samples"),
    allow_single_cluster: bool = typer.Option(False, "--allow-single-cluster"),
    voronoi_resolution: float = typer.Option(500.0, "--voronoi-resolution"),
    centrality_method: str | None = typer.Option(
        None, "--centrality-method",
        help="Centrality method: katz (canonical default) or eigenvector (legacy undirected projection).",
    ),
    centrality_direction: str = typer.Option(
        "incoming", "--centrality-direction",
        help="Compatibility option; canonical Katz combines incoming and outgoing and ignores this. Eigenvector also ignores it.",
    ),
    distance_tempering: float = typer.Option(0.15, "--distance-tempering"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run spatial/economic analysis from the previously loaded places GeoParquet."""
    try:
        road_source = _road_source(roads, managed_roads, roads_layer, required=True)
        shared_store = _initialized_source_store(source_store)
        workspace = _workspace_for(area, workspace, areas_file)
        progress = _progress()
        config = _config(
            equivalent=equivalent, mwas_method=mwas_method,
            transaction_preprocessing=transaction_preprocessing,
            source_store=shared_store, roads_layer=roads_layer,
            min_cluster_size=min_cluster_size, min_samples=min_samples,
            allow_single_cluster=allow_single_cluster, voronoi_resolution=voronoi_resolution,
            centrality_method=centrality_method, centrality_direction=centrality_direction,
            distance_tempering=distance_tempering,
        )
        job = _job(
            area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
            output_dir=output_dir, source_store=shared_store, economy=economy,
            areas_file=areas_file, config=config, progress=progress,
        )
        if progress is not None:
            progress(f"analysis input: {job.places_path}")
            progress("starting spatial, economic, X, centrality, scoring, and export stages")
        result = job.run(force=force)
        payload = {"run_manifest": str(result.run_manifest) if result.run_manifest else None,
                   "places_input": str(job.places_path),
                   "outputs": {k: str(v) for k, v in result.outputs.items()}}
        _echo_json(payload) if json_output else typer.echo(str(result.run_manifest or "run complete"))
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("load")
def load(
    area: str,
    workspace: Path | None = typer.Option(
        None, "--workspace", file_okay=False,
        help="Workspace directory. Defaults to <SIGMA home>/workspaces/<area>.",
    ),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False, help="Set the durable workspace export directory during loading."),
    source_store: Path | None = typer.Option(None, "--source-store", file_okay=False, hidden=True),
    areas_file: Path | None = typer.Option(None, "--areas-file", exists=True, dir_okay=False),
    economy: str | None = typer.Option(None, "--economy"),
    refresh_geofabrik: bool = typer.Option(False, "--refresh-geofabrik", help="Refresh the initialized national OSM source before loading places."),
    refresh_overture: bool = typer.Option(False, "--refresh-overture", help="Refresh the area-specific Overture Places snapshot."),
    clip: bool = typer.Option(True, "--clip/--no-clip"),
    use_llm: bool = typer.Option(False, "--llm/--no-llm"),
    top_n: int = typer.Option(5, "--top-n"),
    min_score: float = typer.Option(0.45, "--min-score"),
    min_margin: float = typer.Option(0.12, "--min-margin"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Load, reconcile, classify, and label an area's places into editable GeoParquet."""
    try:
        shared_store = _initialized_source_store(source_store)
        workspace = _workspace_for(area, workspace, areas_file)
        progress = _progress()
        config = _config(
            source_store=shared_store, refresh_geofabrik=refresh_geofabrik,
            refresh_overture=refresh_overture, clip=clip, use_llm=use_llm,
            top_n=top_n, min_score=min_score, min_margin=min_margin,
        )
        job = _job(area=area, workspace=workspace, roads=None, roads_layer=None,
                   output_dir=output_dir, source_store=shared_store, economy=economy,
                   areas_file=areas_file, config=config, progress=progress)
        if progress is not None:
            progress(f"loading places for {area}: OSM + Overture reconciliation and economic labelling")
        result = job.load(force=force)
        payload = {"canonical": _artifact_payload(result.canonical),
                   "psic": _artifact_payload(result.psic_classified),
                   "classified": _artifact_payload(result.classified_places),
                   "places_geoparquet": str(job.places_path)}
        if json_output:
            _echo_json(payload)
        else:
            typer.echo(f"Loaded places GeoParquet: {job.places_path}")
            typer.echo("You may inspect or filter this file before running 'sigma run'.")
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@network_app.command("prepare")
def network_prepare(
    area: str,
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default shared Geofabrik managed-road profile."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    economy: str | None = typer.Option(None, "--economy"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        road_source = _road_source(roads, managed_roads, roads_layer, required=True)
        config = _config(roads_layer=roads_layer, source_store=shared_store)
        result = _job(area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
                      output_dir=None, source_store=shared_store, economy=economy,
                      areas_file=None, config=config, progress=progress).prepare_network(force=force)
        payload = _artifact_payload(result.roads)
        _echo_json(payload) if json_output else typer.echo(result.roads.artifact_id)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@spatial_app.command("run")
def spatial_run(
    area: str,
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default shared Geofabrik managed-road profile."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    economy: str | None = typer.Option(None, "--economy"),
    min_cluster_size: int = typer.Option(5, "--min-cluster-size"),
    min_samples: int | None = typer.Option(None, "--min-samples"),
    classification: str | None = typer.Option(None, "--classification"),
    classification_column: str | None = typer.Option(None, "--classification-column"),
    io80_column: str | None = typer.Option(None, "--io80-column"),
    io16_column: str | None = typer.Option(None, "--io16-column"),
    allow_single_cluster: bool = typer.Option(False, "--allow-single-cluster"),
    voronoi_resolution: float = typer.Option(500.0, "--voronoi-resolution"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        road_source = _road_source(roads, managed_roads, roads_layer, required=True)
        config = _config(
            source_store=shared_store, roads_layer=roads_layer, classification=classification,
            classification_column=classification_column, io80_column=io80_column,
            io16_column=io16_column, min_cluster_size=min_cluster_size,
            min_samples=min_samples, allow_single_cluster=allow_single_cluster,
            voronoi_resolution=voronoi_resolution,
        )
        result = _job(area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
                      output_dir=None, source_store=shared_store, economy=economy,
                      areas_file=None, config=config, progress=progress).run_spatial(force=force)
        payload = {"centers": _artifact_payload(result.centers),
                   "point_distances": _artifact_payload(result.points_with_center_distance),
                   "partitions": _artifact_payload(result.partitions)}
        _echo_json(payload) if json_output else typer.echo(result.partitions.artifact_id)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@economy_app.command("graph")
def economy_graph(
    area: str,
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    economy: str | None = typer.Option(None, "--economy"),
    transaction_preprocessing: str = typer.Option("none", "--transaction-preprocessing"),
    equivalent: bool = typer.Option(False, "--equivalent"),
    mwas_method: str = typer.Option("fast", "--mwas-method"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        config = _config(equivalent=equivalent, mwas_method=mwas_method,
                         transaction_preprocessing=transaction_preprocessing, source_store=shared_store)
        result = _job(area=area, workspace=workspace, roads=None, roads_layer=None,
                      output_dir=None, source_store=shared_store, economy=economy,
                      areas_file=None, config=config, progress=progress).run_economy(force=force)
        payload = _artifact_payload(result.graph)
        _echo_json(payload) if json_output else typer.echo(result.graph.artifact_id)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@analysis_app.command("run")
def analysis_run(
    area: str,
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default shared Geofabrik managed-road profile."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    economy: str | None = typer.Option(None, "--economy"),
    transaction_preprocessing: str = typer.Option("none", "--transaction-preprocessing"),
    equivalent: bool = typer.Option(False, "--equivalent"),
    mwas_method: str = typer.Option("fast", "--mwas-method"),
    centrality_method: str | None = typer.Option(
        None, "--centrality-method",
        help="Centrality method: katz (canonical default) or eigenvector (legacy undirected projection).",
    ),
    centrality_direction: str = typer.Option(
        "incoming", "--centrality-direction",
        help="Compatibility option; canonical Katz combines incoming and outgoing and ignores this. Eigenvector also ignores it.",
    ),
    distance_tempering: float = typer.Option(0.15, "--distance-tempering"),
    min_cluster_size: int = typer.Option(5, "--min-cluster-size"),
    min_samples: int | None = typer.Option(None, "--min-samples"),
    allow_single_cluster: bool = typer.Option(False, "--allow-single-cluster"),
    voronoi_resolution: float = typer.Option(500.0, "--voronoi-resolution"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        road_source = _road_source(roads, managed_roads, roads_layer, required=True)
        config = _config(
            equivalent=equivalent, mwas_method=mwas_method, source_store=shared_store,
            transaction_preprocessing=transaction_preprocessing, roads_layer=roads_layer,
            centrality_method=centrality_method, centrality_direction=centrality_direction,
            distance_tempering=distance_tempering,
            min_cluster_size=min_cluster_size, min_samples=min_samples,
            allow_single_cluster=allow_single_cluster, voronoi_resolution=voronoi_resolution,
        )
        result = _job(area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
                      output_dir=None, source_store=shared_store, economy=economy,
                      areas_file=None, config=config, progress=progress).run_analysis(force=force)
        payload = {"x": _artifact_payload(result.x_graph),
                   "centrality": _artifact_payload(result.centrality),
                   "scores": _artifact_payload(result.scored_points)}
        _echo_json(payload) if json_output else typer.echo(result.scored_points.artifact_id)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("export")
def export_command(
    area: str,
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default shared Geofabrik managed-road profile."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False),
    economy: str | None = typer.Option(None, "--economy"),
    transaction_preprocessing: str = typer.Option("none", "--transaction-preprocessing"),
    equivalent: bool = typer.Option(False, "--equivalent"),
    mwas_method: str = typer.Option("fast", "--mwas-method"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        road_source = _road_source(roads, managed_roads, roads_layer, required=True)
        config = _config(equivalent=equivalent, mwas_method=mwas_method,
                         transaction_preprocessing=transaction_preprocessing,
                         source_store=shared_store, roads_layer=roads_layer)
        bundle = _job(area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
                      output_dir=output_dir, source_store=shared_store, economy=economy,
                      areas_file=None, config=config, progress=progress).export(force=force)
        payload = {"run_manifest": str(bundle.run_manifest),
                   "files": {k: str(v) for k, v in bundle.files.items()}}
        _echo_json(payload) if json_output else typer.echo(str(bundle.run_manifest))
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("status")
def status_command(
    area: str,
    workspace: Path | None = typer.Option(
        None, "--workspace", file_okay=False,
        help="Workspace directory. Defaults to <SIGMA home>/workspaces/<area>.",
    ),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default shared Geofabrik managed-road profile."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    economy: str | None = typer.Option(None, "--economy"),
    transaction_preprocessing: str = typer.Option("none", "--transaction-preprocessing"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        workspace = _workspace_for(area, workspace)
        road_source = _road_source(roads, managed_roads, roads_layer, required=False)
        config = _config(transaction_preprocessing=transaction_preprocessing, source_store=shared_store, roads_layer=roads_layer)
        job = _job(area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
                   output_dir=None, source_store=shared_store, economy=economy,
                   areas_file=None, config=config, progress=_progress())
        if not job.places_path.is_file():
            payload = {
                "initialization": "ready",
                "loaded_places": "missing",
                "places_path": str(job.places_path),
            }
            if json_output:
                _echo_json(payload)
            else:
                typer.echo(f"loaded places	missing	{job.places_path}")
                typer.echo("next	load	sigma load " + area)
            return
        status = job.status()
        payload = {stage: {"status": item.status, "reason": item.reason,
                           "valid": item.valid, "artifact_id": item.artifact_id}
                   for stage, item in sorted(status.stages.items())}
        if json_output:
            _echo_json(payload)
        else:
            for stage, item in payload.items():
                typer.echo(f"{stage}\t{item['status']}\t{item['reason']}")
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("stage")
def stage_command(
    area: str,
    stage: str,
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default shared Geofabrik managed-road profile."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    economy: str | None = typer.Option(None, "--economy"),
    transaction_preprocessing: str = typer.Option("none", "--transaction-preprocessing"),
    equivalent: bool = typer.Option(False, "--equivalent"),
    mwas_method: str = typer.Option("fast", "--mwas-method"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Ensure one exact managed stage and its prerequisites."""
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        road_source = _road_source(roads, managed_roads, roads_layer, required=False)
        config = _config(
            equivalent=equivalent, mwas_method=mwas_method,
            transaction_preprocessing=transaction_preprocessing, source_store=shared_store, roads_layer=roads_layer,
        )
        ref = _job(
            area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
            output_dir=None, source_store=shared_store, economy=economy,
            areas_file=None, config=config, progress=progress,
        ).ensure(stage, force=force)
        payload = _artifact_payload(ref)
        _echo_json(payload) if json_output else typer.echo(ref.artifact_id)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("recompute")
def recompute_command(
    area: str,
    stage: str,
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    roads: Path | None = typer.Option(None, "--roads", exists=True, dir_okay=False),
    managed_roads: bool = typer.Option(
        False, "--managed-roads", help="Explicitly select the default shared Geofabrik managed-road profile."
    ),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    economy: str | None = typer.Option(None, "--economy"),
    transaction_preprocessing: str = typer.Option("none", "--transaction-preprocessing"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        road_source = _road_source(roads, managed_roads, roads_layer, required=False)
        config = _config(transaction_preprocessing=transaction_preprocessing, source_store=shared_store, roads_layer=roads_layer)
        ref = _job(area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
                   output_dir=None, source_store=shared_store, economy=economy,
                   areas_file=None, config=config, progress=progress).recompute(stage)
        payload = _artifact_payload(ref)
        _echo_json(payload) if json_output else typer.echo(ref.artifact_id)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("from-partitions")
def from_partitions_command(
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    partitions: Path = typer.Option(..., "--partitions", exists=True, dir_okay=False),
    centers: Path = typer.Option(..., "--centers", exists=True, dir_okay=False),
    points_with_center_distance: Path = typer.Option(..., "--points-with-center-distance", exists=True, dir_okay=False),
    roads: Path = typer.Option(..., "--roads", exists=True, dir_okay=False),
    roads_layer: str | None = typer.Option(None, "--roads-layer"),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False),
    economy: str | None = typer.Option(None, "--economy"),
    mwas_method: str = typer.Option("fast", "--mwas-method"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        shared_store = _initialized_source_store()
        progress = _progress()
        job = Sigma.from_partitions(
            workspace=workspace, partitions=partitions, centers=centers,
            points_with_center_distance=points_with_center_distance,
            roads=roads, roads_layer=roads_layer, output_dir=output_dir, source_store=shared_store,
            economy=_economy(economy), config=SigmaConfig.equivalent(mwas_method=mwas_method),  # type: ignore[arg-type]
            progress=progress,
        )
        result = job.run()
        payload = {"run_manifest": str(result.run_manifest) if result.run_manifest else None,
                   "outputs": {k: str(v) for k, v in result.outputs.items()}}
        _echo_json(payload) if json_output else typer.echo(str(result.run_manifest or "restart complete"))
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@areas_app.command("list")
def areas_list(
    kind: str | None = typer.Option(None, "--kind"),
    search: str | None = typer.Option(None, "--search"),
    areas_file: Path | None = typer.Option(None, "--areas-file", exists=True, dir_okay=False),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    try:
        rows = AreaCatalog(areas_file).list(kind=kind, search=search)
        payload = [{"slug": a.slug, "name": a.name, "kind": a.kind,
                    "psgc_code": a.psgc_code, "aliases": list(a.aliases)} for a in rows]
        if json_output:
            _echo_json(payload)
        else:
            for row in payload:
                typer.echo(f"{row['slug']}\t{row['kind']}\t{row['name']}\t{row['psgc_code'] or ''}")
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@areas_app.command("show")
def areas_show(
    value: str,
    areas_file: Path | None = typer.Option(None, "--areas-file", exists=True, dir_okay=False),
) -> None:
    try:
        area = AreaCatalog(areas_file).resolve(value)
        _echo_json(asdict(area))
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


def _classification_asset_report() -> dict[str, Any]:
    root = resources.files("sigma.resources.classification")
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    verified = 0
    for relative, expected in sorted(manifest["assets"].items()):
        data = root.joinpath(*relative.split("/")).read_bytes()
        canonical = _canonical_manifest_bytes(relative, data)
        actual = hashlib.sha256(canonical).hexdigest()
        if actual != expected["sha256"] or len(canonical) != expected["size_bytes"]:
            failures.append(relative)
        else:
            verified += 1
    return {"schema_version": manifest.get("schema_version"), "verified_assets": verified,
            "asset_count": len(manifest["assets"]), "failures": failures}


@app.command("classification-check")
def classification_check(json_output: bool = typer.Option(False, "--json")) -> None:
    try:
        payload = _classification_asset_report()
        semantic = {"status": "not_run", "reason": "pyarrow unavailable"}
        if importlib.util.find_spec("pyarrow") is not None:
            taxonomy = PsicTaxonomy.builtin_rev5()
            refs80 = TaggingReferences.builtin(taxonomy, Economy.builtin("io80"))
            refs16 = TaggingReferences.builtin(taxonomy, Economy.builtin("io16"))
            structure = taxonomy.structural_report()
            semantic = {
                "status": "ok" if not structure.errors else "failed",
                "taxonomy_fingerprint": taxonomy.fingerprint,
                "io80_references": refs80.fingerprint,
                "io16_references": refs16.fingerprint,
                "structure_errors": list(structure.errors),
                "level_gaps": list(structure.level_gaps),
            }
        payload["semantic_validation"] = semantic
        ok = not payload["failures"] and semantic.get("status") != "failed"
        if json_output:
            _echo_json(payload)
        else:
            typer.echo(f"classification assets: {payload['verified_assets']}/{payload['asset_count']} verified")
            typer.echo(f"semantic validation: {semantic['status']}")
        if not ok:
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        _handle_error(exc)


@app.command("doctor")
def doctor(json_output: bool = typer.Option(False, "--json")) -> None:
    checks: dict[str, Any] = {"sigma_version": __version__}
    required = {
        "geopandas": "geopandas",
        "networkx": "networkx",
        "numpy": "numpy",
        "openpyxl": "openpyxl",
        "osmium": "osmium",
        "overturemaps": "overturemaps",
        "pandas": "pandas",
        "pyarrow": "pyarrow",
        "pyogrio": "pyogrio",
        "PyYAML": "yaml",
        "rapidfuzz": "rapidfuzz",
        "requests": "requests",
        "rich": "rich",
        "scikit-learn": "sklearn",
        "scipy": "scipy",
        "shapely": "shapely",
        "typer": "typer",
    }
    checks["dependencies"] = {
        distribution: importlib.util.find_spec(module) is not None
        for distribution, module in required.items()
    }
    checks["optional_dependencies"] = {
        "openai": importlib.util.find_spec("openai") is not None,
    }
    init_state = load_initialization()
    checks["initialization"] = (
        {
            "status": "ready",
            "home": str(init_state.home),
            "source_store": str(init_state.source_store),
            "geofabrik_path": str(init_state.geofabrik.path),
            "geofabrik_version": init_state.geofabrik.version,
        }
        if init_state is not None
        else {"status": "not_initialized", "home": str(sigma_home())}
    )
    try:
        checks["area_catalog_fingerprint"] = AreaCatalog().identity()["fingerprint"]
        checks["economy"] = {
            "io80": Economy.builtin("io80").economy_fingerprint,
            "io16": Economy.builtin("io16").economy_fingerprint,
        }
        checks["classification_assets"] = _classification_asset_report()
    except Exception as exc:
        checks["validation_error"] = str(exc)
    base_ok = all(checks["dependencies"].values()) and "validation_error" not in checks and not checks["classification_assets"]["failures"]
    initialized = checks["initialization"]["status"] == "ready"
    ok = base_ok and initialized
    checks["status"] = "ok" if ok else ("not_initialized" if base_ok and not initialized else "failed")
    if json_output:
        _echo_json(checks)
    else:
        typer.echo(f"SIGMA {__version__}: {checks['status']}")
        typer.echo(f"initialization: {checks['initialization']['status']}")
        if checks["initialization"]["status"] != "ready":
            typer.echo(f"shared data: {checks['initialization']['home']}")
            typer.echo("next: sigma init")
        else:
            typer.echo(f"shared data: {checks['initialization']['home']}")
            typer.echo(f"Philippines OSM PBF: {checks['initialization']['geofabrik_path']}")
        missing = [name for name, present in checks["dependencies"].items() if not present]
        if missing:
            typer.echo("missing dependencies: " + ", ".join(missing))
    if not ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

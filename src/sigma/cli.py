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
storage_app = typer.Typer(help="Inventory and clean old SIGMA workspace files.", no_args_is_help=True)
app.add_typer(network_app, name="network")
app.add_typer(spatial_app, name="spatial")
app.add_typer(economy_app, name="economy")
app.add_typer(analysis_app, name="analysis")
app.add_typer(areas_app, name="areas")
app.add_typer(storage_app, name="storage")

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


def _storage_workspace_paths(workspace: Path | None) -> list[Path]:
    if workspace is not None:
        return [workspace.expanduser().resolve()]
    base = sigma_home() / "workspaces"
    if not base.is_dir():
        return []
    return sorted(
        p for p in base.iterdir()
        if p.is_dir() and not p.is_symlink() and (p / "workspace.json").is_file()
    )


def _storage_size(nbytes: int) -> str:
    if nbytes >= 1024 ** 3:
        return f"{nbytes / (1024 ** 3):.2f} GiB"
    return f"{nbytes / (1024 ** 2):.1f} MiB"


def _storage_inspect(
    workspace: Path | None, *, older_than_days: int,
    obsolete: bool, quarantine: bool, apply: bool,
) -> None:
    from .storage import inspect_workspace, prune

    paths = _storage_workspace_paths(workspace)
    if not paths:
        typer.echo("No SIGMA workspaces found.")
        return
    grand_total = 0
    for path in paths:
        report = inspect_workspace(
            path, older_than_days=older_than_days, obsolete=obsolete,
            quarantine=quarantine,
        )
        typer.echo(f"\n{report.workspace}")
        for category, size in report.categories.items():
            if size:
                typer.echo(f"  {category}: {_storage_size(size)}")
        if report.stage_sizes:
            typer.echo("  Largest artifact stages:")
            for name, size in sorted(
                report.stage_sizes.items(), key=lambda item: item[1], reverse=True
            )[:5]:
                typer.echo(f"    {name}: {_storage_size(size)}")
        if report.largest_files:
            typer.echo("  Largest files (diagnostic only):")
            for filename, size in report.largest_files[:5]:
                typer.echo(f"    {_storage_size(size)} {filename}")
        if report.protected_reason:
            typer.echo(f"  Protected: {report.protected_reason}")
        for candidate, status in prune(report, apply=apply):
            typer.echo(
                f"  {status}: {_storage_size(candidate.bytes)} "
                f"[{candidate.category}] {candidate.path}"
            )
            if status == "deleted" or not apply:
                grand_total += candidate.bytes
    mode = "Deleted" if apply else "Previewed for cleanup"
    typer.echo(f"\n{mode}: {_storage_size(grand_total)}")
    if not apply:
        typer.echo("Nothing was deleted. Use 'sigma storage prune --apply' to act on this preview.")


@storage_app.command("report")
def storage_report(
    workspace: Path | None = typer.Option(None, "--workspace", help="Inspect one workspace (default: all)."),
    obsolete: bool = typer.Option(False, "--obsolete", help="Also preview superseded immutable artifacts."),
    quarantine: bool = typer.Option(False, "--quarantine", help="Also preview old quarantines."),
    older_than_days: int = typer.Option(30, "--older-than-days", min=1),
) -> None:
    """Inspect storage, without deleting anything."""
    _storage_inspect(
        workspace, older_than_days=older_than_days,
        obsolete=obsolete, quarantine=quarantine, apply=False,
    )


@storage_app.command("prune")
def storage_prune(
    workspace: Path | None = typer.Option(None, "--workspace", help="Prune one workspace (default: all)."),
    apply: bool = typer.Option(False, "--apply", help="Actually remove the reviewed candidates."),
    obsolete: bool = typer.Option(
        False, "--obsolete", help="Opt in to removing unreferenced immutable artifacts."
    ),
    quarantine: bool = typer.Option(False, "--quarantine", help="Opt in to removing old quarantines."),
    older_than_days: int = typer.Option(30, "--older-than-days", min=1),
) -> None:
    """Remove old SIGMA-created staging; nothing happens without --apply.

    Stop SIGMA jobs first. Current exports, Explorer bundles, user-reviewed places,
    and current artifacts and their dependencies are protected. Obsolete artifacts
    are never pruned unless explicitly requested with --obsolete.
    """
    _storage_inspect(
        workspace, older_than_days=older_than_days,
        obsolete=obsolete, quarantine=quarantine, apply=apply,
    )

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
    prefer_hierarchical: bool = True,
) -> Sigma:
    from .economy.hierarchical_auto import auto_economy
    resolved_economy = _economy(economy)
    if prefer_hierarchical and economy is None and config.spatial.classification is None:
        resolved_economy = auto_economy(workspace) or resolved_economy
    return Sigma(
        area,
        workspace=workspace,
        roads=roads,
        roads_layer=roads_layer,
        output_dir=output_dir,
        source_store=source_store,
        economy=resolved_economy,
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
        if (economy is None and config.spatial.classification is None
                and (Path(workspace) / "places" / "places.parquet").is_file()):
            from .economy.hierarchical_auto import read_profile, profile_is_current
            profile = read_profile()
            if profile is not None and not profile_is_current(workspace, profile):
                if progress is not None:
                    progress("rebuilding this area's hierarchical sector partition")
                _hierarchical_build_from_profile(workspace, profile)
            if profile is None and not (workspace / "hierarchical" / "economy" / "economy.yml").is_file():
                typer.echo("Hierarchical IO240 not configured; running the IO80 economy. "
                           "Configure once with 'sigma economy hierarchical-configure --help'.", err=True)
        job = _job(
            area=area, workspace=workspace, roads=road_source, roads_layer=roads_layer,
            output_dir=output_dir, source_store=shared_store, economy=economy,
            areas_file=areas_file, config=config, progress=progress,
        )
        if progress is not None:
            # Keep the public CLI compatible with jobs that expose places_path
            # without the private resolver (including CLI integration fakes).
            resolver = getattr(job, "_require_loaded_places", None)
            input_path = resolver() if callable(resolver) else job.places_path
            progress(f"analysis input: {input_path}")
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
                   areas_file=areas_file, config=config, progress=progress,
                   prefer_hierarchical=False)
        if progress is not None:
            progress(f"loading places for {area}: OSM + Overture reconciliation and economic labelling")
        result = job.load(force=force)
        if economy is None and (Path(workspace) / "places" / "places.parquet").is_file():
            from .economy.hierarchical_auto import read_profile
            profile = read_profile()
            if profile is None:
                typer.echo("Hierarchical IO240 not configured: using IO80. Run "
                           "'sigma economy hierarchical-configure --help' for one-time setup.", err=True)
            else:
                if progress is not None:
                    progress("constructing area-specific IO240/IO80/IO16 residual economy")
                _hierarchical_build_from_profile(workspace, profile)
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


@economy_app.command("hierarchical-build")
def hierarchical_build(
    workspace: Path = typer.Option(..., "--workspace", file_okay=False,
                                   help="Existing workspace containing loaded places/places.parquet"),
    io240_dir: Path = typer.Option(..., "--io240-dir", exists=True, file_okay=False,
                                   help="IO240 Economy directory with sectors, transactions, and total_output"),
    crosswalk: Path = typer.Option(..., "--crosswalk", exists=True, dir_okay=False,
                                   help="CSV with io240_code,io80_code,io16_code parent mapping"),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False),
    replace: bool = typer.Option(False, "--replace", help="Replace previously generated hierarchical outputs"),
    strict_coarse: bool = typer.Option(False, "--strict-coarse", help="Error if a broad place tag has no residual sector"),
    min_places: int = typer.Option(
        1, "--min-places", min=1,
        help="Keep an IO240 sector (or a whole IO80 sector) only if at least this many places "
             "support it; thinner ones fold into the next coarser group. 1 keeps every observed sector. "
             "Setting it to the run's --min-cluster-size avoids sectors too small to form a cluster.",
    ),
    activate: bool = typer.Option(False, "--activate", help="Back up and replace loaded places GeoParquet"),
    check_psa: bool = typer.Option(False, "--check-psa", help="Report IO80/IO16 discrepancies with bundled PSA tables"),
    cluster_report_threshold: int = typer.Option(
        5, "--cluster-report-threshold", min=1,
        help="Only for diagnostics: report assigned sectors with fewer than this many places; "
             "does not change partition selection (controlled by --min-places).",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Build residual IO240/IO80/IO16 sectors and retag already-loaded places."""
    import tempfile
    import shutil
    from uuid import uuid4
    import yaml
    import pandas as pd
    import numpy as np
    import geopandas as gpd
    from .economy.hierarchical import (
        activate_hierarchical_places, build_hierarchical_economy,
        reconciliation, require_sigma_io80_io16, tagging_consistency,
        write_hierarchical_package, _file_sha256,
    )
    from .errors import EconomyValidationError

    def _overlaps(a: Path, b: Path) -> bool:
        return a == b or a in b.parents or b in a.parents

    def _owned_previous_build(folder: Path) -> None:
        """Never allow --replace to recursively delete arbitrary user data.

        Supports v3's exact published file set, as well as v4/v5 output with a
        marker file. Reject anything unfamiliar, even in an otherwise valid package.
        An empty folder (for example, created in advance by the user) is accepted.
        """
        if not any(folder.iterdir()):
            return
        expected_root = {"economy", "places.parquet", ".sigma-hierarchical-manifest.json"}
        expected_economy = {
            "economy.yml", "sectors.csv", "transactions.csv", "total_output.csv",
            "membership.csv", "audit.json",
        }
        present_root = {f.name for f in folder.iterdir()}
        if not {"economy", "places.parquet"} <= present_root or not present_root <= expected_root:
            raise ValueError("--replace requires a previously generated hierarchical directory "
                             "with no unrelated files; refusing to delete user data")
        nested = folder / "economy"
        if not nested.is_dir() or not (folder / "places.parquet").is_file():
            raise ValueError("--replace target is not a complete hierarchical output")
        present_economy = {f.name for f in nested.iterdir()}
        if present_economy != expected_economy or not all((nested / n).is_file() for n in present_economy):
            raise ValueError("--replace target contains missing or unrelated economy files")
        metadata = yaml.safe_load((nested / "economy.yml").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("derivation"), dict):
            raise ValueError("--replace target lacks hierarchical derivation provenance")
        if metadata["derivation"].get("source_kind") != "hierarchical_io240_residual":
            raise ValueError("--replace target is not a SIGMA hierarchical generated economy")
        manifest = folder / ".sigma-hierarchical-manifest.json"
        if manifest.exists():
            marker = json.loads(manifest.read_text(encoding="utf-8"))
            if marker.get("artifact_kind") != "sigma-hierarchical-residual" or marker.get("schema_version") != 1:
                raise ValueError("--replace target has an unrecognized SIGMA manifest")

    try:
        workspace = workspace.expanduser().resolve()
        original = workspace / "places" / "places.parquet"
        if not original.is_file():
            raise ValueError(f"load the area first; missing {original}")
        destination = (output_dir or workspace / "hierarchical").expanduser().resolve()
        # Never write over the workspace, its managed folders, its export folder,
        # or the shared source store ('--replace' moves the destination away).
        protected = [workspace / name for name in ("artifacts", "places", "sources", "runs", "output", "workspace.json")]
        metadata_path = workspace / "workspace.json"
        if metadata_path.is_file():
            stored = json.loads(metadata_path.read_text(encoding="utf-8"))
            for key in ("output_dir", "artifact_store_root", "source_store_root"):
                if stored.get(key):
                    protected.append(Path(str(stored[key])).expanduser().resolve())
        if destination == workspace or destination in workspace.parents or any(
                _overlaps(destination, p) for p in protected):
            raise ValueError("hierarchical output must be separate from the workspace's managed, "
                             "export, and source-store folders")
        # --replace must not destroy the IO240 source or its hierarchy CSV.
        source_dir = io240_dir.expanduser().resolve()
        hierarchy_file = crosswalk.expanduser().resolve()
        if _overlaps(destination, source_dir) or _overlaps(destination, hierarchy_file):
            raise ValueError("hierarchical output may not contain or replace the IO240 source or crosswalk")
        if activate:
            backup = original.with_name("places.pre-hierarchical.parquet")
            if backup.exists():
                raise ValueError(f"activation backup already exists: {backup}")
        if destination.exists() and not replace:
            raise ValueError(f"output directory already exists: {destination}; use --replace to rebuild")
        if destination.exists() and not destination.is_dir():
            raise ValueError(f"hierarchical destination is not a directory: {destination}")
        if destination.exists() and replace:
            _owned_previous_build(destination)
        io240 = Economy.from_directory(io240_dir)
        if len(io240.sectors) != 240:
            raise ValueError(f"expected exactly 240 IO240 source sectors; found {len(io240.sectors)}")
        parents = pd.read_csv(crosswalk, dtype=str, keep_default_na=False)
        # A complete official 240-to-80-to-16 hierarchy must have all parent sectors.
        # Do not silently accept a crosswalk that lumps unrelated parents together.
        for column, expected in (("io240_code", 240), ("io80_code", 80), ("io16_code", 16)):
            if column not in parents or parents[column].nunique() != expected:
                raise ValueError(f"crosswalk must describe exactly {expected} distinct {column} values")
        # Only IO240 -> IO80 links are new information; codes and links above IO80
        # must be SIGMA's own PSA structure (its IO80 table sums exactly to its IO16 table).
        require_sigma_io80_io16(parents)
        consistency = tagging_consistency(parents)
        crosswalk_file_sha256 = _file_sha256(hierarchy_file)
        places_sha256 = _file_sha256(original)
        places = gpd.read_parquet(original)
        if ("economy_source" in places and
                places["economy_source"].astype(str).eq("hierarchical_io240_io80_io16").any()):
            raise ValueError("input places already carry hierarchical labels; restore original before rebuilding")
        try:
            result = build_hierarchical_economy(
                places, io240, parents, strict_coarse=strict_coarse, min_places=min_places
            )
        except EconomyValidationError as exc:
            if consistency["consistent"]:
                raise
            raise EconomyValidationError(
                f"{exc} -- note: the crosswalk disagrees with SIGMA's tagging references on "
                f"{len(consistency['io240_parent_mismatches'])} IO240 parent link(s) and "
                f"{len(consistency['io80_parent_mismatches'])} IO80 parent link(s), e.g. "
                f"{(consistency['io240_parent_mismatches'] + consistency['io80_parent_mismatches'])[:3]}"
            ) from exc
        diagnostics = dict(result.diagnostics)
        diagnostics["places_input"] = {"path": str(original), "sha256": places_sha256}
        diagnostics["crosswalk_input"] = {"path": str(hierarchy_file), "sha256": crosswalk_file_sha256}
        diagnostics["tagging_consistency"] = consistency
        # Report potential clustering losses independently of partition-selection policy.
        diagnostics["cluster_report_threshold"] = int(cluster_report_threshold)
        diagnostics["observed_sectors_below_cluster_threshold"] = [
            {"economy_code": code, "assigned_places": count}
            for code, count in sorted(diagnostics["assigned_places_by_final_sector"].items())
            if count < cluster_report_threshold
        ]
        if check_psa:
            diagnostics["reference_checks"] = {
                key: reconciliation(io240, parents, Economy.builtin(key), resolution=key)
                for key in ("io80", "io16")
            }
        destination.parent.mkdir(parents=True, exist_ok=True)
        # All output files are completed and verified before replacing any existing
        # result or modifying the loaded places. Publication and activation share
        # one rollback scope; the old output survives until both steps succeed.
        with tempfile.TemporaryDirectory(prefix=".sigma-hierarchical-build-", dir=destination.parent) as temporary:
            stage = Path(temporary) / "complete"
            stage.mkdir()
            write_hierarchical_package(result, stage / "economy")
            (stage / "economy" / "audit.json").write_text(
                json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            # A content hash of the provided crosswalk, as distinct from the
            # canonical parent mapping digest, belongs in run-visible lineage.
            meta_file = stage / "economy" / "economy.yml"
            meta = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
            meta["derivation"]["crosswalk_file_sha256"] = crosswalk_file_sha256
            meta_file.write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
            result.places.to_parquet(stage / "places.parquet", index=False)
            (stage / ".sigma-hierarchical-manifest.json").write_text(
                json.dumps({
                    "artifact_kind": "sigma-hierarchical-residual",
                    "schema_version": 1,
                    "partition_sha256": result.diagnostics["partition_sha256"],
                    "sector_code_scheme": result.diagnostics["sector_code_scheme"],
                    "source_economy_fingerprint": io240.economy_fingerprint,
                }, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            loaded = Economy.from_directory(stage / "economy")
            # Economy fingerprints hash IEEE-754 bytes. Pandas CSV parsing can
            # change their last bits without changing the economic data.  Check
            # exact identities and lineage, then validate numbers with tolerance.
            built = result.economy
            if (
                loaded.economy_id != built.economy_id
                or loaded.sector_fingerprint != built.sector_fingerprint
                or loaded.label != built.label
                or loaded.version != built.version
                or loaded.reference_year != built.reference_year
            ):
                raise EconomyValidationError(
                    "written hierarchical Economy changed sector identities or metadata"
                )
            loaded_derivation = loaded.provenance.get("metadata", {}).get("derivation")
            if (
                not isinstance(loaded_derivation, dict)
                or any(loaded_derivation.get(k) != v for k, v in built.provenance.items())
                or loaded_derivation.get("crosswalk_file_sha256") != crosswalk_file_sha256
            ):
                raise EconomyValidationError(
                    "written hierarchical Economy lost or changed derivation provenance"
                )
            stored_z = loaded.Z_raw.to_numpy(dtype=float)
            built_z = built.Z_raw.to_numpy(dtype=float)
            if not np.allclose(stored_z, built_z, rtol=1e-14, atol=1e-10):
                maximum = float(np.abs(stored_z - built_z).max())
                raise EconomyValidationError(
                    f"written hierarchical transactions changed beyond CSV precision "
                    f"(maximum absolute difference: {maximum:.12g})"
                )
            if loaded.x is None or built.x is None:
                raise EconomyValidationError("hierarchical Economy lost its gross-output vector")
            stored_x = loaded.x.to_numpy(dtype=float)
            built_x = built.x.to_numpy(dtype=float)
            if not np.allclose(stored_x, built_x, rtol=1e-14, atol=1e-10):
                maximum = float(np.abs(stored_x - built_x).max())
                raise EconomyValidationError(
                    f"written hierarchical gross output changed beyond CSV precision "
                    f"(maximum absolute difference: {maximum:.12g})"
                )
            preview_check = gpd.read_parquet(stage / "places.parquet")
            if len(preview_check) != len(result.places) or (
                preview_check.economy_code.fillna("").astype(str).tolist()
                != result.places.economy_code.fillna("").astype(str).tolist()
            ):
                raise EconomyValidationError("written places preview failed roundtrip validation")
            # A previous load/activation must not be replaced with a preview
            # constructed against different source bytes.
            if _file_sha256(original) != places_sha256:
                raise ValueError("loaded places changed during the build; refusing to publish")
            # The prior published package MUST NOT be moved into TemporaryDirectory.
            # A failed restore can otherwise make its cleanup permanently delete the
            # only remaining copy. Keep it as a durable sibling until success.
            previous = None
            if destination.exists():
                previous = destination.with_name(
                    f"{destination.name}.previous-{uuid4().hex}"
                )
                destination.rename(previous)
            try:
                stage.rename(destination)
            except BaseException as publish_error:
                if previous is not None:
                    try:
                        previous.rename(destination)
                    except BaseException as restore_error:
                        raise OSError(
                            f"publication failed: {publish_error}; restoration also failed: "
                            f"{restore_error}. Previous package preserved at {previous}"
                        ) from publish_error
                raise
            if activate:
                try:
                    activate_hierarchical_places(
                        original, destination / "places.parquet",
                        expected_original_sha256=places_sha256,
                    )
                except BaseException as activation_error:
                    # The previous package is durable independently of temp cleanup.
                    # Move the failed new package aside before attempting to restore.
                    try:
                        destination.rename(Path(temporary) / "failed")
                        if previous is not None:
                            previous.rename(destination)
                    except BaseException as restore_error:
                        raise OSError(
                            f"activation failed: {activation_error}; restoring the preview "
                            f"also failed: {restore_error}. The previous package remains "
                            f"at {previous if previous is not None and previous.exists() else destination}; "
                            f"inspect the active places and output before retrying"
                        ) from activation_error
                    raise
            # The replacement is now successfully published (and activated if
            # requested); only now is it safe to clean up the previous package.
            # On a Windows lock, retain it instead of turning success into failure.
            if previous is not None and previous.exists():
                try:
                    shutil.rmtree(previous)
                except OSError as cleanup_error:
                    typer.echo(
                        f"Warning: previous hierarchical output retained at {previous}: "
                        f"{cleanup_error}", err=True,
                    )
        economy_dir = destination / "economy"
        tagged_path = destination / "places.parquet"
        payload = {
            "economy_directory": str(economy_dir),
            "tagged_places_preview": str(tagged_path),
            "activated": bool(activate),
            "sector_count": len(result.economy.sectors),
            "min_places": int(min_places),
            "folded_io240_sectors": len(result.diagnostics["folded_io240_codes"]),
            "unresolved_places": result.diagnostics["unresolved_place_count"],
            "unassigned_coarse_places": result.diagnostics["unassigned_coarse_place_count"],
            "coarse_residual_assumption_places": result.diagnostics["coarse_residual_assumption_place_count"],
            "observed_sectors_below_min_places": result.diagnostics["observed_sectors_below_min_places"],
            "observed_sectors_below_cluster_threshold": diagnostics["observed_sectors_below_cluster_threshold"],
            "crosswalk_matches_tagging_references": bool(consistency["consistent"]),
            "next_command": "sigma run <area> (auto-detects this matching economy)",
        }
        _echo_json(payload) if json_output else typer.echo(json.dumps(payload, indent=2))
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@economy_app.command("hierarchical-configure")
def hierarchical_configure(
    io240_dir: Path = typer.Option(..., "--io240-dir", exists=True, file_okay=False),
    crosswalk: Path = typer.Option(..., "--crosswalk", exists=True, dir_okay=False),
    min_places: int = typer.Option(5, "--min-places", min=1),
    check_psa: bool = typer.Option(True, "--check-psa/--no-check-psa"),
) -> None:
    """Once per SIGMA installation: select real IO240 inputs for per-area builds."""
    from .economy.hierarchical_auto import save_profile
    try:
        dest = save_profile(io240_dir, crosswalk, min_places=min_places, check_psa=check_psa)
        typer.echo(f"Configured area-specific hierarchical IO240 references: {dest}")
        typer.echo("Next: sigma load <area>; then sigma run <area> (no --economy required).")
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


def _hierarchical_build_from_profile(workspace: Path, profile: dict, *, json_output: bool = False) -> None:
    # Reuse the same validated, transactional builder as the manual CLI command.
    hierarchical_build(
        workspace=workspace, io240_dir=Path(profile["io240_dir"]),
        crosswalk=Path(profile["crosswalk"]), output_dir=None,
        replace=True, strict_coarse=False, min_places=profile["min_places"],
        activate=False, check_psa=profile["check_psa"],
        cluster_report_threshold=5, json_output=json_output,
    )


@economy_app.command("hierarchical-refresh")
def hierarchical_refresh(
    workspace: Path = typer.Option(..., "--workspace", file_okay=False),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Reconstruct one area's hierarchy after editing/filtering its base places."""
    from .economy.hierarchical_auto import read_profile
    try:
        profile = read_profile()
        if profile is None:
            raise ValueError("IO240 references not configured; run 'sigma economy hierarchical-configure' first")
        _hierarchical_build_from_profile(workspace, profile, json_output=json_output)
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


# SIGMA_EXPLORER_OVERLAY_V3_START
def _explorer_paths(
    area: str, workspace: Path | None, source_dir: Path | None, output_dir: Path | None
) -> tuple[Path, Path]:
    from .web import resolve_output_directory

    source = source_dir if source_dir is not None else resolve_output_directory(_workspace_for(area, workspace))
    destination = output_dir if output_dir is not None else Path(source) / "explorer"
    return Path(source), Path(destination)


@app.command("export-web")
def export_web_command(
    area: str,
    workspace: Path | None = typer.Option(None, "--workspace", file_okay=False),
    source_dir: Path | None = typer.Option(None, "--source-dir", file_okay=False, help="Published SIGMA output directory."),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False, help="Explorer bundle directory."),
    roads: bool | None = typer.Option(
        None, "--roads/--no-roads", help="Include SIGMA's published roads. Default: include unless very large."
    ),
    force: bool = typer.Option(False, "--force", help="Replace an existing SIGMA Explorer bundle."),
    public: bool = typer.Option(False, "--public", help="Omit establishment-level identities and locations for public review."),
) -> None:
    """Create a static Explorer bundle from existing published outputs; never recompute SIGMA."""
    try:
        from .web import build_web_bundle

        source, destination = _explorer_paths(area, workspace, source_dir, output_dir)
        if public and output_dir is None:
            destination = source / "explorer-public"
        result = build_web_bundle(source, destination, include_roads=roads, force=force,
                                  profile="public" if public else "local")
        for warning in result.get("warnings", []):
            typer.echo(f"Note: {warning}")
        typer.echo(f"SIGMA Explorer created: {result['destination']}")
        if not public:
            typer.echo("WARNING: includes individual establishment locations; do not publish without reviewing data rights.")
        hint = "sigma view " + area + (f" --workspace {workspace}" if workspace is not None else "")
        if output_dir is not None:
            hint += f' --output-dir "{destination}"'
        elif public:
            hint += " --public"
        typer.echo("To view it locally: " + hint)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)


@app.command("view")
def view_command(
    area: str,
    workspace: Path | None = typer.Option(None, "--workspace", file_okay=False),
    source_dir: Path | None = typer.Option(None, "--source-dir", file_okay=False, help="Published SIGMA output directory."),
    output_dir: Path | None = typer.Option(None, "--output-dir", file_okay=False, help="Explorer bundle directory."),
    port: int = typer.Option(8765, "--port", min=0, max=65535, help="Local port; the next free port is used if it is taken."),
    no_browser: bool = typer.Option(False, "--no-browser"),
    ui_only: bool = typer.Option(False, "--ui-only", help="Fast UI-only update of an existing Explorer bundle; reuse all published data."),
    refresh: bool = typer.Option(False, "--refresh", help="Rebuild even when the bundle matches the latest outputs."),
    roads: bool | None = typer.Option(
        None, "--roads/--no-roads", help="Include SIGMA's published roads. Default: include unless very large."
    ),
    public: bool = typer.Option(False, "--public", help="View the public-profile bundle (explorer-public)."),
) -> None:
    """Open a local-only Explorer for an area; it is rebuilt automatically after new SIGMA runs."""
    try:
        from .web import build_web_bundle, bundle_is_current, bundle_profile, serve_bundle, refresh_web_assets

        source, destination = _explorer_paths(area, workspace, source_dir, output_dir)
        if public and output_dir is None:
            destination = source / "explorer-public"
        # A public bundle stays public: never rebuild it with establishment-level data.
        public = public or destination.name == "explorer-public" or bundle_profile(destination) == "public"
        profile = "public" if public else "local"
        if ui_only and refresh:
            raise ValueError("--ui-only cannot be combined with --refresh")
        if ui_only:
            updated = refresh_web_assets(destination, profile=profile)
            typer.echo(f"Explorer UI assets refreshed ({updated} files); analytical data reused.")
            typer.echo("Note: --ui-only does not check source-data freshness. Use plain 'sigma view' to validate inputs, or --refresh to rebuild data.")
        elif refresh or not bundle_is_current(source, destination, include_roads=roads, profile=profile):
            result = build_web_bundle(source, destination, include_roads=roads, force=True, profile=profile)
            for warning in result.get("warnings", []):
                typer.echo(f"Note: {warning}")
            typer.echo(f"Explorer data built from the latest SIGMA outputs: {result['destination']}")
        else:
            typer.echo("Explorer data already match the latest SIGMA outputs.")
        serve_bundle(destination, port=port, open_browser=not no_browser)
    except (SigmaError, OSError, ValueError, KeyError) as exc:
        _handle_error(exc)
# SIGMA_EXPLORER_OVERLAY_V3_END


if __name__ == "__main__":
    app()
# sigma-canonical-sparse-hierarchy-v1

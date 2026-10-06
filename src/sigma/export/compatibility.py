"""Managed C17 compatibility/unified export bundle.

Public filenames remain mutable publication contracts; the actual export bundle is
first committed as an immutable managed artifact and only then atomically copied to
``workspace.output_dir``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
from types import MappingProxyType
from typing import Mapping

import geopandas as gpd
import pandas as pd

from sigma._version import __version__
from sigma.artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite
from sigma.execution import ExecutionPlanner
from sigma.places.frame_io import read_geoframe
from sigma.places.pipeline import _attribution_text, _database_license_text, _terms
from sigma.stages import StageSpec
from sigma.workspace import SigmaWorkspace

from .qgis import WGS84, annotate_types, as_wgs84, build_sector_styles, write_qgis_project
from .spatial import build_x_node_outputs, spatial_summary, write_outputs_description, write_spatial_geopackage


@dataclass(frozen=True, slots=True)
class ExportBundle:
    artifact: ArtifactRef
    output_dir: Path
    files: Mapping[str, Path]
    run_manifest: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _clip_roads_to_boundary(
    roads: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Clip only the published road copy to the exact area boundary.

    The managed ``transport.roads`` artifact remains buffered and unchanged for
    routing, snapping, clustering, Voronoi construction, and shortest paths.
    """
    if roads.empty:
        return roads.copy()
    if boundary.empty:
        return roads.iloc[0:0].copy()
    if roads.crs is None or boundary.crs is None:
        raise ValueError("published roads and area boundary must both have a CRS")
    clip_boundary = boundary if roads.crs == boundary.crs else boundary.to_crs(roads.crs)
    clipped = gpd.clip(roads, clip_boundary, keep_geom_type=True)
    clipped = clipped.loc[
        clipped.geometry.notna() & ~clipped.geometry.is_empty
    ].copy()
    return clipped.reset_index(drop=True)


def _build_published_points(
    scores: gpd.GeoDataFrame,
    centrality_table: pd.DataFrame,
    *,
    clustered: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Consolidate the public establishment output into one point layer.

    Managed clustering, point-distance, centrality, and score artifacts remain
    separate internally for caching and provenance.  Only their publication
    surface is merged here.
    """
    if scores.crs is None:
        raise ValueError("published point scores require a declared CRS")
    required = {"type", "cluster", "geometry"}
    missing = required - set(scores.columns)
    if missing:
        raise ValueError(f"published point scores are missing columns: {sorted(missing)}")

    out = scores.copy()
    centrality_columns = [
        column
        for column in (
            "type",
            "cluster",
            "node_id",
            "in_degree",
            "out_degree",
            "katz_in_raw",
            "katz_out_raw",
            "centrality",
        )
        if column in centrality_table.columns
    ]
    if not {"type", "cluster"} <= set(centrality_columns):
        raise ValueError("centrality table must contain type and cluster")
    out = out.merge(
        centrality_table[centrality_columns],
        on=["type", "cluster"],
        how="left",
        validate="many_to_one",
    )

    if clustered is not None and not clustered.empty:
        if "canonical_id" in out.columns and "canonical_id" in clustered.columns:
            key = "canonical_id"
        elif "point_id" in out.columns and "point_id" in clustered.columns:
            key = "point_id"
        else:
            key = None
        if key is not None:
            cluster_extras = []
            for column in clustered.columns:
                if column in out.columns or column == clustered.geometry.name:
                    continue
                series = clustered[column]
                # The final public point product must have exactly one geometry
                # column. Internal clustering may carry auxiliary Shapely/GeoSeries
                # values such as ``network_position``; those remain available in
                # managed spatial artifacts but are not duplicated into the
                # consolidated publication or restart handoff.
                if isinstance(series.dtype, gpd.array.GeometryDtype):
                    continue
                sample = series.dropna().head(1)
                if len(sample) and hasattr(sample.iloc[0], "geom_type"):
                    continue
                cluster_extras.append(column)
            if cluster_extras:
                out = out.merge(
                    clustered[[key, *cluster_extras]],
                    on=key,
                    how="left",
                    validate="one_to_one",
                )

    return gpd.GeoDataFrame(out, geometry=scores.geometry.name, crs=scores.crs)


def _deterministic_created_at(workspace: SigmaWorkspace, deps: Mapping[str, ArtifactRef]) -> str:
    stamps: list[str] = []
    for ref in deps.values():
        try:
            stamps.append(workspace.artifacts.manifest(ref).created_at)
        except Exception:
            pass
    return max(stamps) if stamps else "1970-01-01T00:00:00+00:00"


class ExportPipeline:
    """Publish legacy Siphon/Engine files plus unified lineage from managed artifacts."""

    def __init__(
        self,
        workspace: SigmaWorkspace,
        *,
        analysis_pipeline,
        spatial_pipeline,
        economy_pipeline,
        place_pipeline=None,
        compatibility: bool = True,
        unified: bool = True,
        progress=None,
    ):
        self.workspace = workspace
        self.analysis = analysis_pipeline
        self.spatial = spatial_pipeline
        self.economy = economy_pipeline
        self.places = place_pipeline
        self.compatibility = bool(compatibility)
        self.unified = bool(unified)
        self.progress = progress
        stages = dict(analysis_pipeline.planner.stages)
        dependencies = [
            "spatial.centers",
            "spatial.point_distances",
            "spatial.partitions",
            "transport.roads",
            economy_pipeline.analysis_graph_stage,
            "analysis.x",
            "analysis.centrality",
            "analysis.scores",
        ]
        if place_pipeline is not None:
            dependencies.insert(0, "area.boundary")
        if "spatial.clusters" in stages:
            dependencies.insert(0, "spatial.clusters")
        if (
            place_pipeline is not None
            and getattr(spatial_pipeline, "points_path", None) is None
            and "places.classified" in stages
        ):
            dependencies.insert(0, "places.classified")
        stages["export.bundle"] = StageSpec(
            "export.bundle", tuple(dependencies), self._recipe, self._execute
        )
        self.planner = ExecutionPlanner(workspace, stages, progress=progress)

    def _recipe(self, planner, deps) -> ArtifactRecipe:
        return ArtifactRecipe.build(
            "export.bundle",
            implementation_version="unified-compatibility-export-qgis-v7-single-points-scalar-only",
            dependencies=deps,
            parameters={
                "compatibility": self.compatibility,
                "unified": self.unified,
                "legacy_mwas_method": self.economy.config.legacy_mwas_method,
                "published_crs": WGS84,
                "qgis_parquet_datasource": "bare-relative-v1",
            },
        )

    def _execute(self, planner, recipe, deps, write: ArtifactWrite):
        created_at = _deterministic_created_at(self.workspace, deps)
        outputs: dict[str, str] = {}

        # Publish the exact user-visible places handoff consumed by analysis.  In the
        # legacy direct place branch, fall back to the immutable classified artifact.
        tagged = None
        handoff_path = (
            getattr(self.spatial, "points_path", None) if self.places is not None else None
        )
        if handoff_path is not None:
            tagged = gpd.read_parquet(handoff_path)
        elif "places.classified" in deps and self.places is not None:
            tagged = self.places.read_classified(deps["places.classified"])
        sector_styles = build_sector_styles(self.economy.economy.sectors)

        if tagged is not None:
            tagged = as_wgs84(annotate_types(tagged, sector_styles))
            tagged.to_parquet(write.output("pois.parquet"), index=False)
            source_licenses = _terms(tagged["source_licenses"]) if len(tagged) and "source_licenses" in tagged else []
            write.output("ATTRIBUTION.txt").write_text(_attribution_text(tagged), encoding="utf-8")
            write.output("DATABASE_LICENSE.txt").write_text(
                _database_license_text(source_licenses), encoding="utf-8"
            )
            run_report = self._siphon_run_report(tagged, deps, created_at)
            if handoff_path is not None:
                run_report["analysis_places_input"] = str(handoff_path)
            write.output("run.json").write_text(
                json.dumps(run_report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            outputs.update({name: name for name in ("pois.parquet", "ATTRIBUTION.txt", "DATABASE_LICENSE.txt", "run.json")})

        centers_analysis = self.spatial.read_centers(deps["spatial.centers"])
        partitions_analysis = self.spatial.read_partitions(deps["spatial.partitions"])
        centers = as_wgs84(annotate_types(centers_analysis, sector_styles))
        partitions = as_wgs84(annotate_types(partitions_analysis, sector_styles))
        centers.to_parquet(write.output("sigma_network_centers.parquet"), index=False)
        partitions.to_parquet(write.output("sigma_partitions.parquet"), index=False)
        outputs.update({
            "sigma_network_centers.parquet": "sigma_network_centers.parquet",
            "sigma_partitions.parquet": "sigma_partitions.parquet",
        })

        economic_ref = deps[self.economy.analysis_graph_stage]
        if economic_ref.stage == "economy.graph.legacy_mwas":
            shutil.copy2(economic_ref.path / "io_dag.csv", write.output("sigma_io_dag.csv"))
            outputs["sigma_io_dag.csv"] = "sigma_io_dag.csv"
        else:
            shutil.copy2(economic_ref.path / "economic_graph.csv", write.output("sigma_economic_graph.csv"))
            outputs["sigma_economic_graph.csv"] = "sigma_economic_graph.csv"

        x = self.analysis.load_x(deps["analysis.x"])
        centrality = self.analysis.load_centrality(deps["analysis.centrality"])
        scores_analysis = self.analysis.read_scores(deps["analysis.scores"])
        centrality_table = self.analysis.read_centrality_table(deps["analysis.centrality"])
        clustered = None
        if "spatial.clusters" in deps and hasattr(self.spatial, "read_clusters"):
            clustered = self.spatial.read_clusters(deps["spatial.clusters"], public=True)
        published_points = as_wgs84(
            annotate_types(
                _build_published_points(
                    scores_analysis,
                    centrality_table,
                    clustered=clustered,
                ),
                sector_styles,
            )
        )
        node_table, node_geo = build_x_node_outputs(x.graph, centrality.values, centers_analysis.crs)
        x_paths = as_wgs84(x.paths)
        node_table.to_csv(write.output("sigma_X_nodes.csv"), index=False, float_format="%.17g", lineterminator="\n")
        x.edges.to_csv(write.output("sigma_X_edges.csv"), index=False, float_format="%.17g", lineterminator="\n")
        x.disconnected.to_csv(write.output("sigma_disconnected_overlap_pairs.csv"), index=False, lineterminator="\n")
        published_points.to_parquet(write.output("sigma_points.parquet"), index=False)
        write_spatial_geopackage(
            write.output("sigma_spatial_outputs.gpkg"), partitions, node_geo, x_paths
        )

        roads = as_wgs84(read_geoframe(deps["transport.roads"].path / "roads.json"))
        boundary = None
        if "area.boundary" in deps and self.workspace.area is not None:
            payload = json.loads((deps["area.boundary"].path / "boundary.json").read_text(encoding="utf-8"))
            boundary_source_crs = str(payload.get("crs") or WGS84)
            boundary = as_wgs84(gpd.GeoDataFrame(
                {"area_slug": [self.workspace.area.slug], "area_name": [self.workspace.area.name]},
                geometry=gpd.GeoSeries.from_wkb(
                    [bytes.fromhex(str(payload["geometry_wkb_hex"]))], crs=boundary_source_crs
                ),
                crs=boundary_source_crs,
            ))
            roads = _clip_roads_to_boundary(roads, boundary)

        roads.to_parquet(write.output("sigma_roads.parquet"), index=False)
        outputs["sigma_roads.parquet"] = "sigma_roads.parquet"

        if boundary is not None:
            boundary.to_parquet(write.output("sigma_boundary.parquet"), index=False)
            outputs["sigma_boundary.parquet"] = "sigma_boundary.parquet"

            project_name = f"{self.workspace.area.slug}.qgz"
            write_qgis_project(
                write.output(project_name),
                area_name=self.workspace.area.name,
                area_slug=self.workspace.area.slug,
                boundary=boundary,
                roads=roads,
                partitions=partitions,
                centers=centers,
                points=published_points,
                styles=sector_styles,
            )
            outputs[project_name] = project_name

        outputs.update({name: name for name in (
            "sigma_X_nodes.csv", "sigma_X_edges.csv", "sigma_disconnected_overlap_pairs.csv",
            "sigma_points.parquet", "sigma_spatial_outputs.gpkg",
        )})

        summary = spatial_summary(partitions=partitions, nodes=node_geo, paths=x_paths)
        area = self.workspace.area
        economy_id = self.economy.economy.economy_id
        if self.places is not None:
            classification = f"PSIC -> {economy_id}"
        elif getattr(self.spatial.config, "classification", None):
            classification = str(self.spatial.config.classification)
        else:
            classification = f"economy_code ({economy_id})"
        metadata = {
            "sigma_version": __version__,
            "workflow_version": "unified-c17-qgis-v5-single-points-scalar-only",
            "created_at": created_at,
            "python": platform.python_version(),
            "entrypoint": "from-partitions" if not hasattr(self.spatial, "read_clusters") else "run",
            "economy_id": economy_id,
            "classification": classification,
            "area_slug": area.slug if area is not None else None,
            "area_name": area.name if area is not None else None,
            "transaction_preprocessing": self.economy.config.transaction_preprocessing,
            "legacy_mwas_method": self.economy.config.legacy_mwas_method,
            "x_nodes": len(node_table),
            "x_edges": len(x.edges),
            "scored_points": len(published_points),
            "disconnected_overlap_pairs": len(x.disconnected),
            "road_distance_crs": str(centers_analysis.crs),
            "export_crs": WGS84,
            "published_roads_clipped_to_area": boundary is not None,
            "road_distance_unit": "CRS units",
            **summary,
            "artifacts": {name: ref.artifact_id for name, ref in sorted(deps.items())},
        }
        write.output("sigma_run_metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        outputs["sigma_run_metadata.json"] = "sigma_run_metadata.json"
        description_paths = {name: name for name in outputs}
        write_outputs_description(
            write.output("OUTPUTS.txt"), metadata=metadata, output_paths=description_paths
        )
        outputs["OUTPUTS.txt"] = "OUTPUTS.txt"

        # Unified manifest describes the immutable bundle's dependency lineage and files.
        current_files = []
        for name in sorted(outputs):
            path = write.path / outputs[name]
            current_files.append({"name": name, "size": path.stat().st_size, "sha256": _sha256(path)})
        unified = {
            "schema_version": 1,
            "sigma_version": __version__,
            "created_at": created_at,
            "workspace_id": self.workspace.identity,
            "area_identity": self.workspace.area_identity,
            "dependencies": {
                name: {"stage": ref.stage, "artifact_id": ref.artifact_id, "recipe_fingerprint": ref.recipe_fingerprint}
                for name, ref in sorted(deps.items())
            },
            "files": current_files,
        }
        write.output("sigma_manifest.json").write_text(
            json.dumps(unified, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        outputs["sigma_manifest.json"] = "sigma_manifest.json"
        return {"file_count": len(outputs), "created_at": created_at}, {"published_contract": "c17"}

    def _siphon_run_report(self, tagged: gpd.GeoDataFrame, deps, created_at: str) -> dict[str, object]:
        area = self.workspace.area
        report: dict[str, object] = {
            "package": "sigma-siphon",
            "version": "0.5.0",
            "sigma_version": __version__,
            "created_at": created_at,
            "python": platform.python_version(),
            "area": None if area is None else {
                "slug": area.slug, "name": area.name, "kind": area.kind,
                "psgc_code": area.psgc_code, "bbox": list(area.bbox),
            },
            "counts": {"canonical": len(tagged), "tagged": int(tagged.get("economy_code", pd.Series(dtype=str)).astype("string").fillna("").str.strip().ne("").sum())},
            "classification": {"architecture": "psic-primary-hybrid-io", "psic_canonical": True},
            "output": "pois.parquet",
            "classified_places_artifact_id": (
                deps["places.classified"].artifact_id if "places.classified" in deps else None
            ),
        }
        # Preserve richer managed metadata when available without inventing values.
        for stage, key in (("places.canonical", "canonical"), ("places.psic", "psic")):
            manifest = self.workspace.manifest(stage)
            if manifest is not None:
                managed = report.setdefault("managed_stage_metadata", {})
                assert isinstance(managed, dict)
                managed[key] = manifest.to_dict()["metadata"]
        return report

    def ensure_bundle(self) -> ArtifactRef:
        # Never force byte-regeneration for container formats such as GPKG. If the recipe
        # is identical, immutable reuse is the correct meaning of export recomputation.
        return self.planner.ensure("export.bundle", force=False)

    def publish(self, ref: ArtifactRef | None = None) -> ExportBundle:
        ref = ref or self.ensure_bundle()
        output_dir = self.workspace.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".sigma-export-", dir=output_dir))
        try:
            files: dict[str, Path] = {}
            for item in self.workspace.artifacts.manifest(ref).files:
                if item.path == "manifest.json":
                    continue
                source = ref.path / item.path
                target_tmp = tmp / item.path
                target_tmp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target_tmp)
            for path in sorted(tmp.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(tmp)
                    target = output_dir / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(path, target)
                    files[str(rel)] = target
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        run_manifest = output_dir / "sigma_manifest.json"
        return ExportBundle(ref, output_dir, files, run_manifest)

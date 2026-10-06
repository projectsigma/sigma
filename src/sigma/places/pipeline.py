from __future__ import annotations

import hashlib
import json
import platform
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping

import geopandas as gpd
from shapely import from_wkb, to_wkb

from sigma._version import __version__
from sigma.area import Area, boundary_identity, clip_points, load_boundary, resolve_area
from sigma.artifacts import ArtifactRecipe, ArtifactRef, ArtifactWrite
from sigma.classification import (
    ClassificationDecisionCache,
    EconomicTagger,
    HierarchicalPsicTraverser,
    OpenAICompatibleBackend,
    PsicClassifier,
    TaggingReferences,
    hybrid_io_coverage_summary,
    load_builtin_psic_taxonomy,
)
from sigma.classification.source_rules import source_rules_fingerprint
from sigma.economy import Economy
from sigma.execution import ExecutionPlanner
from sigma.sources import SourceRef, SourceStore
from sigma.stages import StageSpec
from sigma.workspace import SigmaWorkspace

from .frame_io import read_geoframe, write_geoframe
from .reconcile import reconcile

ProgressCallback = Callable[[str], None]


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _hash_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _terms(series) -> list[str]:
    values: set[str] = set()
    for value in series.fillna(""):
        values.update(part.strip() for part in str(value).split("|") if part.strip())
    return sorted(values)


def _attribution_text(tagged) -> str:
    providers = set(_terms(tagged["overture_providers"])) if len(tagged) else set()
    return "\n".join(
        [
            "SIGMA output source attribution",
            "",
            "OpenStreetMap / Geofabrik",
            "Contains information from OpenStreetMap contributors, available under ODbL 1.0.",
            "Philippines extract obtained from Geofabrik GmbH.",
            "https://www.openstreetmap.org/copyright",
            "https://download.geofabrik.de/asia/philippines.html",
            "",
            "Overture Maps Places",
            "Contains data obtained from Overture Maps Foundation Places.",
            "https://docs.overturemaps.org/attribution/",
            "",
            "Observed Overture providers: " + (", ".join(sorted(providers)) or "none recorded"),
            "",
            "Database note",
            "When OSM-derived records are present, this fused POI database is distributed under ODbL 1.0 as a conservative compliance posture for a reconciled database.",
            "",
            "Software",
            "SIGMA software is proprietary and all rights are reserved. Third-party software and source-data licensing are separate.",
            "",
        ]
    )


def _database_license_text(source_licenses: list[str]) -> str:
    if "ODbL-1.0" not in source_licenses:
        return "No ODbL-covered source records were observed in this output.\n"
    return (
        "DATABASE LICENSE NOTICE\n\n"
        "This fused POI database is distributed under the Open Database License (ODbL) 1.0 "
        "as the project's conservative compliance posture for a reconciled database containing "
        "OpenStreetMap-derived records.\n\n"
        "OpenStreetMap attribution: © OpenStreetMap contributors.\n"
        "Geofabrik extract: https://download.geofabrik.de/asia/philippines.html\n"
        "ODbL 1.0: https://opendatacommons.org/licenses/odbl/1-0/\n\n"
        "Individual Overture-origin source content retains its applicable upstream provider "
        "terms. See ATTRIBUTION.txt and the per-row source_licenses field.\n"
    )


@dataclass(frozen=True, slots=True)
class PlaceRunConfig:
    clip: bool = True
    refresh_geofabrik: bool = False
    refresh_overture: bool = False
    use_llm: bool = False
    top_n: int = 5
    min_score: float = 0.45
    min_margin: float = 0.12
    llm_retrieval_top_n: int = 20


@dataclass(slots=True)
class PlaceServices:
    """Provider seams for deterministic tests; production defaults preserve Siphon behavior."""

    geofabrik: Callable[[SourceStore, PlaceRunConfig, ProgressCallback | None], SourceRef] | None = None
    overture: Callable[[SourceStore, tuple[float, float, float, float], PlaceRunConfig, ProgressCallback | None], SourceRef] | None = None
    load_overture: Callable[[SourceRef], gpd.GeoDataFrame] | None = None
    load_prepared_osm: Callable[[Path, SourceRef, str, Path | None, ProgressCallback | None], tuple[gpd.GeoDataFrame, str, bool]] | None = None
    taxonomy: Callable[[], object] | None = None
    references: Callable[[object, Economy], TaggingReferences] | None = None


class PlacePipeline:
    """C8 place-branch stage wrapper around preserved Siphon components."""

    def __init__(
        self,
        workspace: SigmaWorkspace,
        *,
        area: Area,
        economy: Economy | None = None,
        config: PlaceRunConfig | None = None,
        areas_file: Path | None = None,
        services: PlaceServices | None = None,
        progress: ProgressCallback | None = None,
    ):
        self.workspace = workspace
        self.area = area
        self.economy = economy or Economy.default()
        self.config = config or PlaceRunConfig()
        self.areas_file = Path(areas_file).resolve() if areas_file is not None else None
        self.services = services or PlaceServices()
        self.progress = progress
        self._started = time.monotonic()
        self._area_source_refs = self._register_area_sources()
        self._taxonomy = None
        self._references = None
        self.planner = ExecutionPlanner(workspace, self._build_stages(), progress=progress)

    def _say(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    def _register_area_sources(self) -> dict[str, SourceRef]:
        store = self.workspace.sources
        refs: dict[str, SourceRef] = {}
        if self.areas_file is not None:
            refs["areas_catalog"] = store.register_user_file(self.areas_file, name="areas-catalog")
            if self.area.boundary is not None:
                refs["boundary_dataset"] = store.register_user_file(
                    self.area.boundary.gpkg, name="area-boundary-dataset", layer=self.area.boundary.layer
                )
        else:
            from sigma.area import default_areas_path

            catalog = default_areas_path()
            refs["areas_catalog"] = store.register_packaged_reference("areas-catalog", catalog)
            if self.area.boundary is not None:
                refs["boundary_dataset"] = store.register_packaged_reference(
                    "areas-boundary-gpkg", self.area.boundary.gpkg
                )
        return refs

    def _taxonomy_obj(self):
        if self._taxonomy is None:
            self._taxonomy = (self.services.taxonomy or load_builtin_psic_taxonomy)()
        return self._taxonomy

    def _reference_obj(self) -> TaggingReferences:
        if self._references is None:
            taxonomy = self._taxonomy_obj()
            factory = self.services.references or (lambda t, e: TaggingReferences.builtin(t, e))
            self._references = factory(taxonomy, self.economy)
        return self._references

    def _geofabrik_ref(self, planner: ExecutionPlanner) -> SourceRef:
        cached = planner.runtime.get("geofabrik_ref")
        if isinstance(cached, SourceRef):
            return cached
        if planner.runtime.get("_inspection"):
            ref = self.workspace.sources.current_geofabrik()
            if ref is None:
                raise RuntimeError("no current Geofabrik snapshot")
        elif self.services.geofabrik is not None:
            ref = self.services.geofabrik(self.workspace.sources, self.config, self.progress)
        else:
            ref = self.workspace.sources.ensure_geofabrik(
                refresh=self.config.refresh_geofabrik, progress=self.progress
            )
        planner.runtime["geofabrik_ref"] = ref
        return ref

    def _overture_ref(self, planner: ExecutionPlanner) -> SourceRef:
        cached = planner.runtime.get("overture_ref")
        if isinstance(cached, SourceRef):
            return cached
        if planner.runtime.get("_inspection"):
            ref = self.workspace.sources.current_overture(self.area.bbox)
            if ref is None:
                raise RuntimeError("no current Overture snapshot")
        elif self.services.overture is not None:
            ref = self.services.overture(self.workspace.sources, self.area.bbox, self.config, self.progress)
        else:
            ref = self.workspace.sources.fetch_overture_snapshot(
                self.area.bbox, refresh=self.config.refresh_overture, progress=self.progress
            )
        planner.runtime["overture_ref"] = ref
        return ref

    @staticmethod
    def _read_source_ref(planner: ExecutionPlanner, ref: ArtifactRef) -> SourceRef:
        payload = _read_json(ref.path / "source.json")
        return planner.workspace.sources.get(str(payload["source_id"]))

    @staticmethod
    def _read_boundary(ref: ArtifactRef):
        payload = _read_json(ref.path / "boundary.json")
        return from_wkb(bytes.fromhex(str(payload["geometry_wkb_hex"])))

    def _build_stages(self) -> dict[str, StageSpec]:
        return {
            "area.definition": StageSpec("area.definition", (), self._recipe_area_definition, self._exec_area_definition),
            "area.boundary": StageSpec("area.boundary", ("area.definition",), self._recipe_area_boundary, self._exec_area_boundary),
            "source.geofabrik_pbf": StageSpec("source.geofabrik_pbf", (), self._recipe_geofabrik, self._exec_source_pointer),
            "source.osm_national_pois": StageSpec("source.osm_national_pois", ("source.geofabrik_pbf",), self._recipe_osm_national, self._exec_osm_national),
            "source.osm_area_index": StageSpec("source.osm_area_index", ("source.osm_national_pois", "area.definition"), self._recipe_osm_index, self._exec_osm_index),
            "source.overture_snapshot": StageSpec("source.overture_snapshot", (), self._recipe_overture_snapshot, self._exec_source_pointer),
            "places.osm_area": StageSpec("places.osm_area", ("source.osm_area_index", "area.boundary"), self._recipe_osm_area, self._exec_osm_area),
            "places.overture_area": StageSpec("places.overture_area", ("source.overture_snapshot", "area.boundary"), self._recipe_overture_area, self._exec_overture_area),
            "places.canonical": StageSpec("places.canonical", ("places.osm_area", "places.overture_area", "area.boundary"), self._recipe_canonical, self._exec_canonical),
            "classification.taxonomy": StageSpec("classification.taxonomy", (), self._recipe_taxonomy, self._exec_taxonomy),
            "classification.tagging_references": StageSpec("classification.tagging_references", ("classification.taxonomy",), self._recipe_tagging_refs, self._exec_tagging_refs),
            "places.psic": StageSpec("places.psic", ("places.canonical", "classification.taxonomy"), self._recipe_psic, self._exec_psic),
            "places.classified": StageSpec("places.classified", ("places.psic", "classification.tagging_references"), self._recipe_classified, self._exec_classified),
        }

    # ---- recipes -----------------------------------------------------
    def _recipe_area_definition(self, planner, deps):
        return ArtifactRecipe.build(
            "area.definition", implementation_version="c8-area-definition-v1",
            sources=self._area_source_refs,
            identities={"area": self.workspace.area_identity or _hash_payload(self.area.slug)},
        )

    def _recipe_area_boundary(self, planner, deps):
        sources = {k: v for k, v in self._area_source_refs.items() if k == "boundary_dataset"}
        return ArtifactRecipe.build(
            "area.boundary", implementation_version="c8-boundary-v1", dependencies=deps,
            sources=sources, identities={"area": self.workspace.area_identity or ""},
        )

    def _recipe_geofabrik(self, planner, deps):
        source = self._geofabrik_ref(planner)
        return ArtifactRecipe.build(
            "source.geofabrik_pbf", implementation_version="c8-geofabrik-source-v1",
            sources={"geofabrik": source},
        )

    def _recipe_osm_national(self, planner, deps):
        gf = self._read_source_ref(planner, deps["source.geofabrik_pbf"])
        return ArtifactRecipe.build(
            "source.osm_national_pois", implementation_version="c8-osm-national-recipe-v2-provisional-fallback",
            dependencies=deps, sources={"geofabrik": gf, **self._area_source_refs},
            parameters={"preparer": "sigma.sources.osm_prepare"},
        )

    def _recipe_osm_index(self, planner, deps):
        return ArtifactRecipe.build(
            "source.osm_area_index", implementation_version="c8-osm-area-index-v1",
            dependencies=deps, parameters={"area_slug": self.area.slug},
            identities={"area": self.workspace.area_identity or ""},
        )

    def _recipe_overture_snapshot(self, planner, deps):
        source = self._overture_ref(planner)
        return ArtifactRecipe.build(
            "source.overture_snapshot", implementation_version="c8-overture-source-v1",
            sources={"overture": source}, parameters={"bbox": list(self.area.bbox)},
        )

    def _recipe_osm_area(self, planner, deps):
        return ArtifactRecipe.build(
            "places.osm_area", implementation_version="c8-osm-area-v1", dependencies=deps,
            parameters={"clip": self.config.clip},
        )

    def _recipe_overture_area(self, planner, deps):
        return ArtifactRecipe.build(
            "places.overture_area", implementation_version="c8-overture-area-v1", dependencies=deps,
            parameters={"clip": self.config.clip},
        )

    def _recipe_canonical(self, planner, deps):
        return ArtifactRecipe.build(
            "places.canonical", implementation_version="siphon-reconcile-v1", dependencies=deps,
            parameters={"clip": self.config.clip},
        )

    def _recipe_taxonomy(self, planner, deps):
        taxonomy = self._taxonomy_obj()
        return ArtifactRecipe.build(
            "classification.taxonomy", implementation_version="c8-taxonomy-v1",
            identities={"taxonomy_fingerprint": taxonomy.fingerprint},
            resources={"origin": getattr(taxonomy, "origin", "custom"), "asset_sha256": getattr(taxonomy, "asset_sha256", None)},
        )

    def _recipe_tagging_refs(self, planner, deps):
        refs = self._reference_obj()
        return ArtifactRecipe.build(
            "classification.tagging_references", implementation_version="c8-tagging-refs-v2-semantic-content",
            dependencies=deps,
            identities={
                "references_fingerprint": refs.fingerprint,
                "taxonomy_fingerprint": refs.taxonomy_fingerprint,
                "economy_sector_fingerprint": self.economy.sector_fingerprint,
            },
        )

    def _recipe_psic(self, planner, deps):
        taxonomy = self._taxonomy_obj()
        refs = self._reference_obj()
        llm_identity = None
        if self.config.use_llm:
            base_url, model = OpenAICompatibleBackend.configuration_from_environment()
            llm_identity = {"base_url": base_url, "model": model}
        return ArtifactRecipe.build(
            "places.psic", implementation_version="siphon-psic-classifier-v2-rule-and-llm-identity", dependencies=deps,
            parameters={
                "top_n": self.config.top_n,
                "min_score": self.config.min_score,
                "min_margin": self.config.min_margin,
                "use_llm": self.config.use_llm,
                "llm_retrieval_top_n": self.config.llm_retrieval_top_n,
            },
            identities={
                "taxonomy_fingerprint": taxonomy.fingerprint,
                "source_to_psic_refs": refs.fingerprint,
                "source_rules_fingerprint": source_rules_fingerprint(),
                "llm": llm_identity,
            },
        )

    def _recipe_classified(self, planner, deps):
        refs = self._reference_obj()
        return ArtifactRecipe.build(
            "places.classified", implementation_version="c8-economic-tagging-v1", dependencies=deps,
            identities={
                "economy_sector_fingerprint": self.economy.sector_fingerprint,
                "tagging_references_fingerprint": refs.fingerprint,
            },
        )

    # ---- executors ---------------------------------------------------
    def _exec_area_definition(self, planner, recipe, deps, write):
        _write_json(write.output("area.json"), {
            "slug": self.area.slug, "name": self.area.name, "kind": self.area.kind,
            "bbox": list(self.area.bbox), "psgc_code": self.area.psgc_code,
        })
        return {"area_slug": self.area.slug}, {}

    def _exec_area_boundary(self, planner, recipe, deps, write):
        geometry = load_boundary(self.area)
        report = boundary_identity(self.area, geometry)
        _write_json(write.output("boundary.json"), {
            **report, "geometry_wkb_hex": to_wkb(geometry).hex(), "crs": "EPSG:4326",
        })
        return report, {}

    def _exec_source_pointer(self, planner, recipe, deps, write):
        if recipe.stage == "source.geofabrik_pbf":
            source = self._geofabrik_ref(planner)
        elif recipe.stage == "source.overture_snapshot":
            source = self._overture_ref(planner)
        else:
            raise RuntimeError(f"unexpected source pointer stage: {recipe.stage}")
        _write_json(write.output("source.json"), {"source_id": source.source_id, "sha256": source.sha256})
        return {"source_id": source.source_id, "sha256": source.sha256}, {}

    def _exec_osm_national(self, planner, recipe, deps, write):
        gf = self._read_source_ref(planner, deps["source.geofabrik_pbf"])
        # Preserve the legacy fallback across Geofabrik versions by keeping those
        # versions in one preparer cache namespace. Only the area-resource/preparer
        # identity partitions that namespace, closing the old stale-catalog gap.
        preparation_policy = _hash_payload({
            "implementation": "c8-osm-national-recipe-v1",
            "area_sources": {key: ref.source_id for key, ref in sorted(self._area_source_refs.items())},
        })
        cache_base = self.workspace.sources.root / "prepared-osm-recipes" / preparation_policy
        cache_base.mkdir(parents=True, exist_ok=True)
        _write_json(cache_base / "geofabrik" / "philippines-latest.meta.json", {
            "source_version": gf.version or f"sha256-{gf.sha256[:16]}",
            "source_id": gf.source_id, "sha256": gf.sha256,
            "source_url": gf.metadata.get("source_url"),
        })
        if self.services.load_prepared_osm is not None:
            frame, version, fallback = self.services.load_prepared_osm(
                cache_base, gf, self.area.slug, self.areas_file, self.progress
            )
        else:
            from sigma.sources.osm_prepare import load_prepared_area_osm
            frame, version, fallback = load_prepared_area_osm(
                cache_base=cache_base, pbf_file=gf.path, area_slug=self.area.slug,
                areas_file=self.areas_file, progress=self.progress,
            )
        write_geoframe(frame, write.output("osm-area.json"))
        _write_json(write.output("preparation.json"), {
            "cache_base": str(cache_base), "preparation_policy": preparation_policy,
            "geofabrik_source_id": gf.source_id, "prepared_source_version": version,
            "fallback_to_previous_complete_version": bool(fallback),
        })
        return {
            "cache_base": str(cache_base), "preparation_policy": preparation_policy,
            "geofabrik_source_id": gf.source_id, "prepared_source_version": version,
            "fallback": bool(fallback),
            # A cross-version fallback is useful for completing the current run, but it is
            # provisional: the next run must retry preparation for the requested source.
            "cache_reusable": not bool(fallback),
        }, {}

    def _exec_osm_index(self, planner, recipe, deps, write):
        national = deps["source.osm_national_pois"]
        prep = _read_json(national.path / "preparation.json")
        frame = read_geoframe(national.path / "osm-area.json")
        write_geoframe(frame, write.output("osm-area.json"))
        _write_json(write.output("index.json"), {
            "area_slug": self.area.slug,
            "prepared_source_version": prep.get("prepared_source_version"),
            "fallback_to_previous_complete_version": bool(prep.get("fallback_to_previous_complete_version", False)),
        })
        return {
            "area_slug": self.area.slug,
            "prepared_source_version": prep.get("prepared_source_version"),
            "fallback": bool(prep.get("fallback_to_previous_complete_version", False)),
        }, {}

    def _exec_osm_area(self, planner, recipe, deps, write):
        frame = read_geoframe(deps["source.osm_area_index"].path / "osm-area.json")
        if self.config.clip:
            frame = clip_points(frame, self._read_boundary(deps["area.boundary"]))
        write_geoframe(frame, write.output("places.json"))
        return {"rows": len(frame), "clip": self.config.clip}, {}

    def _exec_overture_area(self, planner, recipe, deps, write):
        source = self._read_source_ref(planner, deps["source.overture_snapshot"])
        if self.services.load_overture is not None:
            frame = self.services.load_overture(source)
        else:
            frame = gpd.read_parquet(source.path)
        if self.config.clip:
            frame = clip_points(frame, self._read_boundary(deps["area.boundary"]))
        write_geoframe(frame, write.output("places.json"))
        return {"rows": len(frame), "clip": self.config.clip}, {}

    def _exec_canonical(self, planner, recipe, deps, write):
        osm = read_geoframe(deps["places.osm_area"].path / "places.json")
        overture = read_geoframe(deps["places.overture_area"].path / "places.json")
        boundary = self._read_boundary(deps["area.boundary"]) if self.config.clip else None
        frame = reconcile(osm, overture, boundary=boundary)
        if boundary is not None and len(frame):
            inside = frame.geometry.covered_by(boundary)
            if not bool(inside.all()):
                raise RuntimeError("canonical output contains coordinates outside the configured boundary")
        write_geoframe(frame, write.output("places.json"))
        matched = int((frame["source_count"] == 2).sum()) if len(frame) else 0
        return {"rows": len(frame), "matched_two_source": matched}, {}

    def _exec_taxonomy(self, planner, recipe, deps, write):
        taxonomy = self._taxonomy_obj()
        _write_json(write.output("taxonomy.json"), {
            "scheme": taxonomy.scheme, "version": taxonomy.version,
            "fingerprint": taxonomy.fingerprint, "node_count": len(taxonomy.nodes),
            "origin": getattr(taxonomy, "origin", "custom"),
        })
        return {"fingerprint": taxonomy.fingerprint, "nodes": len(taxonomy.nodes)}, {}

    def _exec_tagging_refs(self, planner, recipe, deps, write):
        refs = self._reference_obj()
        _write_json(write.output("references.json"), {
            "fingerprint": refs.fingerprint, "profile": refs.profile,
            "taxonomy_fingerprint": refs.taxonomy_fingerprint,
            "economy_sector_fingerprint": refs.economy_sector_fingerprint,
        })
        return {"fingerprint": refs.fingerprint, "profile": refs.profile}, {}

    def _exec_psic(self, planner, recipe, deps, write):
        canonical = read_geoframe(deps["places.canonical"].path / "places.json")
        taxonomy = self._taxonomy_obj()
        refs = self._reference_obj()
        decision_cache = None
        traverser = None
        backend = OpenAICompatibleBackend.from_environment() if self.config.use_llm else None
        if backend is not None:
            cache_path = self.workspace.root / "state" / "psic_llm.sqlite"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            decision_cache = ClassificationDecisionCache(cache_path)
            traverser = HierarchicalPsicTraverser(taxonomy, backend)
        classifier = PsicClassifier(
            taxonomy=taxonomy, crosswalk=refs.source_to_psic,
            top_n=self.config.top_n, min_score=self.config.min_score,
            min_margin=self.config.min_margin, traverser=traverser,
            decision_cache=decision_cache, llm_retrieval_top_n=self.config.llm_retrieval_top_n,
        )
        def classification_progress(position: int, total: int) -> None:
            if self.progress is None:
                return
            pct = 100.0 if total == 0 else 100.0 * position / total
            self.progress(f"PSIC classification: {position:,}/{total:,} rows ({pct:.1f}%)")

        try:
            tagged = classifier.classify_frame(
                canonical,
                progress=classification_progress if self.progress is not None else None,
                progress_every=max(100, len(canonical) // 20) if len(canonical) else 1,
            )
            if decision_cache is not None:
                decision_cache.flush()
        finally:
            if decision_cache is not None:
                decision_cache.close()
        write_geoframe(tagged, write.output("places.json"))
        coded = int(tagged["psic_code"].astype("string").fillna("").str.strip().ne("").sum()) if len(tagged) else 0
        method_counts = tagged["psic_method"].fillna("").value_counts().to_dict() if len(tagged) else {}
        status_counts = tagged["psic_status"].fillna("").value_counts().to_dict() if len(tagged) else {}
        return {
            "rows": len(tagged), "psic_coded": coded, "llm_enabled": backend is not None,
            "llm_model": backend.model_name if backend is not None else None,
            "llm_base_url": backend.base_url if backend is not None else None,
            "psic_status_counts": status_counts, "psic_method_counts": method_counts,
        }, {}

    def _exec_classified(self, planner, recipe, deps, write):
        frame = read_geoframe(deps["places.psic"].path / "places.json")
        tagger = EconomicTagger(taxonomy=self._taxonomy_obj(), economy=self.economy, references=self._reference_obj())
        tagged = tagger.tag(frame, compatibility=True)
        write_geoframe(tagged, write.output("places.json"))
        coverage = hybrid_io_coverage_summary(tagged) if self._reference_obj().profile == "builtin-rev5-psa2018" else None
        metadata = {"rows": len(tagged), "economy_id": self.economy.economy_id}
        if coverage is not None:
            metadata["io_coverage"] = coverage
        return metadata, {}

    # ---- public component API ---------------------------------------
    def load(self, *, force: bool = False) -> ArtifactRef:
        return self.planner.ensure("places.classified", force=force)

    def read_classified(self, ref: ArtifactRef | None = None) -> gpd.GeoDataFrame:
        ref = ref or self.workspace.artifact("places.classified")
        if ref is None:
            raise RuntimeError("places.classified has not been prepared")
        return read_geoframe(ref.path / "places.json")

    def publish_compatibility(self, ref: ArtifactRef | None = None) -> tuple[Path, dict[str, object]]:
        ref = ref or self.load()
        tagged = self.read_classified(ref)
        out_root = self.workspace.output_dir
        out_root.mkdir(parents=True, exist_ok=True)
        target = out_root / "pois.parquet"
        tagged.to_parquet(target, index=False)
        source_licenses = _terms(tagged["source_licenses"]) if len(tagged) else []
        overture_providers = _terms(tagged["overture_providers"]) if len(tagged) else []
        (out_root / "ATTRIBUTION.txt").write_text(_attribution_text(tagged), encoding="utf-8")
        (out_root / "DATABASE_LICENSE.txt").write_text(_database_license_text(source_licenses), encoding="utf-8")

        canonical_manifest = self.workspace.manifest("places.canonical")
        psic_manifest = self.workspace.manifest("places.psic")
        boundary_ref = self.workspace.artifact("area.boundary")
        boundary_report = _read_json(boundary_ref.path / "boundary.json") if boundary_ref is not None else {}
        osm_index = self.workspace.artifact("source.osm_area_index")
        osm_meta = _read_json(osm_index.path / "index.json") if osm_index is not None else {}
        gf_ref_art = self.workspace.artifact("source.geofabrik_pbf")
        gf = self._read_source_ref(self.planner, gf_ref_art) if gf_ref_art is not None else None
        coverage = hybrid_io_coverage_summary(tagged) if self._reference_obj().profile == "builtin-rev5-psa2018" else None
        psic_coded = int(tagged["psic_code"].astype("string").fillna("").str.strip().ne("").sum()) if len(tagged) else 0
        matched = int(canonical_manifest.metadata.get("matched_two_source", 0)) if canonical_manifest else 0
        io16 = int(coverage["resolutions"]["io16"]["coded_rows"]) if coverage else 0
        io80 = int(coverage["resolutions"]["io80"]["coded_rows"]) if coverage else int(tagged["economy_code"].astype("string").fillna("").str.strip().ne("").sum())
        io240 = int(coverage["resolutions"]["io240"]["coded_rows"]) if coverage else 0
        report: dict[str, object] = {
            "package": "sigma-siphon",
            "version": "0.5.0",
            "sigma_version": __version__,
            "created_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "area": {"slug": self.area.slug, "name": self.area.name, "kind": self.area.kind, "psgc_code": self.area.psgc_code, "bbox": list(self.area.bbox)},
            "boundary": {k: v for k, v in boundary_report.items() if k != "geometry_wkb_hex"},
            "clip_enabled": bool(self.config.clip),
            "sources": ["osm-geofabrik-prepared", "overture"],
            "counts": {
                "osm": int(self.workspace.manifest("places.osm_area").metadata.get("rows", 0)),
                "overture": int(self.workspace.manifest("places.overture_area").metadata.get("rows", 0)),
                "canonical": len(read_geoframe(self.workspace.artifact("places.canonical").path / "places.json")),
                "matched_two_source": matched, "psic_coded": psic_coded,
                "io16_coded": io16, "io80_coded": io80, "io240_coded": io240,
                "tagged": io80, "unresolved": len(tagged) - io80,
            },
            "classification": {
                "architecture": "psic-primary-hybrid-io", "psic_canonical": True,
                "llm_enabled": bool(psic_manifest.metadata.get("llm_enabled", False)) if psic_manifest else False,
                "llm_model": psic_manifest.metadata.get("llm_model") if psic_manifest else None,
                "llm_base_url": psic_manifest.metadata.get("llm_base_url") if psic_manifest else None,
                "psic_status_counts": dict(psic_manifest.metadata.get("psic_status_counts", {})) if psic_manifest else {},
                "psic_method_counts": dict(psic_manifest.metadata.get("psic_method_counts", {})) if psic_manifest else {},
                "direct_io_status_counts": coverage["direct_status_counts"] if coverage else {},
                "io16": coverage["resolutions"]["io16"] if coverage else {},
                "io80": coverage["resolutions"]["io80"] if coverage else {},
                "io240": coverage["resolutions"]["io240"] if coverage else {},
                "direct_io_role": "conservative downstream resolver",
                "direct_io_never_overrides_psic_candidate_set": True,
            },
            "osm_acquisition": {
                "provider": "Geofabrik",
                "preparation": "resumable checkpoints; one national scan per Geofabrik version; all LGU caches",
                "pbf": str(gf.path) if gf else None,
                "pbf_size_bytes": gf.size if gf else None,
                "prepared_source_version": osm_meta.get("prepared_source_version"),
                "fallback_to_previous_complete_version": bool(osm_meta.get("fallback_to_previous_complete_version", False)),
                "geofabrik_refreshed_for_run": bool(self.config.refresh_geofabrik),
            },
            "licensing": {
                "software": "Proprietary",
                "database_license": "ODbL-1.0" if "ODbL-1.0" in source_licenses else None,
                "source_licenses_observed": source_licenses,
                "overture_providers_observed": overture_providers,
                "osm_public_distribution_note": "The fused database is treated as ODbL-1.0 when OSM-derived records are present",
            },
            "elapsed_seconds": round(time.monotonic() - self._started, 3),
            "output": str(target),
            "classified_places_artifact_id": ref.artifact_id,
        }
        (out_root / "run.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return target, report


def run_pipeline(
    area_slug: str,
    *,
    areas_file: Path | None = None,
    root: Path = Path("."),
    output_dir: Path | None = None,
    cache_dir: Path | None = None,
    refresh: bool = False,
    refresh_geofabrik: bool = False,
    clip: bool = True,
    use_llm: bool = False,
    progress: ProgressCallback | None = None,
    _services: PlaceServices | None = None,
) -> tuple[Path, dict[str, object]]:
    """Compatibility entry point delegating the former Siphon run to C8 stages."""
    started = time.monotonic()
    root = Path(root).resolve()
    area = resolve_area(area_slug, areas_file)
    source_root = (Path(cache_dir).resolve() if cache_dir is not None else root / ".sigma-cache") / ".sigma-sources"
    source_store = SourceStore(source_root)
    legacy_cache = Path(cache_dir).resolve() if cache_dir is not None else root / ".sigma-cache"
    if legacy_cache.exists():
        try:
            source_store.adopt_legacy_cache(legacy_cache)
        except Exception:
            # Adoption is opportunistic; provider acquisition still gives authoritative errors.
            pass
    workspace_root = root / ".sigma" / "workspaces" / area.slug
    area_out = (Path(output_dir).resolve() if output_dir is not None else root / "output") / area.slug
    if (workspace_root / "workspace.json").exists():
        workspace = SigmaWorkspace.open(workspace_root, area=area)
    else:
        workspace = SigmaWorkspace.create(workspace_root, area=area, source_store=source_root, output_dir=area_out)
    pipeline = PlacePipeline(
        workspace, area=area, economy=Economy.default(), areas_file=areas_file,
        config=PlaceRunConfig(clip=clip, refresh_geofabrik=refresh_geofabrik, refresh_overture=refresh, use_llm=use_llm),
        services=_services, progress=progress,
    )
    ref = pipeline.load()
    target, report = pipeline.publish_compatibility(ref)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (target.parent / "run.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target, report

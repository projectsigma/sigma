"""Read-only local Explorer augmentation, separate from scored SIGMA network inputs.

The source of truth for a sector is the Economy's catalog. The source of truth
for an establishment is the published, hash-verified classified POI handoff.
Neither source grants a cluster, an X node, or a SIGMA score.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml


def _s(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def matching_catalog_files(source: Path, run: dict) -> tuple[Path, Path] | None:
    """Find an Economy catalog only in a workspace owning this exact output dir."""
    economy_id = _s(run.get("economy_id"))
    if "-hierarchical-" not in economy_id:
        return None
    source = Path(source).expanduser().resolve()
    candidates = list(source.parents)
    slug = _s(run.get("area_slug"))
    if slug:
        from sigma.paths import sigma_home
        candidates.append(sigma_home() / "workspaces" / slug)
    for candidate in candidates:
        record = candidate / "workspace.json"
        catalog = candidate / "hierarchical" / "economy" / "sectors.csv"
        spec = catalog.with_name("economy.yml")
        if not all(p.is_file() for p in (record, catalog, spec)):
            continue
        workspace = json.loads(record.read_text(encoding="utf-8"))
        configured_output = Path(str(workspace.get("output_dir", ""))).expanduser()
        if not configured_output.is_absolute():
            configured_output = candidate / configured_output
        if configured_output.resolve() != source:
            continue
        model = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
        if _s(model.get("id")) != economy_id:
            raise ValueError("Explorer Economy ID disagrees with the owning workspace's catalog")
        return catalog, spec
    return None


def load_sector_catalog(source: Path, run: dict) -> dict[str, str]:
    """All local Economy sectors, including those containing zero establishments."""
    if "-hierarchical-" not in _s(run.get("economy_id")):
        return {}
    paths = matching_catalog_files(source, run)
    if paths is None:
        raise FileNotFoundError(
            "Cannot locate the exact hierarchical Economy catalog for this Explorer output. "
            "Use the original workspace output directory, or restore its workspace.json and economy files."
        )
    table = pd.read_csv(paths[0], dtype=str, keep_default_na=False)
    if not {"code", "label"}.issubset(table.columns):
        raise ValueError("Hierarchical Economy sectors.csv must contain code and label")
    codes = table["code"].map(_s)
    if not len(table) or not codes.all() or codes.duplicated().any():
        raise ValueError("Hierarchical Economy catalog has empty or duplicate sector codes")
    return dict(zip(codes, table["label"].map(_s), strict=True))


def extend_classified_points(
    scored: gpd.GeoDataFrame,
    classified: gpd.GeoDataFrame,
    allowed_sectors: set[str] | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Append classified-but-unscored establishments, never assigning fake scores.

    All originally scored rows and columns remain untouched. Missing or duplicate
    canonical IDs are errors rather than a reason to guess. Sector disagreements
    are errors rather than silent overrides. Records with no assigned economy
    sector never become points on the Explorer's economic map.
    """
    id_col = "canonical_id"
    for label, frame in (("scored", scored), ("classified", classified)):
        if id_col not in frame:
            raise ValueError(f"{label} input lacks canonical_id")
        ids = frame[id_col].map(_s)
        if ids.eq("").any() or ids.duplicated().any():
            raise ValueError(f"{label} input has missing or duplicate canonical_id")
    if "economy_code" not in classified or "type" not in scored:
        raise ValueError("classified economy_code and scored type columns are required")
    if scored.crs is None or classified.crs is None:
        raise ValueError("both establishment layers must declare CRS")
    if scored.crs != classified.crs:
        classified = classified.to_crs(scored.crs)
    # For every shared ID, the scored network sector must equal the publisher's
    # actual economy assignment. This is the essential anti-stale-data check.
    classified_types = classified.set_index(id_col)["economy_code"].map(_s)
    scored_codes = scored[id_col].map(_s).map(classified_types)
    missing = scored_codes.isna()
    if bool(missing.any()):
        raise ValueError(f"{int(missing.sum())} scored establishments are missing from published classified POIs")
    disagrees = scored_codes.to_numpy() != scored["type"].map(_s).to_numpy()
    if disagrees.any():
        raise ValueError(f"{int(disagrees.sum())} published POI sectors disagree with scored network sectors")

    extra = classified.loc[~classified[id_col].isin(scored[id_col])].copy()
    codes = extra["economy_code"].map(_s)
    extra = extra.loc[codes.ne("")].copy()
    if allowed_sectors is not None:
        unknown = set(extra["economy_code"].map(_s)) - allowed_sectors
        if unknown:
            raise ValueError(f"Classified POIs contain sectors outside the Economy: {sorted(unknown)[:8]}")
    # No score / cluster / node can be inferred from an economic classification.
    extra["type"] = extra["economy_code"].map(_s)
    extra["cluster"] = pd.NA
    extra["sigma_score"] = float("nan")
    # Present these extra cases separately from the network in the same tiles.
    extra["unclustered"] = True
    original = scored.copy()
    original["unclustered"] = False
    if not len(extra):
        return original, 0
    # Preserve geometry and all original columns while allowing new provenance
    # columns on the appended rows. GeoDataFrame/CRS are maintained by pandas.
    out = gpd.GeoDataFrame(pd.concat([original, extra], ignore_index=True),
                           geometry=scored.geometry.name, crs=scored.crs)
    return out, len(extra)

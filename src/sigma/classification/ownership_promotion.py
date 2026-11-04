"""Conservative promotion of institutional ownership evidence during ``sigma load``.

Only explicit OSM/Overture ownership attributes, independently verified canonical
registry links, and official external-ID matches may change IO80/IO240. Registry
name/city matches and operator proxies are diagnostic only. This operates after
normal PSIC/hybrid tagging and never changes PSIC or IO candidate sets.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Mapping

import pandas as pd

from .hybrid_io import _candidate_label
from .registry import RegistryIndex, records_from_csv
from .beis_registry import BEISIndex, LayeredInstitutionIndex, packaged_beis
from .unifast_registry import UniFASTIndex, packaged_unifast
from .national_registry import (
    NationalRegistryIndex, load_national_registry, national_fingerprint, national_registry_path,
)
from .shadow import ShadowResolver, clean, domain_of, load_registry_links

POLICY = "institution-ownership-load-v4-national-beis-unifast"
PROMOTABLE_BASES = frozenset({
    "explicit_source_attribute",
    "verified_canonical_registry_link",
    "official_registry_external_id",
})
AUDIT_COLUMNS = (
    "institution_promotion_status",
    "institution_evidence_basis",
    "institution_evidence_reference",
    "institution_evidence_source_urls",
    "institution_baseline_conflict",
)


def _bundled_registry():
    return resources.files("sigma.resources.classification").joinpath("institution_registry.csv")


def reference_fingerprint(workspace_root: Path | None = None) -> str:
    """Fingerprint the national snapshot when installed, otherwise legacy QC.

    The legacy bundled reference is retained for fallback and remains included
    in the digest; corrupted national snapshots must stop the tagging stage.
    """
    with resources.as_file(_bundled_registry()) as path:
        data = Path(path).read_bytes()
    national = national_fingerprint(workspace_root) if workspace_root is not None else None
    with resources.as_file(resources.files("sigma.resources.classification").joinpath(
            "beis_schools_national.csv.gz")) as path:
        beis_bytes = Path(path).read_bytes()
    with resources.as_file(resources.files("sigma.resources.classification").joinpath(
            "unifast_hei_ra10931.csv.gz")) as path:
        unifast_bytes = Path(path).read_bytes()
    return hashlib.sha256(POLICY.encode() + b"\0" + data + b"\0" +
                          beis_bytes + b"\0" + unifast_bytes + b"\0" +
                          (national or "national-not-installed").encode()).hexdigest()


@lru_cache(maxsize=1)
def _beis_index() -> BEISIndex:
    return BEISIndex(packaged_beis())


@lru_cache(maxsize=1)
def _unifast_index() -> UniFASTIndex:
    return UniFASTIndex(packaged_unifast())


@lru_cache(maxsize=1)
def _qc_registry() -> RegistryIndex:
    with resources.as_file(_bundled_registry()) as path:
        records = records_from_csv(Path(path))
    return RegistryIndex(records)


def verified_links_path(workspace_root: Path) -> Path:
    return Path(workspace_root) / "references" / "institution_links.json"


def verified_links_fingerprint(workspace_root: Path) -> str:
    path = verified_links_path(workspace_root)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "none"


def _verified_links(workspace_root: Path | None):
    if workspace_root is None:
        return {}
    path = verified_links_path(workspace_root)
    return load_registry_links(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}


def promote_institutions(
    frame: pd.DataFrame,
    *,
    taxonomy,
    io_mapping,
    catalog: Mapping,
    area_slug: str = "",
    workspace_root: Path | None = None,
    registry_index: RegistryIndex | None = None,
    registry_links: Mapping | None = None,
) -> pd.DataFrame:
    """Promote only evidence stronger than name guesses, preserving the original candidates.

    `registry_index` and `registry_links` are injectable for isolated tests. The
    built-in registry is confined to Quezon City, its documented geographic scope.
    """
    out = frame.copy()
    if not out.index.is_unique:
        raise ValueError("institution ownership promotion requires a unique row index")
    for column in AUDIT_COLUMNS:
        if column in out.columns:
            raise ValueError(f"institution audit column already exists: {column}")
        out[column] = ""
    if frame.empty or "io80_codes" not in frame or "io240_codes" not in frame:
        return out
    if registry_index is not None:
        registry = registry_index
    elif workspace_root is not None and national_registry_path(workspace_root).is_file():
        # National snapshot supersedes the smaller bundled QC-only registry.
        # Both still require the same strict external-ID / verified-link checks.
        registry = NationalRegistryIndex(load_national_registry(national_registry_path(workspace_root)))
    else:
        registry = _qc_registry() if area_slug == "quezon_city" else None
    if registry_index is None:
        registry = LayeredInstitutionIndex(
            LayeredInstitutionIndex(registry, _beis_index()), _unifast_index()
        )
    links = registry_links if registry_links is not None else _verified_links(workspace_root)
    resolver = ShadowResolver(taxonomy, io_mapping, registry_links=links, registry_index=registry)
    # Avoid expensive row-wise registry lookups for all noninstitution places.
    c80 = frame["io80_codes"].astype("string").fillna("").str.replace(r"\s+", "", regex=True)
    c240 = frame["io240_codes"].astype("string").fillna("").str.replace(r"\s+", "", regex=True)
    possible = c80.isin(("74;75", "75;74", "76;77", "77;76")) | c240.isin(
        ("229;230", "230;229", "231;232", "232;231")
    )
    for index, row in frame.loc[possible].iterrows():
        if not domain_of(row):
            continue
        proposed = resolver.resolve(row)
        basis = proposed["shadow_basis"]
        out.at[index, "institution_evidence_basis"] = basis
        out.at[index, "institution_evidence_reference"] = proposed["shadow_registry_ids"]
        out.at[index, "institution_evidence_source_urls"] = proposed["shadow_registry_urls"]
        out.at[index, "institution_baseline_conflict"] = proposed["shadow_baseline_conflict"]
        if proposed["shadow_status"] != "PROPOSED_IO":
            out.at[index, "institution_promotion_status"] = proposed["shadow_status"]
            continue
        if basis not in PROMOTABLE_BASES:
            out.at[index, "institution_promotion_status"] = "PROVISIONAL_NOT_PROMOTED"
            continue
        if basis == "official_registry_external_id" and proposed["shadow_registry_status"] != "EXACT_EXTERNAL_ID":
            out.at[index, "institution_promotion_status"] = "UNVERIFIED_ID"
            continue
        new80, new240 = proposed["shadow_io80"], proposed["shadow_io240"]
        if not new80 or not new240:
            out.at[index, "institution_promotion_status"] = "NO_COMPATIBLE_IO_PAIR"
            continue
        current80, current240 = clean(row.get("io80_code")), clean(row.get("io240_code"))
        source80, source240 = clean(row.get("io80_source")), clean(row.get("io240_source"))
        # An existing direct/PSIC resolution is not a weak ownership-name guess.
        if ((current80 and current80 != new80 and source80 != "psic+ownership") or
                (current240 and current240 != new240 and source240 != "psic+ownership")):
            out.at[index, "institution_promotion_status"] = "STRONG_BASELINE_CONFLICT"
            continue
        industry = catalog.get(new80)
        expected16 = getattr(industry, "io16_code", None)
        current16 = clean(row.get("io16_code"))
        if industry is None or (current16 and expected16 != current16):
            out.at[index, "institution_promotion_status"] = "IO_LEVEL_CONFLICT"
            continue
        changed = False
        for resolution, old, new in (("io80", current80, new80), ("io240", current240, new240)):
            if old == new:
                continue
            out.at[index, f"{resolution}_code"] = new
            out.at[index, f"{resolution}_status"] = "INSTITUTION_EVIDENCE_RESOLVED"
            out.at[index, f"{resolution}_source"] = "psic+institution"
            if resolution == "io80":
                out.at[index, "io80_label"] = industry.io80_label
            else:
                out.at[index, "io240_label"] = _candidate_label(row, "io240", new)
            changed = True
        # Preserve the original PSIC decision and candidate sets, even if refined IO is new.
        out.at[index, "ownership_domain"] = proposed["shadow_domain"]
        out.at[index, "ownership_side"] = proposed["shadow_side"]
        out.at[index, "ownership_reason"] = f"institution:{basis}"
        out.at[index, "institution_promotion_status"] = "PROMOTED" if changed else "CONFIRMED"
    return out


def summary(frame: pd.DataFrame, workspace_root: Path | None = None) -> dict:
    return {"policy": POLICY,
            "reference_fingerprint": reference_fingerprint(workspace_root),
            "status_counts": dict(sorted(Counter(frame["institution_promotion_status"].loc[
                frame["institution_promotion_status"].ne("")]).items()))}

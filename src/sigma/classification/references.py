"""Explicit, taxonomy-bound resources that connect places, PSIC, and an Economy."""
from __future__ import annotations

import hashlib
import json
from importlib import resources
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping

from sigma.economy import Economy
from sigma.errors import TaxonomyValidationError

from .crosswalk import CrosswalkIndex
from .io_mapping import IOMapping
from .io_mapping_compat import Industry, Rule, load_catalog, load_rules
from .reference import PsicTaxonomy


def _fingerprint(payload: object) -> str:
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()




def _crosswalk_payload(crosswalk: CrosswalkIndex) -> list[dict[str, object]]:
    rows = []
    for entry in crosswalk.entries:
        row = asdict(entry)
        row["mapping_kind"] = str(entry.mapping_kind)
        row["source_field"] = str(entry.source_field)
        row["codes"] = list(entry.codes)
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _catalog_payload(catalog: Mapping[str, Industry]) -> list[dict[str, object]]:
    return [asdict(catalog[key]) for key in sorted(catalog)]


def _direct_rule_payload(rules: tuple[Rule, ...]) -> list[dict[str, object]]:
    return [asdict(rule) for rule in rules]


def _validate_crosswalk(crosswalk: CrosswalkIndex, taxonomy: PsicTaxonomy) -> None:
    unknown=sorted({code for rule in crosswalk.entries for code in rule.codes if code not in taxonomy.nodes})
    if unknown:
        raise TaxonomyValidationError(f"source-to-PSIC references contain unknown taxonomy codes: {unknown[:10]}")

@dataclass(frozen=True, slots=True)
class TaggingReferences:
    taxonomy_fingerprint: str
    economy_sector_fingerprint: str
    source_to_psic: CrosswalkIndex
    economy_resolution: str
    legacy_io_mapping: IOMapping | None = None
    direct_catalog: Mapping[str, Industry] | None = None
    direct_rules: tuple[Rule, ...] = ()
    custom_psic_to_economy: Mapping[str, str] | None = None
    profile: str = "custom"
    fingerprint: str = ""

    @classmethod
    def builtin(cls, taxonomy: PsicTaxonomy, economy: Economy) -> "TaggingReferences":
        bundled_nodes = resources.files("sigma.resources.classification").joinpath(
            "psic_rev5", "nodes.parquet"
        ).read_bytes()
        expected_taxonomy_asset = hashlib.sha256(bundled_nodes).hexdigest()
        if (
            getattr(taxonomy,"origin","custom") != "builtin:psic_rev5"
            or getattr(taxonomy, "asset_sha256", None) != expected_taxonomy_asset
        ):
            raise TaxonomyValidationError(
                "built-in Rev. 5 tagging references require the exact bundled Rev. 5 taxonomy; "
                "custom taxonomies must supply explicit compatible references"
            )
        if economy.economy_id not in {"psa-2018-io80","psa-2018-io16"}:
            raise TaxonomyValidationError(
                "built-in Rev. 5 tagging references target the built-in PSA 2018 IO80/IO16 economies"
            )
        crosswalk=CrosswalkIndex.load_builtin(); _validate_crosswalk(crosswalk,taxonomy)
        mapping=IOMapping.load_builtin(taxonomy)
        catalog=load_catalog(); rules=tuple(load_rules())
        resolution="io80" if economy.economy_id.endswith("io80") else "io16"
        # Validate the final resolution universe against Economy.sectors.
        known=set(economy.sectors.codes)
        referenced=set()
        for row in mapping.reference.concordance:
            referenced.update(getattr(row,f"{resolution}_codes"))
        bad=sorted(referenced-known)
        if bad:
            raise TaxonomyValidationError(f"built-in {resolution} mappings reference unknown Economy sectors: {bad[:10]}")
        payload={"taxonomy":taxonomy.fingerprint,"economy":economy.sector_fingerprint,"resolution":resolution,
                 "taxonomy_asset":taxonomy.asset_sha256,
                 "bridge":mapping.reference.bridge_sha256,"concordance":mapping.reference.concordance_sha256,
                 "crosswalk":_crosswalk_payload(crosswalk),
                 "direct_catalog":_catalog_payload(catalog),
                 "direct_rules":_direct_rule_payload(rules)}
        return cls(taxonomy.fingerprint,economy.sector_fingerprint,crosswalk,resolution,mapping,
                   MappingProxyType(dict(catalog)),rules,None,"builtin-rev5-psa2018",_fingerprint(payload))

    @classmethod
    def custom(
        cls, *, taxonomy: PsicTaxonomy, economy: Economy, source_to_psic: CrosswalkIndex | None = None,
        psic_to_economy: Mapping[str,str],
    ) -> "TaggingReferences":
        crosswalk=source_to_psic or CrosswalkIndex([]); _validate_crosswalk(crosswalk,taxonomy)
        mapping={str(k).strip():str(v).strip() for k,v in psic_to_economy.items()}
        unknown_psic=sorted(set(mapping)-set(taxonomy.nodes)); unknown_econ=sorted(set(mapping.values())-set(economy.sectors.codes))
        if unknown_psic: raise TaxonomyValidationError(f"PSIC-to-Economy mapping contains unknown taxonomy codes: {unknown_psic[:10]}")
        if unknown_econ: raise TaxonomyValidationError(f"PSIC-to-Economy mapping contains unknown Economy sectors: {unknown_econ[:10]}")
        payload={"taxonomy":taxonomy.fingerprint,"economy":economy.sector_fingerprint,"mapping":sorted(mapping.items()),"crosswalk":_crosswalk_payload(crosswalk)}
        return cls(taxonomy.fingerprint,economy.sector_fingerprint,crosswalk,"custom",None,None,(),MappingProxyType(mapping),"custom",_fingerprint(payload))

    def validate_for(self, taxonomy: PsicTaxonomy, economy: Economy) -> None:
        if taxonomy.fingerprint != self.taxonomy_fingerprint:
            raise TaxonomyValidationError("tagging-reference taxonomy fingerprint does not match selected taxonomy")
        if economy.sector_fingerprint != self.economy_sector_fingerprint:
            raise TaxonomyValidationError("tagging-reference Economy sector fingerprint does not match selected Economy")

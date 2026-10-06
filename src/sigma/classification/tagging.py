"""Economic tagging that composes a PSIC taxonomy, explicit references, and an Economy."""
from __future__ import annotations
import pandas as pd
from sigma.economy import Economy
from sigma.errors import TaxonomyValidationError
from .hybrid_io import apply_hybrid_io
from .io_mapping import enrich_frame_with_io
from .reference import PsicTaxonomy
from .references import TaggingReferences

class EconomicTagger:
    def __init__(self, *, taxonomy: PsicTaxonomy, economy: Economy, references: TaggingReferences):
        references.validate_for(taxonomy,economy)
        self.taxonomy=taxonomy; self.economy=economy; self.references=references

    def tag(self, frame: pd.DataFrame, *, compatibility: bool = True) -> pd.DataFrame:
        if "psic_code" not in frame.columns:
            raise ValueError("economic tagging requires a psic_code column")
        if self.references.profile == "builtin-rev5-psa2018":
            out=enrich_frame_with_io(frame,taxonomy=self.taxonomy,mapping=self.references.legacy_io_mapping)
            out=apply_hybrid_io(out,catalog=dict(self.references.direct_catalog or {}),rules=list(self.references.direct_rules))
            r=self.references.economy_resolution
            out["economy_code"]=out[f"{r}_code"].astype("string")
            # Canonical labels are owned by the selected Economy, not concordance text.
            labels={s.code:s.label for s in self.economy.sectors}
            out["economy_label"]=out["economy_code"].map(lambda c: labels.get(str(c),"")).astype("string")
            out["economy_status"]=out[f"{r}_status"].astype("string")
            out["economy_source"]=out[f"{r}_source"].astype("string")
            return out
        mapping=dict(self.references.custom_psic_to_economy or {})
        out=frame.copy(); codes=out["psic_code"].astype("string").fillna("").str.strip()
        out["economy_code"]=codes.map(lambda c:mapping.get(str(c),"")).astype("string")
        labels={s.code:s.label for s in self.economy.sectors}
        out["economy_label"]=out["economy_code"].map(lambda c:labels.get(str(c),"")).astype("string")
        out["economy_status"]=out["economy_code"].map(lambda c:"PSIC_MAP" if str(c) else "UNRESOLVED").astype("string")
        out["economy_source"]=out["economy_code"].map(lambda c:"psic" if str(c) else "").astype("string")
        return out

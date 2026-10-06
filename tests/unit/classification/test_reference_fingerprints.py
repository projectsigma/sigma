import pandas as pd

from sigma.classification.crosswalk import CrosswalkIndex
from sigma.classification.reference import PsicTaxonomy
from sigma.classification.references import TaggingReferences
from sigma.classification.types import MappingKind, MappingRule
from sigma.economy import Economy, Sector, SectorCatalog


def _taxonomy():
    return PsicTaxonomy.from_frame(
        pd.DataFrame(
            [
                {"scheme": "custom", "version": "1", "code": "A", "level": "section", "title": "A", "parent_code": ""},
                {"scheme": "custom", "version": "1", "code": "B", "level": "section", "title": "B", "parent_code": ""},
            ]
        )
    )


def _economy():
    sectors = SectorCatalog([Sector("E", "Economy")])
    return Economy(
        economy_id="custom",
        sectors=sectors,
        raw_transactions=pd.DataFrame([[1.0]], index=["E"], columns=["E"]),
        total_output=pd.Series([1.0], index=["E"]),
    )


def test_reference_fingerprint_changes_when_crosswalk_content_changes_at_same_length():
    taxonomy = _taxonomy()
    economy = _economy()
    first = CrosswalkIndex(
        [MappingRule("osm", "amenity=bank", MappingKind.EXACT, ("A",))]
    )
    second = CrosswalkIndex(
        [MappingRule("osm", "amenity=bank", MappingKind.EXACT, ("B",))]
    )
    refs_a = TaggingReferences.custom(
        taxonomy=taxonomy, economy=economy, source_to_psic=first, psic_to_economy={"A": "E", "B": "E"}
    )
    refs_b = TaggingReferences.custom(
        taxonomy=taxonomy, economy=economy, source_to_psic=second, psic_to_economy={"A": "E", "B": "E"}
    )
    assert refs_a.fingerprint != refs_b.fingerprint

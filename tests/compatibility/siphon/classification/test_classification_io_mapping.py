from __future__ import annotations

import pandas as pd

from sigma.classification.io80_resolver import resolve_io80_ambiguity
from sigma.classification.io_mapping import IOMapping
from sigma.classification.reference import (
    IOBridgeRow,
    IOConcordanceRow,
    IOReferenceCatalog,
    PsicNode,
    PsicTaxonomy,
)


def _taxonomy() -> PsicTaxonomy:
    return PsicTaxonomy(
        [
            PsicNode("A", "section", "Agriculture"),
            PsicNode("01", "division", "Crop production", "A"),
            PsicNode("011", "group", "Growing cereals", "01"),
            PsicNode("0111", "class", "Growing rice", "011"),
        ]
    )


def _mapping() -> IOMapping:
    catalog = IOReferenceCatalog(
        bridge=(
            IOBridgeRow(
                rev5_level="group",
                rev5_code="011",
                rev5_title="Growing cereals",
                psic2019_codes=("011",),
                relation="same",
                basis="reviewed",
            ),
        ),
        concordance=(
            IOConcordanceRow(
                psic_level="group",
                psic_code="011",
                psic_name="Growing cereals",
                io16_codes=("01",),
                io16_names=("Agriculture",),
                io16_confidence="High",
                io80_codes=("55", "56"),
                io80_names=("Retail A", "Retail B"),
                io80_confidence="Medium",
                io240_codes=("001",),
                io240_names=("Rice",),
                io240_confidence="High",
            ),
        ),
        bridge_sha256="bridge",
        concordance_sha256="concordance",
    )
    return IOMapping(_taxonomy(), catalog)


def test_deep_psic_code_maps_through_group_ancestor():
    result = _mapping().map_psic("0111")
    assert result["io_mapping_status"] == "MAPPED_GROUP"
    assert result["io_mapping_psic_code"] == "011"
    assert result["io16_map_code"] == "01"
    assert result["io80_codes"] == "55; 56"
    assert result["io80_map_status"] == "AMBIGUOUS_SET"
    assert result["io240_map_code"] == "001"


def test_io80_same_name_policy_can_resolve_audited_pair():
    frame = pd.DataFrame(
        [
            {"poi_id": "a1", "name": "Alpha", "io80_codes": "55"},
            {"poi_id": "a2", "name": "Alpha", "io80_codes": "55"},
            {"poi_id": "t", "name": "Alpha", "io80_codes": "55; 56"},
        ]
    )
    out = resolve_io80_ambiguity(frame)
    assert out.loc[2, "io80_map_code"] == "55"
    assert out.loc[2, "io80_map_status"] == "NAME_MATCH_RESOLVED"
    assert out.loc[2, "io80_resolution_support"] == "2"

from __future__ import annotations

import importlib.util
from importlib import resources

import pandas as pd
import pytest

from sigma.classification.reference import (
    PsicNode,
    PsicTaxonomy,
    _crosswalk_reports,
    load_builtin_io_reference,
    load_builtin_psic_taxonomy,
    validate_builtin_classification_reference,
)


def test_builtin_io_reference_loads_expected_hierarchy():
    catalog = load_builtin_io_reference()

    assert len(catalog.bridge) == 371
    assert catalog.bridge_level_counts == {"section": 22, "division": 88, "group": 261}
    assert len(catalog.concordance) == 354
    assert catalog.concordance_level_counts == {"section": 21, "division": 88, "group": 245}


def test_bundled_crosswalk_references_only_keep_supported_sources():
    reports = _crosswalk_reports()

    assert {item.name for item in reports} == {"psic_rev5.csv", "psic_rev5_reviewed.csv"}
    assert sum(item.rows for item in reports) == 1284
    for item in reports:
        assert set(item.source_counts) <= {"osm", "overture"}


def test_official_psic_workbook_is_bundled():
    target = resources.files("sigma.resources.classification").joinpath(
        "psic_rev5",
        "PSIC_Revision_5_Detailed_Structure_30July2026.xlsx",
    )
    assert target.is_file()
    assert len(target.read_bytes()) == 101242


def test_taxonomy_hierarchy_helpers_are_psic_specific():
    taxonomy = PsicTaxonomy(
        [
            PsicNode("A", "section", "Agriculture"),
            PsicNode("01", "division", "Crop and animal production", "A"),
            PsicNode("011", "group", "Growing of non-perennial crops", "01"),
            PsicNode("0111", "class", "Growing of cereals", "011"),
            PsicNode("01111", "subclass", "Growing of rice", "0111"),
            PsicNode("01112", "subclass", "Growing of corn", "0111"),
        ]
    )

    assert taxonomy.parent("01111") == "0111"
    assert taxonomy.path_from_root("01111") == ["A", "01", "011", "0111", "01111"]
    assert taxonomy.lca(["01111", "01112"]) == "0111"
    assert taxonomy.leaves("0111") == frozenset({"01111", "01112"})
    assert taxonomy.structural_report().errors == ()


def test_taxonomy_from_frame_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing columns"):
        PsicTaxonomy.from_frame(pd.DataFrame({"code": ["A"]}))


@pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None,
    reason="generic test container lacks pyarrow; sigma-siphon declares it as a dependency",
)
def test_real_builtin_reference_bundle_validates():
    taxonomy = load_builtin_psic_taxonomy()
    assert len(taxonomy.nodes) == 2202
    assert len(taxonomy.roots) == 22

    report = validate_builtin_classification_reference()
    assert report.taxonomy_nodes == 2202
    assert report.bridge_rows == 371
    assert report.concordance_rows == 354
    assert report.crosswalk_rows == 1284

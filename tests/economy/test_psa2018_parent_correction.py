"""Regression checks for PSA 2018 industry 124-126 parent correction.

This repairs versioned references only. The SIGMA tagging and hierarchical
algorithms remain unchanged.
"""
import csv
from importlib.resources import files

from sigma.classification.reference import load_builtin_io_reference
from sigma.classification.io_mapping_compat import load_catalog
from sigma.economy.hierarchical import tagging_consistency, require_sigma_io80_io16
import pandas as pd


def test_2018_psa_124_126_are_io80_42():
    parents = pd.read_csv(
        files("sigma.resources.classification").joinpath("io", "io240_parents.csv"),
        dtype=str, keep_default_na=False,
    )
    assigned = parents.set_index("io240_code").io80_code.to_dict()
    assert {code: assigned[code] for code in ("123", "124", "125", "126", "127")} == {
        "123": "41", "124": "42", "125": "42", "126": "42", "127": "42"
    }
    assert {c: load_builtin_io_reference().io240_parent_map[c] for c in ("124", "125", "126")} == {
        "124": "42", "125": "42", "126": "42"
    }


def test_2019_concordance_is_consistent_with_psa_2018_nesting():
    reference = files("sigma.resources.classification").joinpath("io", "psic_2019_to_io_2018.csv")
    with reference.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = {(row["psic_level"], row["psic_code"]): row for row in csv.DictReader(stream)}
    assert rows[("division", "24")]["io80_codes"] == "41; 42"
    assert rows[("group", "242")]["io80_codes"] == "42"
    assert rows[("group", "243")]["io80_codes"] == "42"
    for key in (("division", "24"), ("group", "242"), ("group", "243")):
        assert "42" in rows[key]["io80_codes"].split("; ")


def test_hierarchy_tagging_agree_after_reference_correction():
    from sigma.classification.io_mapping_compat import load_catalog
    from sigma.economy.hierarchical import require_sigma_io80_io16

    parents = pd.read_csv(
        files("sigma.resources.classification").joinpath("io", "io240_parents.csv"),
        dtype=str, keep_default_na=False,
    )
    catalog = load_catalog()
    parents["io16_code"] = parents.io80_code.map(lambda c: catalog[c].io16_code)
    require_sigma_io80_io16(parents)
    report = tagging_consistency(parents)
    assert report["consistent"], report

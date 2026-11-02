"""Unit checks of the IO240 packager's acceptance rule (no PSA workbook needed)."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sigma.economy import Economy

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sigma_pack_io240_repo.py"


@pytest.fixture(scope="module")
def packer():
    spec = importlib.util.spec_from_file_location("sigma_pack_io240_repo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def split(packer):
    """A 240 table that aggregates exactly to SIGMA's IO80 (fixed random child weights)."""
    h = packer.crosswalk()
    io80 = Economy.builtin("io80")
    parents = h.io80_code.astype(int).to_numpy() - 1
    rng = np.random.default_rng(7)
    w = np.zeros(240)
    for p in set(parents):
        idx = np.where(parents == p)[0]
        raw = rng.uniform(0.2, 1.0, idx.size)
        w[idx] = raw / raw.sum()
    z = io80.Z_raw.to_numpy(float)[parents][:, parents] * np.outer(w, w)
    x = io80.x.to_numpy(float)[parents] * w
    return h, z, x


def test_decimals_detection(packer):
    assert packer.decimals(np.array([1.0, 2.5, 3.25])) == 2
    assert packer.decimals(np.array([1200.0, 3.0])) == 0
    assert packer.decimals(np.array([0.1 + 0.2, 1.0])) == 1
    assert packer.decimals(np.array([np.pi, 1.0])) is None


def test_canonical_hash_ignores_line_endings(packer):
    assert packer.canonical_sha256(b"a,b\r\n1,2\r\n") == packer.canonical_sha256(b"a,b\n1,2\n")
    assert packer.canonical_sha256(b"a,b\n1,2\n") != packer.canonical_sha256(b"a,b\n1,3\n")


@pytest.mark.parametrize("digits", [None, 3, 2, 0])
def test_rounded_official_tables_are_accepted(packer, split, digits):
    h, z, x = split
    if digits is not None:
        z, x = np.round(z, digits), np.round(x, digits)
    results = packer.check_against_builtins(h, z, x, z_decimals=packer.decimals(z),
                                            x_decimals=packer.decimals(x), label="test")
    assert all(r["accepted"] for pair in results.values() for r in pair.values())


@pytest.mark.parametrize("digits", [None, 0])
def test_wrong_parent_link_is_rejected_and_located(packer, split, digits):
    h, z, x = split
    if digits is not None:   # rounding must not hide a misplaced sector
        z, x = np.round(z, digits), np.round(x, digits)
    wrong = h.copy()
    i = wrong.index[wrong.io240_code.eq("124")][0]
    wrong.loc[i, "io80_code"] = "41"            # wrong parent: 124 under IO80 41
    with pytest.raises(RuntimeError) as failure:
        packer.check_against_builtins(wrong, z, x, z_decimals=packer.decimals(z),
                                      x_decimals=packer.decimals(x), label="test")
    message = str(failure.value)
    assert "does NOT reconcile" in message and "41" in message and "42" in message


def test_unit_difference_is_named_not_rescaled(packer, split):
    h, z, x = split
    with pytest.raises(RuntimeError, match="unit difference"):
        packer.check_against_builtins(h, z * 1000, x * 1000, z_decimals=None, x_decimals=None, label="test")


def test_labels_come_from_versioned_parent_table(packer, tmp_path):
    missing = tmp_path / "absent.xlsx"
    labels, report = packer.industry_labels(missing)
    parents = packer.parent_table()
    assert len(labels) == 240 and len(set(labels)) == 240
    first = parents.iloc[0]
    assert labels[0] == " ".join(first.io240_name.split())
    assert report["label_sources"]["io240_parents.csv"] == int(parents.io240_name.str.strip().ne("").sum())


def test_publish_restores_previous_package_on_failure(packer, tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "crosswalk.csv").write_text("old")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "crosswalk.csv").write_text("new")
    missing = stage / "never-created"
    with pytest.raises(FileNotFoundError):
        packer.publish(stage, root, [(stage / "crosswalk.csv", root / "crosswalk.csv"),
                                     (missing, root / "validation.json")], replace_existing=True)
    assert (root / "crosswalk.csv").read_text() == "old"

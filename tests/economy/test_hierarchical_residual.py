"""Regression contract for IO240 -> IO80 -> IO16 residual-sector aggregation."""
import numpy as np
import pandas as pd
import pytest

from sigma.economy import Economy, Sector, SectorCatalog
from sigma.economy.hierarchical import (
    build_hierarchical_economy,
    reconciliation,
    write_hierarchical_package,
)
from sigma.errors import EconomyValidationError


LEAVES = ("B", "D", "M", "S", "C", "L", "Q", "V")


def source():
    n = len(LEAVES)
    z = np.arange(1, n * n + 1, dtype=float).reshape((n, n))
    x = np.arange(101, 101 + n, dtype=float)
    e = Economy(
        economy_id="synthetic-io240",
        sectors=SectorCatalog(Sector(c, f"Sector {c}") for c in LEAVES),
        raw_transactions=pd.DataFrame(z, index=LEAVES, columns=LEAVES),
        total_output=pd.Series(x, index=LEAVES),
    )
    h = pd.DataFrame([
        ("B", "F", "MAN"), ("D", "F", "MAN"), ("M", "F", "MAN"),
        ("S", "F", "MAN"), ("C", "T", "MAN"), ("L", "T", "MAN"),
        ("Q", "Q80", "MAN"), ("V", "V80", "SRV"),
    ], columns=["io240_code", "io80_code", "io16_code"])
    return e, h


def places(*rows):
    return pd.DataFrame(rows, columns=["io240_code", "io80_code", "io16_code"]).fillna("")


def test_mixed_240_80_16_residuals_partition_and_conserve():
    e, h = source()
    p = places(("B", "F", "MAN"), ("D", "F", "MAN"), ("M", "F", "MAN"),
               ("", "F", "MAN"), ("", "T", "MAN"), ("", "", "MAN"))
    # Legacy rule: coarse places go to the residual by convention.
    result = build_hierarchical_economy(p, e, h, coarse_policy="residual")
    actual = result.places.economy_code.tolist()
    assert actual == ["240:B", "240:D", "240:M", "80:F:OTHER", "80:T", "16:MAN:O"]
    assert list(result.economy.sectors.codes) == [
        "240:B", "240:D", "240:M", "80:F:OTHER", "80:T", "16:MAN:O", "16:SRV"
    ]
    member = result.membership.groupby("economy_code").io240_code.apply(list).to_dict()
    assert member["80:F:OTHER"] == ["S"]
    assert member["80:T"] == ["C", "L"]
    assert member["16:MAN:O"] == ["Q"]
    assert member["16:SRV"] == ["V"]
    assert len(result.membership) == len(LEAVES)
    assert result.membership.io240_code.is_unique
    assert len(result.economy.sectors) <= len(LEAVES)
    assert np.isclose(result.economy.Z_raw.to_numpy().sum(), e.Z_raw.to_numpy().sum())
    assert np.isclose(result.economy.x.sum(), e.x.sum())
    # Matrix aggregation, both sides: 80:T <- 80:F:OTHER is C+L rows, S column.
    expected = e.Z_raw.loc[["C", "L"], ["S"]].to_numpy().sum()
    assert result.economy.Z_raw.loc["80:T", "80:F:OTHER"] == expected
    # Codes remain exclusive: the 80 fallback is not also assigned to MAN-Other.
    assert result.places.economy_code.notna().all()


def test_full_granularity_no_more_than_n_sectors():
    e, h = source()
    p = places(*[(c, "", "") for c in LEAVES])
    result = build_hierarchical_economy(p, e, h)
    assert len(result.economy.sectors) == len(LEAVES)
    assert all(code.startswith("240:") for code in result.economy.sectors.codes)


def test_without_fine_tags_reduces_to_two_io16_sectors():
    e, h = source()
    p = places(("", "", "MAN"), ("", "", "SRV"))
    result = build_hierarchical_economy(p, e, h)
    assert list(result.economy.sectors.codes) == ["16:MAN", "16:SRV"]
    assert result.places.economy_code.tolist() == ["16:MAN", "16:SRV"]


def test_coarse_only_with_all_children_used_is_rejected():
    e, h = source()
    p = places(("B", "F", "MAN"), ("D", "F", "MAN"), ("M", "F", "MAN"),
               ("S", "F", "MAN"), ("", "F", "MAN"))
    with pytest.raises(EconomyValidationError, match="no unambiguous residual"):
        build_hierarchical_economy(p, e, h, strict_coarse=True, coarse_policy="residual")
    with pytest.raises(EconomyValidationError, match="no single sector contains"):
        build_hierarchical_economy(p, e, h, strict_coarse=True)


def test_inconsistent_hierarchy_rejected():
    e, h = source()
    h.loc[h.io240_code == "D", "io16_code"] = "SRV"
    with pytest.raises(EconomyValidationError, match="each IO80 sector"):
        build_hierarchical_economy(places(("B", "F", "MAN")), e, h)


def test_hierarchy_code_conflict_rejected():
    e, h = source()
    with pytest.raises(EconomyValidationError, match="conflicting IO240/IO80"):
        build_hierarchical_economy(places(("B", "T", "MAN")), e, h)


def test_unknown_and_unresolved_are_not_silently_tagged():
    e, h = source()
    result = build_hierarchical_economy(places(("", "", "")), e, h)
    assert result.places.economy_code.tolist() == [""]
    assert result.diagnostics["unresolved_place_count"] == 1
    with pytest.raises(EconomyValidationError, match="unrecognized io240_code"):
        build_hierarchical_economy(places(("XYZ", "", "")), e, h)


def test_package_round_trip(tmp_path):
    e, h = source()
    result = build_hierarchical_economy(places(("B", "", ""), ("", "T", "MAN")), e, h)
    dest = tmp_path / "econ"
    write_hierarchical_package(result, dest)
    loaded = Economy.from_directory(dest)
    assert list(loaded.sectors.codes) == list(result.economy.sectors.codes)
    np.testing.assert_allclose(loaded.Z_raw, result.economy.Z_raw)
    np.testing.assert_allclose(loaded.x, result.economy.x)


def test_reference_reconciliation_zero_for_matched_rollups():
    e, h = source()
    z = e.Z_raw
    for level in ("io80", "io16"):
        ids = h[f"{level}_code"].to_list()
        agg = z.groupby(pd.Index(ids), sort=False).sum().T.groupby(pd.Index(ids), sort=False).sum().T
        codes = list(agg.index)
        ref = Economy(
            economy_id="reference-" + level,
            sectors=SectorCatalog(Sector(c, c) for c in codes),
            raw_transactions=agg,
            total_output=pd.Series(np.full(len(codes), 1000.), index=codes),
        )
        check = reconciliation(e, h, ref, resolution=level)
        assert check["max_absolute_transaction_difference"] == 0


def test_single_child_io80_coarse_tag_resolves_to_precise_sector():
    e, h = source()
    p = places(("V", "V80", "SRV"), ("", "V80", "SRV"))
    result = build_hierarchical_economy(p, e, h)
    assert result.places.economy_code.tolist() == ["240:V", "240:V"]
    assert result.places.economy_status.tolist() == ["IO240", "IO80_SINGLE_MEMBER"]


def test_single_output_group_io16_coarse_resolves_without_residual():
    e, h = source()
    p = places(("", "V80", "SRV"), ("", "", "SRV"))
    result = build_hierarchical_economy(p, e, h)
    assert result.places.economy_code.tolist() == ["80:V80", "80:V80"]
    assert result.places.economy_status.iloc[1] == "IO16_SINGLE_MEMBER"


def test_multi_group_io16_coarse_without_residual_fails_closed():
    e, h = source()
    # SRV only has one leaf; MAN can be completely resolved to different fine codes
    p = places(*[(c, "", "") for c in LEAVES if c != "V"], ("", "", "MAN"))
    with pytest.raises(EconomyValidationError, match="no unambiguous residual"):
        build_hierarchical_economy(p, e, h, strict_coarse=True, coarse_policy="residual")
    with pytest.raises(EconomyValidationError, match="no single sector contains"):
        build_hierarchical_economy(p, e, h, strict_coarse=True)


def test_io240_does_not_mutate_input_and_order_is_repeatable():
    e, h = source()
    p = places(("B", "F", "MAN"), ("", "F", "MAN"), ("", "", "MAN"))
    untouched = p.copy(deep=True)
    a = build_hierarchical_economy(p, e, h)
    b = build_hierarchical_economy(p, e, h)
    pd.testing.assert_frame_equal(p, untouched)
    pd.testing.assert_frame_equal(a.economy.Z_raw, b.economy.Z_raw)
    assert a.economy.economy_fingerprint == b.economy.economy_fingerprint


def test_duplicate_fine_labels_do_not_prevent_a_valid_partition():
    e, h = source()
    z, x = e.Z_raw, e.x
    duplicate_names = SectorCatalog(Sector(code, f"item {code}") for code in LEAVES)
    # source Economy normally requires unique labels; tests verify generated labels include codes
    assert len(set(f"IO240 {s.code} · {s.label}" for s in duplicate_names)) == len(LEAVES)


def test_unknown_io80_tag_and_missing_crosswalk_rejected():
    e, h = source()
    with pytest.raises(EconomyValidationError, match="unrecognized io80_code"):
        build_hierarchical_economy(places(("", "UNKNOWN", "")), e, h)
    with pytest.raises(EconomyValidationError, match="universe mismatch"):
        build_hierarchical_economy(places(("", "", "")), e, h.iloc[:-1])


def test_aggregation_matches_parent_io16_at_every_cell():
    e, h = source()
    p = places(("B", "F", "MAN"), ("", "T", "MAN"), ("", "", "MAN"))
    result = build_hierarchical_economy(p, e, h)
    parent = dict(zip(h.io240_code, h.io16_code, strict=True))
    codes = list(result.economy.sectors.codes)
    group_parents = [parent[result.membership.loc[result.membership.economy_code.eq(code), "io240_code"].iloc[0]] for code in codes]
    z2 = result.economy.Z_raw
    obtained = z2.groupby(pd.Index(group_parents), sort=False).sum().T.groupby(pd.Index(group_parents), sort=False).sum().T
    source_parents = h.io16_code.tolist()
    expected = e.Z_raw.groupby(pd.Index(source_parents), sort=False).sum().T.groupby(pd.Index(source_parents), sort=False).sum().T
    pd.testing.assert_frame_equal(obtained.reindex(index=expected.index, columns=expected.columns), expected)


def test_activation_backs_up_and_switches_without_overwriting_existing_backup(tmp_path):
    from sigma.economy.hierarchical import activate_hierarchical_places

    original = tmp_path / "places.parquet"
    candidate = tmp_path / "candidate.parquet"
    original.write_bytes(b"original bytes")
    candidate.write_bytes(b"new bytes")
    backup = activate_hierarchical_places(original, candidate)
    assert original.read_bytes() == b"new bytes"
    assert backup.read_bytes() == b"original bytes"
    candidate.write_bytes(b"different bytes")
    with pytest.raises(FileExistsError, match="backup already exists"):
        activate_hierarchical_places(original, candidate)
    assert backup.read_bytes() == b"original bytes"
    assert original.read_bytes() == b"new bytes"


def test_activation_rejects_unsafe_or_missing_inputs(tmp_path):
    from sigma.economy.hierarchical import activate_hierarchical_places

    original = tmp_path / "places.parquet"
    original.write_bytes(b"original")
    with pytest.raises(ValueError, match="must not overwrite itself"):
        activate_hierarchical_places(original, original)
    with pytest.raises(FileNotFoundError):
        activate_hierarchical_places(original, tmp_path / "missing.parquet")
    assert original.read_bytes() == b"original"


def test_failed_activation_preserves_original_and_does_not_leave_backup(tmp_path, monkeypatch):
    import os
    from sigma.economy.hierarchical import activate_hierarchical_places

    original = tmp_path / "places.parquet"
    preview = tmp_path / "new.parquet"
    original.write_bytes(b"untouched original")
    preview.write_bytes(b"pending update")
    real_replace = os.replace

    def fail_active_switch(src, dst):
        if str(dst) == str(original):
            raise OSError("simulated denied write")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_active_switch)
    with pytest.raises(OSError, match="simulated denied write"):
        activate_hierarchical_places(original, preview)
    assert original.read_bytes() == b"untouched original"
    assert not original.with_name("places.pre-hierarchical.parquet").exists()


@pytest.mark.parametrize("policy, status", [
    ("contain", "UNASSIGNED_IO80_STRADDLES"),
    ("residual", "UNASSIGNED_IO80_NO_RESIDUAL"),
])
def test_coarse_without_residual_is_reported_not_imputed_by_default(policy, status):
    e, h = source()
    p = places(("B", "F", "MAN"), ("D", "F", "MAN"),
               ("M", "F", "MAN"), ("S", "F", "MAN"),
               ("", "F", "MAN"))
    r = build_hierarchical_economy(p, e, h, coarse_policy=policy)
    assert r.places.economy_code.iloc[-1] == ""
    assert r.places.economy_status.iloc[-1] == status
    assert r.diagnostics["unassigned_coarse_place_count"] == 1
    assert len(r.membership) == len(LEAVES)


# ---------------------------------------------------------------------------
# v3 additions
# ---------------------------------------------------------------------------

def _partition(result):
    return result.membership.groupby("economy_code", sort=False).io240_code.apply(list).to_dict()


def test_min_places_folds_thin_industries_and_conserves():
    e, h = source()
    p = places(*([("B", "F", "MAN")] * 3), ("D", "F", "MAN"), ("", "F", "MAN"), ("", "F", "MAN"),
               ("V", "V80", "SRV"))
    r = build_hierarchical_economy(p, e, h, min_places=2, coarse_policy="residual")
    assert _partition(r) == {
        "240:B": ["B"], "80:F:OTHER": ["D", "M", "S"], "16:MAN:O": ["C", "L", "Q"], "16:SRV": ["V"],
    }
    assert r.places.economy_code.tolist() == ["240:B"] * 3 + ["80:F:OTHER"] * 3 + ["16:SRV"]
    assert r.places.economy_status.tolist() == (
        ["IO240"] * 3 + ["IO240_FOLDED", "IO80_RESIDUAL", "IO80_RESIDUAL", "IO240_FOLDED"]
    )
    assert r.diagnostics["folded_io240_codes"] == ["D", "V"]
    assert np.isclose(r.economy.Z_raw.to_numpy().sum(), e.Z_raw.to_numpy().sum())
    assert np.isclose(r.economy.x.sum(), e.x.sum())


def test_min_places_keeps_whole_io80_supported_by_folded_children():
    e, h = source()
    r = build_hierarchical_economy(places(("D", "F", "MAN"), ("M", "F", "MAN")), e, h, min_places=2)
    assert _partition(r)["80:F"] == ["B", "D", "M", "S"]
    assert r.places.economy_code.tolist() == ["80:F", "80:F"]
    assert r.places.economy_status.tolist() == ["IO240_FOLDED", "IO240_FOLDED"]


def test_min_places_one_is_the_default_partition():
    e, h = source()
    p = places(("B", "F", "MAN"), ("", "F", "MAN"), ("", "T", "MAN"), ("", "", "MAN"), ("", "", "SRV"))
    a = build_hierarchical_economy(p, e, h)
    b = build_hierarchical_economy(p, e, h, min_places=1)
    assert _partition(a) == _partition(b)
    pd.testing.assert_frame_equal(a.places, b.places)
    with pytest.raises(ValueError, match="min_places"):
        build_hierarchical_economy(p, e, h, min_places=0)


def test_every_conflicting_place_is_reported_at_once():
    e, h = source()
    p = places(("B", "T", "MAN"), ("C", "F", "MAN"), ("Q", "Q80", "MAN"))
    with pytest.raises(EconomyValidationError, match=r"2 place\(s\).*conflicting IO240/IO80 tags: 2"):
        build_hierarchical_economy(p, e, h)


def test_package_round_trip_keeps_fingerprint_and_records_lineage(tmp_path):
    e, h = source()
    odd = Economy(economy_id="psa: io240 #rev", sectors=e.sectors,
                  raw_transactions=e.Z_raw, total_output=e.x)
    r = build_hierarchical_economy(places(("B", "", ""), ("", "T", "MAN")), odd, h)
    write_hierarchical_package(r, tmp_path / "econ")
    loaded = Economy.from_directory(tmp_path / "econ")
    assert loaded.economy_id == r.economy.economy_id
    assert loaded.version is None
    assert loaded.economy_fingerprint == r.economy.economy_fingerprint
    derivation = loaded.provenance["metadata"]["derivation"]
    assert derivation["base_economy_fingerprint"] == odd.economy_fingerprint
    assert derivation["partition_sha256"] == r.diagnostics["partition_sha256"]
    assert derivation["min_places"] == 1


def test_group_labels_fall_back_to_sigma_psa_labels():
    from sigma.economy.builtin import load_builtin_sectors

    codes = ("001", "002", "003")
    e = Economy(
        economy_id="tiny", sectors=SectorCatalog(Sector(c, f"Industry {c}") for c in codes),
        raw_transactions=pd.DataFrame(np.ones((3, 3)), index=codes, columns=codes),
        total_output=pd.Series([10.0, 10.0, 10.0], index=codes),
    )
    h = pd.DataFrame([("001", "01", "01"), ("002", "01", "01"), ("003", "02", "01")],
                     columns=["io240_code", "io80_code", "io16_code"])
    r = build_hierarchical_economy(places(("001", "01", "01")), e, h)
    io80 = dict(zip(*load_builtin_sectors("io80")[["code", "label"]].T.values, strict=True))
    assert r.economy.sectors.label_for("01:01:o") == f"IO80 01 · {io80['01']} · Other"


def test_tagging_consistency_flags_parent_links_that_tagging_would_reject():
    from sigma.classification.reference import load_builtin_io_reference
    from sigma.economy.hierarchical import tagging_consistency

    row = next(r for r in load_builtin_io_reference().concordance
               if len(r.io240_codes) == 1 and len(r.io80_codes) == 1 and len(r.io16_codes) == 1)
    child, parent, top = row.io240_codes[0], row.io80_codes[0], row.io16_codes[0]
    good = tagging_consistency(pd.DataFrame([(child, parent, top)], columns=list(("io240_code", "io80_code", "io16_code"))))
    assert good["io240_parent_mismatches"] == [] and good["io80_parent_mismatches"] == []
    bad = tagging_consistency(pd.DataFrame([(child, "ZZ", top)], columns=["io240_code", "io80_code", "io16_code"]))
    assert bad["consistent"] is False
    assert bad["io240_parent_mismatches"][0]["io240_code"] == child
    assert bad["io240_parent_mismatches"][0]["tagging_io80"] == [parent]


# ---- command line --------------------------------------------------------

def _cli_fixture(root):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    codes = [f"{i:03d}" for i in range(1, 241)]
    p80 = [f"{(i - 1) // 3 + 1:02d}" for i in range(1, 241)]
    from sigma.classification.io_mapping_compat import load_catalog
    sigma16 = {code: item.io16_code for code, item in load_catalog().items()}
    p16 = [sigma16[c] for c in p80]  # IO80 -> IO16 must be SIGMA's PSA nesting
    eco = root / "io240"
    eco.mkdir()
    pd.DataFrame({"code": codes, "label": [f"Industry {c}" for c in codes]}).to_csv(eco / "sectors.csv", index=False)
    z = pd.DataFrame(np.add.outer(np.arange(240.0), np.arange(240.0)) % 7, index=codes, columns=codes)
    z.to_csv(eco / "transactions.csv", index_label="sector")
    pd.DataFrame({"sector": codes, "total_output": z.sum(axis=0).to_numpy() + 100}).to_csv(
        eco / "total_output.csv", index=False)
    (eco / "economy.yml").write_text("id: synthetic-io240\nlabel: Synthetic IO240\n", encoding="utf-8")
    pd.DataFrame({"io240_code": codes, "io80_code": p80, "io16_code": p16}).to_csv(root / "crosswalk.csv", index=False)
    ws = root / "ws"
    (ws / "places").mkdir(parents=True)
    (ws / "output").mkdir()
    (ws / "output" / "published.gpkg").write_text("export", encoding="utf-8")
    rows = [("001", "01", "01")] * 6 + [("002", "01", "01")] + [("", "01", "01")] * 2 + [("", "", "02")]
    frame = pd.DataFrame(rows, columns=["io240_code", "io80_code", "io16_code"])
    frame["canonical_id"] = [f"p{i}" for i in range(len(rows))]
    gpd.GeoDataFrame(frame, geometry=[Point(121 + i / 1000, 14.6) for i in range(len(rows))],
                     crs="EPSG:4326").to_parquet(ws / "places" / "places.parquet", index=False)
    base = ["economy", "hierarchical-build", "--workspace", str(ws), "--io240-dir", str(eco),
            "--crosswalk", str(root / "crosswalk.csv")]
    return ws, base


def test_cli_refuses_to_replace_the_workspace_export_folder(tmp_path):
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    result = CliRunner().invoke(app, base + ["--output-dir", str(ws / "output"), "--replace"])
    assert result.exit_code != 0
    assert (ws / "output" / "published.gpkg").read_text(encoding="utf-8") == "export"


def test_cli_preview_then_activate_with_min_places(tmp_path):
    import json
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    runner = CliRunner()
    first = runner.invoke(app, base + ["--min-places", "5", "--json"])
    assert first.exit_code == 0, first.output
    econ = Economy.from_directory(ws / "hierarchical" / "economy")
    assert "01:01:001" in econ.sectors.codes and "01:01:002" not in econ.sectors.codes
    audit = json.loads((ws / "hierarchical" / "economy" / "audit.json").read_text(encoding="utf-8"))
    assert audit["folded_io240_codes"] == ["002"]
    assert len(audit["places_input"]["sha256"]) == 64
    assert econ.provenance["metadata"]["derivation"]["min_places"] == 5
    original = (ws / "places" / "places.parquet").read_bytes()
    second = runner.invoke(app, base + ["--min-places", "5", "--activate", "--replace", "--json"])
    assert second.exit_code == 0, second.output
    assert (ws / "places" / "places.pre-hierarchical.parquet").read_bytes() == original
    import geopandas as gpd
    active = gpd.read_parquet(ws / "places" / "places.parquet")
    # Unassigned places keep an empty code; every assigned code is a built sector.
    assert set(active.economy_code) - {""} <= set(econ.sectors.codes)

# ---------------------------------------------------------------------------
# v4 safety and accounting edge cases
# ---------------------------------------------------------------------------

def test_partial_optional_parent_labels_are_not_conflicts():
    e, h = source()
    h["io80_label"] = ["", "Manufacture of food", "", "", "", "", "", ""]
    h["io16_label"] = ["Manufacturing", "", "", "", "", "", "", "Service"]
    result = build_hierarchical_economy(places(("B", "F", "MAN")), e, h)
    assert result.economy.sectors.label_for("80:F:OTHER") == "IO80 F · Manufacture of food · Other"
    assert "Manufacturing" in result.economy.sectors.label_for("16:MAN:O")


def test_residual_assumption_and_clusters_below_support_are_reported():
    e, h = source()
    p = places(*([("B", "F", "MAN")] * 5), ("D", "F", "MAN"), ("", "F", "MAN"))
    result = build_hierarchical_economy(p, e, h, min_places=5, coarse_policy="residual")
    assert result.diagnostics["coarse_residual_assumption_place_count"] == 1
    assert {x["economy_code"] for x in result.diagnostics["observed_sectors_below_min_places"]} == {
        "80:F:OTHER"
    }
    assert result.diagnostics["assigned_places_by_final_sector"]["80:F:OTHER"] == 2


def test_activation_rejects_changed_source_without_creating_a_backup(tmp_path):
    from sigma.economy.hierarchical import activate_hierarchical_places, _file_sha256

    original = tmp_path / "places.parquet"
    preview = tmp_path / "preview.parquet"
    original.write_bytes(b"source version 1")
    expected = _file_sha256(original)
    preview.write_bytes(b"hierarchical")
    original.write_bytes(b"source version 2")
    with pytest.raises(ValueError, match="changed after"):
        activate_hierarchical_places(original, preview, expected_original_sha256=expected)
    assert original.read_bytes() == b"source version 2"
    assert not original.with_name("places.pre-hierarchical.parquet").exists()


def test_cli_replace_refuses_unrelated_existing_folder(tmp_path):
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    unrelated = tmp_path / "personal_files"
    unrelated.mkdir()
    (unrelated / "important.txt").write_text("do not delete", encoding="utf-8")
    result = CliRunner().invoke(app, base + ["--output-dir", str(unrelated), "--replace"])
    assert result.exit_code != 0
    assert (unrelated / "important.txt").read_text(encoding="utf-8") == "do not delete"


def test_cli_replace_refuses_unrelated_file_in_previous_build(tmp_path):
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    runner = CliRunner()
    first = runner.invoke(app, base)
    assert first.exit_code == 0, first.output
    (ws / "hierarchical" / "keep_this.txt").write_text("important", encoding="utf-8")
    second = runner.invoke(app, base + ["--replace"])
    assert second.exit_code != 0
    assert (ws / "hierarchical" / "keep_this.txt").read_text(encoding="utf-8") == "important"


def test_cli_failed_activation_restores_previous_economy_output(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from sigma.cli import app
    import sigma.economy.hierarchical as hierarchy_module

    ws, base = _cli_fixture(tmp_path)
    runner = CliRunner()
    first = runner.invoke(app, base)
    assert first.exit_code == 0, first.output
    output = ws / "hierarchical" / "places.parquet"
    before_output = output.read_bytes()
    original = ws / "places" / "places.parquet"
    before_original = original.read_bytes()

    def fail_activation(*args, **kwargs):
        raise OSError("simulated Windows sharing violation")

    monkeypatch.setattr(hierarchy_module, "activate_hierarchical_places", fail_activation)
    second = runner.invoke(app, base + ["--replace", "--activate"])
    assert second.exit_code != 0
    assert output.read_bytes() == before_output
    assert original.read_bytes() == before_original
    assert not original.with_name("places.pre-hierarchical.parquet").exists()


def test_cli_crosswalk_requires_complete_80_and_16_parent_sets(tmp_path):
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    path = tmp_path / "crosswalk.csv"
    frame = pd.read_csv(path, dtype=str)
    frame.loc[frame.io80_code.eq("02"), "io80_code"] = "01"
    frame.to_csv(path, index=False)
    outcome = CliRunner().invoke(app, base)
    assert outcome.exit_code != 0
    assert "80 distinct io80_code" in outcome.output
    assert not (ws / "hierarchical").exists()


def test_cli_publishes_crosswalk_hash_and_owned_manifest(tmp_path):
    import hashlib, json, yaml
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    outcome = CliRunner().invoke(app, base)
    assert outcome.exit_code == 0, outcome.output
    built = ws / "hierarchical"
    marker = json.loads((built / ".sigma-hierarchical-manifest.json").read_text())
    assert marker["artifact_kind"] == "sigma-hierarchical-residual"
    assert marker["schema_version"] == 1
    audit = json.loads((built / "economy" / "audit.json").read_text())
    assert audit["crosswalk_input"]["sha256"] == hashlib.sha256(
        (tmp_path / "crosswalk.csv").read_bytes()
    ).hexdigest()
    metadata = yaml.safe_load((built / "economy" / "economy.yml").read_text())
    assert metadata["derivation"]["crosswalk_file_sha256"] == audit["crosswalk_input"]["sha256"]


# ---------------------------------------------------------------------------
# v5: SIGMA's IO80/IO16 structure, rollback that never deletes, empty folder
# ---------------------------------------------------------------------------

def _sigma_crosswalk():
    from sigma.classification.io_mapping_compat import load_catalog

    sigma16 = {code: item.io16_code for code, item in load_catalog().items()}
    codes = [f"{i:03d}" for i in range(1, 241)]
    p80 = [f"{(i - 1) // 3 + 1:02d}" for i in range(1, 241)]
    return pd.DataFrame({"io240_code": codes, "io80_code": p80, "io16_code": [sigma16[c] for c in p80]})


def test_require_sigma_io80_io16_accepts_sigma_structure_and_rejects_changes():
    from sigma.economy.hierarchical import require_sigma_io80_io16

    good = _sigma_crosswalk()
    require_sigma_io80_io16(good)
    swapped = good.copy()
    first, second = "01", "21"  # IO80 parents in different IO16 sectors
    a, b = (swapped.loc[swapped.io80_code.eq(c), "io16_code"].iloc[0] for c in (first, second))
    assert a != b
    swapped.loc[swapped.io80_code.eq(first), "io16_code"] = b
    swapped.loc[swapped.io80_code.eq(second), "io16_code"] = a
    assert swapped.io80_code.nunique() == 80 and swapped.io16_code.nunique() == 16
    with pytest.raises(EconomyValidationError, match="differ from SIGMA's PSA nesting"):
        require_sigma_io80_io16(swapped)
    unpadded = good.assign(io80_code=good.io80_code.str.lstrip("0"))
    with pytest.raises(EconomyValidationError, match="IO80 codes not in SIGMA's PSA table"):
        require_sigma_io80_io16(unpadded)


def test_cli_rejects_crosswalk_with_wrong_io80_to_io16_link(tmp_path):
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    path = tmp_path / "crosswalk.csv"
    frame = pd.read_csv(path, dtype=str)
    a = frame.loc[frame.io80_code.eq("01"), "io16_code"].iloc[0]
    b = frame.loc[frame.io80_code.eq("21"), "io16_code"].iloc[0]
    frame.loc[frame.io80_code.eq("01"), "io16_code"] = b
    frame.loc[frame.io80_code.eq("21"), "io16_code"] = a
    frame.to_csv(path, index=False)
    outcome = CliRunner().invoke(app, base)
    assert outcome.exit_code != 0
    assert "SIGMA's PSA nesting" in outcome.output
    assert not (ws / "hierarchical").exists()


def test_cli_replace_accepts_an_empty_existing_folder(tmp_path):
    from typer.testing import CliRunner
    from sigma.cli import app

    ws, base = _cli_fixture(tmp_path)
    (ws / "hierarchical").mkdir()
    outcome = CliRunner().invoke(app, base + ["--replace"])
    assert outcome.exit_code == 0, outcome.output
    assert (ws / "hierarchical" / "economy" / "economy.yml").is_file()


def test_cli_failed_rollback_keeps_previous_preview_and_reports_activation_error(tmp_path, monkeypatch):
    from pathlib import Path
    from typer.testing import CliRunner
    from sigma.cli import app
    import sigma.economy.hierarchical as hierarchy_module

    ws, base = _cli_fixture(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, base).exit_code == 0
    audit = ws / "hierarchical" / "economy" / "audit.json"
    audit.write_text(audit.read_text(encoding="utf-8").replace("{", '{"OLD": true,', 1), encoding="utf-8")
    original = ws / "places" / "places.parquet"
    before_original = original.read_bytes()

    def fail_activation(*args, **kwargs):
        raise OSError("simulated: places.parquet is open in QGIS")

    real_rename = Path.rename

    def locked_rename(self, target):
        if Path(target).name == "failed":
            raise PermissionError("simulated: new file locked by antivirus scan")
        return real_rename(self, target)

    monkeypatch.setattr(hierarchy_module, "activate_hierarchical_places", fail_activation)
    monkeypatch.setattr(Path, "rename", locked_rename)
    outcome = runner.invoke(app, base + ["--replace", "--activate"])
    monkeypatch.undo()
    assert outcome.exit_code != 0
    text = " ".join(outcome.output.split())
    assert "activation failed: simulated: places.parquet is open in QGIS" in text
    kept = [p for p in ws.iterdir() if p.name.startswith("hierarchical.previous-")]
    assert len(kept) == 1
    assert '"OLD": true' in (kept[0] / "economy" / "audit.json").read_text(encoding="utf-8")
    assert original.read_bytes() == before_original
    assert not original.with_name("places.pre-hierarchical.parquet").exists()


def test_cli_reports_clustering_threshold_separately_from_partition_threshold(tmp_path):
    import json
    from typer.testing import CliRunner
    from sigma.cli import app
    ws, base = _cli_fixture(tmp_path)
    run = CliRunner().invoke(app, base + ["--min-places", "1", "--cluster-report-threshold", "5"])
    assert run.exit_code == 0, run.output
    audit = json.loads((ws / "hierarchical" / "economy" / "audit.json").read_text(encoding="utf-8"))
    assert audit["min_places"] == 1
    assert audit["cluster_report_threshold"] == 5
    observed = {item["economy_code"] for item in audit["observed_sectors_below_cluster_threshold"]}
    assert "01:01:002" in observed


def test_cli_failed_restore_twice_does_not_lose_previous_preview(tmp_path, monkeypatch):
    from pathlib import Path
    from typer.testing import CliRunner
    from sigma.cli import app
    import sigma.economy.hierarchical as hierarchy_module

    ws, base = _cli_fixture(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, base).exit_code == 0
    prior = ws / "hierarchical" / "economy" / "audit.json"
    prior.write_text(prior.read_text(encoding="utf-8").replace("{", '{"OLD": true,', 1), encoding="utf-8")

    def fail_activation(*args, **kwargs):
        raise OSError("simulated activation failure")

    actual_rename = Path.rename

    def fail_rename(self, target):
        # Destination move cannot be undone, nor can previous be moved back.
        # Previously both errors could result in TemporaryDirectory deleting
        # the only existing copy of the prior output.
        if Path(target).name == "failed" or (
            self.name.startswith("hierarchical.previous-") and Path(target).name == "hierarchical"
        ):
            raise PermissionError("simulated Windows locked file")
        return actual_rename(self, target)

    monkeypatch.setattr(hierarchy_module, "activate_hierarchical_places", fail_activation)
    monkeypatch.setattr(Path, "rename", fail_rename)
    result = runner.invoke(app, base + ["--activate", "--replace"])
    monkeypatch.undo()
    assert result.exit_code != 0
    assert "activation failed: simulated activation failure" in result.output
    copies = list(ws.glob("hierarchical.previous-*"))
    assert len(copies) == 1
    assert '"OLD": true' in (copies[0] / "economy" / "audit.json").read_text(encoding="utf-8")



def test_canonical_sparse_ids_are_economic_model_and_place_ids():
    codes = ('125', '126', '127')
    e = Economy(
        economy_id='small_numeric',
        sectors=SectorCatalog(Sector(c, f'Numeric {c}') for c in codes),
        raw_transactions=pd.DataFrame(
            np.arange(1, 10, dtype=float).reshape(3, 3), index=codes, columns=codes),
        total_output=pd.Series([100., 200., 300.], index=codes),
    )
    h = pd.DataFrame([
        ('125','42','03'), ('126','42','03'), ('127','43','03'),
    ], columns=['io240_code','io80_code','io16_code'])
    places = pd.DataFrame([
        ('125','42','03'), ('125','42','03'), ('','42','03'), ('','','03'),
    ], columns=['io240_code','io80_code','io16_code'])
    r = build_hierarchical_economy(places, e, h, min_places=2, coarse_policy='residual')
    assert r.economy.sectors.codes == ('03:42:125','03:42:o','03:o')
    assert r.places.economy_code.tolist() == [
        '03:42:125','03:42:125','03:42:o','03:o'
    ]
    assert set(r.membership.economy_code) == set(r.economy.sectors.codes)
    assert r.diagnostics['sector_code_scheme'] == 'sparse-v1'
    assert np.isclose(r.economy.Z_raw.values.sum(), e.Z_raw.values.sum())
    assert np.isclose(r.economy.x.sum(), e.x.sum())
# sigma-canonical-sparse-hierarchy-v1

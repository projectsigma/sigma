"""UniFAST identity candidates must never be promoted from names alone."""
import csv
import gzip
import pytest

from sigma.classification.unifast_registry import (
    FIELDS, SOURCE, UniFASTIndex, load_unifast, packaged_unifast, _record_key,
)


def row(name="Quezon City University", kind="LUC", region="13 - NCR", side="public"):
    return dict(region=region, hei_name=name, hei_type=kind, ownership=side,
                source_url=SOURCE, accessed_utc="2026-11-04T10:00:00Z",
                record_key=_record_key(region, name))


def dump(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_exact_name_is_provisional_not_verified(tmp_path):
    file = tmp_path / "a.csv"
    dump(file, [row()])
    ix = UniFASTIndex(load_unifast(file))
    got = ix.match({"name": "Quezon City University", "region": "13 - NCR"}, "education")
    assert got.status == "UNIFAST_NAME_REGION_PROVISIONAL"
    assert got.side == "public" and got.basis == "unifast_name_provisional"
    assert "unifast_ra10931:" in got.source_ids
    assert ix.match({"name": "Quezon City University"}, "health").status == "NO_MATCH"


def test_duplicate_name_across_regions_is_ambiguous(tmp_path):
    f = tmp_path / "a.csv"
    dump(f, [row(region="13 - NCR"), row(region="03 - Central Luzon")])
    ix = UniFASTIndex(load_unifast(f))
    assert ix.match({"name": "Quezon City University"}, "education").status == "IDENTITY_AMBIGUOUS"
    assert ix.match({"name": "Quezon City University", "region_code": "13"}, "education").status == "UNIFAST_NAME_REGION_PROVISIONAL"
    assert ix.match({"name": "Quezon City University", "region_code": "02"}, "education").status == "CITY_CONFLICT"


def test_secondary_raw_source_cannot_take_ownership(tmp_path):
    f = tmp_path / "a.csv"
    dump(f, [row()])
    ix = UniFASTIndex(load_unifast(f))
    assert ix.match({"name": "Unrelated Clinic", "osm_name": "Quezon City University"}, "education").status == "CANONICAL_NAME_CONFLICT"


def test_conflicting_ownership_abstains(tmp_path):
    f = tmp_path / "a.csv"
    dump(f, [row(region="13 - NCR"), row(region="03 - Central Luzon", kind="Private HEI", side="private")])
    ix = UniFASTIndex(load_unifast(f))
    assert ix.match({"name": "Quezon City University"}, "education").status == "OWNERSHIP_CONFLICT"


def test_special_institutions_review(tmp_path):
    f = tmp_path / "a.csv"
    dump(f, [row(kind="CHED Supervised Inst.", side="")])
    assert UniFASTIndex(load_unifast(f)).match({"name": "Quezon City University"}, "education").status == "UNIFAST_TYPE_REVIEW"


def test_unifast_keys_not_official_and_type_consistent(tmp_path):
    f = tmp_path / "a.csv"
    broken = row()
    broken["ownership"] = "private"
    dump(f, [broken])
    with pytest.raises(ValueError, match="type/ownership disagreement"):
        load_unifast(f)
    broken = row()
    broken["record_key"] = "0" * 20
    dump(f, [broken])
    with pytest.raises(ValueError, match="record key invalid"):
        load_unifast(f)


def test_packaged_source_coverage():
    entries = packaged_unifast()
    assert len(entries) == 1955
    assert sum(e.ownership == "public" for e in entries) == 624
    assert sum(e.ownership == "private" for e in entries) == 1329
    assert sum(not e.ownership for e in entries) == 2

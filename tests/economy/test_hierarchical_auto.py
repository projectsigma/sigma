"""Automation contracts: one-time reference setup, per-area selection and stale-input guards."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
import yaml

from sigma.economy import Economy, Sector, SectorCatalog
from sigma.economy.hierarchical import build_hierarchical_economy, write_hierarchical_package, _file_sha256
from sigma.economy.hierarchical_auto import (
    save_profile, read_profile, auto_economy, selected_places, profile_is_current,
)
from sigma.errors import EconomyValidationError


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGMA_HOME", str(tmp_path / "sigma_home"))
    codes = [f"{i:03d}" for i in range(1, 241)]
    h = pd.DataFrame({
        "io240_code": codes,
        "io80_code": [f"{(i-1)//3+1:02d}" for i in range(1, 241)],
    })
    from sigma.classification.io_mapping_compat import load_catalog
    catalog = load_catalog()
    h["io16_code"] = h["io80_code"].map(lambda c: catalog[c].io16_code)
    z = pd.DataFrame(np.eye(240), index=codes, columns=codes)
    x = pd.Series(np.full(240, 100.), index=codes)
    e = Economy(economy_id="test-240", sectors=SectorCatalog(Sector(c, "Sector " + c) for c in codes),
                raw_transactions=z, total_output=x)
    cw = tmp_path / "crosswalk.csv"
    h.to_csv(cw, index=False)
    data = pd.DataFrame([
        {"io240_code": "001", "io80_code": "01", "io16_code": "01"},
        {"io240_code": "", "io80_code": "01", "io16_code": "01"},
        {"io240_code": "", "io80_code": "", "io16_code": "02"},
    ])
    original = tmp_path / "workspace" / "places" / "places.parquet"
    original.parent.mkdir(parents=True)
    data.to_pickle(original)   # bytes are enough to check digest contracts
    result = build_hierarchical_economy(data, e, h)
    src = tmp_path / "reference"
    # Reference source must use exact original 240-axis, not the hierarchy output.
    src.mkdir(exist_ok=True)
    e.sectors.to_frame().to_csv(src / "sectors.csv", index=False)
    e.Z_raw.to_csv(src / "transactions.csv", index_label="sector")
    e.x.rename("total_output").rename_axis("sector").reset_index().to_csv(src / "total_output.csv", index=False)
    (src / "economy.yml").write_text(yaml.safe_dump({"id":e.economy_id,
          "sectors":"sectors.csv","transactions":"transactions.csv","total_output":"total_output.csv"}))
    generated = tmp_path / "workspace" / "hierarchical"
    write_hierarchical_package(result, generated / "economy")
    preview = generated / "places.parquet"
    result.places.to_pickle(preview)
    audit_file = generated / "economy" / "audit.json"
    audit = json.loads(audit_file.read_text())
    audit.update({"places_input":{"sha256":_file_sha256(original)},
                  "crosswalk_input":{"sha256":_file_sha256(cw)}})
    audit_file.write_text(json.dumps(audit))
    (generated / ".sigma-hierarchical-manifest.json").write_text(json.dumps({
        "artifact_kind": "sigma-hierarchical-residual", "schema_version":1,
        "sector_code_scheme": result.diagnostics["sector_code_scheme"],
        "partition_sha256": result.diagnostics["partition_sha256"],
        "source_economy_fingerprint": Economy.from_directory(src).economy_fingerprint}))
    return tmp_path / "workspace", src, cw, result.economy, original, preview


def test_reference_setup_and_area_selection(tmp_path, monkeypatch):
    ws, source, cw, _, base, preview = fixture(tmp_path, monkeypatch)
    assert read_profile() is None
    assert auto_economy(ws) is not None
    assert auto_economy(ws, explicit="builtin:io80") is None
    assert selected_places(ws, auto_economy(ws)) == preview
    path = save_profile(source, cw, min_places=1)
    assert path.is_file() and read_profile()["min_places"] == 1
    assert profile_is_current(ws, read_profile())


def test_changed_handoff_does_not_use_stale_partition(tmp_path, monkeypatch):
    ws, source, cw, _, base, preview = fixture(tmp_path, monkeypatch)
    save_profile(source, cw, min_places=1)
    chosen = auto_economy(ws)
    base.write_bytes(b"changed filtered base")
    assert not profile_is_current(ws, read_profile())
    with pytest.raises(EconomyValidationError, match="changed since"):
        selected_places(ws, chosen)


def test_no_preview_for_unrelated_economy(tmp_path, monkeypatch):
    ws, source, cw, _, base, preview = fixture(tmp_path, monkeypatch)
    different = Economy(economy_id="other", sectors=SectorCatalog([Sector("A","A")]),
                        raw_transactions=pd.DataFrame([[1.]],index=["A"],columns=["A"]),
                        total_output=pd.Series([10.],index=["A"]))
    assert selected_places(ws, different) is None
    assert auto_economy(ws, explicit="io16") is None


def test_missing_or_incomplete_output_not_silently_reused(tmp_path, monkeypatch):
    ws, source, cw, _, base, preview = fixture(tmp_path, monkeypatch)
    (ws / "hierarchical" / "places.parquet").unlink()
    chosen = auto_economy(ws)
    with pytest.raises(EconomyValidationError, match="no matching places"):
        selected_places(ws, chosen)
# sigma-canonical-sparse-hierarchy-v1

"""Regression checks for the scored/classified split and Economy sector universe."""
from __future__ import annotations
import json
from pathlib import Path
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point
from sigma.web.unclustered import extend_classified_points, load_sector_catalog


def _gdf(ids, sectors, *, classified=False):
    data = {"canonical_id": ids, "geometry": [Point(i, 0) for i in range(len(ids))]}
    data["economy_code" if classified else "type"] = sectors
    if not classified:
        data.update({"cluster": [0] * len(ids), "sigma_score": [0.7] * len(ids)})
    return gpd.GeoDataFrame(data, geometry="geometry", crs="EPSG:4326")


def test_preserves_scored_and_appends_unclustered():
    a = _gdf(["A"], ["01:19"])
    b = _gdf(["A", "B", "C", "D"], ["01:19", "01:19", "03:39", ""] , classified=True)
    out, n = extend_classified_points(a, b, {"01:19", "03:39", "01:o"})
    assert n == 2 and len(out) == 3
    assert out["canonical_id"].tolist() == ["A", "B", "C"]
    assert out["unclustered"].tolist() == [False, True, True]
    assert out["sigma_score"].iloc[0] == 0.7
    assert out["sigma_score"].iloc[1:].isna().all()
    assert out["cluster"].iloc[1:].isna().all()
    assert str(out.crs) == "EPSG:4326"


def test_refuse_disagreement_instead_of_relabelling():
    with pytest.raises(ValueError, match="disagree"):
        extend_classified_points(_gdf(["A"], ["01:19"]), _gdf(["A"], ["03:39"], classified=True))


def test_refuse_missing_scored_id():
    with pytest.raises(ValueError, match="missing from"):
        extend_classified_points(_gdf(["A"], ["01:19"]), _gdf(["B"], ["01:19"], classified=True))


def test_refuse_duplicate_id():
    with pytest.raises(ValueError, match="duplicate"):
        extend_classified_points(_gdf(["A"], ["01:19"]), _gdf(["A", "A"], ["01:19", "01:19"], classified=True))


def test_refuse_unknown_economy_code():
    with pytest.raises(ValueError, match="outside the Economy"):
        extend_classified_points(_gdf(["A"], ["01:19"]), _gdf(["A", "B"], ["01:19", "unknown"], classified=True), {"01:19"})


def test_catalog_includes_empty_sectors(tmp_path: Path):
    ws = tmp_path / "workspaces" / "qc"
    out = ws / "output"
    out.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"output_dir": str(out)}))
    eco = ws / "hierarchical" / "economy"
    eco.mkdir(parents=True)
    (eco / "economy.yml").write_text("id: test-hierarchical-123\n")
    (eco / "sectors.csv").write_text("code,label\n01:19,Fishing\n01:o,Agriculture residual\n")
    catalog = load_sector_catalog(out, {"economy_id": "test-hierarchical-123", "area_slug": "qc"})
    assert catalog == {"01:19": "Fishing", "01:o": "Agriculture residual"}


def test_reject_mismatching_economy_catalog(tmp_path: Path):
    ws = tmp_path / "ws"; out = ws / "output"
    eco = ws / "hierarchical" / "economy"
    out.mkdir(parents=True); eco.mkdir(parents=True)
    (ws / "workspace.json").write_text(json.dumps({"output_dir": str(out)}))
    (eco / "economy.yml").write_text("id: other-hierarchical-123\n")
    (eco / "sectors.csv").write_text("code,label\n01:19,Fishing\n")
    with pytest.raises(ValueError, match="disagrees"):
        load_sector_catalog(out, {"economy_id": "test-hierarchical-123"})

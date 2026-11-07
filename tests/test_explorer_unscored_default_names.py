"""Guard the default visibility and names of unclustered establishments."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from sigma.web.builder import _preferred_establishment_names


STATIC = Path(__file__).resolve().parents[1] / "src" / "sigma" / "web" / "static"


def test_published_scored_and_classified_names_coalesce_per_record():
    mixed = pd.DataFrame({
        "canonical_name": ["Scored, canonical", None, "", None, "", None],
        "name": ["Other scored name", "Fish farm", "Poultry farm", "Water services", "  ", None],
    })
    assert _preferred_establishment_names(mixed).tolist() == [
        "Scored, canonical", "Fish farm", "Poultry farm", "Water services",
        "Unnamed establishment", "Unnamed establishment",
    ]


def test_name_only_legacy_exports_still_work():
    assert _preferred_establishment_names(pd.DataFrame({"name": ["Farm A", "Farm B"]})).tolist() == [
        "Farm A", "Farm B",
    ]


def test_unscored_map_layer_never_starts_visible():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    a = js.index("map.addLayer({id: 'unclustered-establishments'")
    b = js.index("map.addLayer({id: 'establishments'", a)
    layer = js[a:b]
    assert "type: 'circle', source: 'unscored-points'" in layer
    assert "visibility: 'none'" in layer
    assert "map.addSource('unscored-points', {type: 'geojson', data: EMPTY()})" in js
    assert "filter: ['!=', ['get', 'unclustered'], true]" in js[b:b+280]

def test_map_tile_loading_requires_explicit_opt_in():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    loader = js.split('  async function loadVisiblePoints() {', 1)[1].split('  function updateStatus(', 1)[0]
    # Native scored points never require an eager GeoJSON download. Hollow
    # unscored points are fetched from original tiles only after a user opt-in.
    assert 'if (meta.native_points_v7) {' in loader
    native = loader.split('if (meta.native_points_v7) {', 1)[1].split('if (!meta.has_points)', 1)[0]
    assert "setData('points', EMPTY());" in native
    assert 'if (!wantUnscored) {' in native
    assert 'unscoredCandidates = [];' in native
    assert 'feature.properties?.unclustered !== true' in native
    assert 'unscoredCandidates = rows;' in native
    assert 'getJSON(`data/tiles/${z}/${key}.geojson`)' in native
    sync = js.split('  function syncUnscoredOverlay() {', 1)[1].split('  function applyEmphasis()', 1)[0]
    assert "const general = Boolean(!network && control && control.checked && !control.disabled);" in sync
    assert "const scored = Boolean(linked && linked.checked && !linked.disabled);" in sync
    assert "const context = Boolean(network && scored);" in sync
    assert "const enabled = general || scored;" in sync
    assert "setData('unscored-points'" in sync

"""SIGMA Explorer: no startup leakage, no duplicate drawing, hollow circles."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'src/sigma/web/static'


def test_strictly_independent_sources_and_fail_closed_startup():
    s = (STATIC/'app.js').read_text(encoding='utf-8')
    scored = s.split("map.addLayer({id: 'establishments'",1)[1].split('    // Assign browser-only icon identifiers',1)[0]
    unscored = s.split("map.addLayer({id: 'unclustered-establishments'",1)[1].split("map.addLayer({id: 'establishments'",1)[0]
    assert "source: 'points'" in scored
    assert "source: 'unscored-points'" in unscored
    assert "data: EMPTY()" in s.split("map.addSource('unscored-points'",1)[1].split(');',1)[0]
    assert "visibility: 'none'" in unscored
    assert "const general = Boolean(!network && control && control.checked && !control.disabled);" in s
    assert "const scored = Boolean(linked && linked.checked && !linked.disabled);" in s
    assert "const context = Boolean(network && scored);" in s
    assert "const enabled = general || scored;" in s
    assert "setData('unscored-points', {type: 'FeatureCollection', features: locations})" in s
    # Scored establishments now use native PBF tiles. GeoJSON stays empty at
    # full-resolution mode, while hollow unscored context is independently opt-in.
    assert "map.addSource('native-points', {type: 'vector'" in s
    assert "source: 'native-points', 'source-layer': 'places'" in s
    assert "map.setFilter('native-establishments', filter)" in s
    assert "if (meta.native_points_v7) syncNativePointLayer();" in s
    assert "setData('points', EMPTY());" in s
    assert "filter: ['!=', ['get', 'unclustered'], true]" in scored


def test_marker_is_hollow_circle_and_different_from_cluster_center():
    s = (STATIC/'app.js').read_text(encoding='utf-8')
    layer = s.split("map.addLayer({id: 'unclustered-establishments'",1)[1].split("map.addLayer({id: 'establishments'",1)[0]
    assert "type: 'circle'" in layer
    assert "'circle-color': 'rgba(0,0,0,0)'" in layer
    assert "'circle-radius': unclusteredPointRadius" in layer
    sizes = s.split("const unclusteredPointRadius = radiusAtFit([", 1)[1].split("]);", 1)[0]
    assert "[-3, 0.775], [-1, 1.175], [0, 1.375]" in sizes
    assert "[2, 1.975], [4, 2.375]" in sizes
    assert "visual_min_score" not in sizes
    assert "'circle-stroke-width': 1.2" in layer
    assert "'circle-stroke-color': sigmaPointColorExpr" in layer
    assert "const radiusAtFit = stops => ['interpolate', ['linear'], ['zoom']" in s


def test_theme_paint_dedup_and_header_button_order():
    s = (STATIC/'app.js').read_text(encoding='utf-8')
    assert "map.getPaintProperty(layer, key)" in s
    assert 'lastAppliedGraphTheme !== themeMode' in s
    html=(STATIC/'index.html').read_text(encoding='utf-8')
    assert html.index('id="sigma-guided-tour-link"') < html.index('id="theme-toggle"')
    css=(STATIC/'style.css').read_text(encoding='utf-8')
    assert 'order:98 !important' in css
    assert 'order:99 !important' in css

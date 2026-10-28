"""SIGMA Explorer: no startup unscored leakage, no duplicate point drawing, upright icons."""
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
    assert "const enabled = Boolean(control && control.checked && !control.disabled && !network)" in s
    assert "setData('unscored-points', {type: 'FeatureCollection', features: locations})" in s
    assert "setData('points', {type: 'FeatureCollection', features: scoredFeatures})" in s
    assert "filter: ['!=', ['get', 'unclustered'], true]" in scored


def test_marker_is_hollow_upright_triangle_and_different_from_cluster_center():
    s = (STATIC/'app.js').read_text(encoding='utf-8')
    layer = s.split("map.addLayer({id: 'unclustered-establishments'",1)[1].split("map.addLayer({id: 'establishments'",1)[0]
    assert "type: 'symbol'" in layer
    assert "'icon-image': ['get', 'unscored_icon']" in layer
    assert "ctx.moveTo(12, 4); ctx.lineTo(21, 20); ctx.lineTo(3, 20)" in s
    assert "ctx.fillStyle = 'rgba(0,0,0,0)'" in s
    assert "'icon-size': ['interpolate', ['linear'], ['zoom'], 11, 0.32, 14, 0.38, 17, 0.50]" in layer


def test_theme_paint_dedup_and_header_button_order():
    s = (STATIC/'app.js').read_text(encoding='utf-8')
    assert "map.getPaintProperty(layer, key)" in s
    assert 'lastAppliedGraphTheme !== themeMode' in s
    html=(STATIC/'index.html').read_text(encoding='utf-8')
    assert html.index('id="sigma-guided-tour-link"') < html.index('id="theme-toggle"')
    css=(STATIC/'style.css').read_text(encoding='utf-8')
    assert 'order:98 !important' in css
    assert 'order:99 !important' in css

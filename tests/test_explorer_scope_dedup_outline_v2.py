"""SIGMA Explorer regression guards: disjoint point layers, click scope, dynamic triangle outline."""
from pathlib import Path
import re

APP = Path(__file__).resolve().parents[1] / 'src/sigma/web/static/app.js'


def source():
    return APP.read_text(encoding='utf-8')


def span(s, begin, end):
    return s.split(begin, 1)[1].split(end, 1)[0]


def test_scored_layer_never_draws_unscored_points_twice():
    s = source()
    layer = span(s, "map.addLayer({id: 'establishments'", '    // Assign browser-only icon identifiers')
    assert "filter: ['!=', ['get', 'unclustered'], true]" in layer
    emphasis = span(s, '  function applyEmphasis() {', '  function updatePartitions() {')
    assert "map.setFilter('establishments', ['all', ['!=', ['get', 'unclustered'], true], notHidden()]);" in emphasis
    assert "map.setFilter('establishments', notHidden());" not in emphasis


def test_unscored_layer_is_only_unscored_and_opt_in():
    s = source()
    layer = span(s, "map.addLayer({id: 'unclustered-establishments'", "map.addLayer({id: 'establishments'")
    assert "type: 'symbol', source: 'unscored-points'" in layer
    assert "visibility: 'none'" in layer
    assert "filter: ['==', ['get', 'unclustered'], true]" in layer
    assert "'icon-image': ['get', 'unscored_icon']" in layer
    assert "Boolean(control && control.checked && !control.disabled && !network)" in s

def test_map_clicks_and_hover_are_scoped():
    s = source()
    assert 'function selectableMapFeature(feature)' in s
    assert "feature.layer.id === 'unclustered-establishments') return false" in s
    assert 'network.ring.has(String(id))' in s
    assert 'const scopedPlaces = places.filter(selectableMapFeature);' in s
    assert 'const f = hits.find(selectableMapFeature);' in s


def test_triangle_border_follows_link_type_and_depth_not_fixed_blue():
    s = source()
    assert 'sigmaTriangleStyleByNode = computeNetworkTriangleStyles();' in s
    assert "reciprocal ? 'both' : (e.source === near ? 'outgoing' : 'incoming')" in s
    assert 'Math.max(0.26, 1 / Math.sqrt(depth)) * (0.7 + 1.5 * wn)' in s
    assert 'sigmaLinkedCenterIconExpression());' in s
    assert 'sigmaSyncSelectedTriangle();' in s
    assert "const palette = theme === 'dark'" in s
    assert 'map.addImage(name, ctx.getImageData' in s

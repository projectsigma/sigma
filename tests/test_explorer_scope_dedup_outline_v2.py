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
    assert "map.setFilter('establishments', ['all', ['!=', ['get', 'unclustered'], true]," in emphasis
    assert "notHidden(), sigmaOriginalFilter()]);" in emphasis
    assert "map.setFilter('establishments', notHidden());" not in emphasis


def test_unscored_layer_is_only_unscored_and_opt_in():
    s = source()
    layer = span(s, "map.addLayer({id: 'unclustered-establishments'", "map.addLayer({id: 'establishments'")
    assert "type: 'circle', source: 'unscored-points'" in layer
    assert "visibility: 'none'" in layer
    assert "filter: ['==', ['get', 'unclustered'], true]" in layer
    assert "'circle-radius': ['interpolate'" in layer
    assert "Boolean(!network && control && control.checked && !control.disabled)" in s
    assert "const scored = Boolean(linked && linked.checked && !linked.disabled);" in s
    assert "const context = Boolean(network && scored);" in s
    assert "const enabled = general || scored;" in s

def test_map_clicks_and_hover_are_scoped():
    s = source()
    assert 'function selectableMapFeature(feature)' in s
    assert "network.ring.has(String(p.voronoi_node_id || ''))" in s
    assert 'network.ring.has(String(id))' in s
    assert "const scopedPlaces = places.filter(feature =>" in s
    assert "feature.layer.id !== 'selected-center' && selectableMapFeature(feature));" in s
    assert 'const f = hits.find(selectableMapFeature);' in s


def test_triangle_border_follows_link_type_and_depth_not_fixed_blue():
    s = source()
    assert "sigmaTriangleStyleByNode = sigmaPerf('triangleStyles', computeNetworkTriangleStyles);" in s
    assert "reciprocal ? 'both' : (e.source === near ? 'outgoing' : 'incoming')" in s
    assert 'Math.max(0.26, 1 / Math.sqrt(depth)) * (0.7 + 1.5 * wn)' in s
    assert "map.setLayoutProperty('centers', 'icon-image', ids && network ?" in s
    assert "sigmaLinkedCenterIconExpression() : ['get', baseIcon]);" in s
    assert "sigmaLinkedCenterIconExpression() : ['get', base]);" in s
    assert 'sigmaSyncSelectedTriangle();' in s
    assert "const palette = theme === 'dark'" in s
    assert 'map.addImage(name, ctx.getImageData' in s

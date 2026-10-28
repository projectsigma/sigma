"""Regression guards for SIGMA's strict unscored map-layer opt-in and toolbar layout."""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "src" / "sigma" / "web" / "static"


def test_unscored_layer_has_unambiguous_hollow_paint_and_initially_empty_filter():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    layer = js.split("map.addLayer({id: 'unclustered-establishments'", 1)[1].split("map.addLayer({id: 'establishments'", 1)[0]
    assert "type: 'symbol', source: 'unscored-points'" in layer
    assert "visibility: 'none'" in layer
    assert "'icon-image': ['get', 'unscored_icon']" in layer
    assert "map.addSource('unscored-points', {type: 'geojson', data: EMPTY()})" in js
    assert "ctx.fillStyle = 'rgba(0,0,0,0)'" in js

def test_redraw_never_removes_unscored_predicate_or_opt_in():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    fn = js.split('function syncUnscoredOverlay() {', 1)[1].split('\n  }', 1)[0]
    assert "control && control.checked && !control.disabled && !network" in fn
    assert "setData('unscored-points'" in fn
    assert "visibility('unclustered-establishments', enabled)" in fn
    assert 'unscoredToggle.checked = false' in js

def test_header_and_toolbar_positions():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    header = html.split('<header class="top">', 1)[1].split('</header>', 1)[0]
    top_right = header.split('<div class="top-right">', 1)[1].split('</div>', 1)[0]
    assert top_right.index('id="sigma-guided-tour-link"') < top_right.index('id="theme-toggle"')
    assert header.count('id="sigma-guided-tour-link"') == 1
    assert 'order:98 !important' in css and 'order:99 !important' in css
    assert 'width:105px !important; min-width:105px !important; max-width:105px !important;' in css
    assert html.index('id="sigma-details-toggle"') > html.index('<section class="toolbar"')
    assert 'id="show-unscored" autocomplete="off"' in html

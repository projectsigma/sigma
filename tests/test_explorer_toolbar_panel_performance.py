"""Regression checks for toolbar panel control, adjacent tutorial and small-pan cache."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "sigma" / "web" / "static"


def test_panel_toggle_is_prominent_and_inside_toolbar_not_header():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    toolbar_at = html.index('<section class="toolbar"')
    main_at = html.index("<main>")
    toggle_at = html.index('id="sigma-details-toggle"')
    assert toolbar_at < toggle_at < main_at
    assert html.count('id="sigma-details-toggle"') == 1
    assert 'aria-controls="sigma-details-panel"' in html
    assert '.toolbar .sigma-panel-toggle-slot' in css
    assert 'position:absolute; top:8px; right:16px' in css
    assert 'background:#b11116; color:#fff;' in css
    assert 'html[data-theme="dark"] .toolbar #sigma-details-toggle' in css


def test_under_hood_matches_about_and_is_adjacent():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    a = html.index('id="sigma-about-link"')
    u = html.index('id="sigma-guided-tour-link"')
    theme = html.index('id="theme-toggle"')
    header_end = html.index('</header>')
    assert a < u < theme < header_end
    assert html.count('id="sigma-guided-tour-link"') == 1
    assert 'sigma-guided-nearby' in html
    assert 'order:98 !important' in css
    assert 'html[data-theme="dark"] header.top .top-right > #sigma-guided-tour-link' in css

def test_existing_right_panel_controller_still_works():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "setRightPanelCollapsed(!$('sigma-details-panel').hidden)" in js
    assert "panel.hidden = collapsed;" in js
    assert "if (map && map.resize) map.resize();" in js


def test_pan_cache_skips_only_identical_rendered_tile_set():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'let lastRenderedTileSignature = null;' in js
    assert 'if (signature === lastRenderedTileSignature) { updateStatus(); return; }' in js
    assert js.count('lastRenderedTileSignature = null;') == 3  # declaration and two invalidations
    assert 'lastRenderedTileSignature = signature;' in js
    assert js.index("setData('points', {type: 'FeatureCollection'") < js.index("lastRenderedTileSignature = signature;")

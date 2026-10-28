"""Regression checks for the optional red-unscored sector inventory and whole-side collapse."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "sigma" / "web" / "static"


def test_red_unscored_both_themes():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".sector-item.sector-item--unscored > .sector-title" in css
    assert "color: #b11116; font-weight: 650;" in css
    assert 'html[data-theme="dark"] .sector-panel .sector-list .sector-item.sector-item--unscored' in css
    assert "color: #ff888e; font-weight: 650;" in css


def test_right_panel_remains_structurally_intact_and_has_external_toggle():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    button = html.index('id="sigma-details-toggle"')
    aside = html.index('<aside class="side" id="sigma-details-panel">')
    assert button < aside
    assert 'aria-controls="sigma-details-panel" aria-expanded="true"' in html
    for existing in ('finder-section', 'selection', 'graph-section', 'connections-section', 'central-section'):
        assert f'class="{existing}"' in html
    assert '<details class="sidebar-disclosure"' in html


def test_map_is_resized_and_disclosures_are_not_reset():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "function setRightPanelCollapsed(collapsed)" in js
    assert "panel.hidden = collapsed;" in js
    assert "document.body.classList.toggle('details-collapsed', collapsed);" in js
    assert "if (map && map.resize) map.resize();" in js
    assert "if (network) cy.fit(undefined, 24);" in js
    assert "setRightPanelCollapsed(!$('sigma-details-panel').hidden);" in js
    assert "body.details-collapsed main { grid-template-columns: minmax(0, 1fr) !important; }" in css
    assert "details-collapsed" not in (STATIC / "network-model.js").read_text(encoding="utf-8")

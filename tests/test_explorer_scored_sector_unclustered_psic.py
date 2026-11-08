"""Explorer presentation-only invariants: circle sizing, focus gating and PSIC titles."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src/sigma/web/static"
BUILDER = STATIC.parent / "builder.py"


def test_hollow_circles_match_sector_minimum_without_fake_scores():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    builder = BUILDER.read_text(encoding="utf-8")
    layer = app.split("map.addLayer({id: 'unclustered-establishments'", 1)[1].split(
        "map.addLayer({id: 'establishments'", 1)[0]
    assert "type: 'circle'" in layer
    assert "'circle-color': 'rgba(0,0,0,0)'" in layer
    assert "'circle-radius': unclusteredPointRadius" in layer
    sizes = app.split("const unclusteredPointRadius = radiusAtFit([", 1)[1].split("]);", 1)[0]
    assert "scoreRadius(2.1, 4.6, 'visual_min_score')" in sizes
    assert "scoreRadius(2.8, 6.6, 'visual_min_score')" in sizes
    assert "'circle-stroke-color': sigmaPointColorExpr" in layer
    assert "sector.min_score : (meta.score_range?.[0] ?? 0)" in app
    assert "sector_min_scores[code] = min(float(score)" in builder
    assert "\"min_score\": sector_min_scores.get(code)" in builder
    assert "'sigma_score'" not in app.split("const sector = sectors.get(String(feature.properties.type))", 1)[1].split("classifiedOnly.push", 1)[0]


def test_opt_in_scored_sector_visibility_at_rest_and_selected_network_partitions():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    sync = app.split("function syncUnscoredOverlay() {", 1)[1].split(
        "function applyEmphasis() {", 1)[0]
    assert "const scored = Boolean(linked && linked.checked && !linked.disabled);" in sync
    assert "const context = Boolean(network && scored);" in sync
    assert "const enabled = general || scored;" in sync
    assert "if (scored) {" in sync
    assert "const partitions = context ? sigmaSelectedPartitions() : null;" in sync
    assert "const containing = sigmaContainingSelectedPartition(f, partitions);" in sync
    assert "network.ring.entries()" in sync
    assert "p.voronoi_node_id = containing.id;" in sync
    assert "p.score =" not in sync
    assert "sigmaSelectedPartitions()" in app


def test_psic_code_and_label_are_both_published_and_displayed():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    builder = BUILDER.read_text(encoding="utf-8")
    assert '"psic_label": psic_labels.iat[i]' in builder
    assert "load_builtin_psic_taxonomy" in builder
    assert "stat('PSIC label', p.psic_label || '—')" in app
    assert "stat('PSIC label', p && p.psic_label ? String(p.psic_label) : '—')" in app


def test_two_overlay_control_rows_are_aligned():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert ".sector-panel .sector-overlay-control,\n.sector-panel .sigma-linked-unscored-control" in css
    assert "Show unclustered for scored sectors" in app

"""Guard canonical SIGMA docs/Under-the-Hood against stale Gap defaults."""
from pathlib import Path

from sigma.config import SigmaConfig
from sigma.spatial.pipeline import SpatialRunConfig

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_canonical_gap_default_and_legacy_equivalent():
    s = SigmaConfig.default().spatial
    legacy = SigmaConfig.equivalent().spatial
    assert s.median_gap_refinement is True
    assert s.median_gap_workers == 4
    assert legacy.median_gap_refinement is False
    assert SpatialRunConfig().median_gap_refinement is True
    assert SpatialRunConfig().median_gap_workers == 4

    from sigma.cli import _config
    assert _config().spatial.median_gap_refinement is True
    assert _config(equivalent=True).spatial.median_gap_refinement is False
    assert _config(median_gap_refinement=False).spatial.median_gap_refinement is False
    assert _config(equivalent=True, median_gap_refinement=True).spatial.median_gap_refinement is True


def test_docs_pipeline_and_command_overrides():
    docs = [
        read("README.md"),
        read("docs/book/content/intro/index.md"),
        read("docs/book/content/workflow/end_to_end.md"),
        read("docs/book/content/methods/network_gap_medians.md"),
        read("docs/book/content/reference/defaults.md"),
    ]
    assert all("Gap" in d and "HDBSCAN" in d for d in docs)
    assert "**on**" in docs[-1]
    assert "Network Gap worker processes | **4**" in docs[-1]
    assert "--no-median-gap" in docs[0]
    assert "--median-gap-workers 1" in docs[0]
    assert "--equivalent" in docs[0]
    assert "single nonrecursive" in docs[3]


def test_hierarchical_rollup_precedes_gap_and_keeps_noise():
    h = read("docs/book/content/methods/hierarchical.md")
    g = read("docs/book/content/methods/network_gap_medians.md")
    r = read("docs/book/content/reference/outputs.md")
    assert "unrefined" in h and "K=0" in h
    assert "four" in h.lower() and "network Gap" in h
    assert "noise" in g.lower() and "median_gap_audit.json" in g
    assert "hdbscan_cluster" in r and "original_economy_code" in r


def test_book_order_matches_model_execution():
    toc = read("docs/book/_toc.yml")
    indices = [toc.index("content/methods/" + page) for page in
               ("hdbscan", "network_gap_medians", "centers", "voronoi")]
    assert indices == sorted(indices)


def test_under_the_hood_explains_not_reimplements():
    html = read("src/sigma/web/static/tutorial.html")
    assert html.count('id="gap-refinement"') == 1
    assert html.index('id="clusters"') < html.index('id="gap-refinement"') < html.index('id="centers"')
    for token in ("4 independent worker processes", "median_gap_audit.json", "nonrecursive", "K=0", "--no-median-gap"):
        assert token.lower() in html.lower()
    assert "not proof that this particular published bundle" in html


def test_x_routing_is_numerical_and_browser_default():
    source = read("src/sigma/analysis/pipeline.py")
    exports = read("src/sigma/export/compatibility.py")
    assert 'include_paths=False' in source
    assert '"route_geometry": "none"' in source
    assert '"browser",' in exports
    x = read("docs/book/content/methods/x_graph.md")
    assert 'empty GeoParquet placeholder' in x
    assert 'on request' in x and '--route-geometry precomputed' in x
    assert 'hardlinked route files or route geometry reuse as the canonical' in x


def test_algorithm_docs_no_longer_use_stale_io80_or_precomputed_default():
    root = read("README.md")
    cli = read("docs/SIGMA_RUN_VIEW_CLI.md")
    explorer = read("SIGMA_EXPLORER.md")
    assert 'single-pass network Gap k-medoids' in root
    assert 'four workers' in root
    assert 'browser-native route publication' in root
    assert 'Network Gap k-medoids refinement (opt-in)' not in cli
    assert '--route-geometry {browser,precomputed}' in cli
    assert 'Web Worker runs shortest-path reconstruction' in explorer


def test_underhood_overview_and_fallback_are_current():
    tutorial = read("src/sigma/web/static/tutorial.html")
    live = read("src/sigma/web/static/tutorial-live.js")
    assert "'K=0 check → Gap'" in tutorial
    assert 'network HDBSCAN leaf selection' in tutorial
    assert 'Default X route geometry' in tutorial
    assert 'sigma load pasig' in tutorial
    assert 'routePresentation = meta.route_mode' in live
    assert 'precomputed' in live and 'on demand' in live
    generated = read('src/sigma/export/spatial.py')
    assert 'The default browser mode leaves this layer empty' in generated
    assert 'native-CRS Step-4 cluster polygons' not in generated

def test_institutional_production_docs_are_visible_and_precise():
    places = read('docs/book/content/methods/places.md')
    institutions = read('docs/book/content/methods/shadow_classification.md')
    hierarchy = read('docs/book/content/methods/hierarchical.md')
    toc = read('docs/book/_toc.yml')
    references = read('docs/book/content/reference/references.md')
    pipeline = read('src/sigma/places/pipeline.py')
    promotion = read('src/sigma/classification/ownership_promotion.py')
    assert 'apply_administrative_activity' in pipeline
    assert 'promote_registry_evidence=True' in pipeline
    assert 'NationalRegistryIndex' in promotion and 'UniFASTIndex' in promotion
    assert 'per-area hierarchical PSA 2018' in places
    assert 'PSIC 84120' in places
    assert 'production `places.classified`' in institutions
    assert 'Historical registry-backed shadow v3 diagnostic' in institutions
    assert 'content/methods/shadow_classification' in toc
    assert 'registry verification' in hierarchy
    assert 'Tibshirani, R., Walther' in references
    assert 'Kaufman, L., & Rousseeuw' in references

def test_internal_docstrings_match_current_methods():
    xsrc = read('src/sigma/analysis/x_graph.py')
    gapsrc = read('src/sigma/spatial/network_gap.py')
    worker = read('src/sigma/web/static/route-worker.js')
    assert 'mean hub-mediated road' in xsrc
    assert 'technical_coefficient / max(road_distance_in_metres' not in xsrc
    assert 'Canonical SIGMA enables this single-pass' in gapsrc
    assert 'opt-in and audited' not in gapsrc
    assert 'default browser-native route reconstruction' in worker

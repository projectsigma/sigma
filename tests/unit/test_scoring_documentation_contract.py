"""Static documentation contract for canonical SIGMA area-adjusted scoring."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_canonical_scoring_explained_across_entrypoints():
    for path in (
        "README.md", "docs/book/content/intro/index.md",
        "docs/book/content/intro/quickstart.md", "docs/book/content/reference/defaults.md",
        "docs/SIGMA_RUN_VIEW_CLI.md", "src/sigma/web/static/tutorial.html",
    ):
        txt = read(path).lower()
        assert "area" in txt and "inverse" in txt, path


def test_docs_explain_two_tile_perspectives():
    centrality = read("docs/book/content/methods/centrality.md")
    diagnostics = read("docs/book/content/methods/area_adjustment_diagnostics.md")
    assert "FW^{\\mathsf T}" in centrality
    assert "FW^{\\mathsf T}" in diagnostics
    assert "0.44457936" in diagnostics
    assert "2.30" in diagnostics
    assert "0.376620537" in diagnostics


def test_tutorial_no_longer_teaches_legacy_tempering_as_canonical():
    tutorial = read("src/sigma/web/static/tutorial.html")
    assert "canonical inverse-distance point score" in tutorial
    assert "Math.log10" in tutorial
    assert "0.40 / Math.max(d, 1)" in tutorial
    assert "0.40 / 200 = 0.002" in tutorial
    assert "p90 = 800 m" not in tutorial
    assert "0.40 × (1 − 0.15" not in tutorial
    assert "The p90 gives each cluster" not in tutorial
    assert "reduced by at most 15%" not in tutorial


def test_book_navigation_includes_diagnostics():
    toc = read("docs/book/_toc.yml")
    assert "content/methods/area_adjustment_diagnostics" in toc
    assert (ROOT / "docs/book/content/methods/area_adjustment_diagnostics.md").is_file()


def test_about_page_no_longer_describes_distance_tempering():
    import re
    about = re.sub(r"data:image/[^\"')]+", "", read("src/sigma/web/static/about.html"))
    assert "tempering" not in about.lower()
    assert "Area-adjusted Katz ÷ road distance" in about


def test_gravity_motivation_is_attached_to_the_x_weight():
    x_graph = read("docs/book/content/methods/x_graph.md")
    assert "## Gravity-model motivation" in x_graph
    assert "inverse-square" in x_graph and "set to **one**" in x_graph
    assert "catchment-size proxy" in x_graph
    lineage = read("docs/book/content/reference/method_lineage.md")
    rows = lineage.splitlines()
    stage17 = next(line for line in rows if "Establishment scoring (stage 17)" in line)
    assert "Gravity-inspired inverse-distance interaction" not in stage17
    stage14 = next(line for line in rows if "X graph (stage 14)" in line)
    assert "gravity" in stage14.lower()
    references = read("docs/book/content/reference/references.md")
    assert "10.1162/rest.88.4.641" in references


def test_book_explains_units_indirect_effects_and_run_diagnostics():
    centrality = read("docs/book/content/methods/centrality.md")
    assert "f_i>1" in centrality and "indirect walks" in centrality
    assert "shared spectral normalization" in centrality
    assert "inequalities reverse" in centrality
    for key in ("unadjusted_comparison", "area_deciles", "degree_balance",
                "degree_orientation_regressions", "factor_max_min_ratio"):
        assert key in centrality
    diagnostics = read("docs/book/content/methods/area_adjustment_diagnostics.md")
    assert "19 X nodes had zero degree" in diagnostics
    assert "equal incoming and outgoing degree" in diagnostics
    assert "## Implementation notes relative to the reviewed specification" in diagnostics


def test_under_the_hood_animates_gravity_and_tile_area():
    tutorial = read("src/sigma/web/static/tutorial.html")
    for fig in ('data-fig="gravity"', 'data-fig="area"', 'data-fig="katz"'):
        assert fig in tutorial
    for control in ('id="gv-p"', 'id="gv-n"', 'id="ar-w"', 'id="ar-g"', 'id="ar-units"',
                    'id="ar-ops"', 'id="kz-adj"', 'id="kz-g"', 'id="kz-src"'):
        assert control in tutorial
    assert "equal-area four-node graph" not in tutorial
    assert "sigma:tile-area" in tutorial
    live = read("src/sigma/web/static/tutorial-live.js")
    assert "sigma:tile-area" in live and "section === 'gravity'" in live
    assert "section === 'area'" in live and "section === 'katz'" in live


def test_readme_shows_canonical_qgis_label():
    readme = read("README.md")
    assert 'format_number("sigma_score", 10)' in readme
    assert "gravity-inspired" in readme

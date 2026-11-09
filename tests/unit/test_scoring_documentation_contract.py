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

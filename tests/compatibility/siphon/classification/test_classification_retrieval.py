from __future__ import annotations

from sigma.classification.reference import PsicNode, PsicTaxonomy
from sigma.classification.retrieval import PsicRetriever


def _taxonomy() -> PsicTaxonomy:
    return PsicTaxonomy(
        [
            PsicNode("G", "section", "Wholesale and Retail Trade"),
            PsicNode("47", "division", "Retail Trade", "G"),
            PsicNode("471", "group", "Retail sale in non-specialized stores", "47"),
            PsicNode("Q", "section", "Human Health Activities"),
            PsicNode("86", "division", "Human Health Activities", "Q"),
            PsicNode("862", "group", "Medical and dental practice activities", "86"),
            PsicNode("8622", "class", "Dental practice activities", "862"),
            PsicNode("86222", "subclass", "Private dental and laboratory services", "8622"),
        ]
    )


def test_hierarchical_retrieval_respects_branch_root():
    retriever = PsicRetriever(_taxonomy())
    hits = retriever.search_hierarchical(
        "private dental laboratory services",
        top_n=5,
        branch_roots=("862",),
    )
    assert hits
    assert all(hit.code.startswith("862") for hit in hits)
    assert hits[0].code in {"86222", "8622"}


def test_retrieval_cache_closure_includes_root_and_descendants():
    retriever = PsicRetriever(_taxonomy())
    assert retriever.codes_under(("862",)) == {"862", "8622", "86222"}

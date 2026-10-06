from __future__ import annotations

import re

import pandas as pd

from sigma.classification.crosswalk import CrosswalkIndex
from sigma.classification.engine import PsicClassifier
from sigma.classification.model_backend import ChatBackend
from sigma.classification.reference import PsicNode, PsicTaxonomy
from sigma.classification.traversal import HierarchicalPsicTraverser
from sigma.classification.types import PsicDecision


class FirstCandidateBackend(ChatBackend):
    model_name = "fake-model"

    def complete(self, system: str, user: str, temperature: float = 0.0) -> str:
        options = user.split("CANDIDATE CHILDREN", 1)[1]
        code = re.search(r"CODE ([A-Z0-9]+):", options).group(1)
        return f'{{"decision": "{code}", "reason": "supported"}}'


def _taxonomy() -> PsicTaxonomy:
    return PsicTaxonomy(
        [
            PsicNode("A", "section", "Food and beverage service activities"),
            PsicNode("01", "division", "Beverage serving activities", "A"),
            PsicNode("011", "group", "Coffee shop operations", "01"),
        ]
    )


def test_llm_only_resolves_deterministically_unresolved_row():
    taxonomy = _taxonomy()
    traverser = HierarchicalPsicTraverser(
        taxonomy,
        FirstCandidateBackend(),
        passes=3,
        temperature=0.0,
    )
    classifier = PsicClassifier(
        taxonomy=taxonomy,
        crosswalk=CrosswalkIndex([]),
        top_n=1,
        traverser=traverser,
    )
    row = pd.Series(
        {
            "sources": "osm",
            "osm_name": "Example Coffee Shop",
            "osm_category": "",
        }
    )
    deterministic = classifier._classify_row_deterministic(row)
    assert deterministic.code is None
    assert deterministic.status == "CANDIDATES_ONLY"

    resolved = classifier.classify_row(row)
    assert resolved.code == "011"
    assert resolved.status == "LLM_FULL"
    assert resolved.method == "llm"
    assert resolved.traversal_agreement == 1.0


def test_activity_nonactivity_conflict_is_not_model_eligible():
    decision = PsicDecision(
        None,
        None,
        None,
        "CONFLICT",
        "fusion",
        flags=["ACTIVITY_NON_ACTIVITY_CONFLICT"],
    )
    assert not PsicClassifier._needs_llm(decision)


def test_llm_max_rows_bounds_live_model_work():
    taxonomy = _taxonomy()
    traverser = HierarchicalPsicTraverser(
        taxonomy,
        FirstCandidateBackend(),
        passes=3,
        temperature=0.0,
    )
    classifier = PsicClassifier(
        taxonomy=taxonomy,
        crosswalk=CrosswalkIndex([]),
        top_n=1,
        traverser=traverser,
    )
    frame = pd.DataFrame(
        [
            {"sources": "osm", "osm_name": "Coffee Shop One", "osm_category": ""},
            {"sources": "osm", "osm_name": "Coffee Shop Two", "osm_category": ""},
        ]
    )
    out = classifier.classify_frame(frame, llm_max_rows=1)
    assert out.loc[0, "psic_method"] == "llm"
    assert out.loc[1, "psic_code"] == ""
    assert "LLM_LIMIT_SKIPPED" in out.loc[1, "psic_flags"]

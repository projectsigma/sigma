from __future__ import annotations

from sigma.classification.fusion import activity_nonactivity_conflict, fuse
from sigma.classification.reference import PsicNode, PsicTaxonomy
from sigma.classification.types import Evidence, FusionStatus, MappingKind, MappingRule


def _taxonomy() -> PsicTaxonomy:
    return PsicTaxonomy(
        [
            PsicNode("C", "section", "Manufacturing"),
            PsicNode("10", "division", "Food manufacture", "C"),
            PsicNode("101", "group", "Processing of meat", "10"),
            PsicNode("1011", "class", "Processing and preserving of meat", "101"),
            PsicNode("10111", "subclass", "Processing beef", "1011"),
            PsicNode("10112", "subclass", "Processing pork", "1011"),
            PsicNode("102", "group", "Processing fish", "10"),
            PsicNode("1021", "class", "Processing fish", "102"),
            PsicNode("10210", "subclass", "Processing fish products", "1021"),
        ]
    )


def _ev(source: str, code: str, kind: MappingKind = MappingKind.SUBTREE) -> Evidence:
    return Evidence(
        source=source,
        category="x",
        name="n",
        dependency_group=source,
        mapping=MappingRule(
            source,
            "x",
            kind,
            (code,)
            if kind not in {MappingKind.NOT_ACTIVITY, MappingKind.UNCODEABLE}
            else (),
        ),
    )


def test_independent_immediate_siblings_back_off_one_level():
    result = fuse(_taxonomy(), [_ev("overture", "10111"), _ev("osm", "10112")])
    assert result.code == "1011"
    assert result.status == FusionStatus.INTERSECT
    assert "INDEPENDENT_SIBLING_BACKOFF" in result.flags


def test_non_sibling_cousins_are_conflict():
    result = fuse(_taxonomy(), [_ev("overture", "10111"), _ev("osm", "10210")])
    assert result.code is None
    assert result.status == FusionStatus.CONFLICT


def test_activity_nonactivity_conflict_requires_independent_groups():
    coded = _ev("osm", "10111")
    not_activity = _ev("overture", "", MappingKind.NOT_ACTIVITY)
    assert activity_nonactivity_conflict([coded, not_activity])

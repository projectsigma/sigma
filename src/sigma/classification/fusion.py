from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .reference import PsicTaxonomy
from .types import Evidence, FusionDecision, FusionStatus, MappingKind, MappingRule


def normalize_roots(taxonomy: PsicTaxonomy, codes: Iterable[str]) -> list[str]:
    valid = sorted(
        {str(code) for code in codes if str(code) in taxonomy.nodes},
        key=lambda code: (taxonomy.depth(code), code),
    )
    kept: list[str] = []
    for code in valid:
        if any(root in taxonomy.ancestors(code) for root in kept):
            continue
        kept.append(code)
    return kept


def mapping_roots(taxonomy: PsicTaxonomy, mapping: MappingRule | None) -> list[str]:
    if mapping is None or mapping.mapping_kind in {
        MappingKind.NOT_ACTIVITY,
        MappingKind.UNCODEABLE,
    }:
        return []
    return normalize_roots(taxonomy, mapping.codes)


def intersect_subtrees(
    taxonomy: PsicTaxonomy,
    left: Iterable[str],
    right: Iterable[str],
) -> list[str]:
    out: list[str] = []
    for a in left:
        ancestors_a = set(taxonomy.ancestors(a))
        for b in right:
            if a == b:
                out.append(a)
            elif a in taxonomy.ancestors(b):
                out.append(b)
            elif b in ancestors_a:
                out.append(a)
    return normalize_roots(taxonomy, out)


def _union_subtrees(taxonomy: PsicTaxonomy, *parts: Iterable[str]) -> list[str]:
    return normalize_roots(taxonomy, (code for part in parts for code in part))


def _representative(taxonomy: PsicTaxonomy, evidence: Evidence) -> str | None:
    roots = mapping_roots(taxonomy, evidence.mapping)
    if not roots:
        return None
    if len(roots) == 1:
        return roots[0]
    return taxonomy.lca(roots)


def _independent_sibling_parent(
    taxonomy: PsicTaxonomy,
    group_roots: list[list[str]],
) -> str | None:
    if len(group_roots) < 2 or any(len(roots) != 1 for roots in group_roots):
        return None
    codes = list(dict.fromkeys(roots[0] for roots in group_roots))
    if len(codes) < 2:
        return None
    deepest_depth = max(taxonomy.depth(code) for code in codes)
    deepest = [code for code in codes if taxonomy.depth(code) == deepest_depth]
    if len(deepest) < 2:
        return None
    parents = {taxonomy.parent(code) for code in deepest}
    if len(parents) != 1:
        return None
    parent = next(iter(parents))
    if parent is None or parent not in taxonomy.nodes or taxonomy.depth(parent) < 2:
        return None
    ancestors = set(taxonomy.ancestors(parent))
    for code in codes:
        if code in deepest:
            continue
        if code != parent and code not in ancestors:
            return None
    return parent


def activity_nonactivity_conflict(evidence: list[Evidence]) -> bool:
    coded_kinds = {MappingKind.EXACT, MappingKind.SUBTREE, MappingKind.UNION}
    coded_groups = {
        item.dependency_group
        for item in evidence
        if item.mapping is not None and item.mapping.mapping_kind in coded_kinds
    }
    nonactivity_groups = {
        item.dependency_group
        for item in evidence
        if item.mapping is not None and item.mapping.mapping_kind == MappingKind.NOT_ACTIVITY
    }
    return any(left != right for left in coded_groups for right in nonactivity_groups)


def fuse(taxonomy: PsicTaxonomy, evidence: list[Evidence]) -> FusionDecision:
    mapped = [
        item
        for item in evidence
        if item.mapping is not None
        and item.mapping.mapping_kind not in {MappingKind.NOT_ACTIVITY, MappingKind.UNCODEABLE}
    ]
    if not mapped:
        return FusionDecision(FusionStatus.EMPTY, None)

    evidence_sources = list(dict.fromkeys(item.source for item in mapped))
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for item in mapped:
        groups[item.dependency_group].append(item)

    group_roots: list[list[str]] = []
    flags: list[str] = []
    all_codes: list[str] = []

    for dependency_group, items in groups.items():
        constraints = [mapping_roots(taxonomy, item.mapping) for item in items]
        constraints = [roots for roots in constraints if roots]
        if not constraints:
            continue
        current = list(constraints[0])
        for roots in constraints[1:]:
            intersection = intersect_subtrees(taxonomy, current, roots)
            if intersection:
                current = intersection
            else:
                current = _union_subtrees(taxonomy, current, roots)
                flags.append(f"DEPENDENT_CONFLICT:{dependency_group}")
        group_roots.append(current)
        for item in items:
            if item.mapping is not None:
                all_codes.extend(item.mapping.codes)

    if not group_roots:
        return FusionDecision(FusionStatus.EMPTY, None)

    sibling_parent = _independent_sibling_parent(taxonomy, group_roots)
    if sibling_parent is not None:
        return FusionDecision(
            FusionStatus.INTERSECT,
            sibling_parent,
            candidate_codes=sorted(set(all_codes), key=lambda c: (taxonomy.depth(c), c)),
            evidence_sources=evidence_sources,
            independent_groups=len(groups),
            flags=flags + ["INDEPENDENT_SIBLING_BACKOFF"],
        )

    current = list(group_roots[0])
    for roots in group_roots[1:]:
        intersection = intersect_subtrees(taxonomy, current, roots)
        if not intersection:
            return FusionDecision(
                FusionStatus.CONFLICT,
                None,
                candidate_codes=sorted(set(all_codes), key=lambda c: (taxonomy.depth(c), c)),
                evidence_sources=evidence_sources,
                independent_groups=len(groups),
                flags=flags,
            )
        current = intersection

    code = current[0] if len(current) == 1 else taxonomy.lca(current)
    if code is None:
        return FusionDecision(
            FusionStatus.UNION,
            None,
            candidate_codes=sorted(set(all_codes)),
            evidence_sources=evidence_sources,
            independent_groups=len(groups),
            flags=flags + ["NO_COMMON_ANCESTOR"],
        )

    reps = [rep for rep in (_representative(taxonomy, item) for item in mapped) if rep]
    if len(mapped) == 1:
        status = (
            FusionStatus.UNION
            if mapped[0].mapping and mapped[0].mapping.mapping_kind == MappingKind.UNION
            else FusionStatus.SINGLE
        )
    else:
        ordered = sorted((rep for rep in reps if rep in taxonomy.nodes), key=taxonomy.depth)
        nested = bool(ordered) and all(
            ordered[i] in taxonomy.ancestors(ordered[i + 1])
            for i in range(len(ordered) - 1)
        )
        varied = len({taxonomy.depth(rep) for rep in ordered}) > 1
        status = FusionStatus.NESTED if nested and varied else FusionStatus.INTERSECT

    return FusionDecision(
        status,
        code,
        candidate_codes=sorted(set(all_codes)),
        evidence_sources=evidence_sources,
        independent_groups=len(groups),
        flags=flags,
    )

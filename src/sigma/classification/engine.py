from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pandas as pd

from .crosswalk import CrosswalkIndex
from .decision_cache import ClassificationDecisionCache
from .fusion import activity_nonactivity_conflict, fuse, intersect_subtrees, mapping_roots
from .normalize import clean_source_text
from .reference import PsicTaxonomy, load_builtin_psic_taxonomy
from .retrieval import PsicRetriever
from .source_rules import AutoMapping, automatic_mapping
from .traversal import HierarchicalPsicTraverser
from .types import Evidence, FusionStatus, MappingKind, PsicDecision

_SOURCE_NAMES = ("osm", "overture")
_RESOLVED = {FusionStatus.SINGLE, FusionStatus.NESTED, FusionStatus.INTERSECT}
_LLM_ELIGIBLE = {"CANDIDATES_ONLY", "UNION", "CONFLICT", "UNRESOLVED"}


def _text(value: object) -> str | None:
    return clean_source_text(value)


def _split_combined_category(value: object) -> tuple[str | None, str | None]:
    text = _text(value)
    if not text:
        return None, None
    osm_parts: list[str] = []
    overture_parts: list[str] = []
    for part in (piece.strip() for piece in text.split(" | ")):
        if not part:
            continue
        if "=" in part:
            osm_parts.append(part)
        else:
            overture_parts.append(part)
    return (
        " | ".join(osm_parts) or None,
        " | ".join(overture_parts) or None,
    )


def _row_source_payloads(
    row: pd.Series | dict[str, Any],
) -> tuple[list[dict[str, str | None]], list[str]]:
    payloads: list[dict[str, str | None]] = []
    flags: list[str] = []
    for source in _SOURCE_NAMES:
        name = _text(row.get(f"{source}_name"))
        category = _text(row.get(f"{source}_category"))
        if name or category:
            payloads.append({"source": source, "name": name, "category": category})

    if payloads:
        return payloads, flags

    # Compatibility with Stage-2-era canonical outputs. New reconciled outputs preserve
    # source-specific semantics directly, so this branch is only for already-produced data.
    sources = {
        part.strip().casefold()
        for part in str(row.get("sources") or "").split("|")
        if part.strip()
    }
    canonical_name = _text(row.get("name"))
    canonical_category = _text(row.get("category"))

    if sources == {"osm"}:
        payloads.append({"source": "osm", "name": canonical_name, "category": canonical_category})
        flags.append("LEGACY_SOURCE_FIELDS_INFERRED")
    elif sources == {"overture"}:
        payloads.append(
            {"source": "overture", "name": canonical_name, "category": canonical_category}
        )
        flags.append("LEGACY_SOURCE_FIELDS_INFERRED")
    elif {"osm", "overture"}.issubset(sources):
        osm_category, overture_category = _split_combined_category(canonical_category)
        if osm_category:
            payloads.append({"source": "osm", "name": canonical_name, "category": osm_category})
        if overture_category:
            payloads.append(
                {"source": "overture", "name": canonical_name, "category": overture_category}
            )
        if payloads:
            flags.append("LEGACY_SOURCE_FIELDS_PARTIALLY_RECOVERED")
        else:
            flags.append("LEGACY_MERGED_SEMANTICS_UNRECOVERABLE")
    return payloads, flags


def _evidence_text(row: pd.Series | dict[str, Any]) -> str:
    payloads, _ = _row_source_payloads(row)
    parts: list[str] = []
    for payload in payloads:
        source = str(payload["source"]).upper()
        if payload.get("name"):
            parts.append(f"{source} name: {payload['name']}")
        if payload.get("category"):
            parts.append(f"{source} category: {payload['category']}")
    if not parts:
        name = _text(row.get("name"))
        if name:
            parts.append(f"canonical name: {name}")
    return "\n".join(parts)


def _as_float(value: object) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _entity_match_flags(row: pd.Series | dict[str, Any], semantic_conflict: bool) -> list[str]:
    if not semantic_conflict:
        return []
    flags: list[str] = []
    distance = _as_float(row.get("match_distance_m"))
    score = _as_float(row.get("match_name_score"))
    if distance is not None and distance >= 80.0:
        flags.append("ENTITY_MATCH_SUSPECT_DISTANCE")
    if score is not None and score < 0.85:
        flags.append("ENTITY_MATCH_SUSPECT_LOW_MATCH_SCORE")
    return flags


class PsicClassifier:
    """Deterministic PSIC Rev. 5 classifier with hierarchical semantic retrieval."""

    def __init__(
        self,
        taxonomy: PsicTaxonomy | None = None,
        crosswalk: CrosswalkIndex | None = None,
        *,
        top_n: int = 5,
        min_score: float = 0.45,
        min_margin: float = 0.12,
        traverser: HierarchicalPsicTraverser | None = None,
        decision_cache: ClassificationDecisionCache | None = None,
        llm_retrieval_top_n: int = 20,
    ):
        self.taxonomy = taxonomy or load_builtin_psic_taxonomy()
        if crosswalk is not None:
            self.crosswalk = crosswalk
        elif getattr(self.taxonomy, "origin", "custom") == "builtin:psic_rev5":
            self.crosswalk = CrosswalkIndex.load_builtin()
        else:
            # Custom taxonomies may still use semantic retrieval, but must never
            # inherit the bundled Rev. 5 source crosswalk implicitly.
            self.crosswalk = CrosswalkIndex([])
        self.retriever = PsicRetriever(self.taxonomy)
        self.top_n = int(top_n)
        self.min_score = float(min_score)
        self.min_margin = float(min_margin)
        self.traverser = traverser
        self.decision_cache = decision_cache
        self.llm_retrieval_top_n = max(1, int(llm_retrieval_top_n))
        self._auto_cache: dict[tuple[str, str], AutoMapping] = {}
        self._validate_crosswalk()

    def _validate_crosswalk(self) -> None:
        problems: list[str] = []
        for rule in self.crosswalk.entries:
            unknown = [code for code in rule.codes if code not in self.taxonomy.nodes]
            if unknown:
                problems.append(
                    f"{rule.source}:{rule.source_value!r} references unknown PSIC codes {unknown}"
                )
        if problems:
            raise ValueError("invalid PSIC crosswalk:\n- " + "\n- ".join(problems))

    def _name_precedence(self, rules: list) -> tuple[list, bool]:
        if len(rules) < 2:
            return rules, False
        category = [r for r in rules if r.source_field.value == "category"]
        name = [r for r in rules if r.source_field.value == "name"]
        if not category or not name:
            return rules, False
        category_rule = category[0]
        name_rule = name[0]
        coded = {MappingKind.EXACT, MappingKind.SUBTREE, MappingKind.UNION}
        if (
            name_rule.mapping_kind == MappingKind.NOT_ACTIVITY
            and category_rule.mapping_kind in coded
        ) or (
            name_rule.mapping_kind in coded
            and category_rule.mapping_kind == MappingKind.NOT_ACTIVITY
        ):
            return category, True
        category_roots = mapping_roots(self.taxonomy, category_rule)
        name_roots = mapping_roots(self.taxonomy, name_rule)
        if not category_roots or not name_roots:
            return rules, False
        if intersect_subtrees(self.taxonomy, category_roots, name_roots):
            return rules, False
        return category, True

    def _automatic(self, source: str, category: str) -> AutoMapping:
        key = (source, category)
        cached = self._auto_cache.get(key)
        if cached is not None:
            return cached
        result = automatic_mapping(
            self.taxonomy,
            self.retriever,
            source,
            category,
            top_n=self.top_n,
            min_score=self.min_score,
            min_margin=self.min_margin,
        )
        self._auto_cache[key] = result
        return result

    def _map_source(
        self,
        source: str,
        name: str | None,
        category: str | None,
    ) -> tuple[list[Evidence], list[str]]:
        flags: list[str] = []
        # Overture records can carry a primary category plus alternates joined by the
        # acquisition normalizer. Treat each category as dependent evidence from the
        # same source rather than flattening the whole list into one lexical query.
        if source == "overture" and category:
            categories = [part.strip() for part in category.split(" | ") if part.strip()]
        else:
            categories = [category] if category else []

        if not categories:
            matches = self.crosswalk.matches(source, category=None, name=name)
            if matches.ambiguities:
                flags.extend(f"CROSSWALK_AMBIGUOUS:{item}" for item in matches.ambiguities)
            if matches.entries:
                chosen, overridden = self._name_precedence(list(matches.entries))
                if overridden:
                    flags.append("CROSSWALK_CATEGORY_RULE_OVERRULED_NAME")
                return (
                    [
                        Evidence(
                            source=source,
                            category=None,
                            name=name,
                            dependency_group=source,
                            mapping=rule,
                            mapping_origin="reviewed_crosswalk",
                            rule=f"crosswalk:{rule.source_field.value}:{rule.match_type}",
                        )
                        for rule in chosen
                    ],
                    flags,
                )
            if name:
                hits = self.retriever.search_hierarchical(name, top_n=self.top_n)
                return (
                    [
                        Evidence(
                            source=source,
                            category=None,
                            name=name,
                            dependency_group=source,
                            candidate_codes=tuple(hit.code for hit in hits),
                            candidate_scores=tuple(hit.score for hit in hits),
                            query_text=name,
                            rule="name_only_candidate_retrieval",
                        )
                    ],
                    flags + ["NAME_ONLY_NOT_AUTOPROMOTED"],
                )
            return [], flags

        out: list[Evidence] = []
        for index, category_value in enumerate(categories):
            matches = self.crosswalk.matches(
                source,
                category=category_value,
                name=name if index == 0 else None,
            )
            if matches.ambiguities:
                flags.extend(f"CROSSWALK_AMBIGUOUS:{item}" for item in matches.ambiguities)
            if matches.entries:
                chosen, overridden = self._name_precedence(list(matches.entries))
                if overridden:
                    flags.append("CROSSWALK_CATEGORY_RULE_OVERRULED_NAME")
                out.extend(
                    Evidence(
                        source=source,
                        category=category_value,
                        name=name,
                        dependency_group=source,
                        mapping=rule,
                        mapping_origin="reviewed_crosswalk",
                        rule=f"crosswalk:{rule.source_field.value}:{rule.match_type}",
                    )
                    for rule in chosen
                )
                continue

            auto = self._automatic(source, category_value)
            out.append(
                Evidence(
                    source=source,
                    category=category_value,
                    name=name,
                    dependency_group=source,
                    mapping=auto.mapping,
                    mapping_origin=auto.reason,
                    candidate_codes=auto.candidate_codes,
                    candidate_scores=auto.candidate_scores,
                    query_text=auto.query_text,
                    rule=auto.rule,
                )
            )
        return out, flags

    def _classify_row_deterministic(
        self, row: pd.Series | dict[str, Any]
    ) -> PsicDecision:
        payloads, flags = _row_source_payloads(row)
        evidence: list[Evidence] = []
        for payload in payloads:
            mapped, source_flags = self._map_source(
                str(payload["source"]),
                payload["name"],
                payload["category"],
            )
            evidence.extend(mapped)
            flags.extend(source_flags)

        candidate_codes = list(
            dict.fromkeys(code for item in evidence for code in item.candidate_codes)
        )
        retrieval_scores = [score for item in evidence for score in item.candidate_scores]
        retrieval_score = max(retrieval_scores) if retrieval_scores else None
        evidence_sources = list(dict.fromkeys(item.source for item in evidence))
        rules = list(dict.fromkeys(item.rule for item in evidence if item.rule))
        queries = list(dict.fromkeys(item.query_text for item in evidence if item.query_text))

        if not evidence:
            return PsicDecision(
                code=None,
                level=None,
                title=None,
                status="NO_SEMANTIC_EVIDENCE",
                method="none",
                flags=sorted(set(flags)),
            )

        if activity_nonactivity_conflict(evidence):
            match_flags = _entity_match_flags(row, True)
            return PsicDecision(
                code=None,
                level=None,
                title=None,
                status="REVIEW_ENTITY_MATCH" if match_flags else "CONFLICT",
                method="fusion",
                candidate_codes=candidate_codes,
                evidence_sources=evidence_sources,
                flags=sorted(
                    set(flags + match_flags + ["ACTIVITY_NON_ACTIVITY_CONFLICT"])
                ),
                retrieval_score=retrieval_score,
                rule=" | ".join(rules),
                query_text=" || ".join(queries),
            )

        coded = [
            item
            for item in evidence
            if item.mapping is not None
            and item.mapping.mapping_kind
            in {MappingKind.EXACT, MappingKind.SUBTREE, MappingKind.UNION}
        ]
        nonactivity = [
            item
            for item in evidence
            if item.mapping is not None and item.mapping.mapping_kind == MappingKind.NOT_ACTIVITY
        ]
        uncodeable = [
            item
            for item in evidence
            if item.mapping is not None and item.mapping.mapping_kind == MappingKind.UNCODEABLE
        ]

        informative = [
            item
            for item in evidence
            if item.mapping is not None and item.mapping.mapping_kind != MappingKind.UNCODEABLE
        ]
        if not coded and nonactivity and all(
            item.mapping is not None and item.mapping.mapping_kind == MappingKind.NOT_ACTIVITY
            for item in informative
        ):
            return PsicDecision(
                code=None,
                level=None,
                title=None,
                status="NOT_PSIC_ACTIVITY",
                method="source_policy",
                candidate_codes=candidate_codes,
                evidence_sources=list(dict.fromkeys(item.source for item in nonactivity)),
                flags=sorted(set(flags)),
                retrieval_score=retrieval_score,
                rule=" | ".join(rules),
                query_text=" || ".join(queries),
            )

        if not coded and uncodeable and not nonactivity:
            return PsicDecision(
                code=None,
                level=None,
                title=None,
                status="UNCODEABLE",
                method="source_policy",
                candidate_codes=candidate_codes,
                evidence_sources=list(dict.fromkeys(item.source for item in uncodeable)),
                flags=sorted(set(flags)),
                retrieval_score=retrieval_score,
                rule=" | ".join(rules),
                query_text=" || ".join(queries),
            )

        fusion = fuse(self.taxonomy, evidence)
        flags.extend(fusion.flags)
        candidate_codes = list(dict.fromkeys(fusion.candidate_codes + candidate_codes))
        evidence_sources = list(dict.fromkeys(fusion.evidence_sources + evidence_sources))

        if fusion.status == FusionStatus.CONFLICT:
            match_flags = _entity_match_flags(row, True)
            if match_flags:
                flags.extend(match_flags)
                return PsicDecision(
                    code=None,
                    level=None,
                    title=None,
                    status="REVIEW_ENTITY_MATCH",
                    method="fusion",
                    candidate_codes=candidate_codes,
                    evidence_sources=evidence_sources,
                    flags=sorted(set(flags)),
                    retrieval_score=retrieval_score,
                    rule=" | ".join(rules),
                    query_text=" || ".join(queries),
                    audit={
                        "fusion_status": fusion.status.value,
                        "fusion_candidate_codes": list(fusion.candidate_codes),
                        "independent_groups": fusion.independent_groups,
                        "taxonomy_fingerprint": self.taxonomy.fingerprint,
                    },
                )

        if fusion.code is not None and fusion.status in _RESOLVED:
            node = self.taxonomy.get(fusion.code)
            origins = {item.mapping_origin for item in coded if item.mapping_origin}
            if len(coded) > 1:
                method = "fusion"
            elif origins == {"reviewed_crosswalk"}:
                method = "crosswalk"
            elif "trusted_source_floor" in origins:
                method = "trusted_floor"
            elif "semantic_refinement" in origins:
                method = "semantic_refinement"
            else:
                method = "source_rule"
            return PsicDecision(
                code=fusion.code,
                level=node.level,
                title=node.title,
                status=fusion.status.value,
                method=method,
                candidate_codes=candidate_codes,
                evidence_sources=evidence_sources,
                flags=sorted(set(flags)),
                retrieval_score=retrieval_score,
                rule=" | ".join(rules),
                query_text=" || ".join(queries),
                audit={
                    "independent_groups": fusion.independent_groups,
                    "taxonomy_fingerprint": self.taxonomy.fingerprint,
                },
            )

        status = fusion.status.value if fusion.status != FusionStatus.EMPTY else "CANDIDATES_ONLY"
        if fusion.status == FusionStatus.EMPTY and not candidate_codes:
            status = "UNRESOLVED"
        return PsicDecision(
            code=None,
            level=None,
            title=None,
            status=status,
            method="retrieval" if candidate_codes else "source_policy",
            candidate_codes=candidate_codes,
            evidence_sources=evidence_sources,
            flags=sorted(set(flags)),
            retrieval_score=retrieval_score,
            rule=" | ".join(rules),
            query_text=" || ".join(queries),
            audit={
                "fusion_status": fusion.status.value,
                "fusion_candidate_codes": list(fusion.candidate_codes),
                "independent_groups": fusion.independent_groups,
                "taxonomy_fingerprint": self.taxonomy.fingerprint,
            },
        )

    @staticmethod
    def _needs_llm(decision: PsicDecision) -> bool:
        if "ACTIVITY_NON_ACTIVITY_CONFLICT" in decision.flags:
            return False
        return decision.code is None and decision.status in _LLM_ELIGIBLE

    def _resolve_with_llm(
        self,
        row: pd.Series | dict[str, Any],
        decision: PsicDecision,
    ) -> PsicDecision:
        if self.traverser is None or not self._needs_llm(decision):
            return decision

        text = _evidence_text(row)
        if not text.strip():
            decision.flags = sorted(set(decision.flags + ["LLM_NO_EVIDENCE_TEXT"]))
            return decision

        restricted_candidates = decision.candidate_codes
        if decision.status in {"CONFLICT", "UNION"}:
            fusion_candidates = decision.audit.get("fusion_candidate_codes")
            if isinstance(fusion_candidates, list) and fusion_candidates:
                restricted_candidates = [str(code) for code in fusion_candidates]
        restriction = [
            code for code in restricted_candidates if code in self.taxonomy.nodes
        ]
        retrieved: list[dict[str, object]] = []
        if not restriction:
            hits = self.retriever.search_hierarchical(
                text, top_n=self.llm_retrieval_top_n
            )
            restriction = [hit.code for hit in hits]
            retrieved = [
                {"code": hit.code, "score": round(hit.score, 6)} for hit in hits
            ]
        if not restriction:
            decision.flags = sorted(
                set(decision.flags + ["LLM_NO_RETRIEVAL_CANDIDATES"])
            )
            return decision

        cache_key = ClassificationDecisionCache.key(
            "psic",
            "rev5",
            self.taxonomy.fingerprint,
            self.traverser.backend.cache_identity,
            self.traverser.prompt_fingerprint,
            text,
            restriction,
            self.traverser.passes,
        )
        cached = self.decision_cache.get(cache_key) if self.decision_cache else None
        if cached is not None:
            code = cached.get("code")
            agreement = cached.get("agreement")
            audit = dict(cached.get("audit", {}))
            traversal_flags = list(cached.get("flags", []))
            audit["cache_hit"] = True
        else:
            traversal = self.traverser.classify(text, restriction)
            code = traversal.code
            agreement = traversal.agreement
            traversal_flags = list(traversal.flags)
            audit = {
                "path": traversal.path,
                "reason": traversal.reason,
                "decisions": traversal.decisions,
                "restriction": restriction,
                "retrieval": retrieved,
                "cache_hit": False,
            }
            if self.decision_cache is not None:
                self.decision_cache.put(
                    cache_key,
                    {
                        "code": code,
                        "agreement": agreement,
                        "audit": audit,
                        "flags": traversal_flags,
                    },
                )

        agreement_value = float(agreement) if agreement is not None else 0.0
        combined_audit = dict(decision.audit)
        combined_audit["llm_traversal"] = audit
        combined_flags = sorted(set(decision.flags + traversal_flags))

        if code is None or str(code) not in self.taxonomy.nodes:
            return PsicDecision(
                code=None,
                level=None,
                title=None,
                status="REVIEW",
                method="llm",
                candidate_codes=decision.candidate_codes,
                evidence_sources=decision.evidence_sources,
                flags=combined_flags,
                retrieval_score=decision.retrieval_score,
                rule=decision.rule,
                query_text=decision.query_text,
                traversal_agreement=agreement_value,
                model=self.traverser.backend.model_name,
                audit=combined_audit,
            )

        node = self.taxonomy.get(str(code))
        return PsicDecision(
            code=node.code,
            level=node.level,
            title=node.title,
            status="LLM_PARTIAL" if self.taxonomy.has_children(node.code) else "LLM_FULL",
            method="llm",
            candidate_codes=decision.candidate_codes or restriction,
            evidence_sources=decision.evidence_sources,
            flags=combined_flags,
            retrieval_score=decision.retrieval_score,
            rule=decision.rule,
            query_text=decision.query_text,
            traversal_agreement=agreement_value,
            model=self.traverser.backend.model_name,
            audit=combined_audit,
        )

    def classify_row(self, row: pd.Series | dict[str, Any]) -> PsicDecision:
        decision = self._classify_row_deterministic(row)
        return self._resolve_with_llm(row, decision)

    def classify_frame(
        self,
        frame: pd.DataFrame,
        *,
        progress: Callable[[int, int], None] | None = None,
        progress_every: int = 500,
        llm_max_rows: int | None = None,
    ) -> pd.DataFrame:
        result = frame.copy()
        rows: list[dict[str, object]] = []
        total = len(result)
        interval = max(1, int(progress_every))
        if progress is not None:
            progress(0, total)
        llm_attempted = 0
        for position, (_, row) in enumerate(result.iterrows(), start=1):
            decision = self._classify_row_deterministic(row)
            if self.traverser is not None and self._needs_llm(decision):
                if llm_max_rows is None or llm_attempted < llm_max_rows:
                    llm_attempted += 1
                    decision = self._resolve_with_llm(row, decision)
                else:
                    decision.flags = sorted(set(decision.flags + ["LLM_LIMIT_SKIPPED"]))
            rows.append(
                {
                    "psic_code": decision.code or "",
                    "psic_level": decision.level or "",
                    "psic_title": decision.title or "",
                    "psic_status": decision.status,
                    "psic_method": decision.method,
                    "psic_candidate_codes": "|".join(decision.candidate_codes),
                    "psic_evidence_sources": "|".join(decision.evidence_sources),
                    "psic_flags": "|".join(decision.flags),
                    "psic_retrieval_score": decision.retrieval_score,
                    "psic_rule": decision.rule,
                    "psic_query": decision.query_text,
                    "psic_traversal_agreement": decision.traversal_agreement,
                    "psic_model": decision.model,
                    "psic_audit": json.dumps(
                        decision.audit, ensure_ascii=False, separators=(",", ":")
                    )
                    if decision.audit
                    else "",
                }
            )
            if progress is not None and (position % interval == 0 or position == total):
                progress(position, total)
        # Explicit columns preserve the classifier schema even when ``frame`` has zero rows.
        tagged = pd.DataFrame(rows, index=result.index, columns=[
            "psic_code",
            "psic_level",
            "psic_title",
            "psic_status",
            "psic_method",
            "psic_candidate_codes",
            "psic_evidence_sources",
            "psic_flags",
            "psic_retrieval_score",
            "psic_rule",
            "psic_query",
            "psic_traversal_agreement",
            "psic_model",
            "psic_audit",
        ])
        for column in tagged.columns:
            result[column] = tagged[column]
        return result


def classify_psic(frame: pd.DataFrame, **kwargs: object) -> pd.DataFrame:
    return PsicClassifier(**kwargs).classify_frame(frame)

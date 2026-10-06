from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .reference import PSIC_LEVELS, PsicTaxonomy


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    code: str
    score: float


class PsicRetriever:
    """Local hierarchical lexical retrieval over the bundled PSIC taxonomy."""

    def __init__(self, taxonomy: PsicTaxonomy):
        self.taxonomy = taxonomy
        self.codes = list(taxonomy.nodes)
        self._index = {code: index for index, code in enumerate(self.codes)}
        corpus = [
            taxonomy.get(code).retrieval_text or taxonomy.get(code).title
            for code in self.codes
        ]
        self.word = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
        )
        self.char = TfidfVectorizer(
            lowercase=True,
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=1,
            sublinear_tf=True,
        )
        self.word_matrix = self.word.fit_transform(corpus)
        self.char_matrix = self.char.fit_transform(corpus)
        coarse_levels = set(PSIC_LEVELS[:2])
        self._coarse_codes = frozenset(
            code for code, node in taxonomy.nodes.items() if node.level in coarse_levels
        )
        self._closure_cache: dict[tuple[str, ...], frozenset[str]] = {}

    def _scores(self, queries: list[str]) -> np.ndarray:
        if not queries:
            return np.empty((len(self.codes), 0), dtype=float)
        q_word = self.word.transform(queries)
        q_char = self.char.transform(queries)
        scores = (self.word_matrix @ q_word.T).toarray()
        scores *= 0.6
        scores += 0.4 * (self.char_matrix @ q_char.T).toarray()
        return scores

    def _rank(
        self,
        scores: np.ndarray,
        *,
        top_n: int,
        allowed_codes: set[str] | frozenset[str] | None = None,
    ) -> list[RetrievalHit]:
        if top_n < 1:
            return []
        if allowed_codes is None:
            candidates = np.flatnonzero(np.isfinite(scores) & (scores > 0.0))
        else:
            allowed_idx = np.fromiter(
                sorted(self._index[c] for c in allowed_codes if c in self._index),
                dtype=np.intp,
            )
            if allowed_idx.size == 0:
                return []
            allowed_scores = scores[allowed_idx]
            candidates = allowed_idx[np.isfinite(allowed_scores) & (allowed_scores > 0.0)]
        if candidates.size == 0:
            return []
        ranked = candidates[np.argsort(scores[candidates])[::-1]]
        return [RetrievalHit(self.codes[i], float(scores[i])) for i in ranked[:top_n]]

    def codes_under(self, roots: tuple[str, ...] | list[str] | set[str]) -> set[str]:
        key = tuple(sorted({str(root) for root in roots}))
        cached = self._closure_cache.get(key)
        if cached is not None:
            return set(cached)
        allowed: set[str] = set()
        for code in key:
            if code not in self.taxonomy.nodes:
                continue
            allowed.add(code)
            allowed.update(self.taxonomy.descendants(code))
        frozen = frozenset(allowed)
        self._closure_cache[key] = frozen
        return set(frozen)

    def _hierarchical(
        self,
        scores: np.ndarray,
        *,
        top_n: int,
        branch_roots: tuple[str, ...] = (),
        beam_width: int = 4,
    ) -> list[RetrievalHit]:
        if branch_roots:
            allowed = self.codes_under(branch_roots)
            if allowed:
                return self._rank(scores, top_n=top_n, allowed_codes=allowed)

        coarse = self._rank(
            scores,
            top_n=max(1, beam_width),
            allowed_codes=self._coarse_codes,
        )
        if not coarse:
            return self._rank(scores, top_n=top_n)

        allowed: set[str] = set()
        for hit in coarse:
            allowed.update(self.codes_under((hit.code,)))
        return self._rank(scores, top_n=top_n, allowed_codes=allowed)

    def search_hierarchical(
        self,
        query: str,
        *,
        top_n: int = 20,
        branch_roots: tuple[str, ...] = (),
        beam_width: int = 4,
    ) -> list[RetrievalHit]:
        query = str(query).strip()
        if not query:
            return []
        return self._hierarchical(
            self._scores([query])[:, 0],
            top_n=top_n,
            branch_roots=branch_roots,
            beam_width=beam_width,
        )

    def search_many(
        self,
        requests: list[tuple[str, tuple[str, ...]]],
        *,
        top_n: int = 20,
        beam_width: int = 4,
        batch_size: int = 256,
    ) -> list[list[RetrievalHit]]:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if not requests:
            return []

        keys = [(str(q).strip(), tuple(roots)) for q, roots in requests]
        unique_queries = list(dict.fromkeys(q for q, _ in keys if q))
        scored: dict[str, np.ndarray] = {}
        for start in range(0, len(unique_queries), batch_size):
            batch = unique_queries[start : start + batch_size]
            matrix = self._scores(batch)
            for column, query in enumerate(batch):
                scored[query] = matrix[:, column]

        out: list[list[RetrievalHit]] = []
        for query, roots in keys:
            if not query:
                out.append([])
            else:
                out.append(
                    self._hierarchical(
                        scored[query],
                        top_n=top_n,
                        branch_roots=roots,
                        beam_width=beam_width,
                    )
                )
        return out

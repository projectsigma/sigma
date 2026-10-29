# Hierarchical economy: IO240, IO80 and IO16 sectors per area

The PSA 2018 input-output tables exist at three nested levels: 240, 80 and 16 industries. Each IO240 industry belongs to one IO80 industry, and each IO80 industry to one IO16 industry. The hierarchical economy uses the finest level where an area's places support it and a coarser level elsewhere, so that every sector used in clustering has enough places and the national table is still used in full.

This page describes, in order: how a place gets IO tags, how the per-area sectors are chosen, how a place is assigned to one sector, and what the statuses mean.

## 1. From a place to IO tags

A place first receives a PSIC Rev. 5 code (see the places page). The PSIC code is then mapped to sets of candidate IO industries at each level:

1. **Bridge and concordance.** The Rev. 5 code goes up its ancestors until it reaches a row of the Rev. 5 → PSIC 2019 bridge (group, division or section). The PSIC 2019 code is mapped through the PSIC 2019 → PSA 2018 IO concordance. These two tables stop at PSIC groups.
2. **Refinement below the group.** `io/psic_rev5_io240_refinement.csv` lists Rev. 5 classes and subclasses whose title names one IO240 industry (or a smaller set) inside their group's candidate set. Example: subclass 01121 "Growing of rice in irrigated lowland" is in group 011, which maps to 11 IO240 industries; the refinement narrows it to IO240 001 Palay. A refinement row may only narrow the set; a row that would add an industry is reported as `not_applied`. The IO80 and IO16 sets are then the parents of the remaining IO240 industries, from `io/io240_parents.csv`.
3. **Union decisions.** A source category can name several PSIC subtrees (for example Overture `lodging` = hotels, other short-term accommodation, camping grounds or other accommodation). The PSIC decision then has status `UNION` and no single PSIC code. Its IO candidates are the union of the members' candidates, so they are never wider than the members justify. If any member has no IO correspondence, nothing is mapped (`UNMAPPED_UNION_PARTIAL`).
4. **A tag at each level.** A level receives a code only when its candidate set has one member. Three kinds of evidence can choose inside a candidate set without leaving it:
   - same-name evidence from other places in the run, for the IO80 pairs (55, 56) and (66, 67);
   - direct OpenStreetMap tag rules for IO80 (`tagging/compatibility/rules.yml`). They match parsed `key=value` tags, never names or substrings. Primary tags decide before the auxiliary keys `cuisine`, `brand` and `operator`. Tags that point to different IO80 industries make the evidence a conflict.
   - ownership evidence for education (IO80 74 public / 75 private) and health (76 / 77), from names such as "National High School" or "Rural Health Unit" and, for a few clinic categories, from the category. It abstains when evidence points both ways or is absent, and does not treat generic terms such as "elementary school", "clinic" or "health center" as ownership proof. Results are inferred, **not** registry-verified.
5. **Consistency.** The three tags must nest. If they do not, the tag from the stronger source is kept (PSIC outranks direct rules): a finer PSIC tag replaces a weaker coarser one by its parent (`DERIVED_FROM_IO240` / `DERIVED_FROM_IO80`); otherwise the finer tag is cleared (`LEVEL_CONFLICT`).

`io_mapping_provisional` is `true` when the mapping depends on a draft bridge row or a draft refinement row, that is, on a link that is not from a published concordance.

## 2. Which sectors an area uses

An IO240 industry is kept as its own sector when at least `min_places` places carry it as an exact tag. Inside an IO80 parent with kept children, the other children form `IO80 · Other`; an IO80 parent without kept children is kept whole when its places reach `min_places`; the remaining industries of an IO16 parent form `IO16 · Other` (or the whole IO16 parent). Every IO240 industry belongs to exactly one sector, and transactions and gross output are aggregated as $M Z M^\top$ and $M x$, so national totals are conserved.

## 3. Assigning a place to one sector

A place with an exact IO240 tag joins the sector that holds that industry.

A **coarse place** has only an IO80 or IO16 tag. It carries its own IO240 candidate set: the candidates from tagging, restricted to the industries under its tag (all industries under the tag **only when no candidates were supplied**). A nonempty candidate set disjoint from the parent tag is a conflict: the place is unassigned for review, not silently imputed into the parent. Two policies exist:

- `contain` (default **for newly configured profiles**). The place joins a sector only when one sector contains all of its candidates. A place whose candidates fall into several sectors of a split parent *straddles* the split. A parent is kept whole instead of split when its straddling places are more than `max_straddle_share` (default 0.25) of its places (straddling plus exactly assigned); IO80 parents are checked first, then IO16 parents. Places that still straddle are left unassigned. No place is assigned to a sector that excludes one of its candidates.
- `residual` (legacy profiles retain this policy until explicitly reconfigured). A coarse place that does not fit one sector is assigned to the `Other` residual of its parent. The residual is made of the industries that were *not* observed often enough to be kept, so this rule places coarse places in the least supported industries (for example bakeries tagged only as "trade" into a residual whose only member is wholesale trade). It is kept only to reproduce earlier builds.

`max_straddle_share` trades sector detail against coverage. A low value keeps parents whole more often (fewer, coarser sectors; fewer unassigned places). A high value keeps more splits but leaves more coarse places unassigned. With `max_straddle_share = 0.5`, a parent is kept whole only when its straddling places outnumber its exactly assigned places.

## 4. Statuses (`economy_status`)

| Status | Meaning |
|---|---|
| `IO240` | exact IO240 tag; its industry is a sector |
| `IO240_FOLDED` | exact IO240 tag; its industry was folded into a coarser sector |
| `IO80`, `IO80_SINGLE_MEMBER`, `IO80_FOLDED`, `IO16`, `IO16_SINGLE_MEMBER` | coarse tag; one sector holds every industry under the tag |
| `IO80_CANDIDATES`, `IO16_CANDIDATES` | coarse tag; one sector holds every candidate of the place |
| `UNASSIGNED_IO80_STRADDLES`, `UNASSIGNED_IO16_STRADDLES` | coarse place whose candidates fall into several sectors (`contain`) |
| `IO80_RESIDUAL`, `IO16_RESIDUAL` | assigned to the residual by convention (`residual` only) |
| `UNASSIGNED_IO80_NO_RESIDUAL`, `UNASSIGNED_IO16_NO_RESIDUAL` | no residual exists (`residual` only) |
| `UNASSIGNED_CANDIDATE_CONFLICT` | supplied IO240 candidates contradict the IO80/IO16 singleton; cannot be assigned, including under legacy residual policy |
| `UNRESOLVED` | no IO tag |

The hierarchical classified preview (published as `pois.parquet` on export) contains `economy_evidence`, `economy_evidence_flags` (all applicable provenance labels), `economy_review_required`, `economy_candidate_source`, `economy_candidate_io240`, and `economy_candidate_local_sectors`. They distinguish provisional concordances, inferred ownership, source conflicts, legacy residual assumptions and exact-but-**unverified** IO tags. These are evidence categories, not accuracy estimates. They are included in the hierarchy audit totals. The local Explorer joins these labels from the published `pois.parquet` by `canonical_id` even when `sigma_points.parquet` omits them; neither the cluster nor the SIGMA score is changed. The scored-point GeoParquet is not rewritten to attach evidence, so users who consume it directly must join to `pois.parquet` by `canonical_id` to inspect provenance.

The Explorer shows a short "Sector basis" text for each establishment, built from this status and evidence when present; older exports may have only the provisional flag. `audit.json` reports the policy, the threshold, the parents kept whole (with their straddling and exact counts), the number of straddling places, and where each coarse place's candidates came from.

```{admonition} SIGMA-specific rules
:class: important
The refinement rows, the IO240 parents chosen by sector name, the ownership patterns and the straddle threshold are SIGMA rules, not published PSA concordances. They are versioned, fingerprinted and reported in provenance so that results can be reproduced or recomputed under a different choice.
```

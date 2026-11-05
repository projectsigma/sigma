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
   - ownership evidence for education (IO80 74 public / 75 private) and health (76 / 77), from names such as "National High School" or "Rural Health Unit" and, for a few clinic categories, from the category. It abstains when evidence points both ways or is absent, and does not treat generic terms such as "elementary school", "clinic" or "health center" as ownership proof. These name/category heuristics are inferred, **not** registry verification. Separately, `places.classified` may promote independently corroborated institutional public/private IO evidence from explicit source ownership, verified registry links or official external-ID matches **when compatible with PSIC candidate sets**. Name/city matching alone remains provisional; conflicts abstain. See [Institutional ownership evidence](shadow_classification.md).
5. **Consistency.** The three tags must nest. If they do not, the tag from the stronger source is kept (PSIC outranks direct rules): a finer PSIC tag replaces a weaker coarser one by its parent (`DERIVED_FROM_IO240` / `DERIVED_FROM_IO80`); otherwise the finer tag is cleared (`LEVEL_CONFLICT`).

`io_mapping_provisional` is `true` when the mapping depends on a draft bridge row or a draft refinement row, that is, on a link that is not from a published concordance.

## 2. Which sectors an area uses

An IO240 industry is kept as its own sector when at least `min_places` places carry it as an exact tag. Inside an IO80 parent with kept children, the other children form `IO80 · Other`; an IO80 parent without kept children is kept whole when its places reach `min_places`; the remaining industries of an IO16 parent form `IO16 · Other` (or the whole IO16 parent). Every IO240 industry belongs to exactly one sector, and transactions and gross output are aggregated as $M Z M^\top$ and $M x$, so national totals are conserved.

### Sparse sector identities

For the validated PSA hierarchy, the current `sparse-v1` codes express each
sector's ancestry rather than prefacing it with a resolution number:

| Form | Meaning |
|---|---|
| `X:Y:Z` | Exact IO240 industry `Z` within IO80 `Y` and IO16 `X` |
| `X:Y:o` | Residual unretained IO240 industries within IO80 `Y` |
| `X:Y` | Whole IO80 industry `Y` within IO16 `X` |
| `X:o` | Residual portion of IO16 `X` |
| `X` | Whole IO16 industry `X` |

`o` is a lower-case residual marker. These are **economic sector keys**,
not cluster IDs or PSIC codes. Hierarchical network nodes still pair an
exact sector key with a spatial cluster index. Sector keys are assigned when
an area's partition is built and may change if that area's support or policy
changes; the manifest and audit record `sector_code_scheme=sparse-v1`.

<!-- sigma-docs-20261104-v1:begin -->
### Post-clustering iterative roll-up (run-stage default)

The preceding partition is the **baseline classification** produced by
`sigma load`; it is still available unchanged using
`sigma run AREA --no-iterative-rollup`. Since no spatial clustering happens
at load time, a sector's cluster count is not known until `sigma run`.
For a generated area-specific hierarchical economy, the default `sigma run`
uses a residual-first iterative roll-up pass after evaluating the original
HDBSCAN sectors. A sector is eligible as a **source** only if it produced zero retained
clusters (`K=0`). The method tests a valid ancestor/residual coarsening,
reclusters affected sector assignments, and accepts an eligible change only
under the implemented positive net-retention criterion. It does **not** apply
an arbitrary *few clusters* threshold, split successful HDBSCAN sectors, or
assign noise observations to their nearest Voronoi owner. The process may
leave zero-cluster sectors unresolved when no admissible improvement exists.

The derived economy has its own identity and provenance; an original source
classification remains available as `original_economy_code`. The effective
sector after roll-up governs HDBSCAN, all X nodes `(type, cluster)`, network
Voronoi, IO aggregation, centrality and SIGMA scores. The original tag is
retained for audit and display, **not** as a parallel scored network sector.
These are modeling/engineering choices around established clustering and
IO aggregation, not an observed economic merger of the industries.

Use `sigma run AREA --iterative-rollup` to opt in explicitly or
`--no-iterative-rollup` to preserve the baseline. This default applies to
generated hierarchical areas, not fixed `--io-level 16|80|240`, explicit
custom economies or equivalent mode. Switching the CLI option changes the
*next analysis*, not the already-published Explorer data. To display a
different run, publish its corresponding outputs and rebuild/check Explorer.

### Relationship to network Gap refinement and network medians

The two adaptive steps have **different inputs, decisions and effects**:

1. **Baseline hierarchy at `sigma load`:** classify place industries using
   sparse IO240/IO80/IO16 sector keys and the area's support/residual policy.
2. **Baseline network HDBSCAN at `sigma run`:** find retained clusters and
   sector-level `K=0`; use these **unrefined** counts to evaluate residual-first
   iterative roll-up where eligible, potentially rebuilding the effective
   economic partition and affected sector clusters.
3. **Canonical network Gap pass:** for each **retained HDBSCAN cluster** of the
   final effective sector partition, test `k=1..6` (subject to sampling and
   admissibility) and subdivide only if supported by its adapted one-SE
   rule. Four independent workers run by default. This stage does **not**
   rescue K=0 sectors, merge economic types, reassign HDBSCAN noise, or
   recursively test the new children.
4. **Network centers and partitions:** compute a new, full-network 1-median
   for each final child cluster; use these final memberships to create
   type-specific network Voronoi, X nodes, centrality and scores.

The audit keeps both `original_economy_code` and effective `economy_code` for
hierarchical roll-up, while refined clustered points separately retain
`hdbscan_cluster` beside the **final** `cluster` label. A change to either
method can invalidate downstream spatial/economic artifacts; Explorer must
show matching published output. See [Gap k-medoids](network_gap_medians.md),
[End-to-end workflow](../workflow/end_to_end.md), and
[Reading outputs](../reference/outputs.md).

### Fixed hierarchical palette and original-child inspection

The canonical color lookup contains exactly **16 + 80 + 240 = 336 fixed
colors**. A sparse IO240 (`X:Y:Z`) uses its IO240 color; a whole IO80
(`X:Y`) uses its IO80 color; a whole IO16 (`X`) uses its IO16 color. An
`X:Y:o` residual inherits `X:Y`, and an `X:o` residual inherits `X`.
Legacy source code formats map to the same fixed entries. No area-based
palette generation or sector-order hash is required for these built-in tags.

In Explorer, a parent receiving formerly separate sectors can expand to
show each original label, code and classified-place count. Original-child
point visibility and color are browser-only; they do not create new HDBSCAN
clusters, recalculate cluster shares, or split the parent economy. Local
per-establishment original tags are part of the derived classified provenance;
a compact metadata override may serve older local Explorer tiles without
rewriting large tiles. Public bundles omit establishment-level records.
<!-- sigma-docs-20261104-v1:end -->

## 3. Assigning a place to one sector

A place with an exact IO240 tag joins the sector that holds that industry.

A **coarse place** has only an IO80 or IO16 tag. It carries its own IO240 candidate set: the candidates from tagging, restricted to the industries under its tag (all industries under the tag **only when no candidates were supplied**). A nonempty candidate set disjoint from the parent tag is a conflict: the place is unassigned for review, not silently imputed into the parent. Two policies exist:

- `contain` (optional candidate-conservative policy). The place joins a sector only when one sector contains all of its candidates. A place whose candidates fall into several sectors of a split parent *straddles* the split. A parent is kept whole instead of split when its straddling places are more than `max_straddle_share` (default 0.25) of its places (straddling plus exactly assigned); IO80 parents are checked first, then IO16 parents. Places that still straddle are left unassigned. No place is assigned to a sector that excludes one of its candidates.
- `residual` (**default for new profiles**). A coarse place that does not fit one sector is assigned to the `Other` residual of its parent. The residual is made of the industries that were *not* observed often enough to be kept, so this rule places coarse places in the least supported industries (for example bakeries tagged only as "trade" into a residual whose only member is wholesale trade). It is the exploratory default, with this assumption explicitly recorded in provenance.

`max_straddle_share` applies only when `coarse_policy=contain`; it trades sector detail against coverage. A low value keeps parents whole more often (fewer, coarser sectors; fewer unassigned places). A high value keeps more splits but leaves more coarse places unassigned. With `max_straddle_share = 0.5`, a parent is kept whole only when its straddling places outnumber its exactly assigned places.

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
| `UNASSIGNED_CANDIDATE_CONFLICT` | supplied IO240 candidates contradict the IO80/IO16 singleton; cannot be assigned, including under residual policy |
| `UNRESOLVED` | no IO tag |

The hierarchical classified preview (published as `pois.parquet` on export) contains `economy_evidence`, `economy_evidence_flags` (all applicable provenance labels), `economy_review_required`, `economy_candidate_source`, `economy_candidate_io240`, and `economy_candidate_local_sectors`. They distinguish provisional concordances, inferred ownership, source conflicts, legacy residual assumptions and exact-but-**unverified** IO tags. These are evidence categories, not accuracy estimates. They are included in the hierarchy audit totals. The local Explorer joins these labels from the published `pois.parquet` by `canonical_id` even when `sigma_points.parquet` omits them; neither the cluster nor the SIGMA score is changed. The scored-point GeoParquet is not rewritten to attach evidence, so users who consume it directly must join to `pois.parquet` by `canonical_id` to inspect provenance.

The Explorer shows a short "Sector basis" text for each establishment, built from this status and evidence when present; older exports may have only the provisional flag. `audit.json` reports the policy, the threshold, the parents kept whole (with their straddling and exact counts), the number of straddling places, and where each coarse place's candidates came from.

```{admonition} SIGMA-specific rules
:class: important
The refinement rows, the IO240 parents chosen by sector name, the ownership patterns and the straddle threshold are SIGMA rules, not published PSA concordances. They are versioned, fingerprinted and reported in provenance so that results can be reproduced or recomputed under a different choice.
```

<!-- sigma-augment-docs-v1:begin:hierarchy -->
## 5. Explicit IO tags supplied during augmentation

A post-load CSV/Parquet supplied to `sigma augment` may carry independent `io16`, `io80`, and `io240` columns. All are optional. The finest supplied level determines the ancestor codes: an IO240 tag establishes its IO80/IO16 parents; an IO80 tag establishes its IO16 parent; an IO16-only tag remains coarse. **No finer child code is guessed from a coarser parent.** When multiple levels are present, their actual parent-child links must agree; a mismatch blocks augmentation and identifies the source row. A conflicting automatic/inferred tag is reported as a warning, while the user-supplied tag is authoritative.

Users enter **national** IO codes, not dynamic local `:o` residual sector identifiers. After augmentation, the hierarchical build assigns the tagged places to the current area-specific partition, including residuals where applicable. See [Augment user-provided places](augmentation.md) and [its input specification](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_AUGMENT.md).
<!-- sigma-augment-docs-v1:end:hierarchy -->

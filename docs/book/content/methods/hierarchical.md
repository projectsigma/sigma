# Hierarchical economy: area sectors from IO240, IO80 and IO16 (stages 4–5)

*Pipeline stages 4–5 of 17 · `sigma load` (stage 5 is rebuilt by `sigma run` when it is older than the handoff). Under the Hood shows both stages with interactive examples (sections “Stage 4” and “Stage 5”).*

The PSA 2018 input-output tables exist at three nested levels: 240, 80 and 16 industries. Each IO240 industry belongs to one IO80 industry, and each IO80 industry to one IO16 industry. The hierarchical economy uses the finest level where an area's places support it and a coarser level elsewhere, so that every sector used in clustering has enough places and the national table is still used in full.

This page describes, in order: how a place gets IO tags (stage 4), how the per-area sectors are chosen (stage 5), how a place is assigned to one sector, what the statuses mean, how the national table is aggregated, which settings apply, and what happens after clustering (stages 9 and 10).

## 1. From a place to IO tags (stage 4)

A place first receives a PSIC Rev. 5 code (stage 3, see [Places](places.md)). The PSIC code is then mapped to sets of candidate IO industries at each level:

1. **Bridge and concordance.** The Rev. 5 code goes up its ancestors until it reaches a row of the Rev. 5 → PSIC 2019 bridge (group, division or section). The PSIC 2019 code is mapped through the PSIC 2019 → PSA 2018 IO concordance. These two tables stop at PSIC groups.
2. **Refinement below the group.** `io/psic_rev5_io240_refinement.csv` lists Rev. 5 classes and subclasses whose title names one IO240 industry (or a smaller set) inside their group's candidate set. Example: class 0112 "Growing of rice" is in group 011, which maps to 1 IO16, 6 IO80 and 11 IO240 industries; the refinement row for class 0112 narrows IO240 to 001 Palay, and its parents fix IO80 01 and IO16 01. A refinement row may only narrow the set; a row that would add an industry is reported as `not_applied`. The IO80 and IO16 sets are then the parents of the remaining IO240 industries, from `io/io240_parents.csv`.
3. **Union decisions.** A source category can name several PSIC subtrees (for example Overture `lodging` = hotels, other short-term accommodation, camping grounds or other accommodation). The PSIC decision then has status `UNION` and no single PSIC code. Its IO candidates are the union of the members' candidates, so they are never wider than the members justify. If any member has no IO correspondence, nothing is mapped (`UNMAPPED_UNION_PARTIAL`).
4. **A tag at each level.** A level receives a code only when its candidate set has one member. Three kinds of evidence can choose inside a candidate set without leaving it:
   - same-name evidence from other places in the run, for the IO80 pairs (55, 56) and (66, 67);
   - direct OpenStreetMap tag rules for IO80 (`tagging/compatibility/rules.yml`). They match parsed `key=value` tags, never names or substrings. Primary tags decide before the auxiliary keys `cuisine`, `brand` and `operator`. Tags that point to different IO80 industries make the evidence a conflict.
   - ownership evidence for education (IO80 74 public / 75 private) and health (76 / 77), from names such as "National High School" or "Rural Health Unit" and, for a few clinic categories, from the category. It abstains when evidence points both ways or is absent, and does not treat generic terms such as "elementary school", "clinic" or "health center" as ownership proof. These name/category heuristics are inferred, **not** registry verification. Separately, `places.classified` can promote independently corroborated institutional public/private IO evidence from explicit source ownership, verified registry links or official external-ID matches **when compatible with PSIC candidate sets**. Name/city matching alone remains provisional; conflicts abstain. See [Institutional ownership evidence](shadow_classification.md).
5. **Consistency.** The three tags must nest. If they do not, the tag from the stronger source is kept (PSIC outranks direct rules): a finer PSIC tag replaces a weaker coarser one by its parent (`DERIVED_FROM_IO240` / `DERIVED_FROM_IO80`); otherwise the finer tag is cleared (`LEVEL_CONFLICT`).

`io_mapping_provisional` is `true` when the mapping depends on a draft bridge row or a draft refinement row, that is, on a link that is not from a published concordance.

## 2. Which sectors an area uses (stage 5)

An IO240 industry is kept as its own sector when at least `min_places` places (5 by default) carry it as an exact tag. Inside an IO80 parent with kept children, the other children form the IO80 residual; an IO80 parent without kept children is kept whole when its IO80-only places plus the places of its folded children reach `min_places`; the remaining industries of an IO16 parent form the IO16 residual (or the whole IO16 parent when nothing under it was kept). Every one of the 240 industries belongs to exactly one sector, including industries with no observed place, so the national table is used in full.

Worked example (also interactive in Under the Hood): one IO16 industry `X` has IO80 children `Y1` (IO240 `Z1`, `Z2`, `Z3`), `Y2` (`Z4`, `Z5`) and `Y3` (`Z6`, `Z7`). Exact tags: `Z1` 9, `Z2` 6, `Z3` 2, `Z4` 3, `Z5` 1. Coarse tags: 3 places with only `Y1`, 2 with only `Y2`, 1 with only `X`. With `min_places = 5`, `Z1` and `Z2` are kept; `Z3` forms `X:Y1:o`; `Y2` has 2 + 3 + 1 = 6 places and stays whole as `X:Y2`; `Z6` and `Z7` form `X:o`. Under the default residual policy, the 3 `Y1`-only places go to `X:Y1:o`, the 2 `Y2`-only places to `X:Y2`, and the `X`-only place to `X:o`.

### Sparse sector identities

For the validated PSA hierarchy, the `sparse-v1` codes express each sector's ancestry:

| Form | Meaning |
|---|---|
| `X:Y:Z` | Exact IO240 industry `Z` within IO80 `Y` and IO16 `X` |
| `X:Y:o` | Residual unretained IO240 industries within IO80 `Y` |
| `X:Y` | Whole IO80 industry `Y` within IO16 `X` |
| `X:o` | Residual portion of IO16 `X` |
| `X` | Whole IO16 industry `X` |

`o` is a lower-case residual marker. These are **economic sector keys**, not cluster IDs or PSIC codes. Network nodes pair an exact sector key with a spatial cluster index. Sector keys are assigned when an area's partition is built and may change if that area's support or policy changes; the manifest and audit record `sector_code_scheme=sparse-v1`.

## 3. Settings, selection and rebuilds

The first hierarchical `sigma load` writes `<SIGMA_HOME>/hierarchical-defaults.json` with `min_places = 5`, `coarse_policy = residual`, `max_straddle_share = 0.25` and `check_psa = true`; its source paths point to the packaged national IO240 reference (`package:psa_2018_io240`). Change them with `sigma economy hierarchical-configure`. The area's choice is recorded in `economy-selection.json` (IO level, handoff hash, settings, reference fingerprints), and `sigma run` follows it:

- if the handoff is newer than the hierarchy and the settings are unchanged, `sigma run` rebuilds stage 5 with the recorded settings;
- if the settings differ from those recorded at load time, `sigma run` stops and lists the differences; use `sigma economy hierarchical-refresh --workspace PATH` to adopt the new settings or `sigma load AREA` to reload;
- fixed `--io-level 16|80|240` and custom `--economy` areas never build a hierarchy; a workspace without a recorded selection keeps IO80 until it is reloaded.

Before any OSM or Overture work, a hierarchical `sigma load` validates the packaged IO240 reference (file hashes, all 240 sectors, the IO240 → IO80 → IO16 parents, and consistency with the PSIC/IO tagging references). See [`docs/SIGMA_LOAD_PORTABILITY.md`](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_LOAD_PORTABILITY.md).

## 4. Assigning a place to one sector (stage 5)

A place with an exact IO240 tag joins the sector that holds that industry.

A **coarse place** has only an IO80 or IO16 tag. It carries its own IO240 candidate set: the candidates from tagging, restricted to the industries under its tag (all industries under the tag **only when no candidates were supplied**). A nonempty candidate set disjoint from the parent tag is a conflict: the place is unassigned for review, not silently imputed into the parent. Two policies exist:

- `contain` (optional candidate-conservative policy). The place joins a sector only when one sector contains all of its candidates. A place whose candidates fall into several sectors of a split parent *straddles* the split. A parent is kept whole instead of split when its straddling places are more than `max_straddle_share` (default 0.25) of its places (straddling plus exactly assigned); IO80 parents are checked first, then IO16 parents. Places that still straddle are left unassigned. No place is assigned to a sector that excludes one of its candidates.
- `residual` (**default**). A coarse place that does not fit one sector is assigned to the `Other` residual of its parent. The residual is made of the industries that were *not* observed often enough to be kept, so this rule places coarse places in the least supported industries (for example bakeries tagged only as "trade" into a residual whose only member is wholesale trade). It is the exploratory default, with this assumption explicitly recorded in provenance.

`max_straddle_share` applies only when `coarse_policy=contain`; it trades sector detail against coverage. A low value keeps parents whole more often (fewer, coarser sectors; fewer unassigned places). A high value keeps more splits but leaves more coarse places unassigned. With `max_straddle_share = 0.5`, a parent is kept whole only when its straddling places outnumber its exactly assigned places.

## 5. Statuses (`economy_status`)

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

The hierarchical classified preview (published as `pois.parquet` on export) contains `economy_evidence`, `economy_evidence_flags` (all applicable provenance labels), `economy_review_required`, `economy_candidate_source`, `economy_candidate_io240`, and `economy_candidate_local_sectors`. They distinguish provisional concordances, inferred ownership, source conflicts, residual assumptions (`legacy_residual`) and exact-but-**unverified** IO tags. These are evidence categories, not accuracy estimates. They are included in the hierarchy audit totals. The local Explorer joins these labels from the published `pois.parquet` by `canonical_id` even when `sigma_points.parquet` omits them; neither the cluster nor the SIGMA score is changed. The scored-point GeoParquet is not rewritten to attach evidence, so users who consume it directly must join to `pois.parquet` by `canonical_id` to inspect provenance.

The Explorer shows a short "Sector basis" text for each establishment, built from this status and evidence when present; an export without the evidence columns shows only the provisional flag. `audit.json` reports the policy, the threshold, the parents kept whole (with their straddling and exact counts), the number of straddling places, and where each coarse place's candidates came from.

## 6. Aggregating the national table

With membership matrix $M$ (one row per area sector, one column per IO240 industry, entries 0 or 1), SIGMA aggregates the national IO240 transactions $Z$ and gross output $x$:

$$Z_\text{area}=M\,Z\,M^\top,\qquad x_\text{area}=M\,x.$$

Rows and columns use the same partition, so total transactions and total output are conserved. Technical coefficients are recomputed from the aggregated table in stage 13 ([Economy](economy.md)); a merged coefficient therefore equals the output-weighted average of the merged industries' coefficients, not their simple average. For example, merging industries with $z_{b,c}=6$, $x_c=60$ and $z_{b,d}=1$, $x_d=40$ gives $a_{b,cd}=7/100=0.070$, while the simple average of $0.100$ and $0.025$ would be $0.0625$.

## 7. After clustering: stages 9 and 10

The partition above is the **baseline classification** of `sigma load`. No clustering happens at load time, so a sector's cluster count is not known until `sigma run`. Two later stages act on clusters:

1. **Stage 9, zero-cluster roll-up** (generated hierarchies only, on by default). Network HDBSCAN* is first run on the baseline sectors with **unrefined** labels. Only a sector with zero retained clusters (`K=0`) can be merged, residual-first, into an existing residual, and only when the merge strictly increases the number of retained places. The derived economy keeps `original_economy_code` beside the effective `economy_code`. `sigma run AREA --no-iterative-rollup` keeps the baseline. See [Zero-cluster roll-up](iterative_rollup.md).
2. **Stage 10, network Gap refinement** (all economies, on by default). For each retained HDBSCAN* cluster of the final sectors, one nonrecursive network Gap k-medoid pass, run using up to four worker processes, decides whether to split the cluster. It never rescues a `K=0` sector, never merges sectors and never reassigns noise. Refined points keep `hdbscan_cluster` beside the final `cluster`. See [Gap refinement](network_gap_medians.md).

Stage 11 then computes a new full-network 1-median for each final cluster, and these final memberships define network Voronoi, X nodes, centrality and scores. Both stages are modeling choices around established clustering and IO aggregation; neither is an observed economic merger of industries.

## 8. Explicit IO tags supplied during augmentation

A post-load CSV/Parquet supplied to `sigma augment` may carry independent `io16`, `io80`, and `io240` columns. All are optional. The finest supplied level determines the ancestor codes: an IO240 tag establishes its IO80/IO16 parents; an IO80 tag establishes its IO16 parent; an IO16-only tag remains coarse. **No finer child code is guessed from a coarser parent.** When multiple levels are present, their actual parent-child links must agree; a mismatch blocks augmentation and identifies the source row. A conflicting automatic/inferred tag is reported as a warning, while the user-supplied tag is authoritative.

Users enter **national** IO codes, not dynamic local `:o` residual sector identifiers. After augmentation, the hierarchical build assigns the tagged places to the current area-specific partition, including residuals where applicable. See [Augment user-provided places](augmentation.md) and [its input specification](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_AUGMENT.md).

## 9. Fixed palette and original-child inspection

The canonical color lookup contains exactly **16 + 80 + 240 = 336 fixed colors**. A sparse IO240 (`X:Y:Z`) uses its IO240 color; a whole IO80 (`X:Y`) uses its IO80 color; a whole IO16 (`X`) uses its IO16 color. An `X:Y:o` residual inherits `X:Y`, and an `X:o` residual inherits `X`. Tiered source codes (for example `240:001` or `80:72:OTHER`) map to the same fixed entries. No area-based palette generation or sector-order hash is required for these built-in tags.

In Explorer, a parent receiving formerly separate sectors can expand to show each original label, code and classified-place count. Original-child point visibility and color are browser-only; they do not create new HDBSCAN clusters, recalculate cluster shares, or split the parent economy. Local per-establishment original tags are part of the derived classified provenance; a compact metadata override (`original_type_overrides`) can serve existing local Explorer tiles without rewriting them. Public bundles omit establishment-level records.

```{admonition} SIGMA-specific rules
:class: important
The refinement rows, the IO240 parents chosen by sector name, the ownership patterns, the support threshold and the straddle threshold are SIGMA rules, not published PSA concordances. They are versioned, fingerprinted and reported in provenance so that results can be reproduced or recomputed under a different choice.
```

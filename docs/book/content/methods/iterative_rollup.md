# Zero-cluster roll-up (stage 9)

*Pipeline stage 9 of 17 · `sigma run` · generated hierarchical economies only. Under the Hood shows this stage with an interactive example (section “Stage 9”).*

Stage 5 ([Hierarchical economy](hierarchical.md)) chooses the sectors of a study area from place counts. Clustering happens later, so stage 5 cannot know whether a sector will form any cluster. Stage 9 handles sectors that end with **zero retained clusters** (`K=0`): it tries to merge each of them into the nearest existing residual sector, and keeps a merge only when more establishments are retained in clusters.

## Why a sector can have K = 0

SIGMA runs network HDBSCAN* with `allow_single_cluster = False` by default. With this setting, HDBSCAN* never returns a whole sector as one cluster. A sector keeps a cluster only when its density tree splits into at least two groups, and each group has at least `min_cluster_size` establishments (5 by default).

Two consequences follow:

- A sector with fewer than `2 × min_cluster_size` = 10 establishments always has `K = 0`, however close its places are. Stage 5 can still keep such a sector, because its support rule needs only `min_places` = 5 places.
- A sector with 10 or more establishments can still have `K = 0`, for example two well-separated groups of 6 and 4 places: the group of 4 drops out as noise and the tree never splits into two groups of at least 5.

A worked example on one road (checked with SIGMA's clustering code): two far-apart, evenly spaced groups of sizes 5 and 5 give `K = 2`; sizes 7 and 6 give `K = 2`; sizes 6 and 4, 5 and 4, or 9 and 3 give `K = 0`.

A successful extraction with `K = 0` is a valid result. It is not an exception and does not start the Euclidean recovery path described in [Network HDBSCAN*](hdbscan.md). Without stage 9, all establishments of such a sector are noise: they have no X node and no SIGMA score.

## When stage 9 runs

| Run | Stage 9 |
|---|---|
| `sigma run AREA` on an area loaded with the default hierarchical economy | on |
| `sigma run AREA --iterative-rollup` | on (explicit; requires the generated hierarchy) |
| `sigma run AREA --no-iterative-rollup` | off: the stage 5 sectors are used as loaded |
| `--io-level 16`, `80`, `240`, a custom `--economy`, or `--equivalent` | off; `--iterative-rollup` is refused |

## Algorithm

1. **Baseline clustering without Gap refinement.** SIGMA clusters the stage 5 sectors with network HDBSCAN* and the run's clustering settings, but with network Gap refinement (stage 10) switched off. Roll-up decisions always use these unrefined labels.
2. **Find the sources.** A sector whose saved assignments contain no retained cluster has `K = 0`. If the clustering audit disagrees with the saved assignments, the affected sector is replayed exactly; a replay that does not reproduce the saved labels stops the run without publishing anything.
3. **Choose the nearest existing residual.** For a source code, the candidates are tried in this order, and only residuals that already exist in the area (that is, that hold places) are used:

   | Source | First candidate | Second candidate |
   |---|---|---|
   | `X:Y:Z` | `X:Y:o` | `X:o` |
   | `X:Y` | `X:o` | — |
   | `X:Y:o` | `X:o` | — |
   | `X:o`, `X` | none: these cannot be sources | — |

   No new residual is created, and a sector is never merged into an unrelated parent.
4. **Trial.** All sources that target the same residual are tried together. The places of these sources and of the residual are clustered again as one sector, with the same road graph, snaps and HDBSCAN* settings. Let `b` be the number of retained places of the participating sectors before the trial and `a` the number after it. The merge is **accepted only if `a > b`** (strictly positive net retention). The audit also records the gross number of source places recovered, which can differ from the net gain when some places of the residual stop being retained.
5. **Iterate.** After a round, the sectors are recomputed. A source whose first candidate was rejected tries its second candidate in a later round. The loop ends when no untried candidate remains. Sectors with `K ≥ 1` are never sources, whatever their share of noise.
6. **Aggregate the economy.** The accepted mapping folds each source into its residual. With membership matrix `M` (sectors × IO240 industries), SIGMA computes `Z_eff = M Z M^T` and `x_eff = M x` from the national IO240 table, checks that total transactions and total output are unchanged, and checks that every source is an ancestor-compatible member of its destination in the IO240 membership file. Technical coefficients are then recomputed by stage 13 from the aggregated table; they are never averaged.
7. **Write a separate package.** The derived economy and places are written to `hierarchical/iterative_rollup/<recipe-hash>/` with `economy/economy.yml`, `sectors.csv`, `transactions.csv`, `total_output.csv`, `membership.csv`, `rollup_audit.json`, `places.parquet` and `rollup_manifest.json` (file hashes). The stage 5 package, the handoff `places/places.parquet`, and existing artifacts are not edited. An existing package with the same recipe hash is reused only after its file hashes are verified.
8. **Verify, then continue.** SIGMA clusters the effective sectors again, still without Gap refinement, and stops if the cluster count differs from the count predicted by the trials. Only then does the run continue with the effective economy: stage 10 Gap refinement, then stages 11–17.

## Worked example

Three invented sectors on one road, with `min_cluster_size = 5` (positions checked with SIGMA's clustering code):

| Sector | Places | Baseline `K` |
|---|---:|---:|
| `X:Y1:Z2` | 6 (one group) | 0 |
| `X:Y1:o` | 11 (groups of 6 and 5) | 2 |
| `X:Y2` | 4 | 0 |
| `X:o` | 3 | 0 |

| Trial | Sources → destination | `b` | `a` | Net | Result |
|---|---|---:|---:|---:|---|
| 1 | `X:Y1:Z2` → `X:Y1:o` | 11 | 17 | +6 | accepted; `X:Y1:o` now has 3 clusters |
| 2 | `X:Y2` → `X:o` | 0 | 0 | 0 | rejected; `X:Y2` keeps `K = 0` |

`X:o` has no residual ancestor, so it is not a source.

## Two sector identities

Every place of the derived package keeps `original_economy_code` (its stage 5 sector) and receives `economy_code`, the **effective** sector. The effective sector governs clustering, the IO table, network Voronoi, X nodes, centrality and scores. The original code is provenance and is used by Explorer only to show and color the original sub-sectors of an effective sector (`rollup_children` in the Explorer metadata). There are no child X nodes and no child scores. A moved place also records `rollup_iteration`.

## What stage 9 does not do

- It does not split or merge sectors that already have clusters.
- It does not assign noise to the nearest cluster or territory.
- It does not change `min_cluster_size`, the HDBSCAN* search horizon or any other spatial parameter.
- It does not run Gap refinement; stage 10 runs afterwards on the retained clusters of the effective sectors.
- It measures retention only. A merge is not evidence that the merged industries trade with each other or form one market.

## Audit and comparison

`rollup_audit.json` lists every tested and accepted merge (`destination`, `sources`, `before_retained`, `after_retained`, `net_retained_gain`, `gross_recovered`, `trial_clusters`), the input and effective sector counts, the baseline cluster count and the predicted cluster count. To compare with the stage 5 sectors, rerun with `--no-iterative-rollup`; to isolate the clustering refinement, also use `--no-median-gap`.

See also [Network Gap refinement](network_gap_medians.md) (stage 10), [Reading outputs](../reference/outputs.md) and the engineering note [`docs/iterative_rollup.md`](https://github.com/projectsigma/sigma/blob/main/docs/iterative_rollup.md).

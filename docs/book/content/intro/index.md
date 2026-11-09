# SIGMA: from establishments to a spatial-economic influence network

SIGMA is a reproducible pipeline for turning observed establishments, a road network, and an input-output economy into a **spatial-economic graph** and point-level influence scores.

This book documents the model as it is implemented. Its purpose is not merely to tell you which command to run. It spells out the transformations, equations, assumptions, fallbacks, and provenance of the methods so that a SIGMA result can be inspected as a chain of explicit analytical decisions.

For hands-on exploration after a run, **[SIGMA Explorer](explorer.md)** provides a browser map connected to the directed cluster-level X graph. Select a mapped establishment to examine the network neighborhood of its assigned economic-type cluster and draw the shortest road routes between linked cluster centers; Explorer visualizes already-published results and does not alter the model. Its **Under the Hood** page walks through all stages below with interactive, worked examples.

## The pipeline in 17 stages

SIGMA numbers its modeling stages from 1 to 17. The same numbers are used in this book, in the README and in Under the Hood.

```text
sigma load ─────────────────────────────────────────────────────────────────────
  1  sources            OSM (Geofabrik PBF) + Overture Places, clipped to the area
  2  matching           distance/name rule, one-to-one → canonical places
  3  activity           PSIC classification; narrow administrative-office rule
  4  IO tags, evidence  PSIC → IO240/80/16 candidates; public/private evidence
  5  area sectors       per-area IO240/IO80/IO16 partition (min_places = 5)
     ── optional: review the handoff, sigma augment AREA FILE --source NAME ──
sigma run ──────────────────────────────────────────────────────────────────────
  6  road graph         managed motor roads, undirected, shared-vertex topology
  7  snapping           places → nearest road position; road distance d_R
  8  HDBSCAN*           network HDBSCAN* per sector (baseline, unrefined labels)
  9  zero-cluster       generated hierarchy: residual-first roll-up of K=0 sectors
     roll-up            (recluster affected sectors; verify predicted count)
 10  Gap refinement     one nonrecursive network Gap k-medoid pass, up to 4 workers;
                        retained clusters only, noise stays noise
 11  centers            network-node 1-median of every final cluster
 12  territories        network Voronoi per sector, rendered as polygons on a grid
                        (50 m start, halved until ownership converges or a limit)
 13  economy            effective-sector table → coefficients a_ij = z_ij / x_j
 14  graph X            IO edge ∧ territory overlap ∧ road-connected centers;
                        weight with sector shares and mean hub distance
 15  Katz               per-geography PPML area scaling; tile-adjusted in/out Katz
 16  balanced           sqrt(K_in · K_out), one final L2 normalization
 17  scores             inverse-road-distance transfer from cluster centrality
publication ────────────────────────────────────────────────────────────────────
     export             GIS/CSV/GeoParquet; compact routing graph (default)
     sigma view         Explorer draws routes on request (no new numbers)
```

The sequence is a conceptual dependency order, not a list of managed artifacts; [End-to-end workflow](../workflow/end_to_end.md) maps each stage to its managed stage IDs and chapter. Two adaptive steps deserve attention because they act at different levels:

- **Stage 9** changes the *economic sector partition* of generated hierarchies, and only for sectors with zero retained clusters (`K=0`). It uses the unrefined HDBSCAN* labels of stage 8. Use `sigma run AREA --no-iterative-rollup` to keep the stage 5 sectors. See [Zero-cluster roll-up](../methods/iterative_rollup.md).
- **Stage 10** changes the *clusters inside each final sector*: one pass of the network Gap statistic decides whether a retained HDBSCAN* cluster is better described by several road medoids. It is **on by default** for every economy (up to four worker processes; `--no-median-gap` keeps the unrefined clusters; legacy `--equivalent` keeps them by default). Gap never rescues a `K=0` sector, never reassigns noise and never retests its own children. See [Network Gap refinement](../methods/network_gap_medians.md).

Numerical X (stage 14) uses exact road distances but stores no route lines. By default the export publishes a compact routing graph and Explorer draws a route only when an edge is shown, after checking its length against the published distance; `--route-geometry precomputed` writes all routes at export instead. See [Route publication](../methods/routing.md).

The default is deliberately conservative: deterministic place classification, no LLM requirement, no transaction preprocessing, the full directed economic graph, road-network-first spatial methods, and a **tile-area-adjusted** balanced directed Katz score (default on). New areas loaded with `sigma load AREA` use a per-area hierarchical PSA 2018 IO240/IO80/IO16 economy; an older workspace without a recorded selection keeps IO80 until it is explicitly reloaded. The X graph does not identify observed suppliers: its directed links combine input-output coefficients, positive-area territory overlap, connected 1-medians, clustered-sector shares, and mean hub-mediated road-distance attenuation.

```{admonition} What is a SIGMA node?
:class: note
A node of the final graph is not an individual establishment. It is a **spatial cluster of establishments of one sector**, identified by `(type, cluster)`. Establishments receive their final score from the centrality of that cluster divided by their road distance to its 1-median (1 m floor). Area adjustment is performed on the focal tile's incoming/outgoing X weights **before** Katz, not again on the establishment score. See [Centrality](../methods/centrality.md), [Scoring](../methods/scoring.md), and [Empirical diagnostics](../methods/area_adjustment_diagnostics.md).
```

```{admonition} Two sector identities after stage 9
:class: note
After a roll-up, each moved establishment keeps its stage 5 sector as `original_economy_code` and receives an effective `economy_code`. The effective sector governs clustering, the IO table, X, centrality and scores. The original code is provenance only; Explorer can show and color the original sub-sectors of an effective sector, but they are not separate X nodes.
```

## Reading the book

If you want to run SIGMA first, start with [Quickstart](quickstart.md). If you want the model specification, read [End-to-end workflow](../workflow/end_to_end.md) and then the method chapters in stage order. The [Method lineage](../reference/method_lineage.md) page distinguishes published algorithms from SIGMA-specific implementation rules; the [References](../reference/references.md) page consolidates the published literature supporting the methods used by SIGMA.

## Scope of the mathematical specification

The equations in this book describe the current `sigma` source tree. When the implementation contains a recovery path, the primary method and the fallback are documented separately. In particular:

- clustering is HDBSCAN* on sparse bounded **road-network distance**, with a Euclidean recovery path only after network clustering fails;
- the network Gap refinement uses a road-vertex reference distribution and PAM-style k-medoids, an adaptation of the Euclidean Gap statistic;
- cluster centers are exact **network-node 1-medians**, with a centroid-to-road-to-node recovery path;
- network Voronoi ownership is exact on the 1-D road graph, while its published polygon layer is a finite-resolution **2-D rendering** of that ownership; the grid starts at 50 m and is refined until at most 0.5 % of the area changes owner between successive grids, within a cell budget;
- the default economy preserves the full directed technical-coefficient graph; optional `mwas_ras_fast` changes the transaction table before coefficients are recomputed;
- canonical centrality is a SIGMA geometric-mean rescaling of paired incoming/outgoing Katz scores, grounded in the sender-receiver Katz product literature rather than presented as a separately published named index.

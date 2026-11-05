# Methodological Foundations and Adjustments

This page summarizes the methodological foundations of the analytical workflow and the adjustments used in their practical application. The latter concern data representation, computational procedures, parameterization, numerical safeguards, and fallback behavior. The cited literature provides the theoretical context, with further details available in the method pages and bibliography.

| Analytical component | Methodological foundations | Methodological adjustments |
|---|---|---|
| Place reconciliation (stages 1–2) | Geographic and name-based record-linkage methods | Matching thresholds, candidate-evidence weighting, and deterministic greedy matching; the same rule for user sources added by `sigma augment`. |
| Activity and ownership evidence (stages 3–4) | PSIC Rev. 5; PSA PSIC–IO concordances; official institution registries | Reviewed crosswalks and refinement rows that may only narrow candidate sets; a narrow administrative-office rule (PSIC 84120); public/private IO changed only by a verified registry link, an official external ID, or an explicit source attribute. |
| Area sectors (stage 5) | PSA 2018 IO nesting (240/80/16); aggregation of IO tables by a membership matrix ($M Z M^\top$, $M x$) | Support threshold `min_places`, sparse residual codes, residual or contain policy for coarse places. |
| Road shortest paths (stages 6–7) | Dijkstra (1959); SciPy (Virtanen et al., 2020) | Projected road representation, shared-vertex topology, batched routing, and validity checks. |
| Network clustering (stage 8) | HDBSCAN* (Campello et al., 2013, 2015); network-space clustering (Yiu & Mamoulis, 2004; Wang et al., 2019) | Bounded sparse-neighborhood search, adaptive-radius diagnostics, deterministic tie handling, and fallback procedures. |
| Zero-cluster roll-up (stage 9) | HDBSCAN* extraction with `allow_single_cluster=False`; IO aggregation | Residual-first merge of sectors with `K=0`, accepted only for a strictly positive gain in retained establishments; replay and count verification; derived economy package. |
| Post-HDBSCAN Gap refinement (stage 10) | Gap statistic and one-standard-error selection (Tibshirani, Walther & Hastie, 2001); Partitioning Around Medoids (Kaufman & Rousseeuw, 1990) | **Canonical default** on retained HDBSCAN clusters; adapted road-vertex bounding-rectangle null, observed-site candidate medoids, seeded sampling (max 64), up to 10 reference draws, `k≤6`, validity guard, exact bounded Dijkstra, vectorized SWAP, deterministic four-process execution; single pass (nonrecursive). |
| Cluster centers (stage 11) | Network median and location theory (Hakimi, 1964, 1965; Handler & Mirchandani, 1979; Kariv & Hakimi, 1979) | Road-node candidate restriction for network-median selection, with centroid recovery where required. |
| Network territories (stage 12) | Graph and network Voronoi methods (Erwig, 2000; Hakimi, Labbé & Schmeichel, 1992; Okabe et al., 2008; Okabe & Sugihara, 2012) | Grid-based boundary rendering, spatial refinement, and Euclidean fallback where network partitioning is unavailable. |
| Input-output coefficients (stage 13) | Standard input-output coefficient convention, $a_{ij}=z_{ij}/x_j$ | Economy-data configuration and validation procedures. |
| Spatial-economic X graph (stage 14) | Positive directed IO relationships; positive-area overlap of type-specific Voronoi partitions; shortest-road distances | Mean hub-mediated separation (center route plus both cluster mean radii), exact-type clustered-establishment shares at both endpoints, and inverse-power attenuation; distances only, no route geometry. These are modeling/engineering choices, not verified local supply-chain flows. |
| Optional transaction sparsification | Maximum-weight acyclic-subgraph formulation; RAS / iterative proportional fitting | Fast deterministic MWAS heuristic, ordered feasibility repairs, and transaction-support constraints. |
| Directed Katz centrality (stage 15) | Katz (1953) | Attenuation scaling, numerical safeguards, and consistent computational conventions. |
| Sender–receiver coupling (stage 16) | Sharkey (2017); directed in/out-role coupling (Everett & Schoch, 2022); HITS precedent (Kleinberg, 1999) | Componentwise geometric mean, $\sqrt{K^{in}K^{out}}$, followed by a final L2 normalization. |
| Establishment scoring (stage 17) | Distance-based score tempering | Cluster-level 90th-percentile distance reference and bounded linear distance tempering. |
| Route display (publication) | Dijkstra shortest paths | Contracted routing graph without establishment vertices; on-request routing in a Web Worker with a length check against the published distance. |

## Conditional hierarchical roll-up and fixed visualization palette

**Zero-cluster iterative roll-up** is a SIGMA-specific methodological
adjustment, not a standard additional HDBSCAN extraction mode. It acts only
after identifying generated-hierarchy sectors with `K=0`, tests a
residual-first valid ancestor/coarsening candidate, and retains a candidate
only under the implementation's positive net-retention criterion. It does
not apply an arbitrary minimum cluster count to already successful sectors
and does not use Voronoi proximity to impute noise membership.

The fixed palette (16 + 80 + 240 sector colors), original child-point
visibility, contextual unclustered markers, and the hovered Voronoi outline
are **browser/QGIS representation choices**. They must not be confused with
network HDBSCAN membership, Voronoi ownership, national IO coefficients, or
observed economic relationships. The roll-up decision precedes the Gap
post-clustering pass; Gap children do not revise the K=0 roll-up criterion.
The fitted medoids are candidates for splitting only: final centers are
recomputed by the subsequent exact network-node 1-median stage.

## Implementation notes

The table is a concise reference to the methods and computational settings used in the workflow. Detailed method pages and canonical defaults describe the applicable conventions and parameter settings. Computational adjustments can be reviewed or revised according to data characteristics and analytical requirements.

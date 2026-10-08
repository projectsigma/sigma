# Methodological Foundations and Adjustments

This page summarizes the methodological foundations of the analytical workflow and the adjustments used in their practical application. The latter concern data representation, computational procedures, parameterization, numerical safeguards, and fallback behavior. The cited literature provides the theoretical context, with further details available in the method pages and bibliography.

| Analytical component | Methodological foundations | Methodological adjustments |
|---|---|---|
| Road shortest paths | Dijkstra (1959); SciPy (Virtanen et al., 2020) | Projected road representation, shared-vertex topology, batched routing, and validity checks. |
| Network clustering | HDBSCAN* (Campello et al., 2013, 2015); network-space clustering (Yiu & Mamoulis, 2004; Wang et al., 2019) | Bounded sparse-neighborhood search, adaptive-radius diagnostics, deterministic tie handling, and fallback procedures. |
| Cluster centers | Network median and location theory (Hakimi, 1964, 1965; Handler & Mirchandani, 1979; Kariv & Hakimi, 1979) | Road-node candidate restriction for network-median selection, with centroid recovery where required. |
| Network territories | Graph and network Voronoi methods (Erwig, 2000; Hakimi, Labbé & Schmeichel, 1992; Okabe et al., 2008; Okabe & Sugihara, 2012) | Grid-based boundary rendering, spatial refinement, and Euclidean fallback where network partitioning is unavailable. |
| Input-output coefficients | Standard input-output coefficient convention, $a_{ij}=z_{ij}/x_j$ | Economy-data configuration and validation procedures. |
| Optional transaction sparsification | Maximum-weight acyclic-subgraph formulation; RAS / iterative proportional fitting | Fast deterministic MWAS heuristic, ordered feasibility repairs, and transaction-support constraints. |
| Directed Katz centrality | Katz (1953) | Attenuation scaling, numerical safeguards, and consistent computational conventions. |
| Sender–receiver coupling | Sharkey (2017); directed in/out-role coupling (Everett & Schoch, 2022); HITS precedent (Kleinberg, 1999) | Componentwise geometric mean, $\sqrt{K^{in}K^{out}}$, followed by a final L2 normalization. |
| Establishment scoring | Distance-based score tempering | Cluster-level 90th-percentile distance reference and bounded linear distance tempering. |
| Place reconciliation | Geographic and name-based record-linkage methods | Matching thresholds, candidate-evidence weighting, and deterministic greedy matching. |

## Implementation notes

The table is a concise reference to the methods and computational settings used in the workflow. Detailed method pages and canonical defaults describe the applicable conventions and parameter settings. Computational adjustments can be reviewed or revised according to data characteristics and analytical requirements.

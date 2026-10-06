# Method lineage: what is published and what is SIGMA-specific?

This page is the shortest defensible description of provenance.

| SIGMA step | Method lineage | SIGMA-specific part |
|---|---|---|
| Road shortest paths | Dijkstra (1959); SciPy implementation (Virtanen et al., 2020) | projected-road policy, shared-vertex topology, batching, guards |
| Network clustering | HDBSCAN* (Campello et al., 2013, 2015); network clustering precedent Yiu & Mamoulis (2004), Wang et al. (2019) | bounded sparse neighbor engine, adaptive-radius diagnostic, deterministic tie treatment, fallbacks |
| Cluster center | network median/location theory (Hakimi, 1964, 1965; Handler & Mirchandani, 1979; Kariv & Hakimi, 1979) | current pipeline restricts candidate center to road nodes; centroid recovery path |
| Network territories | graph/network Voronoi (Erwig, 2000; Hakimi, Labbé & Schmeichel, 1992; Okabe et al., 2008; Okabe & Sugihara, 2012) | boundary grid rendering, refinement policy, Euclidean fallback |
| IO coefficients | standard input-output coefficient convention $a_{ij}=z_{ij}/x_j$ | economy packaging and validation contracts |
| Optional sparse transaction support | maximum-weight acyclic-subgraph idea + RAS/IPF balancing | deterministic fast MWAS heuristic, feasibility repair order, exact support contract |
| Directed Katz | Katz (1953) | common safe alpha scaling and exact software conventions |
| Sender/receiver coupling | Sharkey (2017); related directed in/out coupling Everett & Schoch (2022); HITS precedent Kleinberg (1999) | $\sqrt{K^{in}K^{out}}$ monotone rescaling and one final L2 normalization |
| Point score | — | cluster-p90 bounded linear distance tempering |
| Place reconciliation | standard geographic/name-record linkage ingredients | exact thresholds, candidate-strength weighting, greedy deterministic match policy |

## A note on `net-hdbscan`, `net-voronoi`, and `net-center`

Those repositories were used as methodological reference implementations and contain fuller standalone discussions of their respective methods. Unified SIGMA contains its own internal implementation and does not need them as runtime dependencies. Where SIGMA deliberately uses a narrower method—for example the network-node 1-median rather than every center problem implemented by `net-center`—this book describes the narrower SIGMA behavior.

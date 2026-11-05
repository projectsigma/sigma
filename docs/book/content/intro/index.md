# SIGMA: from establishments to a spatial-economic influence network

SIGMA is a reproducible pipeline for turning observed establishments, a road network, and an input-output economy into a **spatial-economic graph** and point-level influence scores.

This book documents the model as it is implemented. Its purpose is not merely to tell you which command to run. It spells out the transformations, equations, assumptions, fallbacks, and provenance of the methods so that a SIGMA result can be inspected as a chain of explicit analytical decisions.

For hands-on exploration after a run, **[SIGMA Explorer](explorer.md)** provides a browser map connected to the directed cluster-level X graph. Select a mapped establishment to examine the network neighborhood of its assigned economic-type cluster and highlight SIGMA's computed road paths; Explorer visualizes already-published results and does not alter the model.

The canonical workflow is

```text
OSM + Overture establishments ──> reconcile ──> PSIC / IO candidates
                                                    │
PSA 2018 IO240 hierarchy ──> sigma load: baseline sparse local sectors
                                                    │
road graph ──> snap ──> baseline network HDBSCAN* (sector K counts)
                                                    │
             generated hierarchy only: K=0 residual-first roll-up
                         (recluster affected effective sectors)
                                                    │
                         retained HDBSCAN clusters + noise
                                                    │
                  network Gap k-medoids, one pass (4 workers)
                  (only retained clusters; noise remains noise)
                                                    │
                              final child clusters
                                    │           │
                       network-node 1-medians  network Voronoi
                                    └─────┬─────┘
                                          │
IO transactions ──> effective sector coefficients ──> spatial-economic X
                                          │
                                balanced directed Katz
                                          │
                                distance-tempered scores
```

The Gap refinement step is **on by default** for canonical runs (including
fixed IO-level areas). Hierarchical iterative roll-up is a separate, conditional
run-stage policy only for generated hierarchies; it evaluates **unrefined**
HDBSCAN cluster counts before Gap. Final medians are recalculated for every
accepted child, but Gap does **not** repeatedly rerun on those children.
See [Gap refinement](../methods/network_gap_medians.md) and
[Hierarchical economy](../methods/hierarchical.md).

The diagram is a conceptual **dependency sequence**, not a direct code-stage
DAG. It separates the baseline HDBSCAN K=0 test used for conditional economic
roll-up from the subsequent single-pass Gap subdivision and the final
network 1-medians. Its X stage uses numerical road distances without route
geometries; the default Explorer draws shortest road routes on request from a
compact published graph. [The X graph](../methods/x_graph.md) describes the
route publication modes. The default is deliberately conservative: deterministic place classification, no LLM requirement, no transaction preprocessing, the full directed economic graph, road-network-first spatial methods, and a balanced directed Katz score. New areas loaded with `sigma load AREA` use a per-area hierarchical PSA 2018 IO240/IO80/IO16 economy; legacy unselected IO80 workspaces retain IO80 until explicitly reloaded. The X graph does not identify observed suppliers: its directed links combine input-output coefficients, positive-area spatial partition overlap, connected 1-medians, clustered-sector shares, and mean hub-mediated road-distance attenuation.

```{admonition} What is a SIGMA node?
:class: note
A node of the final graph is not an individual establishment. It is a **spatial cluster of establishments of one economic type**, identified by `(type, cluster)`. Establishments receive their final score from the centrality of that cluster, tempered by their road distance from the cluster center.
```

<!-- sigma-docs-20261104-v1:begin -->
**Current hierarchical run behavior:** `sigma load AREA` creates the
baseline IO240/IO80/IO16 partition. A normal `sigma run AREA` on that
generated hierarchy can perform residual-first **zero-cluster** (`K=0`)
iterative roll-up after the baseline HDBSCAN evaluation. The baseline is
available using `sigma run AREA --no-iterative-rollup`; no clusters are
fabricated for individual noise points. The resulting effective economic
sectors determine X and scoring, while each establishment's original sector
code is retained separately for provenance and Explorer point presentation.

The local Explorer uses a fixed 336-color hierarchical palette and can
reveal rolled-up original industries, unclustered points within the selected
network's published Voronoi polygons, and a sector-colored hover outline
for an individual cluster's partition. These are **display operations**, not
additional cluster assignments or supplier relationships.
<!-- sigma-docs-20261104-v1:end -->

## Reading the book

If you want to run SIGMA first, start with [Quickstart](quickstart.md). If you want the model specification, read [End-to-end workflow](../workflow/end_to_end.md) and then the method chapters in order. The [Method lineage](../reference/method_lineage.md) page distinguishes published algorithms from SIGMA-specific implementation rules; the [References](../reference/references.md) page consolidates the published literature supporting the methods used by SIGMA.

## Scope of the mathematical specification

The equations in this book describe the current `sigma` source tree. When the implementation contains a recovery path, the primary method and the fallback are documented separately. In particular:

- clustering is HDBSCAN* on sparse bounded **road-network distance**, with a Euclidean recovery path only after network clustering fails;
- cluster centers are exact **network-node 1-medians**, with a centroid-to-road-to-node recovery path;
- network Voronoi ownership is exact on the 1-D road graph, while its published polygon layer is a finite-resolution **2-D rendering** of that ownership;
- the default economy preserves the full directed technical-coefficient graph; optional `mwas_ras_fast` changes the transaction table before coefficients are recomputed;
- canonical centrality is a SIGMA geometric-mean rescaling of paired incoming/outgoing Katz scores, grounded in the sender-receiver Katz product literature rather than presented as a separately published named index.

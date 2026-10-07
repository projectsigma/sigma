# SIGMA: from establishments to a spatial-economic influence network

SIGMA is a reproducible pipeline for turning observed establishments, a road network, and an input-output economy into a **spatial-economic graph** and point-level influence scores.

This book documents the model as it is implemented. Its purpose is not merely to tell you which command to run. It spells out the transformations, equations, assumptions, fallbacks, and provenance of the methods so that a SIGMA result can be inspected as a chain of explicit analytical decisions.

The canonical workflow is

```text
area boundary
   │
   ├── OSM places ─────┐
   │                   ├─ canonical places ─ PSIC ─ economic type
   └── Overture places ┘                         │
                                                 ▼
shared OSM roads ─ snap ─ network HDBSCAN* ─ clusters
                                      │             │
                                      │             ├─ network 1-median centers
                                      │             └─ network-Voronoi surface partitions
                                      │
IO transactions ─ technical coefficients ─ directed economic graph
                                      │
                                      └─────────────┐
                                                    ▼
                                      directed spatial-economic X graph
                                                    │
                                      balanced sender-receiver Katz
                                                    │
                                      distance-tempered point scores
```

The default is deliberately conservative: deterministic place classification, no LLM requirement, no transaction preprocessing, the full directed economic graph, road-network-first spatial methods, and a balanced directed Katz score.

```{admonition} What is a SIGMA node?
:class: note
A node of the final graph is not an individual establishment. It is a **spatial cluster of establishments of one economic type**, identified by `(type, cluster)`. Establishments receive their final score from the centrality of that cluster, tempered by their road distance from the cluster center.
```

## Reading the book

If you want to run SIGMA first, start with [Quickstart](quickstart.md). If you want the model specification, read [End-to-end workflow](../workflow/end_to_end.md) and then the method chapters in order. The [Method lineage](../reference/method_lineage.md) page distinguishes published algorithms from SIGMA-specific implementation rules; the [References](../reference/references.md) page consolidates the published literature supporting the methods used by SIGMA.

## Scope of the mathematical specification

The equations in this book describe the current `sigma` source tree. When the implementation contains a recovery path, the primary method and the fallback are documented separately. In particular:

- clustering is HDBSCAN* on sparse bounded **road-network distance**, with a Euclidean recovery path only after network clustering fails;
- cluster centers are exact **network-node 1-medians**, with a centroid-to-road-to-node recovery path;
- network Voronoi ownership is exact on the 1-D road graph, while its published polygon layer is a finite-resolution **2-D rendering** of that ownership;
- the default economy preserves the full directed technical-coefficient graph; optional `mwas_ras_fast` changes the transaction table before coefficients are recomputed;
- canonical centrality is a SIGMA geometric-mean rescaling of paired incoming/outgoing Katz scores, grounded in the sender-receiver Katz product literature rather than presented as a separately published named index.

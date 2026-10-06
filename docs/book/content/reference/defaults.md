# Canonical defaults

These are the main current defaults exposed by `SigmaConfig`.

## Places

| Parameter | Default |
|---|---:|
| clip to area | `True` |
| use LLM | `False` |
| deterministic retrieval `top_n` | 5 |
| minimum classification score | 0.45 |
| minimum margin | 0.12 |

## Spatial

| Parameter | Default |
|---|---:|
| `vertex_digits` | 11 |
| `min_cluster_size` | 5 |
| `min_samples` | `None` → cluster size |
| cluster selection | `eom` |
| allow single cluster | `False` |
| HDBSCAN max distance | 5,000 m |
| HDBSCAN distance mode | `adaptive` |
| distance growth | 1.5 |
| distance steps | 4 |
| core truncation tolerance | 0.01 |
| membership stability tolerance | $10^{-12}$ |
| max neighbor pairs | 20,000,000 |
| Voronoi surface resolution | 500 m |
| max Voronoi cells | 1,000,000 |
| Voronoi refine factor | 0.5 |
| max refinements | 5 |

## Economy

| Parameter | Default |
|---|---:|
| transaction preprocessing | `none` |
| RAS absolute tolerance | $10^{-8}$ |
| RAS relative tolerance | $10^{-10}$ |
| RAS max iterations | 10,000 |

## Analysis

| Parameter | Default |
|---|---:|
| centrality | `katz` |
| Katz alpha factor | 0.85 |
| Katz beta | 1.0 |
| distance tempering | 0.15 |

## Managed roads

| Policy | Current value |
|---|---|
| boundary buffer | 5,000 m |
| projection | local UTM inferred from boundary bbox centroid |
| graph direction | undirected |
| OSM oneway | retained as metadata only |
| simplification | none |

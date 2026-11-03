# Canonical defaults

These are the main current defaults exposed by `SigmaConfig`.
**Economy-resolution selection is a CLI/workspace policy, not a field of
`SigmaConfig`:** `sigma load AREA` defaults to a per-area hierarchical
IO240/IO80/IO16 economy (packaged IO240 reference, `min_places=5`,
`coarse_policy=residual` for new profiles). Explicit `--io-level 16|80|240`
selects a fixed national resolution; `--economy` chooses a custom system.
`Economy.default()` and unselected legacy areas continue to use IO80.
`sigma run` honors the area's recorded load choice instead of silently
migrating it. See [Hierarchical economy](../methods/hierarchical.md).

<!-- sigma-docs-20261104-v1:begin -->
## Hierarchical run and Explorer presentation defaults

| Policy | Current behavior |
|---|---|
| Generated hierarchical economy at `sigma load` | Build baseline sparse IO240/IO80/IO16 classification; no spatial roll-up during load |
| `sigma run AREA` on generated hierarchy | Iterative roll-up **on** by default, triggered only when a sector has `K=0` retained HDBSCAN clusters |
| `sigma run AREA --no-iterative-rollup` | Preserve the original hierarchical economic partition |
| Fixed IO16, IO80, IO240, custom/equivalent runs | No implicit iterative roll-up |
| Built-in sector colors | Exact 336-color fixed lookup (16/80/240); nearest parent color for `o` residuals |
| Explorer Strongest selector | 3 links per explored cluster |
| Explorer original roll-up children | Collapsed initially; independently filter establishment points only |
| Explorer contextual unclustered overlay | Off until opted into; focused 0.96, depth `d`: `0.90/sqrt(d)` |
| Explorer hovered center outline | Display-only, in sector color, when a selection is active |

This CLI default is an **economy/workspace-specific policy**. It is not a
`SigmaConfig` constant and does not change HDBSCAN's `min_cluster_size=5`.
<!-- sigma-docs-20261104-v1:end -->

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
| X inverse-distance exponent `x_distance_decay_lambda` | 1.0 |
| X distance floor | 1 metre |
| X effective separation | center road distance + source mean road radius + target mean road radius |
| X cluster size shares | cluster members / all clustered members in the identical economic type, at each endpoint |
| distance tempering (establishments) | 0.15 |

## Managed roads

| Policy | Current value |
|---|---|
| boundary buffer | 5,000 m |
| projection | local UTM inferred from boundary bbox centroid |
| graph direction | undirected |
| OSM oneway | retained as metadata only |
| simplification | none |

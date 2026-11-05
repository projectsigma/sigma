# Canonical defaults

These are the main defaults, grouped by pipeline stage. Most are fields of `SigmaConfig`. **Economy-resolution selection is a CLI/workspace policy, not a field of `SigmaConfig`:** `sigma load AREA` defaults to a per-area hierarchical IO240/IO80/IO16 economy; `--io-level 16|80|240` selects a fixed national resolution and `--economy` a custom system. The Python API's `Economy.default()` and a workspace without a recorded selection use IO80. `sigma run` follows the area's recorded load choice instead of migrating it. See [Hierarchical economy](../methods/hierarchical.md).

## Sector policies (stages 5 and 9) and presentation

| Policy | Default |
|---|---|
| Economy for a new area (`sigma load`) | per-area hierarchical PSA 2018 IO240/IO80/IO16 |
| `min_places` (stage 5) | 5 |
| `coarse_policy` (stage 5) | `residual` (`contain` optional) |
| `max_straddle_share` (stage 5, `contain` only) | 0.25 |
| `check_psa` (stage 5) | `true` |
| Zero-cluster roll-up (stage 9) | **on** for generated hierarchies; acts only on sectors with `K=0` retained HDBSCAN* clusters; `--no-iterative-rollup` disables it |
| Fixed IO16/IO80/IO240, custom and `--equivalent` runs | no roll-up |
| Route publication (`--route-geometry`) | `browser`: compact routing graph, routes drawn on request (`precomputed` optional) |
| Built-in sector colors | exact 336-color lookup (16/80/240); `o` residuals use the parent color |
| Explorer Strongest selector | 3 links per explored cluster |
| Explorer original roll-up children | collapsed initially; filter establishment points only |
| Explorer unclustered overlays | two independent opt-ins, both initially off; scored-sector points use selected matching-sector Voronoi polygons; hollow circle sized by sector scored minimum (global fallback); no depth-based opacity |
| Explorer hovered center outline | display only, in sector color, when a selection is active |

The stage 5 settings live in `<SIGMA_HOME>/hierarchical-defaults.json` (written by the first hierarchical `sigma load`; change them with `sigma economy hierarchical-configure`). The roll-up default is a CLI policy for generated hierarchies, not a `SigmaConfig` constant. Gap refinement, in contrast, is a `SigmaConfig` default that applies to every selected economy except the legacy `--equivalent` profile. Neither changes HDBSCAN*'s `min_cluster_size=5`.

## Places (stages 1–4)

| Parameter | Default |
|---|---:|
| clip to area | `True` |
| use LLM | `False` |
| deterministic retrieval `top_n` | 5 |
| minimum classification score | 0.45 |
| minimum margin | 0.12 |

## Spatial (stages 6–12)

| Parameter | Default |
|---|---:|
| `vertex_digits` | 11 |
| `min_cluster_size` | 5 |
| Network Gap k-medoids refinement | **on** (canonical; `--no-median-gap` disables; legacy `--equivalent` off) |
| Network Gap worker limit | **4** (configurable 1–4; actual processes may be fewer) |
| Network Gap passes | **1** per retained original HDBSCAN cluster (no recursion) |
| Network Gap maximum tested k | 6 |
| Network Gap reference draws | 10 |
| Network Gap fitted observations per HDBSCAN cluster | 64 maximum |
| Network Gap seed | 20261105 (per cluster: SHA-256 of seed, sector, cluster) |
| Network Gap minimum child size | `min_cluster_size` (5) |
| Network Gap eligibility | at least `2 × min_cluster_size` members and 3 distinct road positions |
| `min_samples` | `None` → cluster size |
| cluster selection | `eom` |
| allow single cluster | `False` (so a sector needs a split into two groups of at least `min_cluster_size` to keep any cluster) |
| HDBSCAN max distance | 5,000 m |
| HDBSCAN distance mode | `adaptive` |
| distance growth | 1.5 |
| distance steps | 4 |
| core truncation tolerance | 0.01 |
| membership stability tolerance | $10^{-12}$ |
| max neighbor pairs | 20,000,000 |
| Voronoi start resolution (`--voronoi-resolution`) | 50 m (coarser only when the grid would exceed the cell budget) |
| max Voronoi candidate cells (bounding box of the study boundary) | 1,000,000 |
| Voronoi refine factor | 0.5 |
| max refinements | 5 (at most six renderings per sector) |
| Voronoi convergence tolerance | 0.005 changed-owner area fraction (code constant) |

## Economy (stage 13)

| Parameter | Default |
|---|---:|
| transaction preprocessing | `none` |
| RAS absolute tolerance | $10^{-8}$ |
| RAS relative tolerance | $10^{-10}$ |
| RAS max iterations | 10,000 |

## Analysis (stages 14–17)

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

## Managed roads (stage 6)

| Policy | Current value |
|---|---|
| boundary buffer | 5,000 m |
| projection | local UTM inferred from boundary bbox centroid |
| graph direction | undirected |
| OSM oneway | retained as metadata only |
| simplification | none |

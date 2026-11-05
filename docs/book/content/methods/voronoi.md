# Network Voronoi ownership and 2-D surface partitions (stage 12)

*Pipeline stage 12 of 17 · `sigma run`. Under the Hood shows the multi-source search, the split point inside an edge and the grid rendering (section “Stage 12”).*

For each sector separately, every road position is owned by the nearest member of one of the sector's **final** clusters (after stages 8–10). SIGMA needs two related but distinct objects:

1. **exact ownership on the one-dimensional road graph**, and
2. a polygon surface that allows spatial overlap tests between clusters of different economic types.

Keeping those objects distinct avoids overclaiming what a finite-resolution polygon layer represents.

## Exact network ownership

For one economic type, cluster-member network nodes act as sources. Multi-source Dijkstra computes the distance from every reachable road node to the nearest source and assigns the corresponding cluster label. Ties are resolved deterministically by the smaller cluster label.

This is a graph/network Voronoi construction in the lineage of Erwig (2000), Hakimi, Labbé & Schmeichel (1992), Okabe et al. (2008), and the network-analysis treatment of Okabe & Sugihara (2012).

### Ownership within an edge

Consider a road edge $(u,v)$ of length $L$. Let $D_u$ and $D_v$ be the already-computed distance from the nearest source associated with the owners at endpoints $u$ and $v$. At offset $t$ from $u$, competing route distances are

$$
D_u+t
\quad\text{and}\quad
D_v+L-t.
$$

Their equality occurs at

$$
t^*=\frac{D_v+L-D_u}{2},
$$

clipped to $[0,L]$. This determines the owner on the interior of an edge when the endpoint owners differ. Exact ties are resolved deterministically.

## Rendering a 2-D polygon surface

Economic relations are later instantiated when partitions of two types have **positive-area overlap**. A one-dimensional road Voronoi object therefore has to be rendered into area.

SIGMA overlays a regular grid on the exact study boundary. For each positive-area grid cell, a representative point is attached to the nearest **source-reachable** road edge. The owner at that continuous edge location is read from the exact network-Voronoi distances above. Cells are then dissolved by `(type, cluster)`.

The grid spacing (the side length of one cell) is chosen separately for each sector. It starts at 50 m and is halved until little area changes owner from one grid to the next, within a cell budget; {ref}`the next section <voronoi-grid-spacing>` gives the rule.

```{admonition} Important interpretation
:class: warning
The ownership decision attached to each cell is network-based, but the resulting polygon boundary is a finite-resolution **rendering**. It should not be described as an exact planar network Voronoi boundary. Convergence (below) means that the rendering has stopped depending much on the grid spacing; it does not make the polygon an exact planar boundary.
```

(voronoi-grid-spacing)=
## Choosing the grid spacing

**The question.** How fine must the grid be before the polygons stop depending on it? Each cell takes one owner, so a cell crossed by a territory boundary is still assigned to just one cluster, and a narrow territory can receive no cell at all. Graph X (stage 14) creates an edge only where the territories of two sectors overlap with positive area, so the spacing can add or remove X edges. A finer grid reduces this effect, but each halving of the spacing needs about four times as many cells.

**The rule.** For each sector separately, SIGMA:

1. **Starts** at `--voronoi-resolution`, **50 m** by default.
2. **Checks the cell budget before building any cell.** The candidate-cell count is the number of grid squares that cover the bounding box of the study boundary, $\lceil \text{width}/s \rceil \times \lceil \text{height}/s \rceil$ for spacing $s$. It must not exceed `voronoi_max_cells` (1,000,000). If the start spacing needs more cells than that, SIGMA doubles the spacing until the count fits and then bisects between the last spacing that did not fit and the first that did, so it approaches the finest budget-feasible spacing (12 bisections) instead of stopping at the next doubling. For example, a 60 km × 80 km bounding box needs 1,920,000 cells at 50 m; SIGMA starts at about 69.3 m (999,364 cells), not at 100 m.
3. **Refines even after a success.** A grid that gives every cluster at least one cell is *valid*, but validity does not show that the spacing is fine enough. SIGMA therefore halves the spacing (`voronoi_refine_factor` = 0.5), renders again and compares the two valid surfaces ({ref}`changed-owner area <voronoi-changed-owner-area>`). If a grid gives no cell to some cluster, SIGMA halves the spacing without a comparison.
4. **Stops** at the first of these: the comparison shows convergence; the next finer grid would exceed the cell budget; a finer rendering fails for a reason other than a cluster without cells; or five refinements have been made (`voronoi_max_refinements`; at most six renderings, for example 50, 25, 12.5, 6.25, 3.125 and 1.5625 m). In every case SIGMA keeps the **finest valid network surface** it has produced. A failure at a finer spacing never discards a valid coarser surface, and the Euclidean fallback is used only when the sector has no valid network surface.

(voronoi-changed-owner-area)=
### Changed-owner area

The comparison asks: what share of the study area changed its owning cluster between the previous valid grid and the new one? For one sector, let $P_c$ be the polygon of cluster $c$ at the previous spacing and $P'_c$ the polygon of the same cluster at the new spacing. Each surface covers the whole study boundary and its polygons do not overlap, so the area that kept its owner is $\sum_c |P_c \cap P'_c|$, where $|\cdot|$ is area. The **changed-owner area fraction** is

$$
\Delta = 1-\frac{\sum_c |P_c \cap P'_c|}{\sum_c |P_c|}.
$$

$\Delta = 0$ means that the two grids assign every location to the same cluster. The sector has **converged** when $\Delta \le 0.005$ (0.5 % of the area), and SIGMA keeps the finer of the two surfaces. The tolerance is a code constant (`VORONOI_CONVERGENCE_TOLERANCE`), not a CLI option. The comparison is made cluster by cluster because the union of all polygons is always the study boundary; a comparison of the union alone would always report no change.

*Where the measure works.* Suppose a sector's clusters share a 10 km² study area, and moving from 50 m to 25 m changes the owner of a strip of 0.03 km². Then $\Delta = 0.003 \le 0.005$, and the sector stops at 25 m.

*Where the measure is weak.* $\Delta$ is a share of the **whole** study area, not of each cluster's territory. In a 100 km² area, 0.5 % is 0.5 km², so a cluster with a 0.4 km² territory could change most of its territory while the sector still counts as converged. $\Delta$ also compares only two valid grids: it indicates limited change at that step, not an exact planar boundary or stability of Graph X edges. Since X tests positive-area overlap, even a small area change can create or remove an edge.

### How far the cell budget allows refinement

Because each halving needs about four times as many cells, the default budget limits how many comparisons are possible. The bounding box, and therefore this limit, is the same for every sector of a study area. For an approximately square bounding box:

| Bounding-box area of the study boundary | Finest spacing reachable | Renderings | Comparisons |
|---|---:|---:|---:|
| up to about 2.4 km² | 1.5625 m | 6 | 5 |
| up to about 9.8 km² | 3.125 m | 5 | 4 |
| up to about 39 km² | 6.25 m | 4 | 3 |
| up to about 156 km² | 12.5 m | 3 | 2 |
| up to about 625 km² | 25 m | 2 | 1 |
| up to about 2,500 km² | 50 m | 1 | 0 |
| above about 2,500 km² | coarser than 50 m | 1 | 0 |

These are upper limits; a sector usually stops earlier when it converges. When no comparison is possible, the sector keeps its first valid surface, which has **not** been checked for convergence; its diagnostics record `retain_last_valid_network_resolution`. If that first grid gives no cell to some cluster, no finer grid fits either, and the sector uses the Euclidean fallback (`grid_budget_cluster_conflict`, then `fallback_euclidean_voronoi`).

Different sectors can stop at different spacings. Graph X then tests overlap between polygons rendered at different spacings.

(voronoi-spacing-audit)=
### Diagnostics

`partition_diagnostics.json` in the `spatial.partitions` artifact gives, for each cluster, `surface_resolution`: the spacing of the surface that was kept. Because the finer surface is kept, a sector that converged at the first comparison reports 25 m, not 50 m; a fallback surface reports no spacing. The `events` list records how the spacing of each sector was chosen. In a canonical run the actions are:

| `action` | `status` | Meaning |
|---|---|---|
| `converged_resolution` | `converged` | $\Delta$ is at most the tolerance; records `changed_owner_area_fraction`, `convergence_tolerance` and `used_resolution` |
| `retain_last_valid_network_resolution` | `bounded` | the next finer grid exceeded the cell budget or failed; the last valid network surface is kept |
| `max_refinements_reached` | `bounded` | five refinements were made without convergence; the finest surface is kept |
| `coarsened_grid_budget` | `adjusted` | the start spacing needed more cells than the budget; records the spacing used and its `candidate_cells` |
| `refined_resolution` | `recovered` | a grid gave no cell to some cluster, and a finer grid succeeded |
| `grid_budget_cluster_conflict` | `bounded` | a grid gave no cell to some cluster, and the next finer grid exceeds the budget; no network surface |
| `fallback_euclidean_voronoi` | `recovered` | the planar fallback below was used |
| `euclidean_voronoi_duplicate_centers_use_raw_centroids` | `recovered` | the fallback substituted raw centroids for coincident centers |
| `skip_type_after_euclidean_voronoi_failure` | `skipped` | the fallback also failed; the sector has no partitions |

Every sector with a network surface ends with exactly one of `converged_resolution`, `retain_last_valid_network_resolution` or `max_refinements_reached`, so a non-empty event list is normal and is not by itself a warning. SIGMA's progress output also prints each comparison (`compared resolution …; changed-owner area=…`).

### Cost, resumption and reproducibility

A 50 m grid has 100 times as many cells as a 500 m grid, and each refinement has about four times as many as the one before. Stage 12 therefore takes longer than in earlier SIGMA versions, which started at 500 m and kept the first valid grid. Work that does not depend on the spacing is shared: the network Voronoi of a sector is computed once for all of its renderings, and a grid is reused by later sectors while the cached grids stay within the cell budget.

A sector is written as one savepoint unit only after its refinement has ended. A resumed run reuses a saved sector without rendering any spacing again; a sector that was interrupted during refinement restarts from its start spacing.

The `spatial.partitions` recipe records the start spacing, `max_cells`, `refine_factor`, `max_refinements` and the convergence tolerance. Changing `--voronoi-resolution` recomputes `spatial.partitions` and the stages that depend on it (graph X, centrality, scores and export); clusters and centers are reused. The stage's implementation version changed together with this rule, so a workspace computed with the earlier rule recomputes stage 12 and the later stages on its next `sigma run`. `--voronoi-resolution` sets only the start spacing: `--voronoi-resolution 500` restores the earlier start but not the earlier stopping rule. The legacy `--equivalent` profile uses the same 50 m start.

## Browser highlighting and unclustered contextual points

The Explorer may temporarily outline the **published** polygon for a hovered
cluster-center triangle once a cluster or scored establishment is selected.
This is a MapLibre line layer filtered by the existing X-node ID and colored
from the fixed sector palette; it does not alter 1-D network ownership or
reconstruct polygons. The outline can be shown even while the ordinary
partition-polygon display is off.

With a scored establishment or cluster selected, the opt-in
**Show unclustered for scored sectors** checkbox uses the published 2-D polygons as a
spatial inclusion test. It shows unclustered establishments only within the focus or
linked partitions **of their own
effective economic sector**. With no selection, the same checkbox shows all eligible
unclustered establishments of scored sectors, without a polygon test. The independent
**Show unscored sectors** checkbox operates only without a selection and only on sectors
with zero clusters. Both are initially off; their hollow-circle opacity does not vary
with network depth. A point may geographically fall in overlapping polygons of different
economic sectors, but Explorer tests it only against polygons of its **own** effective sector.
Neither containment nor display assigns HDBSCAN membership, changes a network Voronoi owner,
creates X edges, or infers a SIGMA score. Each polygon remains a finite-grid approximation
of network ownership, not an exact planar road-network boundary.

## Euclidean recovery fallback

If a sector has no valid network surface after its network-Voronoi rendering attempts, SIGMA may construct an ordinary planar Euclidean Voronoi surface from final cluster-center coordinates. If centers coincide, it first substitutes raw projected cluster centroids for only those coincident sites. This path is explicitly labeled `euclidean_voronoi_fallback`.

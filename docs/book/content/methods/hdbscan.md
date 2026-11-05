# Network HDBSCAN*: discovering localized ecosystems (stage 8)

*Pipeline stage 8 of 17 · `sigma run`. Under the Hood computes core distances, the minimum spanning tree, the ε cut and EOM selection on a worked example (section “Stage 8”).*

Stage 8 produces the **baseline** clusters of every sector. Two later stages build on it: for generated hierarchies, [zero-cluster roll-up](iterative_rollup.md) (stage 9) uses the unrefined labels of this stage to decide which sectors with `K=0` merge into a residual; then [network Gap refinement](network_gap_medians.md) (stage 10, on by default) can split retained clusters once. HDBSCAN* noise is never reassigned by either stage. `--no-median-gap` keeps the clusters of this stage as final; the legacy `--equivalent` profile does so by default.

SIGMA clusters establishments **separately for each economic type**. The clustering model is HDBSCAN*, but its pairwise distance is shortest-path distance on the supplied road network rather than Euclidean distance.

The implementation lineage is HDBSCAN* (Campello, Moulavi & Sander, 2013; Campello et al., 2015) plus network-constrained clustering (Yiu & Mamoulis, 2004; Wang et al., 2019).

## Distinct network positions and weights

Several establishments can snap to the same exact network position. SIGMA compresses such duplicate positions for the distance search and carries their multiplicity as an integer weight $w_p$.

Let $k$ be `min_samples` (default: `min_cluster_size`, itself default 5).

## Core distance

The weighted core distance is

$$
\operatorname{core}(p)=
\min\left\{r\ge0:\sum_{q:\,d(p,q)\le r}w_q\ge k\right\}.
$$

If the reachable weight within the current search horizon never reaches $k$, the core distance is infinite at that trial.

## Mutual reachability

For two retained positions,

$$
d_{mr}(p,q)=\max\{\operatorname{core}(p),\operatorname{core}(q),d(p,q)\}.
$$

HDBSCAN* constructs the hierarchy from the minimum spanning forest of finite mutual-reachability edges. Writing $\lambda=1/d_{mr}$, dense structure appears at larger $\lambda$.

## Cluster stability

For a cluster $C$,

$$
S(C)=\sum_{p\in C}w_p\bigl(\lambda_p-\lambda_{birth}(C)\bigr).
$$

The default `eom` selection keeps a cluster when its stability dominates the selected descendants according to the HDBSCAN* excess-of-mass rule. `leaf` selection is also available.

For a point position $p$ assigned to selected cluster $C$, membership strength is

$$
P(p\mid C)=
\frac{\min\{\lambda_p,\lambda_{max}(C)\}}{\lambda_{max}(C)},
$$

with the implementation's conventional handling of zero/infinite limiting cases; noise receives zero membership.

## Sparse bounded distance horizon

`hdbscan_max_distance` is a **search/truncation horizon**, not DBSCAN `eps`. Only pairs with $d(p,q)\le R$ are stored.

Default `distance_mode="adaptive"` evaluates an increasing geometric ladder. With ceiling $R$, growth $g$, and nominal step count $s$,

$$
r_0=\frac{R}{g^{s-1}},\qquad
r_{t+1}=\min(R,gr_t).
$$

Defaults are $R=5000$, $g=1.5$, $s=4$, so the intended ladder begins at about $0.296R$ and grows to $R$.

SIGMA may stop when two successive successful trials have identical flat labels and membership values within tolerance and the share of otherwise-resolvable observations with truncated core distance is at or below 1%. This is a **local stability diagnostic**, not a proof of invariance to every larger radius.

A hard default guard of 20,000,000 unordered neighbor pairs protects memory. If a larger adaptive trial exceeds the guard after a successful smaller trial, SIGMA can retain the last successful result with a `pair_cap_limited` diagnostic.

```{admonition} Published method vs SIGMA engineering
:class: important
Core distance, mutual reachability, hierarchy, stability, and EOM/leaf extraction are HDBSCAN* concepts. Sparse bounded network-neighbor construction, the adaptive radius stopping diagnostic, deterministic tie handling, pair caps, and the Euclidean recovery path are SIGMA implementation choices around that model.
```

## When a sector has zero retained clusters

With the default `allow_single_cluster = False`, the root of the condensed tree cannot be selected, so HDBSCAN* never returns a whole sector as one cluster. A sector keeps a cluster only when its density tree splits into at least two groups, each with at least `min_cluster_size` establishments. A sector with fewer than `2 × min_cluster_size` establishments (10 by default) therefore always has zero retained clusters (`K=0`), and so does a larger sector whose tree never splits into two groups of that size (for example two separated groups of 6 and 4).

A `K=0` result from a successful extraction is legitimate. It is not a Python exception and not evidence that the Euclidean fallback ran: the network EOM → network leaf → Euclidean rules below are recovery paths for **failures**, and they do not turn a successful zero-cluster output into clusters. For a generated hierarchical economy, stage 9 ([zero-cluster roll-up](iterative_rollup.md)) can merge such a sector into an existing residual when that strictly increases the number of retained establishments; `--no-iterative-rollup` keeps the baseline. Sectors with at least one retained cluster are never rolled up, whatever share of their establishments is noise. `--allow-single-cluster` changes this behavior for all sectors and is not the default.

## Fallback

The default extraction is **network HDBSCAN EOM**. If the HDBSCAN call raises
*after a road-distance neighbor graph has been constructed*, SIGMA retries
**network HDBSCAN leaf** on that **same sparse distance graph**, with the same
clustering parameters except `cluster_selection_method`. It does not rerun the
road-neighbor search for that retry. If both network selections fail, or the
neighbor search itself fails, SIGMA uses the existing **Euclidean HDBSCAN**
recovery path (EOM by default), separately within each connected road component (when
continuation is enabled). A run explicitly configured for leaf does not retry
leaf again.

A successful EOM result, even one with no clusters or oversized clusters, is
**not** an error and does not trigger fallback. The adaptive horizon's
last-successful-trial and pair-cap handling apply as described above. Audit fields identify
`network_hdbscan`, `network_hdbscan_leaf_fallback`, or
`euclidean_hdbscan_fallback`; the network leaf recovery also records the
original EOM exception in `eom_failure` and in a recovery event.

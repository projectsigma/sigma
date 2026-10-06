# Network HDBSCAN*: discovering localized ecosystems

SIGMA clusters establishments **separately for each economic type**. The clustering model is HDBSCAN*, but its pairwise distance is shortest-path distance on the supplied road network rather than Euclidean distance.

The implementation lineage is HDBSCAN* (Campello, Moulavi & Sander, 2013; Campello et al., 2015) plus earlier network-constrained clustering (Yiu & Mamoulis, 2004; Wang et al., 2019).

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

## Fallback

If the network HDBSCAN path fails for a type and continuation is enabled, SIGMA has a separately labeled Euclidean HDBSCAN recovery path scoped by road component. Audits should therefore inspect method/status fields rather than assuming every cluster came from the primary network metric.

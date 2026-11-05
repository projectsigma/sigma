# Network Gap k-medoids: optional post-HDBSCAN refinement

SIGMA can refine each **retained** Network HDBSCAN cluster into several
network-nearest-medoid cells, without rerunning HDBSCAN. This is **opt-in**:

```powershell
sigma run quezon_city --median-gap --refresh
```

Disable with `--no-median-gap` (the default). The original HDBSCAN cluster
label is recorded as `hdbscan_cluster` in the refined clustered-points artifact;
`cluster` is the final downstream label. Unclustered HDBSCAN observations
remain noise; there is **no invalidation** and no automatic reassignment of
noise. The feature works with generated hierarchy and the zero-cluster
iterative sector roll-up: the roll-up decision uses unrefined HDBSCAN, then
median refinement runs on the final economic partition.

## Selection method

The candidate sites for network **k-medoids** are the observed demand network
nodes. The objective, for retained observations $i$ at road vertices $q_i$,
is

$$J_k(C)=\min_{m_1,\ldots,m_k\in\{q_i\}}\sum_{i\in C}\min_j d_G(q_i,m_j).$$

Here $d_G$ is exact shortest-path distance on the augmented SIGMA road
network. Candidate medoids are constructed using deterministic greedy BUILD,
then improved by PAM-style SWAP until no strict improvement remains. This is
an **approximation**, not a certificate of the globally optimal k-median.
After partitioning, SIGMA's existing `spatial.centers` stage computes each
child's exact road-node **1-median** using the full road graph (not restricted
to observed establishments).

For each candidate $k$, SIGMA computes an adapted Gap statistic:

$$\mathrm{Gap}(k)=\frac{1}{B}\sum_{b=1}^B\log J^*_{k,b}-\log J_k.$$

The reference draws sample road **vertices** uniformly from the same road
component inside the observations' projected axis-aligned bounding rectangle.
It does *not* draw uniformly by roadway length, and this null model is not
in the canonical Euclidean Gap paper. The selected k is the first to satisfy
the Tibshirani-Walther-Hastie one-standard-error rule:

$$\mathrm{Gap}(k)\geq\mathrm{Gap}(k+1)-s_{k+1},\quad
s_k=\sqrt{1+1/B}\;\mathrm{sd}(\log J^*_{k,b}).$$

If no tested k satisfies the rule, the method selects the configured maximum
and records `upper_bound_reached`: the result is *search-bound-limited*, not
proof of global optimality. If $k=1$ is selected, the original HDBSCAN cluster
is preserved unchanged.

## Numerical and computational safeguards

Defaults are $B=10$, $k_\max=6$, at most 64 establishment observations
per HDBSCAN cluster used for medoid estimation, deterministic seed 20261105,
and minimum child membership equal to `--min-cluster-size` (default 5).
These are **practical tunable limits**, not canonical statistical constants.
Clusters larger than the sample limit use a reproducible sample for model
selection; **all establishments** are assigned afterward using exact network
shortest-path distance to the selected medoids. Results are approximate for
sampled clusters and should be interpreted accordingly. An inadmissible split
(children smaller than the configured minimum) reverts to the original cluster
with `no_admissible_partition`; it never silently deletes establishments.

CLI flags:

- `--median-gap` / `--no-median-gap`: opt in/out (default off)
- `--median-gap-max-k INTEGER`: search bound (default 6)
- `--median-gap-replicates INTEGER`: bootstrap reference repetitions (default 10)
- `--median-gap-max-sites INTEGER`: maximum observations per HDBSCAN cluster used in fit (default 64)
- `--median-gap-seed INTEGER`: reproducible random seed (default 20261105)

The immutable `spatial.clusters` artifact writes `median_gap_audit.json` when
refinement is enabled, containing per-parent selected k, outcome, original and
new labels, sampled vs full size, medoid sites, and the per-k Gap values.
The feature **changes cluster centers, network Voronoi partitions, X topology,
Katz centrality, and scores**. Existing X routing geometry is not a valid
weight-only reuse source when these spatial dependencies change; expect X to
rebuild. Use `sigma run AREA --median-gap --refresh` and then
`sigma view AREA --refresh` to publish the matching Explorer workspace.

## Scope and limitations

A uniformly dispersed cluster may legitimately select k=1. This model tests
**substructure relative to the chosen reference null**, not absolute cluster
compactness. Reference results depend on the road-vertex representation,
network topology, sample limit, and the choice of bounding rectangle. This is
not the original Euclidean Gap test and does not invalidate the HDBSCAN label.
The search is bounded; approximation and boundary statuses must be reported
rather than described as an unqualified global optimum.

## References

Tibshirani, R., Walther, G., & Hastie, T. (2001). Estimating the number of
clusters in a data set via the gap statistic. *JRSS B* 63(2), 411–423.
https://doi.org/10.1111/1467-9868.00293

Kaufman, L., & Rousseeuw, P. J. (1990). *Finding Groups in Data: An
Introduction to Cluster Analysis*. Wiley (Partitioning Around Medoids).

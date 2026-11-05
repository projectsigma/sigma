# Network Gap k-medoids refinement (stage 10)

*Pipeline stage 10 of 17 · `sigma run` · on by default. Under the Hood computes this stage live on a road example (section “Stage 10”).*

Network HDBSCAN* (stage 8) decides which establishments belong to a cluster. It can keep a long, dispersed cluster as one, for example a commercial corridor with two separate concentrations. Stage 10 asks once, for each retained HDBSCAN* cluster of the final sectors, whether several road medoids describe the cluster better than one. Where the network Gap statistic supports a split, the cluster is divided into network-nearest-medoid children.

```powershell
sigma run quezon_city                              # Gap on, up to four worker processes
sigma run quezon_city --no-median-gap              # unrefined HDBSCAN* clusters
sigma run quezon_city --median-gap-workers 1       # same method, serial
```

The refinement is **on by default** for every economy (generated hierarchy, fixed IO level or custom). The legacy `--equivalent` profile keeps unrefined clusters unless `--median-gap` is given. For generated hierarchies, stage 9 ([zero-cluster roll-up](iterative_rollup.md)) is decided first on unrefined labels; stage 10 then runs on the effective sectors. HDBSCAN* noise stays noise: there is no invalidation and no reassignment of noise.

## Which clusters are tested

Each retained HDBSCAN* cluster (sector `t`, cluster label `c`) is one independent task. A cluster is eligible only when:

- it has at least `2 × min_cluster_size` members (10 by default), because each child must later have at least `min_cluster_size` members; and
- its members occupy at least 3 distinct road positions.

An ineligible cluster is kept unchanged, without any shortest-path search or reference draw, with outcome `insufficient_members_for_split`, `one_site` or `insufficient_distinct_positions`.

## Within-cluster cost for k medoids

Members are represented by their road positions (the network nodes of their snap points); several members at the same position count with multiplicity. For a cluster that has more than `--median-gap-max-sites` members (64 by default), the medoids are fitted on a reproducible random sample of 64 members; all members are assigned afterwards.

For `k = 1, …, k_max` the cost is the total shortest road distance from each member to its nearest medoid, with medoids chosen among the members' own positions:

$$W_k=\min_{m_1,\ldots,m_k\in\{q_i\}}\ \sum_{i} w_i \min_{j\le k} d_G(q_i,m_j).$$

Here $d_G$ is the exact shortest-path distance on SIGMA's augmented road graph (computed by Dijkstra searches whose radius is enlarged until every needed target is reached), and $w_i$ is the multiplicity of position $q_i$. Medoids are found by deterministic greedy BUILD (add the medoid that lowers the cost most) followed by PAM-style SWAP (exchange a medoid while the cost strictly falls). This is an approximation, not a proof of the global optimum. The search bound is $k_\max=\min(6,\ \text{distinct positions}-1)$.

## Reference distribution and Gap statistic

$W_k$ always falls as $k$ grows, so its size alone cannot choose $k$. The Gap statistic compares it with structureless data on the same roads. SIGMA draws $B = 10$ reference samples. Each sample places the same number of members uniformly at random, with replacement, on the **road vertices** that lie inside the projected axis-aligned bounding box of the (sampled) member positions and in the same road component; the member positions themselves are part of this pool. The k-medoid search is repeated on each sample, giving $W^*_{k,b}$. Then

$$\mathrm{Gap}(k)=\frac{1}{B}\sum_{b=1}^B\log W^*_{k,b}-\log W_k,\qquad
s_k=\mathrm{sd}_b\!\left(\log W^*_{k,b}\right)\sqrt{1+1/B}.$$

The reference draws vertices uniformly, not road length uniformly. This road-vertex reference is SIGMA's adaptation; the published Gap statistic uses a uniform box in Euclidean space.

## Choosing k: the one-standard-error rule

SIGMA selects the smallest $k$ with

$$\mathrm{Gap}(k)\ \ge\ \mathrm{Gap}(k+1)-s_{k+1}$$

(Tibshirani, Walther and Hastie, 2001). If no $k < k_\max$ satisfies the rule, $k_\max$ is selected with outcome `upper_bound_reached`: the search bound was hit, which is not proof that more subdivision is justified. If $k = 1$ is selected, the cluster is kept unchanged.

## Assignment, admissibility and IDs

When $k \ge 2$ is selected:

1. **All** members (not only the sample) are assigned to the nearest selected medoid by exact road distance; ties go to the first medoid in sorted order.
2. If only one child receives members, or any child has fewer than `min_cluster_size` members, the split is rejected and the original cluster is kept (`no_admissible_partition`). No establishment is ever dropped.
3. The child that contains the first member (in `canonical_id` order) keeps the original cluster label. Other children receive new labels after the largest label already used in the sector.
4. Children are **not** tested again: this is a **single nonrecursive** model-selection pass. Stage 11 then computes an exact full-network 1-median for every final cluster; that is a location computation, not a second test.

The cluster recipe records the Gap settings, so changing them invalidates `spatial.clusters` and every downstream artifact. Splitting changes centers, network Voronoi partitions, X topology, Katz centrality and scores.

(outcomes-and-audit)=
## Outcomes and audit

The `spatial.clusters` artifact keeps the original HDBSCAN* label as `hdbscan_cluster` beside the final `cluster`, and writes `median_gap_audit.json` with the configuration (`max_k`, `replicates`, `max_sites`, `seed`, `min_members`) and one record per HDBSCAN* cluster:

| Field | Meaning |
|---|---|
| `type`, `hdbscan_cluster` | sector and original HDBSCAN* label |
| `observations`, `distinct_demand_nodes` | members and distinct road positions |
| `sampled_observations`, `sampled_approximation` | members used for fitting; true when a sample of 64 was used |
| `reference_vertex_pool` | number of road vertices available to the reference draws |
| `selected_k`, `outcome` | chosen k and the reason (table below) |
| `new_cluster_ids`, `selected_medoid_nodes` | final labels and medoid road nodes |
| `gap_by_k` | Gap(k) for every tested k |

| `outcome` | Meaning |
|---|---|
| `one_se_stopping_rule` | the rule selected k (k = 1 means unchanged) |
| `upper_bound_reached` | no k below the bound satisfied the rule |
| `no_admissible_partition` | a split was selected but a child was too small; cluster kept |
| `insufficient_members_for_split` | fewer than `2 × min_cluster_size` members |
| `one_site`, `insufficient_distinct_positions` | too few distinct road positions |
| `zero_one_median_loss` | all sampled members at one position (cost 0) |
| `insufficient_reference_support` | fewer than 3 road vertices for the reference |

## Defaults and options

| Option | Default | Meaning |
|---|---|---|
| `--median-gap` / `--no-median-gap` | on (off with `--equivalent`) | run or skip stage 10 |
| `--median-gap-max-k` | 6 | largest tested k |
| `--median-gap-replicates` | 10 | reference draws B |
| `--median-gap-max-sites` | 64 | members used for fitting per cluster |
| `--median-gap-seed` | 20261105 | base seed |
| `--median-gap-workers` | 4 (1–4) | maximum independent worker processes |

These are practical, tunable limits, not statistical constants. The minimum child size is `--min-cluster-size`.

## Reproducibility and parallel execution

Every cluster has its own random generator, seeded with the first 8 bytes of SHA-256 of `seed | sector | cluster`. Results therefore do not depend on the order in which clusters are processed. With `--median-gap-workers` greater than 1, SIGMA starts up to that many independent worker processes for eligible parallel tasks (spawned, so the same code runs on Windows); a single eligible task runs serially. Each worker receives the road adjacency, component labels and coordinates once, keeps its own shortest-path caches, and processes one cluster at a time; workers return only selections and assignments. The parent process assigns child labels in a fixed, sorted order. One to four workers give identical clusters, audit records and messages; the worker count is not part of the artifact recipe. More workers use more memory, and speed gains depend on the area.

Shortest paths are exact: the bounded Dijkstra search enlarges its radius until all needed targets are reached, so no road distance is truncated or replaced by a Euclidean distance. Progress messages are printed only for clusters that split.

## Scope and limitations

A uniformly dispersed cluster may legitimately select k = 1. The test detects substructure relative to the chosen reference, not absolute compactness. Results depend on the road-vertex representation, the network topology, the sample limit and the bounding box. The search is bounded and approximate, so `upper_bound_reached` and `sampled_approximation` must be reported rather than described as a global optimum. Subdividing one sector's clusters does **not** guarantee a smaller union of its Voronoi territories, fewer X overlaps or less concentrated Katz scores; those outcomes need direct empirical checks.

## References

Tibshirani, R., Walther, G., & Hastie, T. (2001). Estimating the number of
clusters in a data set via the gap statistic. *JRSS B* 63(2), 411–423.
https://doi.org/10.1111/1467-9868.00293

Kaufman, L., & Rousseeuw, P. J. (1990). *Finding Groups in Data: An
Introduction to Cluster Analysis*. Wiley (Partitioning Around Medoids).

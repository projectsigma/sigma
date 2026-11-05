# Cluster centers: the network-node 1-median (stage 11)

*Pipeline stage 11 of 17 · `sigma run`.*

After HDBSCAN* (stage 8), any zero-cluster roll-up (stage 9) and the [network Gap refinement](network_gap_medians.md) (stage 10, on by default; `--no-median-gap` disables it), SIGMA chooses one road-network node to represent **each final** `(economic type, cluster)`. If a retained HDBSCAN* cluster was split, each child receives its own full-network 1-median. These centers are not the observed-node medoids used during Gap model selection: the 1-median may be any road vertex of the cluster's component.

## Objective

Let a cluster contain demand nodes $q_1,\ldots,q_m$ on road graph $G_R$. For candidate road node $v$,

$$
M(v)=\sum_{i=1}^{m} d_R(q_i,v).
$$

The SIGMA center is

$$
v^*=\operatorname*{argmin}_{v\in V_R} M(v).
$$

This is the classical unit-weight **network-node 1-median** / minisum location problem. SIGMA computes demand-to-node shortest-path distances in batches and minimizes the column sum.

The key location-theory lineage is Hakimi (1964, 1965), Handler & Mirchandani (1979), and Kariv & Hakimi (1979). The current SIGMA pipeline uses the network-node 1-median objective; vertex and absolute 1-center objectives are outside the current pipeline.

## Interpretation

The network 1-median minimizes aggregate travel distance from all establishments in the cluster to one network node. It is therefore an accessibility center, not an arithmetic coordinate centroid and not the minimax network center.

## Recovery fallback

If the exact network-node 1-median fails and continuation is enabled, SIGMA:

1. computes the arithmetic centroid of the cluster's projected point coordinates;
2. finds the nearest road edge within the cluster's road component;
3. snaps the centroid to that road; and
4. selects the nearer endpoint network node, breaking exact ties by smallest node ID.

The output records `center_method`, so `network_1_median` can be separated from `euclidean_centroid_road_snap_fallback` in an audit.

# From cluster centrality to establishment scores

Centrality is defined at the `(economic type, cluster)` level. SIGMA transfers it to individual establishments with a bounded road-distance penalty.

For establishment $p$ in cluster $c$, let $d_p$ be its shortest-path road distance to the cluster center. Let

$$
Q_{0.90,c}=\text{90th percentile of }\{d_p:p\in c\}.
$$

Define a cluster-relative normalized distance

$$
q_p=\min\left(\frac{d_p}{\max(Q_{0.90,c},1)},1\right).
$$

For cluster centrality $C_c$ and distance-tempering parameter $\lambda\in[0,1]$,

$$
S_p=C_c(1-\lambda q_p).
$$

The default is $\lambda=0.15$.

Therefore every point score is bounded by

$$
C_c(1-\lambda)\le S_p\le C_c.
$$

At the default, the within-cluster distance adjustment can reduce a point by at most 15% relative to its cluster's centrality.

## Why use the cluster 90th percentile?

The 90th percentile supplies a robust cluster-specific scale rather than forcing every cluster to share one absolute distance. Capping at one prevents extremely distant points from receiving an unbounded penalty; the minimum denominator of 1 prevents division by zero or a sub-metre near-zero scale.

```{admonition} SIGMA-specific scoring rule
:class: important
The p90 normalization and linear tempering formula are model rules, not a standard centrality theorem. They intentionally make spatial position a secondary modifier of cluster-level structural importance rather than a second independent centrality calculation.
```

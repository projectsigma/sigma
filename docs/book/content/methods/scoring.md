# From cluster centrality to establishment scores (stage 17)

*Pipeline stage 17 of 17 · `sigma run`.*

Centrality is defined at the `(economic type, cluster)` level. Clusters receive the tile-area-adjusted balanced Katz score $C_i$ described in [Centrality](centrality.md). Retained establishments inherit the score of their cluster, attenuated by their own road-network distance to the cluster 1-median.

For establishment $p$ in cluster $c(p)$, let $d_R(p,m_{c(p)})$ be its shortest road distance in metres to the cluster 1-median. Then

$$
\boxed{S_i=C_i,\qquad
S_p=\frac{C_{c(p)}}{\max(d_R(p,m_{c(p)})/(1\,\mathrm m),1)}.}
$$

There is no p90 normalization, bounded 0.15 distance tempering, or post-Katz area-share adjustment. The one-metre floor prevents division by zero while keeping inverse road-distance attenuation. Because $S_p$ is inversely proportional to distance, establishment scores within one cluster can differ by several orders of magnitude.

The area-scaling coefficient is estimated for each geography in the centrality stage. The original `analysis.x` weights are not overwritten. Existing valid spatial, X topology and routing artifacts remain reusable.

```{admonition} SIGMA-specific scoring rule
:class: important
The inverse-distance transfer is a model rule, not a standard centrality theorem. Unlike the separate PPML tile-area adjustment, it has not been validated by the Metro Manila cluster-centrality comparison. At 200 m a node with $C_c=0.40$ assigns $S_p=0.002$, while at 1 m or less it assigns $0.40$. This intentionally permits large within-cluster score changes. See [Empirical diagnostics and limits](area_adjustment_diagnostics.md).
```

## Legacy distance tempering

The previous bounded rule remains available to direct Python callers as `tempered_point_scores` **and remains the managed establishment-score rule for explicit legacy eigenvector / `--equivalent` mode**. Canonical Katz runs use the inverse-distance rule and reject non-default `--distance-tempering` through CLI and Python configuration. With $Q_{0.90,c}$ the 90th percentile of member distances in cluster $c$, $q_p=\min\left(d_p/\max(Q_{0.90,c},1),1\right)$ and tempering parameter $\lambda\in[0,1]$, it computed $S_p=C_c(1-\lambda q_p)$, so that $C_c(1-\lambda)\le S_p\le C_c$.


## QGIS score presentation

Canonical inverse-distance results use a display-only 5th–95th percentile size range and 10-decimal labels in QGIS, because raw scores can be very small. These display settings never modify `sigma_score`; explicit legacy eigenvector runs retain their former QGIS presentation.

# The spatial-economic graph X (stage 14)

*Pipeline stage 14 of 17 · `sigma run`. Under the Hood shows overlap, weights and the effect of road distance with interactive examples (section “Stage 14”).*

The X graph is where the economic and spatial branches meet. Its nodes are the final clusters of stages 8–10, and its economic edges come from the effective sectors of stages 5 and 9 through the coefficients of stage 13.

## Nodes

Every retained spatial cluster center becomes a node

$$
n=(t,c),
$$

where $t$ is economic type and $c$ is the cluster number within that type. Isolated nodes are retained.

## When does an X edge exist?

A directed candidate from $u=(t_1,c_1)$ to $v=(t_2,c_2)$ is instantiated only when both conditions hold:

1. the economic graph contains a positive edge $t_1\to t_2$ with technical coefficient $a_{t_1t_2}>0$; and
2. the two type-specific partition polygons have an intersection of strictly positive area.

The overlap test is structural: any positive area qualifies. Overlap area itself is not multiplied into the current edge weight.

## Road separation and within-cluster dispersion

For eligible X clusters $A$ and $B$, SIGMA retains the real shortest-road distance
between their network-node 1-medians $m_A$ and $m_B$:

$$d_{AB}=d_R(m_A,m_B).$$

The point-distance stage also stores each establishment's shortest-road distance
to its own cluster median. For cluster $A$ with $N_A$ scored establishments, define
its **mean road radius**:

$$r_A=\frac{1}{N_A}\sum_{i\in A}d_R(i,m_A).$$

The effective X-edge distance is the **mean hub-mediated road distance**:

$$\boxed{D_{AB}=r_A+d_R(m_A,m_B)+r_B.}$$

This is exactly the mean length of establishment-pair routes **constrained** to
pass through both 1-medians. On SIGMA's undirected road graph it is an upper
bound on the mean direct establishment-to-establishment shortest-road distance;
it is not necessarily an unbiased estimator of that distance. The sums are
**averaged**, so larger clusters are not penalized solely for having more
establishments. Disconnected center pairs are omitted and logged as diagnostics.

## Numerical X and route publication

The `analysis.x` stage is **numerical**: positive-area Voronoi overlap plus a positive IO coefficient produces a candidate cluster-level edge, and an exact shortest-road **distance** between the final network-node 1-medians qualifies it. The weight uses the mean hub-mediated separation and both exact-type clustered-establishment shares. The managed X computation calls the distance-only road solver (`include_paths=False`); it does not generate route predecessors, polyline geometry or per-edge route files. The authoritative analytical fields are the immutable `analysis.x/x_edges.csv` and the published `sigma_X_edges.csv`.

For compatibility the numerical artifact can contain `x_paths.parquet`, but in the canonical numerical path it is an **empty GeoParquet placeholder**, not a second source of X edge geometry or weights. The source contains a helper (`_reuse_x_routes_for_weight_only_change`) for artifacts that stored route geometry, but `_exec_x` does not call it. Do not describe hardlinked route files or route geometry reuse as the canonical X pipeline. A new X recipe reuses matching numeric artifacts or computes the necessary distances under normal immutable-artifact rules; changing a spatial dependency requires numerical X reevaluation.

**Route geometry is a downstream export choice** (see [Route publication](routing.md)):

- `sigma run AREA` / `--route-geometry browser` (**default**) publishes the compact `sigma_routing_graph.bin` and X-center routing IDs. SIGMA Explorer's Web Worker computes geographic shortest paths **on request**, with a length check against the stored numerical `road_distance`. No per-edge route file is generated.
- `sigma run AREA --route-geometry precomputed` materializes each X edge's center-to-center route **during export** and writes it into the published GeoPackage `paths` layer. The numerical X weights and Katz scores are the same in both modes; in browser mode the `paths` layer is empty by design.

Routes are shortest geographical paths from one cluster center to another, not the **mean hub-mediated** effective separation used in weighting. Uncertainty from the road graph (undirected routing, topology and coverage) applies in either mode. A browser reconstruction can follow a different *equal-length* shortest path if ties occur; equal length, not identical coordinates, is the enforced contract.

## Gravity-model motivation

Newton's law of gravitation has the multiplicative form

$$
F_{ij}=G\,\frac{m_i\,m_j}{r_{ij}^{2}}.
$$

SIGMA borrows only this **interaction structure**, not the physics: participation on both sides and an intersectoral linkage coefficient increase potential interaction, and separation decreases it. The same structure underlies the gravity equation for trade (Tinbergen, 1962). The correspondence is:

| Newton | SIGMA X edge $A\to B$ | Meaning in SIGMA |
|---|---|---|
| constant $G$ | $a_{s(A)s(B)}$ | positive **directed** technical coefficient of the exact sectors |
| masses $m_i$, $m_j$ | $1\cdot q_A$ and $1\cdot q_B$ | the two notional masses are set to **one**; $q_A=N_A/N_{s(A)}$ and $q_B=N_B/N_{s(B)}$ are dimensionless participation shares |
| $r^{2}$ | $\max(D_{AB}/1\,\mathrm m,1)^{\lambda_X}$ | mean hub-mediated road distance with a one-metre floor; **exponent $\lambda_X=1$** in the canonical method, not Newton's 2 |

Consequences of this construction:

- The kernel is **inverse-distance**, not inverse-square. With $\lambda_X=1$, a link at 1,400 m keeps $500/1400\approx 1/2.8$ of the weight of an otherwise equal link at 500 m; with exponent 2 it would keep $1/7.84$. A larger exponent gives a larger share of the total weight to short links. `--x-distance-decay-lambda` changes the exponent, but the canonical specification fixes it at 1.
- The shares $q$ are **economic participation factors**, not physical mass, revenue, employment or density.
- The final Voronoi area is **not** used as a mass, a density denominator or an area-share term: neither $A_A/A_{s(A)}$ nor any other area ratio appears in $w$.
- The later tile-area adjustment (stage 15) is a **statistical correction for observed connectivity scaling**, not a new gravity law and not an identified causal effect.
- A tile's area is a catchment-size proxy, and it may be related to how closely the clusters of the *same sector* are spaced. The stage 15 correction can therefore be correlated with local cluster density, even though $w$ does not use the discarded relative-density formula. The two constructions should not be conflated.

Under the Hood shows the analogy term by term, with a slider on the distance exponent, and a second figure in which moving establishments between clusters changes $q$ and $w$ but not the tiles.

## Edge weight

The direct technical coefficient determines economic strength, distributed by cluster shares and attenuated by effective road distance:

$$
 w_{A\to B}=a_{s(A)s(B)}
 \frac{N_A}{N_{s(A)}}\frac{N_B}{N_{s(B)}}
 \left[\max\left(1,\frac{D_{AB}}{1\,\mathrm{m}}\right)\right]^{-\lambda_X},
 \qquad \lambda_X=1\text{ by default}.
$$

The 1-metre floor belongs to the distance kernel only; it is **not** applied to the observed distances. The positive-area Voronoi-overlap rule governs whether an X edge exists. `road_distance` remains the actual numerical **center-to-center shortest
road distance**. The default X artifact contains **no per-edge route
geometry**; an on-demand browser path or explicitly precomputed export path
represents that center-to-center route. `effective_road_distance` is the
derived mean hub-mediated separation used for edge attenuation, not a
route-polyline length.

For a retained cluster $A$ in exact economic type $s(A)$, $N_A$ is its
number of clustered establishments and $N_{s(A)}$ is the sum of the clustered
establishments across **all retained clusters with precisely that type**.
Unclustered classified places do not contribute to either count. The two
fractions distribute the sector relationship across source and destination
clusters; they do not use overlapping polygon *area* as a multiplier.
Establishment counts are an imperfect proxy for economic scale (not revenue,
employment, or transaction volume). This is a proposed modeling assumption,
not an observed trade flow or a canonical gravity equation.
The X exponent $\lambda_X$ is separate from the Katz attenuation and from inverse-distance establishment scoring.

```{admonition} Interpretation of the weight
:class: warning
The mean hub-mediated distance is not an observed commercial trip length or
an estimate of actual trade. It can overstate direct travel when dispersed
clusters intermix or when routes through medians require large detours.
The sector direction denotes a national input-output requirement, not evidence
that the source cluster supplies the target cluster. External sourcing,
including imported and out-of-city inputs, is not identified by X. The
**implemented coefficient is $a_{ij}$**, not the Leontief inverse; an
A-versus-Leontief option is a proposed change, not a deployed feature.
```

## Downstream tile-area normalization

The managed X edge weight above is the **original gravity-inspired weight**, not a density or Voronoi-area-normalized weight. Stage 15 independently estimates how each geography's total directed node degree scales with final Voronoi area, and constructs two orientation-specific adjusted operators for balanced Katz. It does **not** replace the original `analysis.x/x_edges.csv`. See [Tile-area-adjusted balanced Katz](centrality.md).

## Self-use

Positive sector self-use remains in the economic graph. By the X topology policy, an X self-edge whose source and target are the same spatial cluster is omitted, **even though its capped inverse-distance factor would equal 1**. Self-use can instantiate edges between different clusters of the same economic type when their partitions overlap and their centers are road-connected.

## Subsequent tile-area correction (not part of X)

The canonical $W_{ij}$ above does **not** contain an area-share-density term, Voronoi polygon area, or the fitted degree–area exponent. The PPML exponent is estimated from the topology of this **unchanged** graph and final polygon areas, then applied **only inside centrality** as the two focal-tile operators $FW$ and $FW^{\mathsf T}$. No X edge is created or removed by the adjustment. See [Centrality](centrality.md), [Scoring](scoring.md), and [Empirical diagnostics](area_adjustment_diagnostics.md).

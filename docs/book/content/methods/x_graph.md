# The spatial-economic graph X

The X graph is where the economic and spatial branches meet.

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
establishments. Disconnected center pairs remain omitted as before.

## Numerical Network X versus geographical route publication

The canonical `analysis.x` stage (PR #29) performs **numerical** modeling:
positive-area Voronoi overlap plus an IO coefficient produces a candidate
cluster-level edge; exact shortest-road **distances** between final
network-node 1-medians qualify it. The kernel uses mean hub-mediated
separation and both exact-type clustered-establishment shares. The managed
X computation calls the road distance-only solver, with `include_paths=False`.
It does not generate route predecessors, polyline geometry or per-edge route
files. The authoritative analytical fields are the immutable
`analysis.x/x_edges.csv` and published `sigma_X_edges.csv`.

For compatibility the numerical artifact may still contain
`x_paths.parquet`, but in the current canonical numerical path it is an
**empty GeoParquet placeholder**, not a second source of X edge geometry or
weights. A retained legacy helper named `_reuse_x_routes_for_weight_only_change`
and `x_paths_overlay.json` handling exist in source for earlier artifacts,
but the current `_exec_x` no longer calls that route-reuse shortcut. Do not
describe hardlinked route files or route geometry reuse as the canonical X
pipeline. A new X recipe reuses matching numeric artifacts or computes the
necessary distances under normal immutable-artifact rules; changing a
spatial dependency requires numerical X reevaluation.

**Route geometry is a downstream export choice**:

- `sigma run AREA` / `--route-geometry browser` (**default**) publishes the
  compact `sigma_routing_graph.bin` and X-center routing IDs. SIGMA Explorer's
  Web Worker computes geographic shortest paths **on request**, with a
  distance-parity check against the stored numerical `road_distance`. No
  per-edge route file is generated for all X links.
- `sigma run AREA --route-geometry precomputed` materializes each X edge's
  actual center-to-center route **during export** and writes it into the
  published GeoPackage `paths` layer. The same numerical X weights and Katz
  scores apply; the browser mode's paths layer is empty by design.

Routes are shortest geographical paths from one cluster center to another,
not the **mean hub-mediated** effective separation used in weighting.
Uncertainty from the road graph (undirected routing, topology and coverage)
applies in either mode. A browser reconstruction can follow a different
*equal-length* shortest path if ties occur; distance parity, rather than
path-coordinate identity, is the enforced numerical contract.

## Edge weight

The direct technical coefficient continues to determine economic strength,
attenuated by effective road distance:

$$
 w_{A\to B}=a_{s(A)s(B)}
 \frac{N_A}{N_{s(A)}}\frac{N_B}{N_{s(B)}}
 \left[\max\left(1,\frac{D_{AB}}{1\,\mathrm{m}}\right)\right]^{-\lambda_X},
 \qquad \lambda_X=1\text{ by default}.
$$

The 1-metre floor is the preexisting distance-kernel convention; it is **not**
applied to the observed distances. The established positive-area Voronoi-overlap
rule continues to govern whether an X edge exists. `road_distance` remains the actual numerical **center-to-center shortest
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
The exponent, Katz centrality, and point-score tempering are unchanged.

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

## Self-use

Positive sector self-use remains in the economic graph. To preserve the X graph topology policy, an X self-edge whose source and target are the same spatial cluster is still omitted, **even though its capped inverse-distance factor would equal 1**. Self-use can instantiate edges between different clusters of the same economic type when their partitions overlap and their centers are road-connected.

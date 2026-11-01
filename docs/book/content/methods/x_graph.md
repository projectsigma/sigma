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

## Weight-only reruns and cached routes

SIGMA checks the active immutable `analysis.x` artifact before recalculating X.
If **all spatial routing and economic graph dependencies match** and only the
X distance-decay/scoring recipe changed, SIGMA reads the old edge distances
and unchanged route WKB from the validated GeoParquet artifact. It then
recomputes `effective_road_distance`, `edge_weight`, Katz centrality, and point
scores. It does **not** reconstruct shortest paths or route geometries.

The new `analysis.x` artifact contains a **hard link** to the original
immutable `x_paths.parquet` rather than a rewritten copy, and a small
`x_paths_overlay.json` manifest. The **authoritative current** coefficients,
effective distances and edge weights are in its `x_edges.csv`. The supported
`AnalysisPipeline.load_x()` reader checks source/target row identity and
applies the current values to the GeoDataFrame on load. **Do not read numeric
edge attributes straight from the hardlinked raw GeoParquet**, which retains
the prior artifact's numeric values. Published GeoPackages are written through
`load_x()` and have current edge weights. The artifact is independently
checksummed and continues to work if the older artifact directory is pruned.
Its provenance records `x_route_geometry_reused_from`. When spatial or
economic graph inputs change, the existing full route-construction path runs.
When a matched route artifact is malformed, the shortcut fails explicitly
rather than silently reuse wrong routes or initiate a long reroute.

The geometry bytes are **not rewritten** for weight-only changes on a
filesystem that supports hard links (e.g. NTFS). A hardlink failure stops the
run safely: SIGMA never falls back to an expensive copy or reroute. The new
edge CSV, Katz, scores and exported GeoPackage still need some free space.
For a forced rerun of the **same** recipe after a hardlink/overlay-based
weight update, SIGMA re-executes the numerical weighting from the validated
saved edge distances, reproducing the same overlay, provenance and artifact
identity without rerouting. A forced rerun of an ordinary, full-route X artifact
continues to use the full-routing implementation. This prevents a
**same-workspace forced-rerun collision**, but does not make raw GeoParquet
bytes canonical across independent workspaces with different cache histories;
compare current numerical outputs via `load_x()`.
To change only `distance_tempering` or Katz parameters, the existing stage
graph reuses `analysis.x` entirely.

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
rule continues to govern whether an X edge exists. `road_distance` and the
actual `road_path` remain the unchanged **center-to-center route**;
`effective_road_distance` is the derived mean hub-mediated distance used only
for edge attenuation. The route geometry is **not** claimed to have the
`effective_road_distance` length.

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
```

## Self-use

Positive sector self-use remains in the economic graph. To preserve the X graph topology policy, an X self-edge whose source and target are the same spatial cluster is still omitted, **even though its capped inverse-distance factor would equal 1**. Self-use can instantiate edges between different clusters of the same economic type when their partitions overlap and their centers are road-connected.

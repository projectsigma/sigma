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

## Road separation

For the chosen cluster centers, SIGMA computes exact shortest-path road distance

$$
d_{uv}=d_R(m_u,m_v),
$$

where $m_u$ and $m_v$ are their center network nodes. Disconnected center pairs are recorded as diagnostics rather than turned into edges.

## Edge weight

SIGMA now applies a capped inverse-power road-distance attenuation:

$$
w_{uv}=a_{t_1t_2}\left[\max\left(1,\frac{d_{uv}}{1\,\mathrm{m}}\right)\right]^{-\lambda_X},\qquad \lambda_X\geq 0.
$$

By default, $\lambda_X=1$. The lower distance scale of **one metre** makes the factor dimensionless and at most 1, including for coincident or sub-metre centers. The measured road distance is retained unchanged in `road_distance`; only the weight calculation uses the floor. With positive coefficients and representable weights, $0<w_{uv}\leq a_{t_1t_2}$. A zero exponent disables distance attenuation. Larger exponents penalize distant clusters more strongly.

The edge stores `technical_coefficient`, `road_distance`, the exact shortest `road_path`, and the attenuated `weight`. Positive-area overlap determines whether an edge is eligible, not how much it weighs. The calculation assumes road distances in metres (SIGMA managed roads use a metre-based UTM CRS).

```{admonition} Interpretation of the weight
:class: warning
For fixed $a_{t_1t_2}$, greater road separation weakens the modeled connection. `weight` is **not** a verified commercial trade probability. This is a spatial attenuation rule rather than an empirical estimate of transport elasticity. The distance exponent $\lambda_X$ is independent of Katz attenuation $\alpha$ and the establishment score-tempering parameter.
```

## Self-use

Positive sector self-use remains in the economic graph. To preserve the X graph topology policy, an X self-edge whose source and target are the same spatial cluster is still omitted, **even though its capped inverse-distance factor would equal 1**. Self-use can instantiate edges between different clusters of the same economic type when their partitions overlap and their centers are road-connected.

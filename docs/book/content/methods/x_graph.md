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

The current historical multiplicative X definition is

$$
w_{uv}=a_{t_1t_2}\,d_{uv}.
$$

The edge stores both factors separately (`technical_coefficient`, `road_distance`) together with the shortest road path and the product `weight`.

```{admonition} Interpretation of the weight
:class: warning
Because distance is multiplied rather than inverted or passed through a decay kernel, `weight` is **not a proximity score**. Holding the technical coefficient fixed, a longer road separation produces a larger X weight. The model should therefore be described literally as economic coupling multiplied by network separation. Replacing distance by a friction/decay function would define a different model.
```

## Self-use

Positive sector self-use remains in the economic graph. An X self-edge whose source and target are the same spatial cluster has zero road distance, hence zero multiplicative weight, and is omitted. Self-use can still instantiate edges between different clusters of the same economic type when their partitions overlap and their center distance is positive.

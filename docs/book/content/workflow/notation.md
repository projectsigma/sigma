# Notation

The same symbols recur throughout the book.

| Symbol | Meaning |
|---|---|
| $G_R=(V_R,E_R)$ | undirected road graph |
| $d_R(u,v)$ | shortest-path length on the road graph |
| $p$ | an observed establishment point |
| $s(p)$ | its continuous snap position on the road network |
| $t$ | economic type / sector code |
| $c$ | spatial cluster identifier within one type |
| $n=(t,c)$ | one spatial-economic node of graph $X$ |
| $Z=(z_{ij})$ | interindustry transaction matrix |
| $x_j$ | total output of purchasing/user sector $j$ |
| $A=(a_{ij})$ | technical-coefficient matrix |
| $G_E$ | directed economic graph induced by positive $a_{ij}$ |
| $X$ | directed spatial-economic cluster graph |
| $W=(w_{uv})$ | weighted adjacency matrix of $X$ |
| $m_A$ | network-node 1-median of cluster $A$ |
| $r_A$ | mean shortest-road distance from establishments in $A$ to $m_A$ |
| $D_{AB}$ | effective hub-mediated distance $r_A+d_R(m_A,m_B)+r_B$ |
| $N_A/N_{s(A)}$ | share of all retained **clustered** establishments of exact sector $s(A)$ found in cluster $A$ |
| $\lambda_X$ | inverse-road-distance exponent on X edges (default 1) |
| $K^{in},K^{out}$ | raw incoming and outgoing Katz vectors |
| $C_i$ | normalized balanced Katz centrality of X node $i$ |
| $S_p$ | final SIGMA score of establishment $p$ |

Distances are measured in the linear unit of the projected road CRS. Managed area-mode roads are projected to a local metre-based UTM CRS, so the practical unit is metres.

## Direction convention

For an economic edge $i\to j$, sector $i$ supplies an intermediate input used by sector $j$. Accordingly,

$$
a_{ij}=\frac{z_{ij}}{x_j}.
$$

For the final graph $X$, we write $W_{uv}>0$ when there is a directed edge from cluster node $u$ to cluster node $v$. The edge is a modeled spatial-economic relation; supplier/user direction comes from the national coefficient matrix, **not** an observed local buyer-supplier match. The X weight also uses the two endpoint cluster-sector shares and $D_{AB}$ as defined above.

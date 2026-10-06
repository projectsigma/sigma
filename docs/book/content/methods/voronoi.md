# Network Voronoi ownership and 2-D surface partitions

SIGMA needs two related but distinct objects:

1. **exact ownership on the one-dimensional road graph**, and
2. a polygon surface that allows spatial overlap tests between clusters of different economic types.

Keeping those objects distinct avoids overclaiming what a finite-resolution polygon layer represents.

## Exact network ownership

For one economic type, cluster-member network nodes act as sources. Multi-source Dijkstra computes the distance from every reachable road node to the nearest source and assigns the corresponding cluster label. Ties are resolved deterministically by the smaller cluster label.

This is a graph/network Voronoi construction in the lineage of Erwig (2000), Hakimi, Labbé & Schmeichel (1992), Okabe et al. (2008), and the network-analysis treatment of Okabe & Sugihara (2012).

### Ownership within an edge

Consider a road edge $(u,v)$ of length $L$. Let $D_u$ and $D_v$ be the already-computed distance from the nearest source associated with the owners at endpoints $u$ and $v$. At offset $t$ from $u$, competing route distances are

$$
D_u+t
\quad\text{and}\quad
D_v+L-t.
$$

Their equality occurs at

$$
t^*=\frac{D_v+L-D_u}{2},
$$

clipped to $[0,L]$. This determines the owner on the interior of an edge when the endpoint owners differ. Exact ties are resolved deterministically.

## Rendering a 2-D polygon surface

Economic relations are later instantiated when partitions of two types have **positive-area overlap**. A one-dimensional road Voronoi object therefore has to be rendered into area.

SIGMA overlays a regular grid on the exact study boundary. For each positive-area grid cell, a representative point is attached to the nearest **source-reachable** road edge. The owner at that continuous edge location is read from the exact network-Voronoi distances above. Cells are then dissolved by `(type, cluster)`.

The default cell resolution is 500 m with a one-million-cell guard. If a coarse resolution gives no cell to a valid cluster, SIGMA refines by factor 0.5 for up to five refinements.

```{admonition} Important interpretation
:class: warning
The ownership decision attached to each cell is network-based, but the resulting polygon boundary is a finite-resolution **rendering**. It should not be described as an exact planar network Voronoi boundary.
```

## Euclidean recovery fallback

After network-Voronoi rendering attempts are exhausted, SIGMA may construct an ordinary planar Euclidean Voronoi surface from final cluster-center coordinates. If centers coincide, it first substitutes raw projected cluster centroids for only those coincident sites. This path is explicitly labeled `euclidean_voronoi_fallback`.

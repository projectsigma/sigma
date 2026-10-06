# Roads, snapping, and network distance

All primary spatial methods use one common road-distance semantics.

## Managed road extraction

Area-mode SIGMA derives roads from the same shared Geofabrik Philippines PBF used for OSM places. It buffers the exact study boundary by 5 km, selects a pinned motor-road profile, projects to an inferred metre-based UTM CRS, clips to the buffered polygon, and performs no geometry simplification.

Included `highway=*` values are:

`motorway`, `motorway_link`, `trunk`, `trunk_link`, `primary`, `primary_link`, `secondary`, `secondary_link`, `tertiary`, `tertiary_link`, `unclassified`, `residential`, `living_street`, `service`, and `road`.

Roads with `access` equal to `no`, `private`, `agricultural`, or `forestry` are excluded.

OSM `oneway` is retained as audit metadata, but the current routing graph is **undirected**. Thus SIGMA currently models symmetric road distance rather than legal driving direction.

## Graph topology

Each input line is split into straight arcs between consecutive coordinates. Coordinates are canonicalized to `vertex_digits=11` significant digits by default. Two lines connect only when they share a canonicalized vertex. A 2-D geometric crossing without a shared source vertex is not automatically a junction; this protects bridge/flyover crossings from false connectivity.

## Continuous point snapping

For establishment point $x_i$ and the set $N$ of continuous positions on the road network,

$$
s_i=\operatorname*{argmin}_{z\in N}\|x_i-z\|.
$$

Ties between equally near arcs are resolved by the smallest deterministic arc index. The straight-line snap distance $\|x_i-s_i\|$ is retained as QA metadata.

## Network distance

The clustering and downstream road metric is

$$
d(i,j)=d_R(s_i,s_j),
$$

where $d_R$ is shortest-path length along the road network. **Snap distance is not added** to $d(i,j)$. If two snaps lie on disconnected road components, their network distance is infinite/undefined for methods that require a connecting path.

Shortest paths use Dijkstra's algorithm through SciPy. The clustering branch performs bounded sparse searches rather than materializing a full $n\times n$ all-pairs matrix.

## Why a projected CRS is essential

The road geometry determines arc lengths, clustering radii, center objectives, Voronoi attachment, X-edge road distance, and point-center distance. These quantities must therefore be computed in a projected linear CRS. Managed area-mode roads use metre-based UTM, so parameters such as the default 5,000 m HDBSCAN ceiling and 500 m Voronoi grid have their intended physical meaning.

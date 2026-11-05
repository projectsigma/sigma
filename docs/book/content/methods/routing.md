# Route publication and browser routing

*Publication · after stage 17 · `sigma run` export and `sigma view`. This step changes no number computed in stages 1–17. Under the Hood shows it with an interactive example (section “Publication”).*

## Numbers first, route lines on request

Stage 14 ([The X graph](x_graph.md)) needs only the shortest road **distance** between two cluster 1-medians. The managed `analysis.x` stage calls a distance-only shortest-path solver (`include_paths=False`): it computes no predecessors and stores no route line. Each published edge in `sigma_X_edges.csv` carries `technical_coefficient`, `road_distance` (center to center), `effective_road_distance` (center distance plus both mean member radii) and the edge weight.

A route line is needed only for display. The export option `--route-geometry` decides how routes are published:

| Mode | What export writes | Where routes come from |
|---|---|---|
| `browser` (default) | `sigma_routing_graph.bin`, `routing_node` in `sigma_X_nodes.csv`, `route_mode = browser` in `sigma_run_metadata.json`; the GeoPackage `paths` layer is empty | Explorer computes a route when an edge is shown |
| `precomputed` | every X edge's center-to-center route in the GeoPackage `paths` layer | the published geometry |

Both modes publish the same numerical X graph, the same centrality and the same scores. Changing the mode changes only the `export.bundle` recipe.

## The compact routing graph

During analysis, each establishment's snap point is inserted into the road graph as an extra vertex, splitting the original straight road segment into several pieces. Before publication, SIGMA contracts these chains again:

1. Inside each original road segment, the pieces must form one simple straight chain; otherwise export stops instead of publishing an unsafe graph.
2. Original road vertices and the vertices of X cluster centers are kept. Vertices that exist only because an establishment snapped there are removed.
3. Consecutive pieces between kept vertices are joined, and their lengths are added.

Because the removed vertices lie on a straight segment between kept vertices, shortest-path distances between kept vertices are unchanged. The result is written as `sigma_routing_graph.bin` in the binary format `SIGRTE01`: an 8-byte magic string, the vertex and edge counts, WGS84 coordinates of kept vertices, and edges as (vertex, vertex, length in metres). Vertex IDs are new compact IDs; `routing_node` in `sigma_X_nodes.csv` maps each X center to its ID. The run metadata records `routing_graph_privacy = base_vertices_and_x_centers_only`, and the Explorer builder refuses a browser graph without this marker.

The routing graph does not contain establishment snap positions, so the reduced `--public` Explorer profile can still draw routes. It does contain the published road network and cluster-center positions.

## Route on request, with a length check

When an edge is shown, Explorer sends the request to a Web Worker (`route-worker.js`, a background browser thread). The worker:

1. loads `data/routing-graph.bin` once and validates its size, coordinates and edges;
2. runs Dijkstra's algorithm from the source center until all requested targets of that source are settled;
3. compares each route length `d_browser` with the published `road_distance`:

$$|d_\text{browser} - d_\text{published}| \le \max(10^{-6},\ 10^{-8}\, d_\text{published});$$

4. returns the coordinates only if the check passes, and otherwise reports “Route distance disagrees with SIGMA X edge” and draws nothing;
5. keeps up to 256 recent routes in a cache.

A failed check means that the Explorer bundle does not match the analysis that produced it; rebuild it with `sigma view AREA --refresh`. When two different routes have exactly the same length, the browser may draw the other one. The enforced contract is equal length, not identical coordinates.

## Interpretation

A displayed route is the shortest path between two cluster 1-medians on SIGMA's undirected motor-road graph. It is not the effective, hub-mediated separation used for the X weight, not a travel-time route, and not an observed delivery path. Incoming routes are drawn dashed and outgoing routes solid, following the published X direction; the road graph itself has no direction.

See also [SIGMA Explorer](../intro/explorer.md), [Reading outputs](../reference/outputs.md) and the [Explorer guide](https://github.com/projectsigma/sigma/blob/main/SIGMA_EXPLORER.md).

# Explorer interaction latency safeguards

These safeguards are part of the browser Explorer's `app.js` and its regression tests. SIGMA's economic graph, directed Network X, road distances, spatial partitions, clustering parameters, establishment scores, and saved data are not affected.

Explorer has two route sources. In the default **browser route mode**, a Web Worker reconstructs a displayed route on request from the compact routing graph and keeps up to 256 routes in its cache (see [Explorer](book/content/intro/explorer.md) and [Route publication](book/content/methods/routing.md)). In a bundle built with `--route-geometry precomputed`, Explorer reads route files instead; the route-file cache below applies only to that mode.

## Behavior

- A new focus, reset, depth selection or sector-filter change immediately invalidates outstanding route/hover operations and clears the old route GeoJSON sources. Superseded asynchronous route work cannot reappear.
- Map selection emphasis and detail text are updated before deferring diagram reconstruction, sector-list and connection-list rebuilding until after the browser gets an opportunity to paint. A generation number prevents older deferred work from running after a newer selection.
- Mousemove events are coalesced to one map hit test per animation frame. Hover first queries establishment and cluster-center layers; only if no eligible point is found does it query route layers.
- Old establishment points are cleared when the map enters a different geographic tile set. The accepted tile signature is invalidated during the transition so quick pan-back cannot leave the source empty. Existing asynchronous `tileEpoch` validation prevents stale tiles reappearing.
- The 20-depth route palettes are reapplied only when switching theme, not on every selection. The layout for cluster icons is applied once per emphasis refresh rather than twice.
- Reciprocal LineString route equivalence uses direct coordinate comparisons instead of allocating full JSON representations. The original exact-geometry semantics remain.
- In precomputed-route bundles, expanded route files are cached in an LRU with at most 96 entries and are not pinned in the general JSON cache. The limit is **by count**, not by bytes; unusually large routes can still require considerable memory.

## Limitations and safe follow-up

Explorer keeps 60 depth-specific route MapLibre layers and a Cytoscape concentric layout. These safeguards do not alter the Explorer data format, tile size, map visual hierarchy, click scope, network limits, route direction scheme, or GeoJSON geometry precision. Assess changes with the browser Performance and Memory panels under cold and warm cache, rapid clicks, dense multiring networks, and panning.

## Updating the interface

`sigma view quezon_city --fast --port 8766` copies static Explorer assets into an existing bundle without rebuilding SIGMA analytical outputs. Restart any existing server when testing new JavaScript. If the port is in use, SIGMA selects another free one.

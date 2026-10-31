# Explorer interaction latency patch (v1)

This change affects only the browser Explorer's `app.js` and its regression tests. SIGMA's economic graph, directed Network X, road routes, spatial partitions, clustering parameters, establishment scores, and saved data remain unchanged.

## Behavior

- A new focus, reset, depth selection or sector-filter change immediately invalidates outstanding route/hover operations and clears the old route GeoJSON sources. Superseded asynchronous route work cannot reappear.
- Map selection emphasis and detail text are updated before deferring diagram reconstruction, sector-list and connection-list rebuilding until after the browser gets an opportunity to paint. A generation number prevents older deferred work from running after a newer selection.
- Mousemove events are coalesced to one map hit test per animation frame. Hover first queries establishment and cluster-center layers; only if no eligible point is found does it query route layers.
- Old establishment points are cleared when the map enters a different geographic tile set. The accepted tile signature is invalidated during the transition so quick pan-back cannot leave the source empty. Existing asynchronous `tileEpoch` validation prevents stale tiles reappearing.
- The 20-depth route palettes are reapplied only when switching theme, not on every selection. The layout for cluster icons is applied once per emphasis refresh rather than twice.
- Reciprocal LineString route equivalence uses direct coordinate comparisons instead of allocating full JSON representations. The original exact-geometry semantics remain.
- Expanded route files are cached in an LRU with at most 96 entries. Route files are no longer also pinned forever in the general JSON cache. The limit is **by count**, not by bytes; unusually large routes can still require considerable memory.

## Limitations and safe follow-up

This deliberately preserves the 60 depth-specific route MapLibre layers and existing Cytoscape concentric layout. It does not alter the Explorer data format, tile size, map visual hierarchy, click scope, network limits, three-color route direction scheme, or GeoJSON geometry precision. The change should be assessed with browser Performance and Memory panels under cold and warm cache, rapid clicks, dense multiring networks, and panning.

## Installation

Apply via `apply_explorer_latency.py --repo <repo> --dry-run`, then `--apply --test`. Installer refuses missing anchors, validates JS syntax when Node.js is installed, checks source file again before writing, saves a backup under Downloads, and neither switches branches nor alters workspace data.

Update only static Explorer assets with `sigma view quezon_city --ui-only --port 8766` after applying; this does not rebuild SIGMA analytical outputs. Restart any existing server when testing new JS. If the port is in use, SIGMA selects another free one.

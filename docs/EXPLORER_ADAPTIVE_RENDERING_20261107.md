# SIGMA Explorer: adaptive rendering and quiet Voronoi overlays

This patch changes **visual delivery only**. SIGMA's clustering, territorial Voronoi
partitions, network construction, scores, source establishment coordinates and
network coefficients are not recalculated or modified.

## Browser behavior

- In local profiles, display individual establishment circles while the visible
  zoom-13 source tiles contain at most **8,000** points. Exact source records,
  scores, and opt-in semantics for unclustered places remain unchanged.
- For denser visible regions, fetch **visible-only**, pre-generated, scored-place
  summaries. Cell resolutions are Web-Mercator zooms **11, 13, 15 and 17**; the
  browser chooses the finest level with at most **4,000** summary symbols.
  The summaries are sector-specific actual coordinate centroids and counts,
  **not** cluster centers, synthetic establishments, scores, or network nodes.
  Each precomputed summary retains its actual source X node ID (never a synthetic node),
  so a selected network can exclude unlinked establishments from the renderer.
  Screen-space coalescing happens only after selection, and deliberately drops
  the now-ambiguous node ID rather than creating a fictional cluster.
  They use the established original-sector colors and sector filtering.
- The browser filters current-view scored places **before calling MapLibre
  setData**, rather than handing MapLibre thousands of features painted almost
  transparent. With an X cluster selected, only establishments assigned to the
  selected X-network's focus and linked nodes are submitted for drawing; the
  underlying original point tiles, finder data and sector assignments stay intact.
  Hidden sectors and out-of-network places are also omitted from summary sources; classified-but-unscored places keep their existing opt-in.
- Exact point tiles and finder offsets remain intact. Zooming in restores
  individual establishments. The former green heatmap is removed entirely.
- The browser initially reads X-node metadata; it fetches directed adjacency
  shards on selection. Existing BFS graph limits, direction, coefficients,
  route identity, and neighbor ordering remain unchanged.
- Default selected-network Voronoi polygons are loaded from exact original
  geometry shards rather than eagerly parsing every polygon at startup.
  The explicit **All partitions** mode still loads all exact polygons.
- A bounded JSON cache prevents unlimited retention of visited point,
  aggregate, adjacency, and partition shards.

## Voronoi rendering

- Selected polygon: approximately **0.30** opacity (light mode).
- Linked polygons at steps 1, 2, 3: **0.18, 0.045, 0.01125** opacity, respectively.
  The factor per extra step is 0.25, applied **only** to Voronoi fill.
- Nonselected context is a **0.07 opacity sector-colored tint**, never white fill. In default selected-network mode, nonselected Voronoi polygons are not loaded into the MapLibre polygon source. Exact published overlaps within the selection remain intact.
- Persistent partition outlines are hidden; the explicit hovered-partition
  outline is retained. Polygons remain distinct and **overlap is preserved**.

## Compatibility and limitations

A **full bundle rebuild** is required after this patch, not `--ui-only`, because
new adjacency, polygon, and aggregate shards must be generated. Existing
`graph.json`, `clusters.geojson`, `overview.geojson`, exact point tiles and
search index remain published for compatibility and audit.

This is a substantial memory reduction, not a promise of crash-free rendering.
The base road layer still arrives as a full GeoJSON file, and the optional
**All partitions** view can still be heavy on metropolitan-scale bundles.
A future road vector-tiling phase can remove that remaining scaling limit;
this patch intentionally leaves the road graph and route geometry unchanged.

Use `python -m pytest tests/test_web_explorer.py tests/test_explorer_adaptive_lod_contract.py`,
`node --check src/sigma/web/static/app.js`, and
`node tests/test_explorer_adaptive_rendering.js` as verification. Prefer an
interactive Metro Manila smoke test with browser memory inspection before PR.

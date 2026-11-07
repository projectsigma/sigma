# SIGMA Explorer v7 — real-point native map tiles

**Scope**: Browser visualization and its read-only published bundle. No clustering, score, X coefficients, sector tags, Voronoi geometry, or routes change. Existing v4/v5 Voronoi transparency is unchanged.

## Why

The v4/v5 adaptive renderer moved establishments into centroids in a geographic grid. Those dots were not actual establishments and made the metro overview look artificial. The 8,000-point per-source cap then hid many original points too far into the zoom sequence.

## New rendering

`builder.py` writes Mapbox Vector Tile (MVT v2) point tiles using the built-in Python writer `mvt_points.py` and **no new packages**. The browser uses MapLibre's native vector source and paints genuine establishment positions with original sector color and the existing score-based radius at neighborhood zoom. Zooms 8–11 retain stable real-coordinate samples (1.5%, 4%, 10%, 30%); zoom 12 and above contain **all** scored establishment points and remain interactive. Thus the 2-km map scale in Metro Manila falls on the full-resolution side. The complete score/sector/X identity in every tile remains original; native tile coordinates are quantized to a standard 8192-unit tile grid (~1 m at z12, submeter at z13 around Metro Manila).

The visual density at broad zoom is *sampled*, not an establishment count map; it should not be interpreted as complete counts. The sector panel totals continue to show published counts. No centroids, heatmap, arbitrary cluster symbols or count-weighted dot sizes are used in v7.

The map draws and hit-tests native tiles, without constructing giant browser GeoJSON sources each pan. Selected Network X nodes are filtered in the MapLibre vector layer. Original GeoJSON exact point tiles remain untouched for establishment finder and explicit unclustered-point opt-in.

**Privacy:** native tiles are only exported for local profiles; public exports never include point identities or vector tiles. The existing public privacy contract remains.

**Limitations:** native tile parsing still scales with the number of locations at high zoom. This should be better than repeatedly reparsing a single giant GeoJSON source, but performance on the actual Metro Manila computer/browser remains unverified. The 2-km guarantee means all scored coordinates appear without sampling from zoom 12 onward, not that every coincident marker can be visually distinguished. The primary scored native layer is filtered to the selected X ring. Starting with v12, a separate noninteractive ghost layer can show a faint deterministic sample of *other* scored establishments **inside selected/highlighted Voronoi polygons**, without assigning those establishments to the selected X network. The original point records stay in the on-disk tile, and analytical data remain unchanged.

## V12 selected-network ghost context

When an X cluster is selected in **Selected network** partition mode, MapLibre also draws a second, noninteractive circle layer using the **same native PBF tile source**. Only real, scored establishments outside the selected X ring qualify. Their actual locations must be inside one of the included selected or linked published Voronoi polygons; the ghost footprint remains stable during panning. Polygon overlaps and score/sector identities are unchanged. All ghost circles retain sector color, have 30% opacity and a smaller contextual radius, and cannot intercept map clicks or hover selection. Original hollow unclustered-point controls remain independent.

**V13 performance adjustment.** Ghost samples now use approximately two zoom-detail steps less data: 1.5% through zoom 10, 4% at zoom 11, and **at most 10% at zoom 12 and above**. This uses the existing `lod_rank` attribute; no new native tile format or rebuild is necessary after v12 has already generated tiles. The maximum footprint is reduced to **12 polygons and 2,800 vertices**. An exceptionally intricate partition may be excluded from the *ghost-only* footprint rather than forcing slow rendering; actual highlighted Voronoi geometry remains unchanged and visible. The footprint is stable across camera pans and the MapLibre filter is rebuilt only for a changed network, enabled sectors, zoom-density bucket, or loaded polygon collection. The cheap deterministic rank predicate precedes the expensive `within` containment predicate. The normal all-sectors view, click behavior, and independent hollow-unclustered toggle remain unchanged. Ghost coverage can be partial in deep networks in exchange for responsiveness.

**Deployment:** `sigma view AREA --refresh` is mandatory once after applying v12 to regenerate the local PBF tiles with `lod_rank`; `--fast` alone cannot add the attribute. Public-profile bundles still omit establishment-level coordinates. Rendering performance remains to be measured in the actual Metro Manila browser.

## Applying

Apply this v7 patch ON TOP OF existing v4 + v5 (v6 optional; skipped v6 expression gets repaired). First `--check`, then `--apply`. Backups of the two changed files are written under `~/Downloads/sigma_before_native_v7_TIMESTAMP/`. The patch creates the new module, two focused tests and these notes; it never stages, commits or pushes. After passing regression checks use `sigma view metro_manila --refresh` to create the new point vector tiles. `--fast` alone is insufficient because this changes exported data formats.

Run `python -m pytest tests/test_explorer_vector_lod_v7.py tests/test_web_explorer.py` and optionally `node --check src/sigma/web/static/app.js` and `node tests/test_explorer_vector_lod_v7.js`.

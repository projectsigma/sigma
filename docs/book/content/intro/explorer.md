# SIGMA Explorer: interactive maps and cluster networks

SIGMA Explorer is a **browser visualizer for a completed SIGMA analysis**. It uses the same published establishments, spatial cluster polygons, X-network nodes and directed links that you can inspect in QGIS, and it draws shortest road routes between linked cluster centers on request from a compact published routing graph. It does **not** run SIGMA's classification, clustering, economic, or scoring algorithms again.

## Launch a local explorer

From a SIGMA installation with an existing area run:

```powershell
sigma run pasig
sigma view pasig
```

The default output is `Documents\SIGMA\workspaces\pasig\output\explorer` on Windows, unless the workspace has a different configured output directory. The local server normally opens `http://127.0.0.1:8765/`; it listens on the same computer only. Leave the terminal open while exploring and press `Ctrl+C` when finished.

If the SIGMA output has changed, refresh the browser bundle:

```powershell
sigma view pasig --refresh
```

If you have already run the analysis, you need only `sigma view pasig`.

## Under the Hood

**Under the Hood** (from the Explorer header) explains the whole pipeline in its 17 stages, each with a worked, interactive example: matching, the administrative-office rule and the ownership evidence ladder, area sectors and coarse-place policies, review and augmentation, road graph and snapping, HDBSCAN*, zero-cluster roll-up, **default-on network Gap refinement with up to four worker processes** (illustrated interactively in the browser; computed by SIGMA during `run`), network 1-medians, network Voronoi, coefficients, graph X, the pooled degree–area PPML and **two focal-tile-adjusted Katz operators**, balanced Katz, **inverse-road-distance** establishment scores, and browser route publication. Part 4 also explains the **gravity analogy** behind the X weight (Newton's form beside SIGMA's weight, with a slider on the distance exponent) and the **tile-area correction** step by step: why a larger tile overlaps more tiles, a PPML fit on invented tiles, the factor curve and its unit invariance, $FW$ and $FW^{\mathsf T}$ as matrices, and the four-node Katz example with unequal tile areas and a switch for the correction. That example uses $\gamma$ as an example value, because four tiles are too few for SIGMA's estimator. When the bundle publishes them, the run's $\hat\gamma$, each cluster's tile area and factor, its raw Katz components and the run's area-decile diagnostics appear beside the worked examples. The scoring slider uses the canonical $1/\max(d_R/(1\,\mathrm m),1)$ relationship. A “Current SIGMA run” panel and a note under every step show what the opened bundle publishes for that stage (for example its sector codes, rolled-up sectors, final cluster counts and route mode).

The worked examples are illustrations, not a per-run guarantee: for the actual run, inspect `run.json`, `rollup_audit.json` and `median_gap_audit.json`. A bundle built from an earlier analysis shows the defaults of the analysis that produced it; rebuild it with `sigma view AREA --refresh` after a new `sigma run`. `sigma view AREA --fast` changes only static website assets, not the underlying analytical results.

### Fast website-only changes

When you are changing only Explorer or Under the Hood **HTML, CSS, JavaScript, images, logo or favicon**, update an *existing* Explorer bundle without recreating its graph, routing data, polygons or establishment tiles:

```powershell
sigma view pasig --fast
# For another already-built area:
sigma view quezon_city --fast
```

`--fast` starts the normal local browser server, but copies only static website assets. It refuses an absent or unrecognized bundle, preserves the bundle's local/public profile, and **does not check whether the SIGMA data have changed**. Use `sigma view pasig` to check for changed outputs, or `sigma view pasig --refresh` to force regeneration; do not combine `--fast` with `--refresh`. Ordinary `sigma view` can rebuild after frontend code changes because the published bundle fingerprint includes frontend code.
 The CLI also supports custom `--workspace`, `--source-dir`, and `--output-dir` paths, and `--no-browser` or `--port` for local hosting preferences.

## Explore a cluster network

1. Pan and zoom the geographic map. Establishments are colored by economic type, with cluster partitions, centers, optional roads, and the analysis boundary as geographic context.
2. Select an establishment or cluster center. An establishment inherits its assigned `(type, cluster)` X node; it **does not** have its own firm-level supply-chain links.
3. Inspect incoming, outgoing, or combined connections, and increase the neighborhood depth from direct connections to two steps or the reachable neighborhood. Direction choices govern **neighborhood discovery**; the diagram retains the directed relationships among the displayed nodes.
4. Use theater view and fit-to-graph when a network is too crowded. Inspect edge attributes and highlight center-to-center shortest paths (drawn in the browser on request by default, precomputed only by explicit option). Incoming routes are dashed blue and outgoing routes solid red.

**Interpretation matters:** A directed X edge represents a *modeled spatial-economic link* grounded in IO technical coefficients, overlapping cluster partitions, and routable road-network separation. It is **not verified trade between two specific establishments**. The displayed X edge weight is **not** just the coefficient divided by the
center-to-center road distance. It is
`technical_coefficient * source_cluster_sector_share * target_cluster_sector_share / max(effective_road_distance_metres, 1) ** x_distance_decay_lambda`.
Here `effective_road_distance` equals the center-to-center shortest-road
distance **plus the two clusters' mean establishment-to-1-median road
distances**; each share counts that cluster's establishments relative to all
retained clustered establishments of the same exact economic type. The numerical `road_distance` describes the actual **center-to-center**
shortest road separation, not the effective hub-mediated quantity. Under the
default `--route-geometry browser`, Explorer reconstructs displayed shortest
road paths from a published compact routing graph and checks each against
that numerical distance; a route geometry is **not** stored with every X
edge. Explicit `--route-geometry precomputed` materializes GIS routes at
export, without changing the numerical X graph. Neither edge weight nor direction proves a transaction or local
sourcing relationship. The routing graph itself is undirected. See
[The X graph](../methods/x_graph.md) for the exact equation and limitations.

At metro zoom levels, Explorer displays a deterministic preview of REAL establishment locations using native vector tiles, not generated centroids or heatmaps. Zoom 12 and above displays all scored establishments, including a 2 km scale-bar view of Metro Manila. Preview samples are incomplete counts; the industry table shows actual published counts. Exact original point records and establishment finder remain unchanged. Network X, scores, colors and overlapping Voronoi shapes remain analytically unchanged. The network view is capped at 300 nodes and 1,500 directed edges per selection and marks truncated displays. Neither cap modifies the original SIGMA outputs.

## Fixed industry colors, rolled-up sectors, and contextual inspection

SIGMA uses a **fixed 336-sector color specification** (16 broad, 80
intermediate, 240 detailed industries). `X:Y:Z`, `X:Y`, and `X` use their
specified canonical colors, also available by tiered source-sector codes;
residual `o` sectors inherit the corresponding parent color. Palette changes
are visual only and cannot change an X weight or a SIGMA score.

For generated hierarchical economies, the normal run performs **post-clustering
zero-cluster roll-up** (stage 9) by default. Expanding an affected sector in the local
Explorer shows original sector tags, counts, and separate point-visibility
checkboxes. A moved establishment can retain the fixed color of its *original*
industry, but the effective rolled-up sector remains its analytical X type.
Expanding or hiding children does **not** create child clusters or recompute
network scores. See [Hierarchical economy](../methods/hierarchical.md).

There are two independent, opt-in displays for classified establishments without a cluster.
Both start off and draw hollow circles with no SIGMA score. **Show unscored sectors** reveals
establishments of zero-cluster sectors only while no network is selected.
**Show unclustered for scored sectors** reveals all eligible unclustered places of
scored sectors without a selection; with a scored establishment or cluster selected,
it shows only points lying in
the *published* focus and linked Voronoi polygons **of the point's own effective sector**.
The subset follows the Depth, Links, Strongest and sector-visibility settings. Hollow-circle
size follows the smallest scored point of the effective sector, falling back to the smallest
scored point overall in a zero-cluster sector. Their opacity does not fade with network depth.
This is geographic context, **not** assignment of HDBSCAN membership, X links or a score.
The public-profile Explorer does not expose establishment points.

The local selected-establishment details show a PSIC code and its title when available;
source-provided titles take precedence over the bundled PSIC Rev. 5 taxonomy. The browser
does not infer a classification from a missing title.

Hovering a visible cluster-center triangle while a selection is active
transiently outlines just that cluster's existing Voronoi polygon in its
sector's color, including if the ordinary partitions layer is switched off.
The outline disappears on hover exit, selection changes, and map movements.

The **Strongest** toolbar starts at **3 per cluster**, with 1, 5, 10, and
Custom alternatives. `sigma view AREA --fast` updates UI assets only; when
new analytical output, catalog, or per-point original-tag data are needed,
use a validated normal/full Explorer refresh instead. Updating one existing
bundle's small metadata file does not automatically update tiles or analytics.

## Export a browser bundle

```powershell
sigma export-web pasig             # full local-profile bundle
sigma export-web pasig --public    # reduced-data public-review profile
```

The first bundle normally lives in `<output>/explorer/` and includes individual establishments. **Do not publish it by default.** The `--public` variant normally lives in `<output>/explorer-public/` and omits individual establishment records, names, positions, IDs, and PSIC codes while retaining cluster/network information. It is **not an anonymity guarantee or license clearance**; locations of cluster centers and very small aggregate counts can still be revealing. Any public deployment requires independent data-rights, confidentiality, and attribution review.

Bundles are static website files; serve them over HTTP, not with `file://`. `sigma view` is the supported local server. The separate [SIGMA Jupyter Book website](https://projectsigma.github.io/sigma/) publishes **these explanations**, not your local datasets or an interactive Explorer automatically.

## Compare with QGIS and inspect source files

Use the generated `<area>.qgz` when you need normal GIS tooling and detailed layer inspection. Use **Explorer** to start from a mapped establishment and navigate its **cluster-level X neighborhood** interactively. Both are views of published SIGMA products, not alternate analytical engines.

Explorer principally reads `sigma_points.parquet`, `sigma_X_nodes.csv`, `sigma_X_edges.csv`, the `clusters` layer of `sigma_spatial_outputs.gpkg`, and either `sigma_routing_graph.bin` (default browser routing) or the GeoPackage `paths` layer (precomputed mode); optional published roads, boundary, metadata, and manifest add map context and integrity checks. See [Route publication](../methods/routing.md). More detail is available in the repository's [SIGMA Explorer guide](https://github.com/projectsigma/sigma/blob/main/SIGMA_EXPLORER.md) and [Reading outputs](../reference/outputs.md).

`--ui-only` is accepted as an alias for `--fast`.

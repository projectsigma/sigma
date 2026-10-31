# SIGMA Explorer: interactive maps and cluster networks

SIGMA Explorer is a **browser visualizer for a completed SIGMA analysis**. It uses the same published establishments, spatial cluster polygons, X-network nodes and directed links, and shortest-road-path geometries that you can inspect in QGIS. It does **not** run SIGMA's classification, clustering, economic, or scoring algorithms again.

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

### Fast website-only changes

When you are changing only Explorer/Guided Tutorial **HTML, CSS, JavaScript, images, logo or favicon**, update an *existing* Explorer bundle without recreating its graph, route geometries, polygons or establishment tiles:

```powershell
sigma view pasig --ui-only
# For another already-built area:
sigma view quezon_city --ui-only
```

`--ui-only` starts the normal local browser server, but copies only static website assets. It refuses an absent or unrecognized bundle, preserves the bundle's local/public profile, and **does not check whether the SIGMA data have changed**. Use `sigma view pasig` to check for changed outputs, or `sigma view pasig --refresh` to force regeneration; do not combine `--ui-only` with `--refresh`. Ordinary `sigma view` can rebuild after frontend code changes because the published bundle fingerprint includes frontend code.
 The CLI also supports custom `--workspace`, `--source-dir`, and `--output-dir` paths, and `--no-browser` or `--port` for local hosting preferences.

## Explore a cluster network

1. Pan and zoom the geographic map. Establishments are colored by economic type, with cluster partitions, centers, optional roads, and the analysis boundary as geographic context.
2. Select an establishment or cluster center. An establishment inherits its assigned `(type, cluster)` X node; it **does not** have its own firm-level supply-chain links.
3. Inspect incoming, outgoing, or combined connections, and increase the neighborhood depth from direct connections to two steps or the reachable neighborhood. Direction choices govern **neighborhood discovery**; the diagram retains the directed relationships among the displayed nodes.
4. Use theater view and fit-to-graph when a network is too crowded. Inspect edge attributes and highlight computed X-edge road paths in the map. Incoming routes are dashed blue and outgoing routes solid red.

**Interpretation matters:** A directed X edge represents a *modeled spatial-economic link* grounded in IO technical coefficients, overlapping cluster partitions, and routable road-network separation. It is **not verified trade between two specific establishments**. The displayed X edge weight is `technical_coefficient / max(road_distance_in_metres, 1) ** x_distance_decay_lambda`, not a probability. Routes use SIGMA's published shortest-path geometries; the routing graph itself is undirected.

For large views, Explorer can switch to density shading rather than loading more than 150,000 establishments at once. The network view is capped at 300 nodes and 1,500 directed edges per selection and marks truncated displays. Neither cap modifies the original SIGMA outputs.

## Export a browser bundle

```powershell
sigma export-web pasig             # full local-profile bundle
sigma export-web pasig --public    # reduced-data public-review profile
```

The first bundle normally lives in `<output>/explorer/` and includes individual establishments. **Do not publish it by default.** The `--public` variant normally lives in `<output>/explorer-public/` and omits individual establishment records, names, positions, IDs, and PSIC codes while retaining cluster/network information. It is **not an anonymity guarantee or license clearance**; locations of cluster centers and very small aggregate counts can still be revealing. Any public deployment requires independent data-rights, confidentiality, and attribution review.

Bundles are static website files; serve them over HTTP, not with `file://`. `sigma view` is the supported local server. The separate [SIGMA Jupyter Book website](https://projectsigma.github.io/sigma/) publishes **these explanations**, not your local datasets or an interactive Explorer automatically.

## Compare with QGIS and inspect source files

Use the generated `<area>.qgz` when you need normal GIS tooling and detailed layer inspection. Use **Explorer** to start from a mapped establishment and navigate its **cluster-level X neighborhood** interactively. Both are views of published SIGMA products, not alternate analytical engines.

Explorer principally reads `sigma_points.parquet`, `sigma_X_nodes.csv`, `sigma_X_edges.csv`, and the `clusters` and `paths` layers of `sigma_spatial_outputs.gpkg`; optional published roads, boundary, metadata, and manifest add map context and integrity checks. More detail is available in the repository's [SIGMA Explorer guide](https://github.com/projectsigma/sigma/blob/main/SIGMA_EXPLORER.md) and [Reading outputs](../reference/outputs.md).

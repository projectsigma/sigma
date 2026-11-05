# SIGMA Explorer — interactive map and directed network

SIGMA Explorer renders **existing published SIGMA results** as a static browser site. No SIGMA spatial, economic, classification, or network computations are rerun. The QGIS `.qgz` and all published analytical artifacts are left unchanged.

## Get started

Install SIGMA from its current source checkout in your active Python environment (Python 3.11+):

```powershell
python -m pip install -e .
```

Run the normal SIGMA analysis once, or reuse results that are already published:

```powershell
sigma run pasig
sigma view pasig
```

`view` generates or refreshes a derived `explorer/` site from SIGMA's existing output files, then starts a **local-only** HTTP server and normally opens your default browser. Press `Ctrl+C` in that terminal to stop the server. No separate QGIS or Node.js installation is required for ordinary use. The browser visualization does not recompute the analytical model.

For a run stored in a nondefault workspace or output location, pass `--workspace`, `--source-dir`, or `--output-dir` (see `sigma view --help`). The output directory must already contain a complete published SIGMA export.

The [README walkthrough](README.md) and [Explorer chapter in the SIGMA Jupyter Book](docs/book/content/intro/explorer.md) provide short entry points. The Jupyter Book website is documentation, not an automatic public deployment of any Explorer bundle.

## Commands

```powershell
sigma view pasig                        # build if stale and open at http://127.0.0.1:8765/
sigma view pasig --refresh              # force rebuild of the local bundle
sigma view pasig --fast                 # fast UI-only refresh for an existing bundle
sigma view pasig --no-roads             # omit visual road context; exact routes remain
sigma export-web pasig --force           # replace the existing full local bundle
sigma export-web pasig --public          # create a reduced public-review bundle
sigma export-web pasig --public --force
sigma view pasig --public               # view the public bundle; it stays public
```

By default `sigma view` reads the SIGMA workspace's published output directory, then serves `<output>\explorer`. It accepts `--workspace`, `--source-dir`, and `--output-dir`. The Python server listens on loopback only; change `--port` if needed.

`export-web --public` writes to `<output>\explorer-public` and **excludes individual establishment records, names, identifiers, positions, and PSIC codes**. It retains aggregate counts, cluster centers, cluster polygons, X edges, and the compact routing data used to draw exact X routes. Public-profile export is a privacy-reduction measure, **not** a legal review or a guarantee of safe publication; inspect input-output, source-data, attribution, and licensing obligations. The default `export-web` profile includes individual establishments and **must not** be published without such review. A public bundle is never rebuilt with establishment-level data: `sigma view` keeps the public profile for `explorer-public` (or any folder whose marker says public), and the builder refuses to write the full local profile into such a folder.

## Fast UI-only refresh

For changes to Explorer or Under the Hood **HTML, CSS, JavaScript, logo or favicon**, first make sure an Explorer bundle has already been generated. Then run:

```powershell
sigma view pasig --fast
# or for Quezon City:
sigma view quezon_city --fast
```

This copies the current UI assets into the existing SIGMA-owned bundle, starts the usual loopback-only local server, and opens the browser. It **does not** regenerate tiles, routes, cluster polygons, graph JSON or establishment data; it also **does not** recompute the analytical model. The existing public/private bundle profile remains unchanged, and a missing or unrecognized bundle is refused. It may be used with `--public`, `--workspace`, `--source-dir`, `--output-dir` and `--no-browser` as appropriate.

If your installed CLI reports `No such option: --fast`, make sure you are using this checkout and run `python -m pip install -e .`. Confirm with `sigma view --help`. `--ui-only` is an alias for `--fast`.

**Safety and freshness:** `--fast` deliberately skips source-data checks and leaves the generated ownership/freshness marker unchanged. Only use it when the published SIGMA data are unchanged. Ordinary `sigma view pasig` checks freshness and may perform a full rebuild, including after code or UI changes. `sigma view pasig --refresh` explicitly forces a full rebuild; it cannot be combined with `--fast`. If the generated Explorer's data schema has changed, use `--refresh` instead.

## Interface

The initial network view uses **Direct links** with the **3 per cluster** strongest-link limit. Both can be changed from the toolbar. The map uses no third-party background tiles; the published SIGMA roads give the geographic context.

- MapLibre GL JS map: sector-colored establishments, partitions, centers, boundary and optional published roads. Click an establishment or cluster center to select the corresponding X node.
- **Depth-based map opacity:** when a cluster is selected, its linked establishments, cluster-center triangles, and partition polygons fade according to **1/sqrt(network step)**. At step 1, linked establishments retain 90% opacity; at steps 2, 3, and 5 they retain about 63.6%, 52.0%, and 40.2%. Cluster triangles and polygon fills/outlines follow the same scaling relative to their own first-step opacity. The selected cluster and any selected establishment remain prominent. Colored road routes still use their existing depth-dependent width and opacity scaling; their paths, colors and the Cytoscape diagram are unchanged. The fade follows the current Links, Depth, Strongest, and sector filters.
- **Establishment finder (local bundles):** search by establishment name across the full area, optionally narrow to one sector, and select a match to zoom to its actual point. Duplicate names remain separate results. The finder is disabled in public bundles because those exclude establishment names and locations.
- **Collapsible right panel:** the Establishment Finder starts collapsed to leave space for the network. Selected location, Cluster network, Linked clusters, and Most central clusters can each be collapsed independently. The network starts expanded. Selecting an establishment from finder results automatically collapses the finder; reopening the network resizes its diagram.
- Cytoscape.js directed graph: direct, two-step or all reachable neighborhoods; outgoing, incoming, or both directions; top-N strongest connections per visited cluster. Direction controls how the neighborhood is discovered; the diagram shows all permitted directed edges among those discovered clusters, including edges between clusters at the maximum selected depth and reciprocal pairs. Arrowheads and coefficients follow the published X edge direction.
- **Theater view:** expand the network to a full-screen work surface; `Esc` returns to the normal layout, `Fit graph` restores the extent.
- **Exact road routes, computed in the browser by default:** numerical X exports the center-to-center road distances and weights **without** precomputing route geometries. The default bundle contains a validated compact road graph (road vertices and cluster centers only; establishment snap points are removed) and the center-node IDs. A Web Worker runs shortest-path reconstruction **on demand** for displayed links and checks each route length against the numerical X distance (tolerance `max(1e-6, 1e-8 × distance)`); it keeps up to 256 routes in a cache. A route is not a Euclidean chord or an approximation of the weighted `effective_road_distance`. Incoming routes are dashed blue and outgoing routes solid red; edge weights and hover explanations are those of the published numerical model. `sigma run AREA --route-geometry precomputed` instead writes GIS route paths into the GeoPackage at export, and a bundle built from that output reads them (with `reverse_of` reuse for reciprocal links). The browser mode does not store a route file for each X edge.
- **Large views:** when more than 150,000 individual establishments lie in the visible zoom-13 tiles, the map shows density shading built from establishment counts on a grid of about 1 km (zoom-15 cells, placed at cell centers, not at establishments) rather than an empty establishment layer. Zoom in to see individual records. This is an aggregation fallback, **not** a full vector-tile implementation.
- **Network limits:** a maximum of 300 network nodes and 1,500 **directed** edges are visualized per selection; the interface marks truncated views. Graph weights and provenance remain available in the source CSV/GeoPackage.

The network is **cluster-level**, not firm-to-firm. The presence of an X edge represents SIGMA's modeled input-output-spatial coupling with road-network reachability, **not a confirmed commercial transaction**. The graph direction represents modeled sector input supply, while road routing is computed on SIGMA's undirected road network. A numeric X `edge_weight` is `technical_coefficient * source_cluster_sector_share * target_cluster_sector_share / max(effective_road_distance_metres, 1) ** x_distance_decay_lambda` (exponent 1 by default), bounded by the coefficient; it is **not** a trade probability. The effective separation adds each cluster's mean establishment-to-median road distance to the actual center-to-center route length; a drawn route is always center-to-center. A bundle shows the weights of the analysis it was built from; after a new `sigma run`, refresh it with `sigma view AREA --refresh`.

## Fixed sector colors, rolled-up industries, and contextual polygons

- **Fixed sector palette:** SIGMA uses one 336-color specification: 16 IO16, 80 IO80, and 240 IO240 colors. A sector's color is stable across areas and sector order, for sparse hierarchy codes and for plain numeric codes alike. An `o` residual uses its parent's color. Sector swatches, scored-point circles, cluster triangles, and polygon boundaries use the effective sector's color, except for points whose original industry is shown separately.
- **Rolled-up original industries (stage 9):** In the local Explorer, a sector that received places from zero-cluster roll-up has an expandable breakdown of original industry codes, labels and place counts. Each child has a fixed-color swatch and an independent *point-layer* checkbox. Child-specific points keep their original industry's fixed color; their economic type for scoring is the effective rolled-up parent. Visibility does not split the parent's X nodes, cluster counts, Voronoi surfaces or scores. Counts refer to classified establishments, not only HDBSCAN-retained members.
- **Two different opt-in unclustered views:** The unclustered toggle shows classified-but-unscored points without a selected X network. With a scored point or cluster selected, **Unclustered within highlighted partitions** instead displays unclustered points of the matching effective sector that lie inside the published Voronoi polygons of the focused and linked X clusters. Focus markers use opacity 0.96; a linked cluster at step `d` has opacity `0.90 / sqrt(d)`. Points outside that context stay hidden. This is geographic context, **not** inferred HDBSCAN membership, Voronoi-based reassignment, a new X node, or an imputed SIGMA score. Different sectors' partition polygons may overlap.
- **Cluster-center hover boundary:** After selecting a scored establishment or cluster, hovering a visible cluster-center triangle temporarily outlines that center's exported Voronoi partition in the center's sector color. This works even with the ordinary partitions setting off. The overlay clears when the pointer leaves, the map moves, or the selection or filters change. It never rewrites the partitions or alters the selected X neighborhood.

These are browser presentation rules. They do not change network HDBSCAN, Gap refinement, 1-medians, the road graph, national IO transactions, technical coefficients, network X, centrality or establishment scores. The local point-level overlays are **not available** in public bundles. Explorer bundles include per-establishment original-sector provenance; a metadata-only migration of an existing local bundle can use its validated rolled-up published inputs and a compact original-ID override. A static-only `sigma view AREA --fast` does not regenerate data, metadata, routing data, or establishment tiles.

## Inputs

Required: `sigma_points.parquet`, `sigma_X_nodes.csv`, `sigma_X_edges.csv`, and `sigma_spatial_outputs.gpkg` containing `clusters` and `paths` layers. In the **default browser-routing mode**, the `paths` layer contains no precomputed X routes; `sigma_routing_graph.bin`, `sigma_run_metadata.json` with `route_mode=browser`, and node-table `routing_node` IDs provide the on-demand route inputs. The Explorer builder verifies that these correspond and refuses an unsafe or incomplete browser graph. The explicit precomputed mode instead fills the `paths` layer. Optional: `sigma_manifest.json`, `sigma_boundary.parquet`, `sigma_roads.parquet`, `ATTRIBUTION.txt`, and `DATABASE_LICENSE.txt`.

The bundle builder compares file content hashes, checks the listed SHA-256 hashes and sizes in an authentic SIGMA export manifest where present, validates X edges against the selected route publication mode, and rejects cluster partitions without X nodes. A failed staged replacement preserves the previously published bundle. Hash checking may take noticeable disk I/O for large GeoPackages; this prioritizes correctness over instantaneous freshness checks. SIGMA's export overwrites files but never deletes old ones, so when the manifest lists the run's files, an optional file it does not list (for example a boundary left from an earlier run) is ignored and reported as a note.

### Storage and cleanup

An Explorer bundle is a separate, browser-ready copy of selected published data. It is **not**
a disposable cache: SIGMA's storage cleanup preserves the current `explorer/` and
`explorer-public/` folders, their ownership markers, and all published GIS output.
After a successful refresh, the builder removes its own staging and replaced backup.
If an interrupted run leaves abandoned `.explorer.staging-*`,
`.explorer.backup-*`, or `.sigma-ui-*` files, use `sigma storage report` or
`sigma storage prune` to preview eligible debris; `sigma storage prune --apply` removes
only recognized candidates older than 30 days. Explorer backups are eligible only when
a replacement bundle with its ownership marker and `index.html` exists. Close SIGMA
viewers and other processes before applying cleanup. See [Storage maintenance](STORAGE.md).

Explorer's generated data files contain only the fields explicitly selected by the builder; extra columns from SIGMA's source point dataset are not copied. Coordinates in browser geometries are rounded to six decimal places **only in the derived visualization**. Native SIGMA files remain unchanged.

The site uses bundled MapLibre GL JS (4.7.1) and Cytoscape.js (3.30.4) with licenses. It does not use third-party background-map tiles: the map shows published SIGMA roads and local Explorer data. Open through `sigma view` or an HTTP server, not `file://`.

## Testing

```powershell
python -m pytest -q tests/test_web_explorer.py
python -m pytest -q
python -m compileall -q src/sigma/web
```

JavaScript regressions use Node.js when available:

```powershell
node --check src/sigma/web/static/network-model.js
node tests/test_explorer_network.js
```

The repository also includes `.github/workflows/explorer_js.yml` to run these JavaScript checks on GitHub pushes and pull requests. Real Pasig results have been generated and the principal browser interactions checked manually; local data content and rendering may still differ across areas or environments.

## Safety, upgrades, and publication

Explorer is part of the `sigma.web` Python package in this repository. Normal SIGMA package upgrades carry the visualizer with them; no overlay installer is needed. Generated browser files are separate from the managed analytical outputs, and the builder stages replacements so a failed build does not overwrite the prior valid site. Browser bundles are subject to source-file integrity checks.

The full local export contains individual establishment locations; do not upload it to GitHub Pages or other public hosting without independent review of data rights, source licenses, confidentiality, and inference risks. `--public` writes a reduced-data bundle, but cluster centers, polygons, and small aggregate counts can still create disclosure risks. A public-marked bundle is not silently replaced with a full local bundle. Publishing a reviewed static site is an **explicit separate step**; `sigma view` never creates an internet-facing server.

The output directory must not overwrite the SIGMA source export directory or its ancestors. Avoid manually modifying the generated `.sigma-explorer` ownership marker or force-replacing unknown directories.

## Under the Hood (area and economy aware)

Open **Under the Hood** in the Explorer header. It explains the whole SIGMA pipeline in its 17 stages, each with a worked, interactive example:

| Part | Stages | Interactive examples |
|---|---|---|
| 1 Places and sectors (`sigma load`) | 1–5 | source matching; the administrative-office rule; PSIC → IO candidates; the ownership evidence ladder; area sectors with `min_places` and the residual or contain coarse-place policy; review and augmentation between load and run |
| 2 Roads, clusters and territories (`sigma run`) | 6–12 | road graph and snapping; network HDBSCAN*; zero-cluster roll-up (why a sector of fewer than 10 places always has K=0, and the residual-first trials); network Gap k-medoids, computed live on a road example; 1-median centers; network Voronoi |
| 3 Economy (`sigma run`) | 13 | technical coefficients and the default graph |
| 4 Graph X and scores (`sigma run`) | 14–17 | X weights, directed Katz, balanced centrality, establishment scores |
| 5 Routes and limits | publication | browser route reconstruction from the compact routing graph, the precomputed alternative, what each setting recomputes, and limitations |

Read-only evidence panels are tailored to this Explorer bundle's **area**, selected **economy**, **sectors**, **cluster centers**, **X links**, **coefficients**, **centrality**, and **score range**, and a note under every step shows what the bundle publishes for that stage (for example its sector codes, rolled-up sectors, final cluster counts and route mode). The sector and cluster selectors change the real-world case study; choose **Examine this cluster in Explorer** to return to the map and its shortest road routes. An Explorer X node that is selected when you open Under the Hood is passed to it.

The worked examples show the canonical defaults (Gap refinement with four worker processes, zero-cluster roll-up for generated hierarchies); they are **not a claim that a given bundle ran with those settings**. Audit the run's configuration in `run.json`, `rollup_audit.json` and `median_gap_audit.json`. The Gap example runs in the browser on its own small road graph; Under the Hood does not rerun Gap on the bundle's data or read `median_gap_audit.json` as a browser input.

The panels use `data/metadata.json` and `data/graph.json` and do not run classification, clustering, route-finding on the bundle's data, IO recalculation, or scoring. The animated diagrams and example numbers are **illustrative**: matching candidate scores, core distances, the transaction matrix Z, raw Katz components, and individual point scores are not all part of the exported graph, and Under the Hood never invents them. On `--public` bundles, it reads only published aggregate data and does not look for individual establishment records.

For a CSS or Under the Hood-only change, use `sigma view pasig --fast` on an existing bundle. For changed SIGMA outputs or a required data-schema rebuild, use `sigma view pasig --refresh` (or another existing area slug). A plain `sigma view pasig` also rebuilds when the fingerprint changes. Under the Hood is included in both local and reduced public-profile bundles.

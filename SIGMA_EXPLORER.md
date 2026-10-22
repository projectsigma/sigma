# SIGMA Explorer — interactive map and directed network

This additive module renders **existing published SIGMA results** as a static browser site. No SIGMA spatial, economic, classification, or network computations are rerun. The QGIS `.qgz` and all published analytical artifacts are left unchanged.

## Get started

Install SIGMA from its current source checkout in your active Python environment (Python 3.11+):

```powershell
python -m pip install -e .
```

Run the normal SIGMA analysis once, or reuse previously published results:

```powershell
sigma run pasig
sigma view pasig
```

`view` generates or refreshes a derived `explorer/` site from SIGMA's existing output files, then starts a **local-only** HTTP server and normally opens your default browser. Press `Ctrl+C` in that terminal to stop the server. No separate QGIS installation, Node.js installation, or Explorer ZIP patch is required for ordinary use. The browser visualization does not recompute the analytical model.

For a run stored in a nondefault workspace or output location, pass `--workspace`, `--source-dir`, or `--output-dir` (see `sigma view --help`). The output directory must already contain a complete published SIGMA export.

The [README walkthrough](README.md) and [Explorer chapter in the SIGMA Jupyter Book](docs/book/content/intro/explorer.md) provide short entry points. The Jupyter Book website is documentation, not an automatic public deployment of any Explorer bundle.

## Commands

```powershell
sigma view pasig                        # build if stale and open at http://127.0.0.1:8765/
sigma view pasig --refresh              # force rebuild of the local bundle
sigma view pasig --no-roads              # omit visual road context; exact routes remain
sigma export-web pasig --force           # replace the existing full local bundle
sigma export-web pasig --public          # create a reduced public-review bundle
sigma export-web pasig --public --force
sigma view pasig --public               # view the public bundle; it stays public
```

By default `sigma view` reads the SIGMA workspace's published output directory, then serves `<output>\explorer`. It accepts `--workspace`, `--source-dir`, and `--output-dir`. The Python server listens on loopback only; change `--port` if needed.

`export-web --public` writes to `<output>\explorer-public` and **excludes individual establishment records, names, identifiers, positions, and PSIC codes**. It retains aggregate counts, cluster centers, cluster polygons, X edges, and exact X routes. Public-profile export is a privacy-reduction measure, **not** a legal review or a guarantee of safe publication; inspect input-output, source-data, attribution, and licensing obligations. The default `export-web` profile includes individual establishments and **must not** be published without such review. A public bundle is never rebuilt with establishment-level data: `sigma view` keeps the public profile for `explorer-public` (or any folder whose marker says public), and the builder refuses to write the full local profile into such a folder.

## Interface

The initial network view uses **Direct links** with the **5 per cluster** strongest-link limit. Both can be changed from the toolbar. The optional OpenStreetMap raster background has been removed; the published SIGMA roads remain available.

- MapLibre GL JS map: sector-colored establishments, partitions, centers, boundary and optional published roads. Click an establishment or cluster center to select the corresponding X node.
- **Depth-based map opacity:** when a cluster is selected, its linked establishments, cluster-center triangles, and partition polygons fade according to **1/sqrt(network step)**. At step 1, linked establishments retain 90% opacity; at steps 2, 3, and 5 they retain about 63.6%, 52.0%, and 40.2%. Cluster triangles and polygon fills/outlines follow the same scaling relative to their own first-step opacity. The selected cluster and any selected establishment remain prominent. Colored road routes still use their existing depth-dependent width and opacity scaling; their paths, colors and the Cytoscape diagram are unchanged. The fade follows the current Links, Depth, Strongest, and sector filters.
- **Establishment finder (local bundles):** search by establishment name across the full area, optionally narrow to one sector, and select a match to zoom to its actual point. Duplicate names remain separate results. The finder is disabled in public bundles because those exclude establishment names and locations.
- **Collapsible right panel:** the Establishment Finder starts collapsed to leave space for the network. Selected location, Cluster network, Linked clusters, and Most central clusters can each be collapsed independently. The network starts expanded. Selecting an establishment from finder results automatically collapses the finder; reopening the network resizes its diagram.
- Cytoscape.js directed graph: direct, two-step or all reachable neighborhoods; outgoing, incoming, or both directions; top-N strongest connections per visited cluster. Direction controls how the neighborhood is discovered; the diagram shows all permitted directed edges among those discovered clusters, including edges between clusters at the maximum selected depth and reciprocal pairs. Arrowheads and coefficients follow the published X edge direction.
- **Theater view:** expand the network to a full-screen work surface; `Esc` returns to the normal layout, `Fit graph` restores the extent.
- **Exact routes:** incoming and outgoing edges retain their **own** published road geometries. They are not merged or approximated as straight geographic chords. On the map, incoming routes are dashed blue and outgoing routes solid red; for a link in both directions both lines lie on the same road. Line width reflects the coefficient **relative to the strongest direct displayed link**. Hovering a route lists every route under the pointer (up to three linked clusters), each with both coefficients, X weights and the road distance. In a route file, a reverse edge whose path is exactly the reversed forward path is stored once (`reverse_of`) and rebuilt in the browser; paths that differ are stored separately.
- **Large views:** when more than 150,000 individual establishments lie in the visible zoom-13 tiles, the map shows density shading built from establishment counts on a grid of about 1 km (zoom-15 cells, placed at cell centers, not at establishments) rather than an empty establishment layer. Zoom in to see individual records. This is an aggregation fallback, **not** a full vector-tile implementation.
- **Network limits:** a maximum of 300 network nodes and 1,500 **directed** edges are visualized per selection; the interface marks truncated views. Graph weights and provenance remain available in the source CSV/GeoPackage.

The network is **cluster-level**, not firm-to-firm. The presence of an X edge represents SIGMA's modeled input-output-spatial coupling with road-network reachability, **not a confirmed commercial transaction**. The graph direction represents modeled sector input supply, while road routing is computed on SIGMA's undirected road network. A numeric X `edge_weight` is `technical_coefficient × road_distance`; it is **not** a proximity probability.

## Inputs

Required: `sigma_points.parquet`, `sigma_X_nodes.csv`, `sigma_X_edges.csv`, and `sigma_spatial_outputs.gpkg` containing `clusters` and `paths` layers. Optional: `sigma_run_metadata.json`, `sigma_manifest.json`, `sigma_boundary.parquet`, `sigma_roads.parquet`, `ATTRIBUTION.txt`, and `DATABASE_LICENSE.txt`.

The bundle builder compares file content hashes, checks the listed SHA-256 hashes and sizes in an authentic SIGMA export manifest where present, validates X-edge-to-route correspondences, and rejects cluster partitions without X nodes. A failed staged replacement preserves the previously published bundle. Hash checking may take noticeable disk I/O for large GeoPackages; this prioritizes correctness over instantaneous freshness checks. SIGMA's export overwrites files but never deletes old ones, so when the manifest lists the run's files, an optional file it does not list (for example a boundary left from an earlier run) is ignored and reported as a note.

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

## Guided tutorial (area and economy aware)

Open **Guided tutorial** in the Explorer header. The tutorial retains the
original *SIGMA, Step by Step* interactive mathematical walkthrough and adds
read-only evidence panels tailored to this Explorer bundle's **area**, selected
**economy**, **sectors**, **cluster centers**, **X links**, **coefficients**,
**centrality**, and **score range**. The sector and cluster selectors let you
change the real-world case study; choose **Examine this cluster in Explorer**
to jump back to the map and its exact computed road paths. A currently selected
Explorer X node is passed to the tutorial when opened from the header.

The additional panels use `data/metadata.json` and `data/graph.json` and do not
run classification, clustering, route-finding, IO recalculation, or scoring.
The tutorial's animated diagrams and example numbers remain **illustrative**:
matching candidate scores, core distances, the transaction matrix Z, raw Katz
components, and individual point scores are not all part of the exported graph.
The tutorial never invents them. On `--public` bundles, the tutorial reads only
published aggregate data and does not seek individual establishment records.

After installing an Explorer update, refresh derived bundles with
`sigma view pasig --refresh` (or another existing area slug). A plain
`sigma view pasig` will also rebuild when the fingerprint changes. The tutorial
is included in both local and reduced public-profile bundles.


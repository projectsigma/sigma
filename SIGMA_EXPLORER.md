# SIGMA Explorer — interactive map and directed network

This additive module renders **existing published SIGMA results** as a static browser site. No SIGMA spatial, economic, classification, or network computations are rerun. The QGIS `.qgz` and all published analytical artifacts are left unchanged.

## Installation (PowerShell)

Extract the supplied ZIP. In the active SIGMA Python/conda environment run:

```powershell
& "$HOME\Downloads\sigma_explorer_v3.1.1_final_overlay\Apply-SigmaExplorerOverlay.ps1"
```

The installer defaults to `C:\Users\James Matthew\Documents\GitHub\sigma`. Supply `-Repo 'D:\path\sigma'` for another checkout. It replaces the clearly owned Explorer section in `src/sigma/cli.py`, updates the `sigma.web` package-data entry in `pyproject.toml`, adds `src/sigma/web`, tests, and this documentation, reinstalls the editable package, and runs tests when available. Review `git diff` before committing. It can be reapplied over the previous Explorer overlays.

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

- MapLibre GL JS map: sector-colored establishments, partitions, centers, boundary and optional published roads. Click an establishment or cluster center to select the corresponding X node.
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

The site uses bundled MapLibre GL JS (4.7.1) and Cytoscape.js (3.30.4) with licenses. It makes no network request unless the optional OpenStreetMap raster background is enabled. Open through `sigma view` or an HTTP server, not `file://`.

## Testing

```powershell
python -m pytest -q tests/test_web_explorer.py
node tests/test_explorer_network.js
python -m compileall -q src/sigma/web
```

The Python suite requires all normal SIGMA dependencies, including `pyarrow`. It includes a **genuine synthetic SIGMA run** integration test (which can take longer than the small fixture tests). The Node test checks direction-specific multi-hop traversal and reciprocal edges. Browser behaviour was checked with headless Chromium on two genuine SIGMA exports of synthetic cities (1,513 establishments / 70 clusters / 1,736 X edges, and 15,826 / 826 / 27,290); see FINAL_PASS_NOTES.md in the overlay ZIP. A check on real Pasig outputs is still recommended before release.

## Upgrade, remove, safety

The installer replaces only Explorer-owned files and a marked CLI section plus its package-data entry. It does not change SIGMA algorithms or underlying outputs. Inspect before committing:

```powershell
git diff --check
git diff -- src/sigma/cli.py pyproject.toml
git status --short
```

To remove, restore the affected CLI and pyproject lines and delete `src/sigma/web/`, `tests/test_web_explorer.py`, `tests/test_explorer_network.js`, and `SIGMA_EXPLORER.md`. No SIGMA artifacts or workspaces need removal.

The Explorer protects against publishing on top of the source output root or its ancestors. Within source outputs it uses only the dedicated `explorer/` and `explorer-public/` children; replacing an existing site requires an ownership marker and `index.html`. Avoid manually modifying markers or running `--force` on unreviewed paths.

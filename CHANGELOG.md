# Changelog

## Unreleased — Explorer unclustered visibility and PSIC details (PR #35)

- Local Explorer now provides two independent, initially off checkboxes: **Show unscored sectors**
  (zero-cluster sectors, no network selected) and **Show unclustered for scored sectors**
  (all eligible points without a selection; inside highlighted focus/linked same-sector
  Voronoi polygons with a scored-network selection).
- Both overlays use hollow, sector-colored circles sized from the minimum scored establishment
  of the effective sector, or the global scored minimum for zero-cluster sectors. This is only
  visual sizing; unclustered places remain without a cluster, X membership, or SIGMA score.
- Unclustered circle opacity is not network-depth dependent. Scored establishments retain their
  own depth-based opacity, and visibility follows network and sector filters.
- The local establishment panel displays PSIC code and available descriptive title, preferring
  explicit source titles before the bundled PSIC Rev. 5 taxonomy; missing titles are not inferred.

## Unreleased — Network Voronoi grid convergence (stage 12)

- The default start spacing of the Voronoi grid is now 50 m (`--voronoi-resolution`, `SpatialConfig.voronoi_resolution`, `SpatialRunConfig.voronoi_resolution`); it was 500 m. The legacy `--equivalent` profile uses the same start.
- Before building any cell, SIGMA counts the candidate cells over the bounding box of the study boundary. If the start spacing needs more than `voronoi_max_cells` (1,000,000), it doubles the spacing and bisects 12 times toward the finest budget-feasible spacing (event `coarsened_grid_budget`).
- A successful grid no longer ends refinement. Each sector is halved and rendered again until the changed-owner area fraction between successive valid surfaces is at most 0.005 (`converged_resolution`), the next grid would exceed the cell budget, a finer rendering fails (`retain_last_valid_network_resolution`), or five refinements are made (`max_refinements_reached`). The finest valid network surface is kept; a failure at a finer spacing does not discard it. Euclidean fallback runs only when a sector has no valid network surface; a cluster that gets no cell at a spacing whose finer grid exceeds the budget is recorded as `grid_budget_cluster_conflict`.
- `surface_resolution` now reports the spacing of the kept (finest valid) surface, and `partition_diagnostics.json` contains one terminal event per sector with a network surface, so a clean run no longer has an empty event list.
- The `spatial.partitions` recipe records `convergence_tolerance`, and its implementation version changed (`network-voronoi-step4-v5-50m-bidirectional-convergence`). Existing workspaces recompute stage 12 and the later stages on the next `sigma run`; clusters and centers are reused. Stage 12 takes longer than before.
- Documentation: the Network Voronoi method page (grid spacing, changed-owner area, cell-budget limits, diagnostics), defaults, outputs, README, CLI reference and Under the Hood describe the new rule.

## Unreleased — IO tagging review fixes

- IO tagging below PSIC groups: added `io/psic_rev5_io240_refinement.csv` (280 draft rows that narrow
  IO240 candidates of Rev. 5 classes and subclasses inside their group's set) and `io/io240_parents.csv`
  (one IO80 parent per IO240 code). Refinement may only narrow; IO80/IO16 sets follow the IO240 parents.
- PSIC decisions with status `UNION` are mapped as the union of their members' IO sets.
- Reviewed category rows point below Rev. 5 divisions that mix I-O sectors (retail 47, accommodation 55,
  wholesale 46, finance 64); OSM `shop=beauty` is now a beauty service (962), as the OSM wiki defines it;
  the hotel/resort name rule targets group 551; the construction name rule excludes supply and hardware stores.
- A trusted category floor now takes precedence over a disjoint name rule (`NAME_RULE_OVERRULED_BY_CATEGORY`).
- Direct IO80 rules match parsed OSM `key=value` tags only (no substrings, no names); primary tags decide
  before `cuisine`/`brand`/`operator`; tags that disagree are a conflict.
- Added ownership evidence (policy ownership-v2, tightened after review) for public/private education and health pairs.
- Added a per-row level-consistency guard (`LEVEL_CONFLICT`, `DERIVED_FROM_IO240`, `DERIVED_FROM_IO80`)
  and an `io_mapping_provisional` flag.
- Hierarchical economy: optional `coarse_policy="contain"` assigns a coarse place only to a sector that
  contains all of its IO240 candidates and keeps a parent whole when more than `max_straddle_share`
  (default 0.25) of its places would straddle the split. The default is `coarse_policy="residual"`
  (`DEFAULT_COARSE_POLICY`); `contain` is used only when a profile selects it explicitly, and profiles
  without a saved policy use residual.
- `tagging_consistency` checks every IO240 parent link. The Explorer shows a "Sector basis" for each place.
- Targeted second-pass corrections: disjoint IO240 candidate sets become explicit conflicts rather
  than parent fallbacks; generic education/health ownership cues no longer imply ownership;
  hierarchical exports label provisional and inferred classifications for review. Added a read-only
  before/after workspace and optional scored-output comparison utility.
- Documentation: new method page "Hierarchical economy".

## Unreleased — SIGMA Explorer

- Added local browser exploration of published SIGMA establishments, clusters, directed X-network edges, and exact road paths.
- Added `sigma view` and `sigma export-web`, bundled offline map/graph libraries, and an explicitly reduced public-review profile.
- Added Explorer regression/integration tests and protections for source integrity and generated bundle replacement.

## 0.1.0.dev0

Initial unified SIGMA development release.

- Unified place acquisition/classification, road-network spatial analysis, input-output modeling, and
  spatial-economic graph analysis in one `sigma` package.
- Added the public `Sigma` facade and thin `sigma` CLI over a shared dependency-aware stage graph.
- Added manifest-backed immutable artifacts, resumable workspaces, shared source storage, provenance,
  and selective recomputation.
- Added the canonical Philippine area catalog and exact boundaries.
- Added OSM/Geofabrik and Overture place acquisition, reconciliation, PSIC classification, and
  PSIC-to-economy tagging.
- Added managed Geofabrik roads as the normal area-mode road source, with explicit file-road override.
- Added sparse road-network clustering, network centers/distances, network Voronoi partitions, and
  spatial outputs.
- Added built-in PSA 2018 IO80/IO16 economies and custom-economy support.
- Made unprocessed directed input-output relationships the canonical economic graph; added optional
  fast MWAS + RAS balanced sparsification.
- Added spatial-economic X graph construction, centrality, point scoring, unified export, and restart
  compatibility readers.
- Removed obsolete two-repository orchestration and construction-checkpoint scaffolding from the
  distributable repository.

# Changelog

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
- Hierarchical economy: new default `coarse_policy="contain"` assigns a coarse place only to a sector that
  contains all of its IO240 candidates and keeps a parent whole when more than `max_straddle_share`
  (default 0.25) of its places would straddle the split. The legacy residual rule remains as
  `coarse_policy="residual"`. Newly configured profiles use containment; historical profiles
  without a saved policy keep the legacy residual policy to avoid silent migration.
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

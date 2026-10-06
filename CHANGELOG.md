# Changelog

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

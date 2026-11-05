# Resumable savepoints for long SIGMA stages

The normal artifact store is authoritative. SIGMA can reuse a stage only when its entire artifact has been committed and verified. In addition, the stages that can otherwise waste hours when interrupted keep **durable intermediate work units** (savepoints):

| Stage | Recovery unit | What is resumed |
| --- | --- | --- |
| `spatial.clusters` (stages 8–10) | one economic type | final memberships, cluster IDs, summary/trace and per-type recovery events |
| `spatial.partitions` (stage 12) | one economic type | completed GeoParquet partition(s) and fallback/skip audit events |
| `analysis.x` (stage 14) | one source economic type | X edges, disconnected-pair diagnostics and omitted self-edge counts (`edges.json`); the managed run computes numerical X without route geometry |
| `export.bundle` (publication) | completed GeoPackage / QGIS project | full verified output file; remaining export contents may still be regenerated |

## Storage, integrity, and stale data

Recovery data is stored under `<workspace>/state/savepoints/<stage>/<artifact-recipe-fingerprint>-<implementation-signature>/`. A work unit is eligible for reuse **only** when its manifest exists, its exact stage and recipe-plus-code fingerprint agree, and **all** constituent files match their declared SHA-256 hashes and lengths. The manifest is published last, using atomic replacement. A partial write, missing file or corrupt file therefore causes the affected unit to be recomputed. No untrusted pickle deserialization is used.

When a complete, immutable stage artifact is committed (or an already valid artifact is reused), SIGMA clears that stage's savepoints best-effort. If an operating-system lock prevents deletion, the committed artifact is not invalidated. If the stage is interrupted, savepoints remain available for the next identical recipe.

**Changing source data, roads, the economic graph, upstream artifact IDs, configuration, or the stage implementation/producer fingerprint creates a distinct recovery namespace.** A signature of the relevant installed implementation files also prevents reuse after local code changes that have not changed the package version. Savepoints of unsuccessful runs are not deleted by the storage pruner; they can consume disk. To inspect them, look under `state/savepoints/` while SIGMA is idle. Do not remove a current run's savepoints or delete them in the middle of an active run.

## What is *not* checkpointed

- Individual HDBSCAN trials, individual Gap reference draws and individual Voronoi refinement attempts.
- A source type's X edges before that source type completes.
- Katz centrality iterations and establishment scoring (these have separate completed-stage artifacts).
- Download streams: Geofabrik has its own range-resumable download; OSM preparation maintains its own nationwide/LGU-stage savepoints.
- The entire export bundle is committed once, even though completed heavy files can be reused if the export build is interrupted.

## Operational notes

A Python process that imported SIGMA before an update keeps the modules it imported; let a running process finish before updating the installation. `python -m pytest tests/test_resume_savepoints.py -q` checks the savepoint behaviour. To keep normal artifact reuse, use the same `sigma run ...` command again without `--force`. Savepoints never override SIGMA's validated upstream artifact identities. Checkpoint failures are reported as ordinary stage failures rather than silently accepting partial or corrupt results.

Savepoints do **not** change road distances, shortest paths, sector selection, clustering parameters, edge weight formulas, centrality methods, score formulas, or published output schemas.

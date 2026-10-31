# Resumable savepoints for long SIGMA stages

The normal artifact store remains authoritative. SIGMA can reuse a stage only when
its entire artifact has been committed and verified. This patch adds **durable
intermediate work units** for stages that can otherwise waste hours when interrupted.

| Stage | Recovery unit | What is resumed |
| --- | --- | --- |
| `spatial.clusters` | one economic type | final memberships, cluster IDs, summary/trace and per-type recovery events |
| `spatial.partitions` | one economic type | completed GeoParquet partition(s) and fallback/skip audit events |
| `analysis.x` instantiation | one source economic type | all shortest-path node sequences, X edges, disconnected diagnostics and skipped self-edge counts |
| `analysis.x` route geometry | 25,000 directed X edges | complete route geometries (WKB); the normal stage still writes WGS84 GeoParquet |
| `export.bundle` | completed GeoPackage / QGIS project | full verified output file; remaining export contents may still be regenerated |

## Storage, integrity, and stale data

Recovery data is stored under
`<workspace>/state/savepoints/<stage>/<artifact-recipe-fingerprint>-<implementation-signature>/`.
A work unit is eligible for reuse **only** when its manifest exists, its exact stage
and recipe-plus-code fingerprint agree, and **all** constituent files match their declared
SHA-256 hashes and lengths. The manifest is published last, using atomic replacement.
A partial write, missing file or corrupt file therefore causes the affected unit
to be recomputed. No untrusted pickle deserialization is used.

When a complete, immutable stage artifact is committed (or an already valid artifact
is reused), SIGMA clears that stage's savepoints best-effort. If an operating-system
lock prevents deletion, the committed artifact is not invalidated. If the stage is
interrupted, savepoints remain available for the next identical recipe.

**Changing source data, roads, the economic graph, upstream artifact IDs, configuration,
or the stage implementation/producer fingerprint creates a distinct recovery namespace.**
A signature of the relevant installed implementation files also prevents reuse after
local code changes that have not yet bumped the package version.
Old, unsuccessful-run savepoints are not automatically deleted by the current storage
pruner; they can consume disk. To inspect these, look under `state/savepoints/` while
SIGMA is idle. Do not remove a current run's savepoints or delete them in the middle
of an active run.

## What is *not* checkpointed

- Individual HDBSCAN trials and individual Voronoi refinement attempts.
- A source type's route solving before that source type completes.
- Route geometries inside an incomplete 25,000-edge batch.
- Katz centrality iterations and establishment scoring (already have separate
  completed-stage artifacts).
- Download streams: Geofabrik has its own range-resumable download; OSM preparation
  maintains its own nationwide/LGU-stage savepoints.
- The entire export bundle is still committed once, even though completed heavy
  files can be reused if the export build is interrupted.

## Operational instructions

Leave a SIGMA process already running to finish before installing the patch. A
Python process that imported the old modules cannot retroactively acquire savepoints.

After applying the patch, run `python -m pytest tests/test_resume_savepoints.py -q`.
For subsequent runs, use the same `sigma run ...` command without `--force` to retain
normal artifact reuse. Savepoints never override SIGMA's validated upstream artifact
identities. Checkpoint failures are reported as ordinary stage failures rather than
silently accepting partial or corrupt results.

The patch deliberately does **not** modify road distances, shortest-path geometry,
sector selection, clustering parameters, edge weight formulas, centrality methods,
score formulas, or published output schemas.

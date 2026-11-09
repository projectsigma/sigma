# Reproducibility: recipes, artifacts, and selective recomputation

SIGMA does not treat a pipeline stage as valid merely because a file with the expected name exists. Each managed stage has a deterministic **artifact recipe**.

A recipe records:

- stage name;
- artifact schema version;
- implementation version;
- SIGMA producer version;
- normalized parameters;
- upstream artifact identities;
- external source identities and hashes where applicable;
- packaged resource identities; and
- additional semantic identities such as economy fingerprints.

The recipe is canonicalized to JSON and hashed with SHA-256. Output files are themselves hashed. The resulting artifact identity therefore binds requested computation to both the recipe and the actual produced files.

## Roll-up and Explorer presentation provenance

A generated hierarchical analysis can retain a baseline catalog and a
separately identified, provenance-checked **iterative roll-up derived
economy** (stage 9) under `hierarchical/iterative_rollup/<recipe-hash>/`, with a
`rollup_manifest.json` of file hashes that is verified before reuse. The resulting run's declared Economy ID, classified POIs, X
nodes, polygon partition ownership and published outputs must agree before
its Explorer data are considered current. The original sector tag is kept
separately from the effective sector used by the model.

Presentation-only changes—fixed colors, child-point checkboxes, contextual
unclustered overlays, and hovered partition outlines—do not invalidate
spatial or scoring artifacts. `sigma view AREA --fast` copies only frontend
assets into an already-owned Explorer; it does **not** refresh sector
metadata or tile contents. A separately guarded, local metadata-only
migration can update small provenance/color metadata for an existing verified
bundle without regenerating its routing data or tiles. A full `sigma view` refresh is
needed when genuinely changed underlying published data must be reflected.

(resumable-savepoints-inside-long-stages)=
## Resumable savepoints inside long stages

A stage artifact is reusable only after it has been committed completely. Long stages additionally keep **savepoints**, durable work units under `<workspace>/state/savepoints/<stage>/<recipe-fingerprint>-<code-signature>/`, so that an interrupted run resumes instead of starting the stage again:

| Stage | Work unit |
|---|---|
| `spatial.clusters` | one sector: final memberships, cluster IDs, summary, trace and recovery events |
| `spatial.partitions` | one sector: completed partitions and fallback events |
| `analysis.x` | one source sector: X edges, disconnected-pair diagnostics and omitted self-edges (no route geometry) |
| `export.bundle` | the completed GeoPackage and the completed QGIS project |

A unit is reused only when its manifest exists, its stage, recipe fingerprint and implementation-code signature agree, and every file matches its recorded SHA-256 hash and length. The manifest is written last, by atomic replacement, so a partial or corrupt unit is recomputed. Savepoints are cleared once the stage artifact is committed. They never override validated upstream artifact identities, and they change no formula or output schema. See [`docs/SIGMA_SAVEPOINTS.md`](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_SAVEPOINTS.md).

## Selective invalidation

Suppose only the Katz attenuation parameter or area-adjustment choice changes. Area, source, places, roads, clusters, centers, final partitions, economy, and **original unadjusted X** can remain reusable because their recipes do not depend on these centrality settings. The canonical adjusted centrality stage additionally reads the existing partition areas, without rewriting them. `analysis.centrality` changes, and `analysis.scores` changes because it depends on centrality.

Conversely, changing `vertex_digits` invalidates road topology and propagates through every network-dependent spatial and analysis stage.

Other examples: switching Gap refinement on or off, or changing its settings, invalidates `spatial.clusters` and everything downstream; changing `--median-gap-workers` invalidates nothing, because the worker count is not part of any recipe and 1 to 4 workers give identical results; changing `--route-geometry` invalidates only `export.bundle`; changing `--voronoi-resolution` (the start spacing of the stage 12 grid) invalidates `spatial.partitions` and everything downstream but reuses clusters and centers; switching the zero-cluster roll-up on or off changes the economy definition and the analysed places, so roads and loaded sources are reused while every stage from spatial points onward is recomputed.

This dependency-local invalidation is the practical reason the workflow is represented as a DAG rather than a monolithic script. `sigma run AREA --plan` inspects expected reuse without analysis; normal runs guard unexpected expensive rebuilding of completed stages, and `--allow-expensive` is an explicit opt-in after review. Existing validated hierarchical roll-up receipts can be reused without repeating their baseline clustering. Older producer-version artifacts may be reused only when their other recipe semantics and content hashes match.

This cache compatibility is **not** scientific validation: the Metro Manila analysis of the new correction was read-only, and the end-to-end post-repair large-workspace run was still pending at the time of its original review. See [diagnostics](../methods/area_adjustment_diagnostics.md).

## Storage retention is not the same as cache reuse

A managed artifact is an immutable, hashed computation result, not an arbitrary scratch file.
SIGMA may retain multiple historical recipe versions in `artifacts/` while only the current
stage references appear in `.state/active.json`. That history consumes disk space but helps
explain and reproduce older runs. The ordinary cleanup targets abandoned staging only;
`--obsolete` explicitly offers old artifacts outside the active transitive dependency graph,
subject to age, metadata checks, and a run-archive safeguard. Deleting these artifacts may
force recomputation and compromise historical reproducibility.

For safe previews, retention rules, and command examples, see
[Workspace storage and retention](storage.md).

## Provenance versus scientific assumptions

Artifact reproducibility answers: **“Can I recreate the same computation from the same identified inputs and code contract?”** It does not by itself answer: **“Was this the right modeling assumption?”**

The method chapters therefore pair every artifact with the assumptions that generated it: source matching thresholds, road topology, HDBSCAN horizon, center objective, Voronoi resolution, IO preprocessing, X weighting, PPML degree–area adjustment, centrality, and canonical inverse-road-distance point scoring (legacy bounded tempering only in eigenvector mode).

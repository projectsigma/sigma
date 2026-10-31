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

## Selective invalidation

Suppose only the Katz attenuation parameter changes. Area, source, places, roads, clusters, centers, partitions, economy, and X can remain reusable because their recipes do not depend on that parameter. `analysis.centrality` changes, and `analysis.scores` changes because it depends on centrality.

Conversely, changing `vertex_digits` invalidates road topology and propagates through every network-dependent spatial and analysis stage.

This dependency-local invalidation is the practical reason the workflow is represented as a DAG rather than a monolithic script.

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

The method chapters therefore pair every artifact with the assumptions that generated it: source matching thresholds, road topology, HDBSCAN horizon, center objective, Voronoi resolution, IO preprocessing, X weighting, centrality, and score tempering.


## Recovery within expensive stages

In addition to immutable stage artifacts, clustering and Voronoi can persist a
completed economic type, Network X can persist a completed source type and each
25,000-edge route-geometry batch, and export can persist completed GeoPackage
and QGIS project files. These are **temporary recovery savepoints**, not
immutable scientific outputs. SIGMA checks the stage recipe and each savepoint
file's SHA-256 before reuse; incomplete writes are recomputed. Successful
artifact commit clears recovery data. See
[Savepoint scope and limitations](../../../SIGMA_SAVEPOINTS.md).

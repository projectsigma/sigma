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

## Provenance versus scientific assumptions

Artifact reproducibility answers: **“Can I recreate the same computation from the same identified inputs and code contract?”** It does not by itself answer: **“Was this the right modeling assumption?”**

The method chapters therefore pair every artifact with the assumptions that generated it: source matching thresholds, road topology, HDBSCAN horizon, center objective, Voronoi resolution, IO preprocessing, X weighting, centrality, and score tempering.

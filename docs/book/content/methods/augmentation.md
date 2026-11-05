# Augment user-provided places after loading

*Optional step between `sigma load` (stages 1–5) and `sigma run` (stages 6–17). Under the Hood shows the weighted position update and the explicit-tag rule with interactive examples (section “Between load and run”).*

`sigma augment` supplements an **already loaded** SIGMA area with observations from a user-supplied CSV or Parquet. It merges places using SIGMA's existing name-and-distance reconciliation method, keeps unmatched establishments, and preserves arbitrary additional fields. It does not re-fetch OpenStreetMap or Overture Places, and it does not ingest Foursquare. The Overture policy excludes Foursquare-attributed records.

## Command sequence

```bash
sigma load quezon_city
sigma augment quezon_city path/to/registry.csv --source company_registry --check
sigma augment quezon_city path/to/registry.csv --source company_registry
sigma run quezon_city
```

`--check` is a read-only preflight; only the call without `--check` modifies the loaded places. `--source` is required, names the external dataset, and must match `[a-z][a-z0-9_]{0,39}`. Optional `--workspace` selects a specific loaded workspace; `--areas-file` selects a custom area catalog; `--json` returns the report in structured form. `--clip` is enabled by default and excludes points outside the loaded area's boundary; `--no-clip` explicitly disables that check.

## Input schema

CSV and Parquet use the same field names. There are **exactly four required columns**; all others are optional.

| Column | Required | Meaning |
|---|---|---|
| `source_id` | Yes | Unique stable source identifier (string, including leading zeros) |
| `name` | Yes | Establishment/place name |
| `lon` | Yes | Finite WGS84 longitude in degrees, −180 to 180 |
| `lat` | Yes | Finite WGS84 latitude in degrees, −90 to 90 |
| `category` | No | Source activity/category description or recognized `key=value` tags |
| `psic_code` | No | Explicit valid PSIC Rev. 5 classification |
| `io16` | No | Explicit national IO16 code |
| `io80` | No | Explicit national IO80 code |
| `io240` | No | Explicit national IO240 code |
| Other columns | No | Additional CSV/Parquet attributes, kept for future analyses |

Use string types for all classification codes to preserve leading zeros; blank cells mean *unspecified*. The old single-column `io_code` input is **not** accepted. Supplying `geometry` as an additional column does not replace required `lon`/`lat` coordinates.

Example (codes are illustrative; actual parentage is checked against SIGMA's bundled reference):

```text
source_id,name,lon,lat,category,io16,io80,io240,employees,annual_revenue
P001,Example State School,121.050,14.640,education,14,74,,85,
P002,Example Factory,121.048,14.641,manufacturing,,,001,120,50000000
P003,Example Shop,121.047,14.642,retail trade,,,,12,8000000
```

## Manual hierarchical IO: infer upward, never downward

| Supplied values | Resolution |
|---|---|
| `io16` only | Retain IO16 only; do not infer IO80/IO240 |
| `io80` only | Infer the IO16 ancestor; do not infer IO240 |
| `io240` only | Infer both IO80 and IO16 ancestors |
| `io16` + `io80` | Validate their parent-child relationship |
| `io80` + `io240` | Validate IO80, infer IO16 |
| `io16` + `io240` | Infer IO80, check the supplied IO16 |
| All three | Validate both links |
| All blank | Apply SIGMA's existing automatic classification |

**Contradictory manual codes** (including parent-child disagreements) fail before any write, with affected `source_id` and row reported. Disagreements between an explicit valid tag and an *automatically inferred* tag are emitted as warnings, not silently ignored: manual evidence takes priority. Compatible prior manual tags on a matched record are preserved, rather than downgraded. National IO16/80/240 fields must not contain local residual `:o` sector IDs; these local groups are created during the subsequent hierarchical economy rebuild. See [Hierarchical IO](hierarchical.md).

## Reconciliation, identity, and retained attributes

Augmentation uses the same OSM/Overture reconciliation policy: a 120 m Haversine candidate radius, name similarity based on RapidFuzz ratio/token-sort ratio, stricter score requirements at greater distances, and deterministic greedy one-to-one matching. The accepted candidate score is `0.82 × name_similarity + 0.18 × (1 − distance_m / 120)`. Generic names require a stricter near-coincidence rule. Consult [Places](places.md) for all threshold bands.

For a matched establishment, the pre-existing `canonical_id` and OSM/Overture identifiers are preserved. The user source is appended to provenance and coordinates use source-count-weighted averaging. If no canonical match passes the rule, the observation becomes an additional place with its own stable deterministic ID.

Every supplied column, even one named like an internal field, is preserved under `aug_<source>__<column>` (e.g., `aug_company_registry__employees`). Manual classification provenance is separately recorded in `augment_io_code`, with an `X`, `X:Y`, or `X:Y:Z` ancestry key calculated by SIGMA, *not* supplied by the user. Additional attributes are **not incorporated into current SIGMA scoring** merely because they are present.

For unmatched observations without manual PSIC/IO tags, SIGMA reuses its classification routines. Because the current classifier understands OSM/Overture source semantics, the augment path uses a documented classification proxy for user categories while preserving the true external source separately. Do not interpret this proxy as a claim that the observation came from OSM or Overture.

## State, safety, and refresh

Augmentation modifies the editable `workspaces/<area>/places/places.parquet` only after validation and a temporary GeoParquet roundtrip. It stores a first-augmentation handoff backup (`places.pre-first-augment.parquet`) and records applied input identities and hashes in `places/augmentations.json`. Reapplying the same source/file is recognized as `already_applied`. Replacing an earlier source snapshot requires restoring or reloading the original handoff first.

The command does not rewrite upstream OSM/Overture source stores, managed acquisition artifacts, road caches, or already-published scores. The next `sigma run AREA` refreshes stale derived hierarchies, clustering, and downstream results as needed; this work is **not performed by** `sigma augment` itself. Fixed-IO mode rebuilds its corresponding preview from the modified handoff. See [End-to-end workflow](../workflow/end_to_end.md) and [Reading outputs](../reference/outputs.md).

For full implementation and CLI detail, see the [source-controlled SIGMA Augment specification](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_AUGMENT.md).

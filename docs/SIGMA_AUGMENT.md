# `sigma augment`: bring your own places after `sigma load`

## Input contract (CSV or Parquet)

Exactly **four columns are mandatory**. The user may add unlimited extra columns, and none of the optional classification fields must be supplied.

| Input column | Type | Required | Meaning |
|---|---|---|---|
| `source_id` | string | **yes** | Unique, stable identifier within this `--source` dataset; IDs such as `001` remain strings |
| `name` | string | **yes** | Place/establishment name |
| `lon` | finite numeric | **yes** | Longitude (EPSG:4326), -180 to 180 |
| `lat` | finite numeric | **yes** | Latitude (EPSG:4326), -90 to 90 |
| `category` | string | no | OSM `key=value` or Overture-style category / free text |
| `psic_code` | string | no | Explicit valid PSIC Rev. 5 classification |
| **`io16`** | string | no | Exact PSA IO16 industry code |
| **`io80`** | string | no | Exact PSA IO80 industry code |
| **`io240`** | string | no | Exact PSA IO240 industry code |
| *Any additional columns* | CSV or Arrow-compatible | no | Kept as namespaced source attributes for future analyses |

**Do not use a single `io_code` field**: IO codes are given in these three columns. The command refuses an input containing an `io_code` column instead of silently ignoring it. IO codes should be written as **strings**, preserving any leading zeros. CSV and Parquet are both supported. The `lon`/`lat` fields always define the point; an additional `geometry` column is preserved as a user-supplied attribute.

Example:

```csv
source_id,name,lon,lat,category,io16,io80,io240,employees,annual_revenue
P001,Example State School,121.050,14.640,education,14,74,,85,
P002,Example Factory,121.048,14.641,manufacturing,,,001,120,50000000
P003,Example Shop,121.047,14.642,retail trade,,,,12,8000000
```

The codes above are *illustrative*; SIGMA checks every nonblank code against the actual bundled PSA hierarchy, not against the example. When a code is absent, use an **empty cell**, not `0`, `NA`, `unknown`, or a made-up category.

## Explicit tagging semantics

All three fields are independent and optional. At least one filled code means an explicit IO tag; all blank means use SIGMA's existing automatic PSIC/IO classification. The **finest supplied level is authoritative**:

| Given fields | Outcome |
|---|---|
| `io16` only | Keep as IO16; **do not invent IO80/IO240** |
| `io80` only | Validate IO80, infer its IO16 parent; **do not invent IO240** |
| `io240` only | Validate IO240, infer both IO80 and IO16 parents |
| `io16` + `io80` | Validate that IO80 belongs to IO16 |
| `io80` + `io240` | Validate that IO240 belongs to IO80; infer IO16 |
| `io16` + `io240` | Infer IO80; validate that inferred IO16 matches supplied IO16 |
| all three | Validate both parent-child links |

The validation is *strict*: it reports every input row with invalid codes or contradictory parent-child combinations, shows `source_id`, and refuses to write any output until those errors are resolved. `--check` is a read-only preflight. When manual IO conflicts with an existing **inferred** singleton tag on a matching loaded place (or with a singleton resulting from supplied PSIC classification), the report contains a source-specific warning; the explicit IO field is authoritative. When two user-supplied IO classifications of a matched establishment contradict, the command refuses that conflict. Compatible previous manual precision is retained, e.g. a new IO16-only row will not erase a prior confirmed IO240 tag.

**Residuals:** IO16/IO80 `:o` groups are local, dynamically constructed sectors, *not* national IO industry codes. Do not put residual codes into these three columns. SIGMA derives the appropriate local residual or containing sector when it rebuilds the hierarchical partition after augmentation. This ensures coarse users never claim an exact unobserved IO240 child.

## CLI

```powershell
sigma load quezon_city
sigma augment quezon_city "C:\data\registry.csv" --source company_registry --check
sigma augment quezon_city "C:\data\registry.csv" --source company_registry
sigma run quezon_city
```

`--source` is a stable source namespace: lowercase letters, digits and underscores, starting with a letter (up to 40 characters). Together, (`--source`, `source_id`) form the unique source identity. `--workspace` selects a non-default loaded workspace; `--areas-file` selects a custom area catalog; `--json` writes a structured report. The default `--clip` keeps points inside the area polygon and reports exclusions. `--no-clip` is an explicit opt-out.

## Reconciliation and provenance

Augment matches user points to existing loaded places using **the same algorithm as SIGMA's OSM/Overture reconciliation**: a 120 m Haversine candidate radius, distance-dependent name similarity thresholds (0.70 at 20 m, 0.82 at 50 m, 0.90 at 90 m, 0.94 at 120 m), stricter handling of very generic names, and greedy, deterministic one-to-one assignment by candidate strength. It does *not* introduce Foursquare ingestion: the existing Overture source policy excludes Foursquare-attributed records.

A match preserves the existing `canonical_id` and OSM/Overture identities, adds source provenance, extends names/categories, and uses source-count-weighted coordinate averaging. An unmatched input gets its own deterministic canonical ID. The prior OSM-Overture match metrics remain unchanged and new source-specific metrics are added.

Every user column—including the three IO inputs and otherwise SIGMA-reserved names—is retained as `aug_<source>__<column>`, for example `aug_company_registry__employees`. An additional internal `augment_io_code` records the resolved ancestry as `X`, `X:Y`, or `X:Y:Z`, but the user does *not* supply this string. User attributes are **not** used in the current SIGMA score unless a future method explicitly opts into them.

Unmatched places are processed through the existing PSIC/IO classifiers. Since today's classifier recognizes OSM and Overture source semantics, augmentation uses a clearly labeled classification *proxy* for new user rows (key=value categories through OSM rules; other text through Overture-style rules), retaining the genuine user source separately. Supplied `psic_code` takes priority over an automatically classified PSIC. Explicit valid IO tags take priority over inferred IO tags; disagreement between precise singleton assignments is reported as a warning, not silently hidden.

## Post-load lifecycle and safety

The editable handoff is `workspaces/<area>/places/places.parquet`. Augmentation uses a temporary, roundtrip-validated GeoParquet and atomically replaces this handoff only after successful matching/classification. The first augmentation preserves `places.pre-first-augment.parquet` and records hashes/counts in `places/augmentations.json`. Re-running the same source and file returns `already_applied`; replacing an old snapshot requires restoring/reloading the original handoff first. The command does not modify OSM, Overture, road caches, managed C8 artifacts, or previously published scores.

On the next `sigma run`, SIGMA regenerates the per-area hierarchical economy from the changed handoff (or you can explicitly invoke `sigma economy hierarchical-refresh --workspace ...`). Fixed-IO workspaces rebuild their previews from the changed handoff. No expensive network/centrality recomputation happens *inside* `sigma augment`.

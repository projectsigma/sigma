# SIGMA — PSA 2018 IO240 parent-link correction (overlay for v4)

## Problem

The v4 national IO240 packager correctly refused to build because SIGMA's PR #17 parent reference and its PSIC–IO concordance assigned IO240 industries **124, 125 and 126** to IO80 **41**, while the actual published PSA 2018 I–O industry classification assigns them to IO80 **42**.

These are different reference frameworks: industry names and ordinary PSIC relationships alone do not establish the parentage in the **specific 2018 input–output tables**. The official 2018 I–O classification is authoritative for aggregating those 2018 matrices.

| IO240 | Industry | SIGMA before repair | Official PSA 2018 |
|---|---|---:|---:|
| 123 | Basic iron and steel | 41 | 41 |
| 124 | Casting/foundry of iron and steel | 41 | **42** |
| 125 | Basic precious and non-ferrous metals | 41 | **42** |
| 126 | Non-ferrous metal casting | 41 | **42** |
| 127 | Structural metal products | 42 | 42 |

## Independent numerical validation

Using the archived, unmodified official **240-Industry Transaction Table, 2018.xlsx**, **80-Industry Transaction Table, 2018.xlsx**, and **2018 Input-Output Industry Classification_0.xlsx**, the 240×240 transactions were aggregated to 80×80 by the published memberships. All currency values are in **million Philippine pesos**.

| Membership | Sum of absolute 80×80 cell discrepancies | L1 discrepancy relative to total transactions | Absolute gross-output discrepancy, summed across 80 sectors |
|---|---:|---:|---:|
| Published PSA membership (124–126 → 42) | 1.13 × 10⁻⁹ | 6.19 × 10⁻¹⁷ | 5.34 × 10⁻⁹ |
| Previous SIGMA membership (124–126 → 41) | 97,595.92 | 0.0053406 | 55,158.61 |

The published mapping reproduces both IO80 quantities to floating-point precision. The old reference does not. The original Excel files are **not** modified by this repair.

## Scope of the repair

The overlay changes only:

1. `io/io240_parents.csv`: three parent codes from `41` to `42`.
2. `io/psic_2019_to_io_2018.csv`: division `24` recognizes both 41 and 42, while groups `242` (basic precious and non-ferrous metals) and `243` (casting) use 42; IO240 candidate sets and confidence fields remain unchanged.
3. `classification/manifest.json`: recalculated SHA-256 and file sizes for those two versioned reference assets.
4. `scripts/sigma_pack_io240_repo.py`: inversion of the obsolete 124–126 hard-coded regression guard (it now requires 42).
5. `tests/economy/test_io240_packager.py` and `tests/economy/test_load_policy.py`: assertions reflect the published hierarchy.
6. A narrowly scoped new regression test verifying reference agreement with the existing tagging and hierarchical code.

**Unchanged:** `sigma load` logic, `sigma run`, `sigma init`, PSIC classification and ownership rules, hierarchical grouping and sparse code construction (`X:Y:Z`, `X:Y:o`), `contain` policy, spatial/network/scoring code, and all local workspaces.

### Consequences and limitations

- Some establishments with exact 124–126 candidates can receive different IO80 parent identities after the next classification/rebuild. This is **intended correction of the reference**, not a new tagging method.
- Previously generated sectors and their hashes are historical; do not silently reuse or overwrite them. New local typologies and network outputs must be rebuilt after the corrected national reference is validated.
- The authoritative national IO240 package must pass **actual official workbook reconciliation**, not merely synthetic tests, before commit or area regeneration.
- The repair does not imply that all PSIC (activity-based) groups and 2018 national I–O groups have identical boundaries.
- The official 2018 I–O classification, rather than sector names inferred from PSIC divisions, governs transactions and gross-output aggregation.

## Source

[Philippine Statistics Authority, 2018 Input-Output Accounts release (December 9, 2021)](https://psa.gov.ph/statistics/supply-and-use-input-output). Original XLSX files were already available in the ChatGPT file archive and bundled with SIGMA v4. The overlay does not download or search local drives for references.

## Application

Apply only **after** v4 is already applied, as in the log where the packager stopped at the first reference mismatch. Run `repair_sigma_io240_parents.py --repo PATH --dry-run`, then `--apply`, then rerun the v4 national packager with the archived XLSX inputs and run tests. A `--revert` option exists before the validated national IO240 package has been created; it refuses reversal after packaging to avoid breaking crosswalk provenance.

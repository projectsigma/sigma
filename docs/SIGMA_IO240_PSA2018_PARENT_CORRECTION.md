# PSA 2018 IO240 parent links for industries 124–126

## Rule

SIGMA assigns IO240 industries **124, 125 and 126** to IO80 **42**, as the published PSA 2018 Input-Output Industry Classification does. An assignment by industry name or by ordinary PSIC relationships would place them under IO80 **41** (basic iron and steel), but names and PSIC relationships do not establish the parentage in the **specific 2018 input–output tables**. The official 2018 I–O classification is authoritative for aggregating those 2018 matrices.

| IO240 | Industry | Name-based parent | Official PSA 2018 parent (used by SIGMA) |
|---|---|---:|---:|
| 123 | Basic iron and steel | 41 | 41 |
| 124 | Casting/foundry of iron and steel | 41 | **42** |
| 125 | Basic precious and non-ferrous metals | 41 | **42** |
| 126 | Non-ferrous metal casting | 41 | **42** |
| 127 | Structural metal products | 42 | 42 |

## Numerical validation

Using the unmodified official **240-Industry Transaction Table, 2018.xlsx**, **80-Industry Transaction Table, 2018.xlsx**, and **2018 Input-Output Industry Classification_0.xlsx**, the 240×240 transactions were aggregated to 80×80 by the published memberships. All currency values are in **million Philippine pesos**.

| Membership | Sum of absolute 80×80 cell discrepancies | L1 discrepancy relative to total transactions | Absolute gross-output discrepancy, summed across 80 sectors |
|---|---:|---:|---:|
| Published PSA membership (124–126 → 42) | 1.13 × 10⁻⁹ | 6.19 × 10⁻¹⁷ | 5.34 × 10⁻⁹ |
| Name-based membership (124–126 → 41) | 97,595.92 | 0.0053406 | 55,158.61 |

The published mapping reproduces both IO80 quantities to floating-point precision; the name-based mapping does not.

## Where the rule is recorded

1. `src/sigma/resources/classification/io/io240_parents.csv`: parent `42` for IO240 124–126.
2. `src/sigma/resources/classification/io/psic_2019_to_io_2018.csv`: PSIC division `24` recognizes both IO80 41 and 42 (IO240 candidates 123–126), while groups `242` (basic precious and non-ferrous metals; IO240 125) and `243` (casting; IO240 124 and 126) use IO80 42.
3. `src/sigma/resources/classification/manifest.json`: SHA-256 and file sizes of those versioned reference assets.
4. `scripts/sigma_pack_io240_repo.py`: a regression guard that requires parent 42 for 124–126.
5. `tests/economy/test_io240_packager.py`, `tests/economy/test_load_policy.py` and `tests/economy/test_psa2018_parent_correction.py`: assertions of the published hierarchy.

### Consequences and limitations

- An establishment with exact IO240 code 124, 125 or 126 belongs to IO80 42 (and IO16 03, manufacturing).
- Area hierarchies and network outputs depend on the reference fingerprint, so a workspace built with a different parent table must be rebuilt rather than reused.
- The national IO240 package must pass reconciliation against the actual official workbooks, not only synthetic tests, before it is committed or used to regenerate areas.
- PSIC (activity-based) groups and 2018 national I–O groups do not always have identical boundaries.
- The official 2018 I–O classification, rather than sector names inferred from PSIC divisions, governs transactions and gross-output aggregation.

## Source

[Philippine Statistics Authority, 2018 Input-Output Accounts release (December 9, 2021)](https://psa.gov.ph/statistics/supply-and-use-input-output). SIGMA does not download the workbooks or search local drives for them; see [SIGMA load portability](SIGMA_LOAD_PORTABILITY.md) for packaging the national IO240 reference.

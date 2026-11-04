# Institution ownership: registry-backed shadow v3

**Status:** opt-in shadow diagnostics, **not** integrated with `sigma run` or `sigma view`. A distinct conservative subset is applied in `sigma load` (see `docs/SIGMA_INSTITUTION_TAGGING_LOAD.md`). Policy `shadow-evidence-v3`.

Running the shadow QC script changes only diagnostic files. It does **not** modify existing PSIC/IO tags, economic-sector assignments, cluster geometries, network edges, centrality, or acquisition scores. Run `scripts/sigma_shadow_qc.py` explicitly to evaluate it against an existing place workspace. The v2 baseline is retained by the reversible installer.

## Why registry evidence?

The QC audits showed that generic OSM and Overture activity tags often resolve only to PSIC hospital or education groups, while the public/private split needs additional evidence. Operator tags are useful but do not prove legal ownership. Name heuristics such as `Holy` or `Laboratory` created errors. A separate institutional identity resolver and independently documented ownership evidence are needed.

## Evidence and safeguards

1. **Official source records** are read from `scripts/registry_qc_official_sources.csv`, a *selective and versioned* QC snapshot. They include official DepEd school IDs, publication-row references for PhilHealth hospitals and CHED CMO listings, and a QC government hospital directory. They carry names, explicit public/private sectors, city, publication dates, source URLs, and identifier types. The registry **does not contain the diagnostic roster or its ownership labels**.
2. **Optional full official exports**: `--doh-export` and `--deped-export` accept CSV/Excel independently obtained from DOH NHFR and DepEd. Unknown ownership types are excluded. DOH requires a facility code, hospital type, major ownership classification and city; DepEd requires a school ID plus explicit sector. They are not fetched automatically or inferred from names.
3. **Exact linkage**: a matching official external ID (if one exists in the OSM/Overture fields) is strongest. Otherwise, require **an exact normalized name and QC-city scope**. Normalization handles punctuation and established final school abbreviations `ES`, `HS`, `NHS`; it never uses token containment, string-similarity thresholds, arbitrary name-to-ownership rules, or the reference evaluation roster. `North Fairview`, `West Fairview`, and `Fairview` are separate identities.
4. **Identity protection**: a canonical-name disagreement, source-city conflict, conflicting official ownership records, same-source duplicate identifiers for one name, and evidence contradicting strong explicit ownership trigger review. Subunits and transport POIs are gated before ownership attribution. A name/city match remains **provisional evidence of entity identity**, even when its ownership label is independently documented. No production assignments are promoted automatically.
5. **PSIC-to-IO mapping** uses the installed taxonomy and `IOMapping` only. A registry match does not fix an incorrect upstream activity, and cannot assign an IO80/IO240 code if the existing candidate sets and the bundled mapping are incompatible. If class/subclass ownership is not exhaustively typed, the original PSIC remains coarse; valid ownership evidence may still produce IO-only refinements under the exact-pair guard.
6. **Audit outputs** retain every proposed sector, registry source record, evidence basis, ambiguity, original SIGMA classification, and upstream blockage. The 45 previously held-out reference labels are read **only for comparison**; registry matches on these same named institutions are not new out-of-sample prediction tests.

## Reference source provenance

| Source | Data used and identifier meaning | Limits |
|---|---|---|
| DepEd NCR [public-school directory](https://www.depedncr.com.ph/directory-of-public-schools/) | Official school IDs and names for selected QC public schools | Not a complete public/private 2026 masterlist; accessed 2026-11-01 |
| [PhilHealth accredited hospitals, May 31 2025](https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_053125.pdf) | Selected NCR/QC hospital names and government (`G`) versus private (`P`) sector column | **PhilHealth, not DOH NHFR**; sequence number is a *document row*, not a durable facility ID; historical snapshot |
| [QC Government hospital directory](https://quezoncity.gov.ph/qcitizen-guides/government-owned-hospitals-in-quezon-city/) | 11 QC government-owned hospitals, national and LGU; directory position is not an official registration number | Updated 2025-05-05, covers public only |
| [CHED CMO No. 02 s. 2025](https://ched.gov.ph/wp-content/uploads/CMO-NO.-02-S.-2025.pdf) | Selected **private** HEIs granted autonomous/deregulated status; CMO sequence number is not an HEI ID | Selective by status; does **not** classify all NCR HEIs |
| [DOH National Health Facility Registry](https://nhfr.doh.gov.ph/VActivefacilitiesList) | Optional full downloaded source; requires facility code, health facility type and `Ownership Major Classification` | **No NHFR records are bundled** because a current export could not be retrieved in this environment |

All bundled references have independent source URLs. `source_id` in a publication-row reference is **not** represented as a government-issued registry ID. The date in DepEd seed rows means *accessed on*, not necessarily the data's effective date. These datasets may be stale or incomplete and are unsuitable for silently changing production classifications.

## Run and compare

Run the v3 script against `places/places.parquet` using the CLI arguments `--workspace`, `--out`, `--evaluation-csv`, and `--matched-records-csv` as in v2; the bundled selective official reference is loaded by default. Specify `--no-seed-registry` to reproduce source-only results with the v3 code. Add official exports only when downloaded; specify their source-specific `--*-as-of` date. No network access is required at runtime.

Outputs include the v2 reports plus:

- `shadow_registry_matches.csv` — exact registry matches, source URLs, ownership and matching basis, original and shadow sector labels.
- `shadow_registry_blocked.csv` — independently matched institutions that cannot be classified due to PSIC, entity, or evidence disagreement.
- `shadow_registry_sources.json` — input snapshot hashes, record counts and explicit origin information.

`shadow_registry_status=EXACT_NAME_CITY` means a provisional *candidate* identity match; `EXACT_EXTERNAL_ID` means an explicit official ID matched with a consistent name. A matching registry name alone is not a proof of identical physical campus, ownership of tenants, or independent predictive accuracy. Also report both precision (including abstentions), and error counts; do not optimize only coverage.

## Reversibility and scope

The v3 patch modifies only the four previously installed v2 shadow files and adds two shadow-only files (`src/sigma/classification/registry.py`, `scripts/registry_qc_official_sources.csv`). It leaves all production modules and artifacts untouched. Installer preflight requires exact v2 or v3 bytes, aborts on mixed/mutated files, and supports `--revert` (restores v2 precisely). Workspace inputs are read only; output must be outside repository and workspace.

# Institutional administrative activity and ownership evidence

## Current production `sigma load` workflow

Institutional activity and public/private ownership are distinct questions. The normal `places.psic` stage may identify clearly administrative government offices as PSIC **84120** under narrowly defined rules; it retains the previous PSIC decision and does not treat a frontline hospital or school as an administrative office. Ambiguous cases are marked for review rather than forcibly reassigned.

The production `places.classified` stage then considers conservative ownership promotion using explicit OSM/Overture ownership attributes, independently verified canonical registry links, or official external-ID matches. The current layered institutional evidence includes packaged national BEIS school references, UniFAST higher-education references and, **when separately installed**, a validated national hospital snapshot; a QC-specific fallback may apply in its defined area. **A normalized name/city match alone is provisional**, not sufficient to prove physical identity or automatically override stronger PSIC/IO evidence. Promotion stays within the PSIC candidate-set constraints, preserves original classification, audits conflict/abstention, and never uses the held-out diagnostic labels as ground truth for classification.

These are production tagging safeguards in `src/sigma/places/pipeline.py` and `src/sigma/classification/ownership_promotion.py`, not an automatic re-run of the separately invoked diagnostic below. See [National institution registry](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_NATIONAL_INSTITUTION_REGISTRY_V1.md) and [Administrative activity](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_ADMIN_ACTIVITY_OWNERSHIP_V1.md) for source coverage and limits.

## Historical registry-backed shadow v3 diagnostic

**Status of the historical v3 shadow procedure:** opt-in diagnostic invoked separately, not a direct `sigma run` step. Its `shadow-evidence-v3` policy and QC-specific reference snapshots must not be mistaken for the complete current production ownership-promotion policy.

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

The historical v3 shadow diagnostic was designed to write independent reports without modifying production artifacts. This statement describes that earlier shadow-only workflow; subsequent production `sigma load` releases added conservative institutional evidence handling separately. Do not interpret the old installer/revert notes as instructions for the current source tree; consult current CLI and production tests before running historical scripts.

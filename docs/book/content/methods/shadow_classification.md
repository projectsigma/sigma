# Institutional activity and ownership evidence (stages 3–4)

*Pipeline stages 3–4 of 17 · `sigma load`. Under the Hood shows the administrative-office rule and the ownership evidence ladder with interactive examples (sections “Stage 3” and “Stage 4”).*

Activity and ownership are two different questions. *Activity* asks what a place does: does it teach or treat patients, or does it administer schools or health programmes? *Ownership* asks whether a school or health facility is public or private. The PSA IO tables separate both: public administration of social programmes is a different industry from education or health services, and education and health are each split into a public and a private industry. SIGMA answers the two questions at different stages and with different evidence.

## Stage 3: administrative offices (activity)

After the deterministic PSIC classifier, `places.psic` applies one narrow rule set (policy `admin-function-v1`) to the place name:

| Name pattern | Decision | Effect |
|---|---|---|
| clear administrative office: DOH or DepEd regional office, schools division office, city/municipal/provincial health department | `REASSIGNED` | PSIC becomes **84120** (public administration of health, education and other social programmes) |
| as above, and PSIC is already 84xxx | `CONFIRMED` | PSIC unchanged |
| administrative pattern, but a name also has a frontline word (hospital, clinic, medical center, health center, school, university, college, laboratory, …) | `REVIEW` | PSIC unchanged |
| administrative pattern, but PSIC was supplied manually | `REVIEW` | PSIC unchanged |
| administrative pattern, but the source names disagree | `REVIEW` | PSIC unchanged |
| agency or office words only (“Department of Health”, “health office”) | `REVIEW` | PSIC unchanged |
| none of the above | — | PSIC unchanged |

Examples: “DepEd Schools Division Office” and “Riverside City Health Department” are reassigned; “DepEd Division Office Health Clinic” and “Department of Health” go to review; “Riverside National High School” is unchanged. The fields `admin_activity_status`, `admin_activity_reason` and `admin_original_psic` record the decision, and `psic_audit` keeps the original classifier evidence. A government owner or an accreditation does not establish an office function, and this rule never decides ownership.

## Stage 4: public or private (ownership)

Education is split into IO80 74 (public) and 75 (private), IO240 229 and 230; health into IO80 76 and 77, IO240 231 and 232. A PSIC code alone often leaves both sides as IO candidates. Two layers of evidence can choose one side.

**Tagging heuristics.** During IO tagging, specific name and category patterns (for example “National High School” or “Rural Health Unit”) can choose a side. They abstain when the evidence points both ways, and generic words such as “elementary school”, “clinic” or “health center” are not ownership proof. A place tagged this way is flagged `ownership_inferred`; this is not registry verification.

**Promotion at production `places.classified`.** For places whose IO candidates are exactly such a public/private pair, SIGMA resolves institutional evidence in this order of strength:

| Rung | Evidence (`institution_evidence_basis`) | Can change the IO industry? |
|---:|---|---|
| 1 | verified link from the canonical place to a registry record (`verified_canonical_registry_link`, from `references/institution_links.json`) | yes |
| 2 | an official registry ID found in the source record, with a consistent name (`official_registry_external_id`) | yes |
| 3 | an explicit ownership attribute in OSM or Overture (`explicit_source_attribute`, for example `ownership=public` or Overture `public_school`) | yes |
| 4 | registry match by normalized name and city only (`official_registry_name_city_provisional`, `official_registry_id_locality_provisional`) | no: provisional |
| 5 | a government operator tag (`government_operator_proxy`) | no: operating is not owning |

Evidence that points to both sides stops the decision (`EXPLICIT_OR_REGISTRY_CONFLICT`), and a government operator tag together with private evidence is flagged (`OPERATOR_VS_PRIVATE_CONFLICT`). Ambiguous registry identities (`REGISTRY_MATCH_REVIEW`) and subunits or transport stops (`ENTITY_REVIEW`, `BLOCKED_UPSTREAM`) also abstain.

When the evidence is promotable, further guards apply before the IO tag changes:

- if a stronger PSIC or direct tag rule already chose the other side, the place is not changed (`STRONG_BASELINE_CONFLICT`);
- the new IO80 must nest under the place's IO16 (`IO_LEVEL_CONFLICT` otherwise) and a compatible IO80/IO240 pair must exist (`NO_COMPATIBLE_IO_PAIR`);
- an official ID that is not an exact external-ID match is not used (`UNVERIFIED_ID`).

The result is `PROMOTED` (the IO tag changed) or `CONFIRMED` (it already had this side). PSIC is never changed by promotion, and the IO candidate sets are never widened. Promoted places record `ownership_side`, `ownership_domain` and `ownership_reason = institution:<basis>`. The audit fields are `institution_promotion_status`, `institution_evidence_basis`, `institution_evidence_reference`, `institution_evidence_source_urls` and `institution_baseline_conflict`.

### Registry layers

The registries are layered and used only through the strict evidence rules above:

- packaged national school identities in BEIS format (`beis_schools_national.csv.gz`);
- packaged higher-education institutions from the UniFAST list (`unifast_hei_ra10931.csv.gz`);
- a validated national hospital snapshot, when it is installed under `SIGMA_HOME/references/institution_national_v1.csv`;
- a small packaged reference limited to Quezon City, used only when no national snapshot is installed;
- verified canonical links stored per workspace in `references/institution_links.json`.

A registry match by name and city is evidence of a possible identity, not proof that it is the same physical site, and not proof of ownership. Source coverage, publication dates and redistribution limits are described in [National institution registry](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_NATIONAL_INSTITUTION_REGISTRY_V1.md), [Administrative activity](https://github.com/projectsigma/sigma/blob/main/docs/SIGMA_ADMIN_ACTIVITY_OWNERSHIP_V1.md), and the BEIS and UniFAST notes in `docs/`. These are production tagging safeguards in `src/sigma/places/pipeline.py` and `src/sigma/classification/ownership_promotion.py`. The reference fingerprint is part of the classified-stage recipe, so changing a registry invalidates `places.classified` and everything downstream.

## Registry-backed shadow diagnostic (opt-in)

`scripts/sigma_shadow_qc.py` runs a separate, opt-in diagnostic (policy `shadow-evidence-v3`) against an existing place workspace. It is not a `sigma load` or `sigma run` step, and it writes only diagnostic files: it does not modify PSIC/IO tags, economic sectors, clusters, network edges, centrality or scores. It applies the same identity rules as production promotion and reports what the evidence would support, so that coverage and errors can be reviewed before evidence is trusted.

### Why registry evidence?

Quality checks showed that generic OSM and Overture activity tags often resolve only to PSIC hospital or education groups, while the public/private split needs additional evidence. Operator tags are useful but do not prove legal ownership. Name heuristics such as `Holy` or `Laboratory` created errors. A separate institutional identity resolver and independently documented ownership evidence are needed.

### Evidence and safeguards

1. **Official source records** are read from `scripts/registry_qc_official_sources.csv`, a *selective and versioned* Quezon City snapshot. They include official DepEd school IDs, publication-row references for PhilHealth hospitals and CHED CMO listings, and a QC government hospital directory, with names, explicit public/private sectors, city, publication dates, source URLs, and identifier types. The registry **does not contain the evaluation roster or its ownership labels**.
2. **Optional full official exports**: `--doh-export` and `--deped-export` accept CSV/Excel files obtained independently from DOH NHFR and DepEd. Unknown ownership types are excluded. DOH requires a facility code, hospital type, major ownership classification and city; DepEd requires a school ID plus explicit sector. They are not fetched automatically or inferred from names.
3. **Exact linkage**: a matching official external ID (if one exists in the OSM/Overture fields) is strongest. Otherwise, the diagnostic requires **an exact normalized name and city scope**. Normalization handles punctuation and the school abbreviations `ES`, `HS`, `NHS`; it never uses token containment, string-similarity thresholds, name-to-ownership rules, or the evaluation roster. `North Fairview`, `West Fairview`, and `Fairview` are separate identities.
4. **Identity protection**: a canonical-name disagreement, source-city conflict, conflicting official ownership records, same-source duplicate identifiers for one name, and evidence contradicting strong explicit ownership trigger review. Subunits and transport POIs are gated before ownership attribution. A name/city match remains **provisional evidence of entity identity**, even when its ownership label is independently documented.
5. **PSIC-to-IO mapping** uses the installed taxonomy and `IOMapping` only. A registry match does not fix an incorrect upstream activity, and cannot assign an IO80/IO240 code if the existing candidate sets and the bundled mapping are incompatible. If class/subclass ownership is not exhaustively typed, the original PSIC remains coarse; valid ownership evidence may still produce IO-only refinements under the exact-pair guard.
6. **Audit outputs** retain every proposed sector, registry source record, evidence basis, ambiguity, original SIGMA classification, and upstream blockage. The 45 held-out reference labels are read **only for comparison**; registry matches on these same named institutions are not out-of-sample prediction tests.

### Reference source provenance

| Source | Data used and identifier meaning | Limits |
|---|---|---|
| DepEd NCR [public-school directory](https://www.depedncr.com.ph/directory-of-public-schools/) | Official school IDs and names for selected QC public schools | Not a complete public/private masterlist; accessed 2026-11-01 |
| [PhilHealth accredited hospitals, May 31 2025](https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_053125.pdf) | Selected NCR/QC hospital names and government (`G`) versus private (`P`) sector column | **PhilHealth, not DOH NHFR**; sequence number is a *document row*, not a durable facility ID |
| [QC Government hospital directory](https://quezoncity.gov.ph/qcitizen-guides/government-owned-hospitals-in-quezon-city/) | 11 QC government-owned hospitals, national and LGU; directory position is not an official registration number | Updated 2025-05-05, covers public only |
| [CHED CMO No. 02 s. 2025](https://ched.gov.ph/wp-content/uploads/CMO-NO.-02-S.-2025.pdf) | Selected **private** HEIs granted autonomous/deregulated status; CMO sequence number is not an HEI ID | Selective by status; does **not** classify all NCR HEIs |
| [DOH National Health Facility Registry](https://nhfr.doh.gov.ph/VActivefacilitiesList) | Optional full downloaded source; requires facility code, health facility type and `Ownership Major Classification` | **No NHFR records are bundled** |

`source_id` in a publication-row reference is **not** a government-issued registry ID. The date in DepEd seed rows means *accessed on*, not necessarily the data's effective date. These datasets may be stale or incomplete and are unsuitable for silently changing production classifications.

### Run and compare

Run the script against `places/places.parquet` with `--workspace`, `--out`, `--evaluation-csv`, and `--matched-records-csv`; the bundled selective reference is loaded by default. Specify `--no-seed-registry` to reproduce source-only results. Add official exports only when downloaded, with their source-specific `--*-as-of` date. No network access is required at runtime.

Outputs include:

- `shadow_registry_matches.csv` — exact registry matches, source URLs, ownership and matching basis, original and shadow sector labels;
- `shadow_registry_blocked.csv` — matched institutions that cannot be classified due to PSIC, entity, or evidence disagreement;
- `shadow_registry_sources.json` — input snapshot hashes, record counts and origin information.

`shadow_registry_status=EXACT_NAME_CITY` means a provisional *candidate* identity match; `EXACT_EXTERNAL_ID` means an explicit official ID matched with a consistent name. Report both precision (including abstentions) and error counts; do not optimize only coverage.

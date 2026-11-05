# UniFAST participating-HEI reference (v12)

Official source: https://unifast.gov.ph/hei-list.html

An independently fetched, attributed snapshot of the public **List of RA 10931 Participating HEIs**, captured on 2026-11-04, is retained as a CSV and packaged gzip reference. The source gives **region, HEI name, and institution type**. It does **not** provide an official institution code, exact municipality/PSGC, street address, or all-HEI coverage. Source publication/effective date is not stated; acquisition time is recorded separately. The data must not be represented as a census of active HEIs.

Of 1,955 rows captured: 1,329 `Private HEI` are marked private, 533 `SUC` + 91 `LUC` are marked public, and 2 `CHED Supervised Inst.` records remain for review. `record_key` is a local hash of the region/name pair, **not** an official HEI ID. Neither name nor region can verify a specific SIGMA physical establishment or branch. Ambiguous or conflicting names abstain; there is **no automatic ownership promotion** from this source.

## Integration

The bundled `unifast_hei_ra10931.csv.gz` is loaded through `UniFASTIndex` (stage 4) and layered with the QC reference and the BEIS basic-school index. The index returns `UNIFAST_NAME_ONLY_PROVISIONAL`, `UNIFAST_NAME_REGION_PROVISIONAL`, `UNIFAST_TYPE_REVIEW` or appropriate conflict statuses, not `EXACT_EXTERNAL_ID`. It does not override verified links, upstream PSIC, IO candidates, or the ownership- and location-conflict safeguards.

The PhilHealth-only national runtime CSV (`SIGMA_HOME/references/institution_national_v1.csv`) contains **125 hospitals only**, and the BEIS snapshot is a separate 30,364-school file. The four QC verified hospital links are workspace-specific. The reference fingerprint includes the packaged UniFAST bytes, so a change to this file invalidates `places.classified` and everything downstream at the next `sigma load`.

Reference candidates affect IO tags only through a deliberate `sigma load`. For a public code release, keep the source attribution and perform the project's normal release-data review.

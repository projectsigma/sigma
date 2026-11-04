# SIGMA national institution reference: compact sources (v3)

## Retained reference coverage, as supplied

| Reference | Rows | Authoritative identity fields retained | Ownership basis |
|---|---:|---|---|
| DepEd BEIS extract (`schools_town_psgc_clean.csv`) | 30,364 | `school_id`, `school_name`, `town_psgc` | Conditional **school-ID-prefix hint** only for conventional six-digit IDs; not an explicit ownership field |
| PhilHealth accredited Level 3 hospitals, 2026-09-30 | 125 | Printed row number, facility name, municipality, street, page, Level 3, G/P sector | Explicit G/P in source PDF |

The original uploaded BEIS file uses Windows-1252 (not UTF-8). SIGMA's bundled
version is faithfully converted to UTF-8, compressed with gzip, and retains
**exactly the same three data columns**. It does not add inferred ownership to
source records.

The BEIS extract has 30,364 unique IDs in 1,593 municipality PSGCs. Of these,
29,870 have conventional six-digit IDs beginning 1–6 and are eligible for a
**provisional** ownership hint, 491 have seven-digit IDs, two have five-digit
IDs, and one has a six-digit ID beginning 9. The latter **494 are abstentions**
for ownership inference. Do not truncate or pad any school IDs; a different
length may reflect another generation or subtype of IDs.

DepEd's own EBEIS support notes conventional six-digit ID prefixes 1/2 for
public elementary, 3 public high school, 4 private, 5 public integrated, and
6 SUC/LUC basic education. See:
https://sites.google.com/deped.gov.ph/icts-usd/helpdesk/beisebeis

**No official BEIS export URL or snapshot date accompanied the user-supplied
CSV.** The dataset therefore remains **identity and provisional ownership
evidence only**. Even matching an external school ID does not automatically
promote IO80/IO240 ownership until independently verified source provenance
and cross-dataset identity have been established. It cannot be cited as an
externally verified official extract just because DepEd documents ID semantics.

## Why names alone are insufficient

A school ID is stable identity evidence; names repeat (e.g. many San Isidro
Elementary Schools). The submitted extract has 796 duplicated normalized
name+municipality combinations (914 additional records). The matcher:

- Uses exact school IDs as identity candidates when present, otherwise exact normalized names.
- Disambiguates by `town_psgc`, `municipality_psgc`, `city_psgc` or `area_psgc` if the input actually contains them.
- Abstains if several school IDs remain possible, a record is a different municipality, or a code conflicts with the place name.
- Never guesses municipality PSGC from free-text names or unverified GPS points.
- Uses a layered registry so existing national hospital and QC reference matches are not replaced by a school-name guess. If both appear compatible, the matcher flags overlapping identities for review.

The matching is indexed; it does not require an all-establishment × all-school
pairwise scan. The school reference contains no new map coordinates and cannot
create establishments in the workspace.

## Hospital data minimization

PhilHealth input drops bed count and omits all phone/email information. Keep:
`No`, `NAME OF HEALTH FACILITY`, `CAT`, `SEC`, `MUNICIPALITY`, `STREET`, `PAGE`.
`No` is the **publication row**, not an NHFR or official facility ID. The
hospital builder keeps these fields as official-source evidence; name+town
matches stay provisional.

## Installation and publication boundaries

The school reference remains a separate, identity-only packaged index that is automatically layered for review during ownership matching. It cannot promote ownership without independent verification. The hospital-only national snapshot is installed separately under SIGMA_HOME; source PDF publication-row identifiers are never facility codes.

The hospital source is:
https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_093026.pdf

The school list was supplied as a compact BEIS-format extract. Its specific official export URL, snapshot date and redistribution permission remain **unverified**. Do not publish the school data in a public repository unless publication rights have been reviewed. No independent source is claimed or invented.

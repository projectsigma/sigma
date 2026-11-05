# Philippine PSA 2018 IO240 reference

Official source: Philippine Statistics Authority (PSA), 2018 Input-Output Tables, released in 2021: https://psa.gov.ph/statistics/supply-and-use-input-output/tables

The 240-sector transaction table and gross-output vector are taken from the official *240-Industry Transaction Table, 2018* workbook. The industry classification is checked against the official *2018 Input-Output Industry Classification* workbook when its layout can be read.

The IO240→IO80 parent mapping is SIGMA's versioned classifier reference, `src/sigma/resources/classification/io/io240_parents.csv`. Some parent assignments (column `basis` = `sector_name` or `code_order`) are SIGMA methodological decisions, not PSA-published concordances. The packager accepts the national table only if it reconciles numerically with SIGMA's bundled PSA IO80 and IO16 tables under this mapping; see `validation.json` for the criteria and results.

Sector labels come from `io240_parents.csv`; the PSA workbook supplies a label only where that file has none.

`validation.json` records SHA-256 digests of the source workbooks and of the stored files. Stored-file digests are computed after converting CRLF to LF, so Windows and Linux checkouts verify the same package. The source XLSX workbooks are used temporarily and are not committed. Check PSA's terms for redistribution of the normalized tables before publishing them, and keep this attribution and the source link.

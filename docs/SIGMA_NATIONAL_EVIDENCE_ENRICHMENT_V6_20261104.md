# Hospital establishment evidence audit

`scripts/sigma_national_evidence_audit.py` examines canonical IDs, source tags, names, categories, geometry and independent facility codes for **hospital** candidates in an existing review CSV. A source name, nearby coordinate, same city or publication-row number does not itself verify a hospital site.

The audit is read-only. It writes a candidate evidence CSV, review queue, grouped candidate records and JSON summary to a new output directory outside the workspace. It does not modify ownership, institution links, PSIC/IO tags, network, Voronoi, clusters or scores.

Only verified establishment evidence may be considered for a separate guarded ownership-promotion operation.

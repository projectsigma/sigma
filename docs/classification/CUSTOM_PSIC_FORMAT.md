# Custom PSIC taxonomy format

A custom activity taxonomy may be loaded from a directory containing either `nodes.csv` or
`nodes.parquet`.

The node table requires the taxonomy columns used by `PsicTaxonomy.from_frame`, including at least
`code`, `level`, `title`, and `parent_code`; optional descriptive fields may also be supplied. The
loader validates hierarchy structure, duplicate codes, parent references, and taxonomy identity.

The bundled Rev. 5 profile is stricter than a generic custom taxonomy. Built-in tagging references
accept only the exact bundled `psic_rev5/nodes.parquet` identity so that an unrelated custom taxonomy
cannot silently consume the reviewed Rev. 5 mappings merely by using the same scheme/version label.

Custom taxonomy-to-economy mappings should be supplied explicitly. SIGMA does not infer a semantic
crosswalk between an arbitrary replacement taxonomy and an economy.

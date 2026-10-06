# Custom economy format

A custom numerical economy is a directory containing sector metadata and a transaction table:

```text
economy.yml
sectors.csv
transactions.csv
total_output.csv              # optional when derivable/supplied elsewhere
technical_coefficients.csv    # optional compatibility override
```

`sectors.csv` defines the ordered sector codes and labels. `transactions.csv` is a square non-negative
matrix whose first column identifies row sectors and whose remaining headers are the same ordered
sector codes; rows are suppliers and columns are users. Both axes must exactly match the sector order.

`Economy.from_directory(path)` validates these contracts and records file hashes in provenance.
Transaction preprocessing is execution policy rather than part of economy identity: the default is
`none`, while `mwas_ras_fast` is an optional downstream preprocessing mode.

PSIC taxonomy data and place-tagging references are intentionally separate from the economy directory.
A replacement economy therefore requires explicit compatible mappings from the selected taxonomy to
its sector codes.

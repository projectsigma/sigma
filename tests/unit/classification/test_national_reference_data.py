"""Published snapshot contains only the 125 verified-source Level 3 hospital rows."""
import csv,json,hashlib
from pathlib import Path
from sigma.classification.national_registry import load_national_registry
ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/"data"/"references"

def test_hospital_only_snapshot():
 p=DATA/"institution_national_v1_20261104.csv"
 records=load_national_registry(p)
 assert len(records)==125
 assert {r.source for r in records}=={"philhealth_hospitals"}
 assert {r.domain for r in records}=={"health"}
 assert sum(r.ownership=="public" for r in records)==63
 assert sum(r.ownership=="private" for r in records)==62
 assert all(r.id_kind=="publication_row" for r in records)
 manifest=json.loads((DATA/"national_reference_hospitals_v10.json").read_text())
 assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest["hospital_csv_sha256"]

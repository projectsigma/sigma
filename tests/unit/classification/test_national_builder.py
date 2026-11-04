"""Hospital CSV builder retains exact publication serial and validated public/private type."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location("national_hospital_builder",ROOT/"scripts/sigma_national_institution_registry.py")
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)

def test_level_three_and_type():
 rows=[{"CAT":"Level 3","SEC":"G","No":"12","NAME OF HEALTH FACILITY":"Public Hospital", "MUNICIPALITY":"Quezon City"},
       {"CAT":"2","SEC":"P","No":"13","NAME OF HEALTH FACILITY":"Other Hospital"}]
 out,stats=MODULE.hospital_rows(rows,source="philhealth_hospitals",url="https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_093026.pdf",as_of="2026-09-30")
 assert len(out)==1 and out[0]["source_id"]=="2026-09-30:row-12"
 assert out[0]["ownership"]=="public" and stats["other_hospital_level"]==1

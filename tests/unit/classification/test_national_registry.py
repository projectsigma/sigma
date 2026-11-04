"""National hospital registry: official source validation and conservative identity matching."""
import csv
import pytest
from sigma.classification.national_registry import (FIELDS,load_national_registry,NationalRegistryIndex,
                                                        national_registry_path,national_fingerprint)

def row(**kw):
 r=dict(source="philhealth_hospitals",source_id="2026-09-30:row-17",name="Public Hospital",
        domain="health",ownership="public",city="QUEZON CITY",province="",address="East Avenue",
        aliases="",source_url="https://www.philhealth.gov.ph/partners/providers/facilities/accredited/HOSP_093026.pdf",
        as_of="2026-09-30",id_kind="publication_row",evidence_type="explicit_sector",facility_level="Level 3")
 r.update(kw);return r

def save(p,rows):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n");w.writeheader();w.writerows(rows)

def test_exact_name_only_provisional(tmp_path):
 p=tmp_path/"a.csv";save(p,[row()]);ind=NationalRegistryIndex(load_national_registry(p))
 got=ind.match({"name":"Public Hospital","city":"Quezon City"},"health")
 assert got.status=="EXACT_NAME_CITY" and got.side=="public" and "provisional" in got.basis
 assert ind.match({"name":"Public Hospital"},"education").status=="NO_MATCH"

def test_publication_row_not_identity(tmp_path):
 p=tmp_path/"a.csv";save(p,[row()]);ind=NationalRegistryIndex(load_national_registry(p))
 assert ind.match({"name":"Unrelated","nhfr_code":"2026-09-30:row-17"},"health").status=="NO_MATCH"

def test_wrong_locality_remains_provisional(tmp_path):
 p=tmp_path/"a.csv";save(p,[row()]);ind=NationalRegistryIndex(load_national_registry(p))
 got=ind.match({"name":"Public Hospital","city":"Pasig City"},"health")
 assert got.status=="NAME_LOCATION_UNVERIFIED" and "branch_or_affiliate" in got.note

def test_refuses_other_source_even_if_schema_valid(tmp_path):
 p=tmp_path/"a.csv";save(p,[row(source="unapproved_directory")])
 with pytest.raises(ValueError,match="invalid official provenance"):load_national_registry(p)

def test_code_match_requires_consistent_name_and_location(tmp_path):
 p=tmp_path/"a.csv";save(p,[row(source="doh_nhfr",source_id="ABC-123",
 source_url="https://nhfr.doh.gov.ph/example",id_kind="official_code")]);ind=NationalRegistryIndex(load_national_registry(p))
 assert ind.match({"name":"Public Hospital","nhfr_code":"ABC-123","city":"Quezon City"},"health").status=="EXACT_EXTERNAL_ID"
 assert ind.match({"name":"Different Clinic","nhfr_code":"ABC-123"},"health").status=="EXTERNAL_ID_NAME_CONFLICT"
 assert ind.match({"name":"Public Hospital","nhfr_code":"ABC-123","city":"Pasig City"},"health").status=="EXTERNAL_ID_LOCALITY_REVIEW"

def test_national_fingerprint_tracks_hospital_snapshot(tmp_path):
 ws=tmp_path/"SIGMA/workspaces/quezon_city";p=national_registry_path(ws)
 assert national_fingerprint(ws) is None
 save(p,[row()]);a=national_fingerprint(ws);assert a
 save(p,[row(name="Another Hospital")]);assert a!=national_fingerprint(ws)

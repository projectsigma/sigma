#!/usr/bin/env python3
"""Install a vetted hospital-only snapshot into an empty SIGMA_HOME reference slot."""
from __future__ import annotations
import argparse,csv,hashlib,json,os
from pathlib import Path
from sigma.classification.national_registry import load_national_registry
DATA="institution_national_v1_20261104.csv"
MANIFEST="national_reference_hospitals_v10.json"
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--repo",required=True,type=Path)
 p.add_argument("--sigma-home",required=True,type=Path)
 g=p.add_mutually_exclusive_group(required=True);g.add_argument("--check",action="store_true");g.add_argument("--apply",action="store_true")
 a=p.parse_args(); data=a.repo/"data/references"/DATA; manifest=a.repo/"data/references"/MANIFEST
 m=json.loads(manifest.read_text(encoding="utf-8"))
 if sha(data)!=m["hospital_csv_sha256"]:raise ValueError("source hash differs from manifest")
 records=load_national_registry(data)
 if len(records)!=125 or any(r.domain!="health" for r in records):raise ValueError("not a 125-record hospital-only registry")
 target=a.sigma_home/"references"/"institution_national_v1.csv"
 meta=a.sigma_home/"references"/"institution_national_v1.manifest.json"
 if target.exists() or meta.exists():raise FileExistsError("existing installed reference; use reviewed migration, never overwrite")
 print(json.dumps({"status":"ready" if a.check else "applied","target":str(target),"hospitals":len(records)},indent=2))
 if a.apply:
  target.parent.mkdir(parents=True,exist_ok=True)
  try:
   with target.open("xb") as f:f.write(data.read_bytes())
   with meta.open("x",encoding="utf-8") as f:f.write(manifest.read_text(encoding="utf-8"))
  except Exception:
   target.unlink(missing_ok=True);meta.unlink(missing_ok=True);raise
if __name__=="__main__":main()

#!/usr/bin/env python3
"""Build a national Level 3 hospital reference from an identified official source.

Source identity and publication date remain explicit. School identity is managed
separately by the packaged school index and is never inferred from this registry.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path
from sigma.classification.national_registry import (FIELDS, _level3, _text, _valid_record, load_national_registry)

def get_field(row: dict, *aliases: str) -> str:
    lower = {re.sub(r"[^a-z0-9]", "", str(k).lower()): _text(v) for k, v in row.items()}
    for name in aliases:
        val = lower.get(re.sub(r"[^a-z0-9]", "", name.lower()), "")
        if val: return val
    return ""

def rows_from(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if path.suffix.lower() == ".xlsx":
        import pandas as pd
        return pd.read_excel(path, dtype=str).fillna("").to_dict("records")
    raise ValueError("Expected official CSV or XLSX export; PDFs must be transcribed to CSV with original row numbers")

def hospital_rows(rows: list[dict], *, source: str, url: str, as_of: str) -> tuple[list[dict], Counter]:
    output, stats = [], Counter()
    for n, record in enumerate(rows, start=2):
        stats["input"] += 1
        level = get_field(record, "CAT", "Hospital Level", "Service Capability Level", "Level", "Hospital Classification")
        if not _level3(level):
            stats["other_hospital_level"] += 1
            continue
        name = get_field(record, "NAME OF HEALTH FACILITY", "Health Facility Name", "Facility Name", "Name")
        city = get_field(record, "MUNICIPALITY", "City/Municipality", "City Municipality", "City")
        address = get_field(record, "STREET", "Address", "Street Address")
        owner = get_field(record, "SEC", "Ownership Major Classification", "Ownership", "Ownership Major")
        side = "public" if owner.casefold() in {"g", "government", "public", "government owned"} else (
               "private" if owner.casefold() in {"p", "private", "privately owned"} else "")
        if source == "doh_nhfr":
            ident = get_field(record, "Health Facility Code", "Facility Code", "NHFR Code")
            kind = "official_code"
        else:
            # PDF serial is a *publication row*, never an NHFR / official facility ID.
            ident = get_field(record, "Row No", "Publication Row", "No", "Number", "#")
            if ident:
                ident = f"{as_of}:row-{ident}"
            kind = "publication_row"
        if not ident or not name or not side:
            raise ValueError(f"Level 3 hospital input row {n}: missing serial/official code, name or explicit G/P ownership")
        output.append(dict(source=source, source_id=ident, name=name, domain="health",
                           ownership=side, city=city, province=get_field(record, "Province"),
                           address=address, aliases="", source_url=url, as_of=as_of,
                           id_kind=kind, evidence_type="explicit_sector", facility_level="Level 3"))
        stats["included"] += 1
    return output, stats


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sigma-home", type=Path, required=True)
    p.add_argument("--hospitals", type=Path, required=True)
    p.add_argument("--hospital-source", choices=("philhealth_hospitals", "doh_nhfr"), default="philhealth_hospitals")
    p.add_argument("--hospital-url", required=True)
    p.add_argument("--hospital-as-of", required=True)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--allow-partial", action="store_true")
    a=p.parse_args()
    date.fromisoformat(a.hospital_as_of)
    rows, stats=hospital_rows(rows_from(a.hospitals), source=a.hospital_source, url=a.hospital_url, as_of=a.hospital_as_of)
    if len(rows)<100 and not a.allow_partial:
        raise ValueError("hospital snapshot has fewer than 100 Level 3 facilities")
    seen=set()
    for n,r in enumerate(rows,2):
        _valid_record(r,n)
        identity=(r["source"],r["source_id"].casefold())
        if identity in seen:raise ValueError("duplicate hospital source ID")
        seen.add(identity)
    target=a.sigma_home.expanduser().resolve()/"references"/"institution_national_v1.csv"
    if target.exists() and a.apply:
        raise FileExistsError(f"registry already exists: {target}; review before replacing")
    report={"status":"ready" if a.check else "applied", "records":len(rows), "source_url":a.hospital_url,
            "source_as_of":a.hospital_as_of,"source_sha256":hashlib.sha256(a.hospitals.read_bytes()).hexdigest()}
    if a.apply:
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_suffix(".csv.tmp")
        if temp.exists():raise FileExistsError(temp)
        try:
            with temp.open("x",encoding="utf-8",newline="") as f:
                w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n");w.writeheader();w.writerows(rows)
            load_national_registry(temp)
            os.replace(temp,target)
        finally:
            temp.unlink(missing_ok=True)
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()

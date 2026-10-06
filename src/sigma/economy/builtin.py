"""Packaged Philippine PSA 2018 economy resources.

The transaction and total-output CSV bytes are copied unchanged from sigma-engine;
sector labels are consolidated from sigma-siphon's reviewed industries catalog.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import as_file, files
from typing import Literal

import numpy as np
import pandas as pd

from .io_utils import read_io_table

PSA_RELEASE_URL = "https://psa.gov.ph/content/psa-releases-2018-input-output-tables"

@dataclass(frozen=True)
class IOInputInfo:
    source_id: str
    source_kind: Literal["builtin", "override"]
    source_path: str | None
    source_url: str | None
    reference_year: int | None
    resource_sha256: str | None

_BUILTINS = {
    "io80": ("sigma.resources.economy.psa_2018_io80", 80, "psa-2018-io80-transaction", "9335f4de98d6b11205b431f8702f26a2c932d641fdd911ce7ddcf08f604840a1", "7159ef3cdc7368d949b4846e21927ddba3c5d116c7cceafcd9efd48273aca061", "295acc34ff4834cc47971d9158445cec75fceeb635614e6fb1a3bdc150fc891d"),
    "io16": ("sigma.resources.economy.psa_2018_io16", 16, "psa-2018-io16-transaction", "f5a2105fc67d2c992eb86531b310b0ce7eff3046a981da88570cea196a49ba76", "8b5653e65002fbedcb7602793da044c4a13cd9664bc0e7f8d7d41ebe9f53e9cf", "d7a15d09df11825f52b1e6c562f72c66642eb8b9f49d6c989e49c314547ebd98"),
}

def _canonical_text_sha256(payload: bytes) -> str:
    normalized = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()

def builtin_resource_package(classification: str) -> tuple[str,int,str,str,str,str]:
    try:
        return _BUILTINS[classification.casefold()]
    except KeyError as exc:
        raise ValueError("classification must be 'io80' or 'io16'") from exc

def load_builtin_transactions(classification: str) -> tuple[pd.DataFrame, IOInputInfo]:
    package, sector_count, source_id, expected_sha, _, _ = builtin_resource_package(classification)
    resource=files(package).joinpath("transactions.csv")
    payload=resource.read_bytes(); actual=_canonical_text_sha256(payload)
    if actual != expected_sha:
        raise RuntimeError(f"bundled {classification} transaction resource failed integrity check: expected {expected_sha}, got {actual}")
    with as_file(resource) as path:
        table=read_io_table(path, expected_sector_count=sector_count)
    table.attrs["source_layout"]="builtin-canonical"; table.attrs["source_id"]=source_id
    return table, IOInputInfo(source_id,"builtin",None,PSA_RELEASE_URL,2018,actual)

def load_builtin_total_output(classification: str) -> pd.Series:
    package, sector_count, _, _, expected_sha, _ = builtin_resource_package(classification)
    resource=files(package).joinpath("total_output.csv")
    payload=resource.read_bytes(); actual=_canonical_text_sha256(payload)
    if actual != expected_sha:
        raise RuntimeError(f"bundled {classification} total-output resource failed integrity check: expected {expected_sha}, got {actual}")
    with as_file(resource) as path:
        frame=pd.read_csv(path,dtype={"sector":str})
    if list(frame.columns) != ["sector","total_output"]:
        raise RuntimeError(f"bundled {classification} total-output resource has an unexpected schema")
    canonical=[f"{i:02d}" for i in range(1,sector_count+1)]
    sectors=frame["sector"].astype(str).str.zfill(2).tolist()
    if sectors != canonical:
        raise RuntimeError(f"bundled {classification} total-output sectors are not canonical")
    values=pd.to_numeric(frame["total_output"],errors="coerce").to_numpy(float)
    if len(values)!=sector_count or not np.isfinite(values).all() or np.any(values<=0):
        raise RuntimeError(f"bundled {classification} total output must contain {sector_count} finite strictly-positive values")
    out=pd.Series(values,index=canonical,dtype=float,name="total_output")
    out.attrs.update(source_id=f"psa-2018-{classification}-total-output", source_kind="builtin", source_url=PSA_RELEASE_URL, reference_year=2018, resource_sha256=actual, resource_filename="total_output.csv")
    return out

def load_builtin_sectors(classification: str) -> pd.DataFrame:
    package, sector_count, _, _, _, expected_sha = builtin_resource_package(classification)
    resource=files(package).joinpath("sectors.csv")
    payload=resource.read_bytes(); actual=_canonical_text_sha256(payload)
    if actual != expected_sha:
        raise RuntimeError(f"bundled {classification} sector resource failed integrity check: expected {expected_sha}, got {actual}")
    with as_file(resource) as path:
        frame=pd.read_csv(path,dtype=str,keep_default_na=False)
    frame.attrs["resource_sha256"] = actual
    if list(frame.columns) != ["code","label"] or len(frame)!=sector_count:
        raise RuntimeError(f"bundled {classification} sector catalog has an unexpected schema/size")
    return frame

"""First-class immutable-by-convention economic domain model."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import yaml

from sigma.errors import EconomyValidationError
from .builtin import load_builtin_sectors, load_builtin_total_output, load_builtin_transactions
from .io_utils import derive_technical_coefficients, normalize_sector_id, read_io_table, read_technical_coefficients, read_total_output_vector

@dataclass(frozen=True, slots=True)
class Sector:
    code: str
    label: str

@dataclass(frozen=True, slots=True)
class SectorCatalog:
    _items: tuple[Sector, ...]

    def __init__(self, sectors: Iterable[Sector]):
        items=tuple(sectors)
        if not items:
            raise EconomyValidationError("economy must contain at least one sector")
        codes=[]; labels=[]
        for s in items:
            code=str(s.code).strip(); label=str(s.label).strip()
            if not code or not label:
                raise EconomyValidationError("sector codes and labels must be nonblank")
            codes.append(code); labels.append(label)
        if len(set(codes)) != len(codes):
            raise EconomyValidationError("sector codes must be unique")
        if len(set(labels)) != len(labels):
            raise EconomyValidationError("sector labels must be unique")
        object.__setattr__(self,"_items",tuple(Sector(c,l) for c,l in zip(codes,labels,strict=True)))

    def __len__(self): return len(self._items)
    def __iter__(self): return iter(self._items)
    def __getitem__(self,item): return self._items[item]
    @property
    def codes(self) -> tuple[str,...]: return tuple(x.code for x in self._items)
    @property
    def labels(self) -> tuple[str,...]: return tuple(x.label for x in self._items)
    def label_for(self, code: str) -> str:
        for s in self._items:
            if s.code == str(code): return s.label
        raise KeyError(code)
    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({"code":self.codes,"label":self.labels})


def _hash_json(value: Any) -> str:
    payload=json.dumps(value,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def _matrix_fingerprint(frame: pd.DataFrame) -> str:
    ids=[str(v) for v in frame.index]
    arr=np.asarray(frame.to_numpy(dtype=float),dtype="<f8",order="C")
    h=hashlib.sha256(); h.update(_hash_json(ids).encode()); h.update(arr.tobytes(order="C")); return h.hexdigest()

def _series_fingerprint(series: pd.Series) -> str:
    ids=[str(v) for v in series.index]
    arr=np.asarray(series.to_numpy(dtype=float),dtype="<f8")
    h=hashlib.sha256(); h.update(_hash_json(ids).encode()); h.update(arr.tobytes()); return h.hexdigest()

def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _read_sector_catalog(path: Path) -> SectorCatalog:
    frame=pd.read_csv(path,dtype=str,keep_default_na=False)
    if list(frame.columns) != ["code","label"]:
        raise EconomyValidationError("sectors.csv must have exactly the columns code,label")
    return SectorCatalog(Sector(row.code,row.label) for row in frame.itertuples(index=False))

def _read_canonical_matrix(path: Path, catalog: SectorCatalog, *, kind: str) -> pd.DataFrame:
    if path.suffix.lower() not in {".csv",".parquet",".pq",".xlsx",".xlsm"}:
        raise EconomyValidationError(f"unsupported {kind} format: {path.suffix or '<no suffix>'}")
    if path.suffix.lower()==".csv":
        frame=pd.read_csv(path,dtype=str,keep_default_na=False)
        if frame.shape[1] < 2: raise EconomyValidationError(f"{kind} must include a sector-id column")
        frame=frame.set_index(frame.columns[0])
    elif path.suffix.lower() in {".parquet",".pq"}:
        frame=pd.read_parquet(path)
        if isinstance(frame.index,pd.RangeIndex): frame=frame.set_index(frame.columns[0])
    else:
        frame=pd.read_excel(path,dtype=str)
        if frame.shape[1] < 2: raise EconomyValidationError(f"{kind} must include a sector-id column")
        frame=frame.set_index(frame.columns[0])
    row=[str(v).strip() for v in frame.index]; col=[str(v).strip() for v in frame.columns]
    if any(not v for v in row+col): raise EconomyValidationError(f"{kind} sector identifiers must be nonblank")
    expected=list(catalog.codes)
    if row != expected or col != expected:
        raise EconomyValidationError(f"{kind} row and column axes must exactly match sectors.csv order")
    numeric=frame.apply(pd.to_numeric,errors="coerce").astype(float); numeric.index=row; numeric.columns=col
    values=numeric.to_numpy()
    if not np.isfinite(values).all() or np.any(values<0):
        raise EconomyValidationError(f"{kind} values must be finite and non-negative")
    return numeric

def _read_custom_output(path: Path, catalog: SectorCatalog) -> pd.Series:
    frame=pd.read_csv(path,dtype=str,keep_default_na=False)
    if list(frame.columns) not in (["sector","total_output"],["code","total_output"]):
        raise EconomyValidationError("total_output.csv must have columns sector,total_output")
    ids=[str(v).strip() for v in frame.iloc[:,0]]; expected=list(catalog.codes)
    if any(not v for v in ids) or ids != expected:
        raise EconomyValidationError("total-output sectors must exactly match sectors.csv order")
    values=pd.to_numeric(frame["total_output"],errors="coerce").to_numpy(float)
    if not np.isfinite(values).all() or np.any(values<=0):
        raise EconomyValidationError("total output must be finite and strictly positive")
    return pd.Series(values,index=expected,dtype=float,name="total_output")

class Economy:
    __slots__=("economy_id","label","version","reference_year","sectors","_z_raw","_x","_explicit_a","provenance","sector_fingerprint","transaction_fingerprint","output_fingerprint","coefficient_fingerprint","economy_fingerprint","_frozen")
    def __init__(self, *, economy_id:str, sectors:SectorCatalog, raw_transactions:pd.DataFrame, total_output:pd.Series|None=None, explicit_technical_coefficients:pd.DataFrame|None=None, label:str|None=None, version:str|None=None, reference_year:int|None=None, provenance:Mapping[str,Any]|None=None):
        object.__setattr__(self,"_frozen",False)
        eid=str(economy_id).strip()
        if not eid: raise EconomyValidationError("economy_id must be nonblank")
        codes=list(sectors.codes)
        z=raw_transactions.copy(deep=True)
        if [str(v) for v in z.index] != codes or [str(v) for v in z.columns] != codes:
            raise EconomyValidationError("raw transaction axes must exactly match sector catalog order")
        zv=z.to_numpy(dtype=float)
        if not np.isfinite(zv).all() or np.any(zv<0): raise EconomyValidationError("raw transactions must be finite and non-negative")
        z=z.astype(float)
        x=None
        if total_output is not None:
            x=pd.Series(total_output,copy=True,dtype=float); x.index=[str(v) for v in x.index]
            if list(x.index)!=codes: raise EconomyValidationError("total output must exactly match sector catalog order")
            xv=x.to_numpy();
            if not np.isfinite(xv).all() or np.any(xv<=0): raise EconomyValidationError("total output must be finite and strictly positive")
            x.name="total_output"
        a=None
        if explicit_technical_coefficients is not None:
            a=explicit_technical_coefficients.copy(deep=True); a.index=[str(v) for v in a.index]; a.columns=[str(v) for v in a.columns]
            if list(a.index)!=codes or list(a.columns)!=codes: raise EconomyValidationError("explicit technical coefficients must exactly match sector catalog order")
            av=a.to_numpy(dtype=float)
            if not np.isfinite(av).all() or np.any(av<0): raise EconomyValidationError("technical coefficients must be finite and non-negative")
            a=a.astype(float)
        if x is None and a is None: raise EconomyValidationError("economy requires total output or an explicit technical-coefficient override")
        object.__setattr__(self,"economy_id",eid); object.__setattr__(self,"label",str(label or eid)); object.__setattr__(self,"version",None if version is None else str(version)); object.__setattr__(self,"reference_year",reference_year); object.__setattr__(self,"sectors",sectors); object.__setattr__(self,"_z_raw",z); object.__setattr__(self,"_x",x); object.__setattr__(self,"_explicit_a",a); object.__setattr__(self,"provenance",MappingProxyType(dict(provenance or {})))
        sf=_hash_json([[s.code,s.label] for s in sectors]); tf=_matrix_fingerprint(z); of=None if x is None else _series_fingerprint(x); cf=None if a is None else _matrix_fingerprint(a)
        object.__setattr__(self,"sector_fingerprint",sf); object.__setattr__(self,"transaction_fingerprint",tf); object.__setattr__(self,"output_fingerprint",of); object.__setattr__(self,"coefficient_fingerprint",cf)
        object.__setattr__(self,"economy_fingerprint",_hash_json({"id":eid,"reference_year":reference_year,"version":version,"sector":sf,"transactions":tf,"output":of,"coefficient":cf}))
        object.__setattr__(self,"_frozen",True)
    def __setattr__(self,name,value):
        if getattr(self,"_frozen",False): raise AttributeError("Economy is immutable")
        object.__setattr__(self,name,value)
    @property
    def Z_raw(self): return self._z_raw.copy(deep=True)
    @property
    def raw_transactions(self): return self.Z_raw
    @property
    def x(self): return None if self._x is None else self._x.copy(deep=True)
    @property
    def total_output(self): return self.x
    @property
    def raw_technical_coefficients(self):
        if self._explicit_a is not None:
            out=self._explicit_a.copy(deep=True); out.attrs["technical_coefficient_source"]="explicit_matrix"; return out
        return derive_technical_coefficients(self._z_raw,self._x)
    @property
    def A_raw(self): return self.raw_technical_coefficients
    @property
    def sector_identity_fingerprint(self): return self.sector_fingerprint
    @property
    def raw_transactions_fingerprint(self): return self.transaction_fingerprint
    @property
    def gross_output_fingerprint(self): return self.output_fingerprint
    @property
    def economy_package_fingerprint(self): return self.economy_fingerprint
    @classmethod
    def default(cls): return cls.builtin("io80")
    @classmethod
    def builtin(cls, classification:str):
        key=classification.casefold().replace("psa-2018-","").replace("psa_2018_","")
        if key not in {"io80","io16"}: raise ValueError("classification must be 'io80' or 'io16'")
        sectors_frame=load_builtin_sectors(key); catalog=SectorCatalog(Sector(r.code,r.label) for r in sectors_frame.itertuples(index=False))
        z,info=load_builtin_transactions(key); x=load_builtin_total_output(key)
        return cls(economy_id=f"psa-2018-{key}",label=f"Philippine PSA 2018 {key.upper()}",version="2018",reference_year=2018,sectors=catalog,raw_transactions=z,total_output=x,provenance={"source_kind":"builtin","source_url":info.source_url,"transaction_sha256":info.resource_sha256,"output_sha256":x.attrs.get("resource_sha256"),"sector_sha256":sectors_frame.attrs.get("resource_sha256")})
    @classmethod
    def psa_2018_io80(cls): return cls.builtin("io80")
    @classmethod
    def psa_2018_io16(cls): return cls.builtin("io16")
    @classmethod
    def from_files(cls, *, sectors: str|Path, transactions:str|Path, total_output:str|Path|None=None, technical_coefficients:str|Path|None=None, economy_id:str, label:str|None=None, version:str|None=None, reference_year:int|None=None, provenance:Mapping[str,Any]|None=None):
        sp=Path(sectors).expanduser().resolve(); zp=Path(transactions).expanduser().resolve()
        if not sp.is_file(): raise FileNotFoundError(sp)
        if not zp.is_file(): raise FileNotFoundError(zp)
        catalog=_read_sector_catalog(sp); z=_read_canonical_matrix(zp,catalog,kind="transactions")
        x=None; a=None; paths={"sectors":str(sp),"transactions":str(zp)}; hashes={"sectors":_file_hash(sp),"transactions":_file_hash(zp)}
        if total_output is not None:
            xp=Path(total_output).expanduser().resolve();
            if not xp.is_file(): raise FileNotFoundError(xp)
            x=_read_custom_output(xp,catalog); paths["total_output"]=str(xp); hashes["total_output"]=_file_hash(xp)
        if technical_coefficients is not None:
            ap=Path(technical_coefficients).expanduser().resolve();
            if not ap.is_file(): raise FileNotFoundError(ap)
            a=_read_canonical_matrix(ap,catalog,kind="technical coefficients"); paths["technical_coefficients"]=str(ap); hashes["technical_coefficients"]=_file_hash(ap)
        p=dict(provenance or {}); p.update(source_kind="custom_files",paths=paths,resource_sha256=hashes)
        return cls(economy_id=economy_id,label=label,version=version,reference_year=reference_year,sectors=catalog,raw_transactions=z,total_output=x,explicit_technical_coefficients=a,provenance=p)
    @classmethod
    def from_directory(cls, directory:str|Path):
        root=Path(directory).expanduser().resolve(); meta_path=root/"economy.yml"
        if not meta_path.is_file(): raise FileNotFoundError(meta_path)
        meta=yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        if not isinstance(meta,dict): raise EconomyValidationError("economy.yml must contain a mapping")
        eid=str(meta.get("id") or "").strip()
        if not eid: raise EconomyValidationError("economy.yml requires nonblank id")
        def filename(section, default=None):
            value=meta.get(section)
            if value is None: return default
            if isinstance(value,str): return value
            if isinstance(value,dict): return value.get("file",default)
            raise EconomyValidationError(f"economy.yml {section} must be a filename or mapping")
        sec=filename("sectors","sectors.csv"); trans=filename("transactions","transactions.csv"); out=filename("total_output",None); coeff=filename("technical_coefficients",None)
        # conventional files may be omitted from YAML while remaining present
        if out is None and (root/"total_output.csv").is_file(): out="total_output.csv"
        if coeff is None and (root/"technical_coefficients.csv").is_file(): coeff="technical_coefficients.csv"
        ry=meta.get("reference_year")
        if ry is not None:
            try: ry=int(ry)
            except Exception as exc: raise EconomyValidationError("reference_year must be an integer") from exc
        return cls.from_files(sectors=root/sec,transactions=root/trans,total_output=None if out is None else root/out,technical_coefficients=None if coeff is None else root/coeff,economy_id=eid,label=meta.get("label"),version=meta.get("version"),reference_year=ry,provenance={"economy_yml":str(meta_path),"economy_yml_sha256":_file_hash(meta_path),"metadata":meta})
    @classmethod
    def from_legacy_inputs(cls, classification:str="io80", *, transactions_override_path:str|Path|None=None, transactions_sheet:str|int=0, technical_coefficients_path:str|Path|None=None, technical_coefficients_sheet:str|int=0):
        base=cls.builtin(classification); codes=list(base.sectors.codes); expected=len(codes)
        if transactions_override_path is None:
            z=base._z_raw.copy(); x=base._x.copy(); txprov={"transaction_source":"builtin"}
        else:
            path=Path(transactions_override_path).expanduser().resolve(); z=read_io_table(path,sheet_name=transactions_sheet,expected_sector_count=expected); x=None; txprov={"transaction_source":"override","transaction_path":str(path)}
        a=None
        if technical_coefficients_path is not None:
            ap=Path(technical_coefficients_path).expanduser().resolve(); a=read_technical_coefficients(ap,sheet_name=technical_coefficients_sheet,expected_sector_count=expected); txprov["coefficient_source"]="explicit_matrix_override"; txprov["coefficient_path"]=str(ap)
        elif transactions_override_path is not None:
            x=read_total_output_vector(Path(transactions_override_path).expanduser().resolve(),sheet_name=transactions_sheet,sector_ids=codes); txprov["coefficient_source"]="derived_from_transaction_total_output"
        else: txprov["coefficient_source"]="derived_from_builtin_psa_total_output"
        return cls(economy_id=base.economy_id,label=base.label,version=base.version,reference_year=base.reference_year,sectors=base.sectors,raw_transactions=z,total_output=x,explicit_technical_coefficients=a,provenance={**dict(base.provenance),**txprov})

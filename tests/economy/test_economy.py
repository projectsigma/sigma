import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from sigma import Economy, Sector, SectorCatalog
from sigma.errors import EconomyValidationError
from sigma.economy.builtin import load_builtin_total_output, load_builtin_transactions
from sigma.economy.io_utils import derive_technical_coefficients, normalize_sector_id


def test_default_is_exact_io80_builtin():
    economy=Economy.default()
    z_old, info=load_builtin_transactions("io80")
    x_old=load_builtin_total_output("io80")
    assert economy.economy_id == "psa-2018-io80"
    assert len(economy.sectors)==80
    assert economy.sectors.codes == tuple(f"{i:02d}" for i in range(1,81))
    assert economy.sectors[0].label == "Palay / unmilled-rice farming"
    pd.testing.assert_frame_equal(economy.Z_raw,z_old,check_exact=True)
    pd.testing.assert_series_equal(economy.x,x_old,check_exact=True)
    pd.testing.assert_frame_equal(economy.A_raw,derive_technical_coefficients(z_old,x_old),check_exact=True)
    assert info.resource_sha256 == "9335f4de98d6b11205b431f8702f26a2c932d641fdd911ce7ddcf08f604840a1"


def test_io16_builtin_exact_order_labels_and_numbers():
    economy=Economy.builtin("io16")
    z_old,_=load_builtin_transactions("io16"); x_old=load_builtin_total_output("io16")
    assert economy.sectors.codes == tuple(f"{i:02d}" for i in range(1,17))
    assert economy.sectors[0].label == "Agriculture, forestry & fishing"
    assert economy.sectors[-1].label == "Arts, recreation & other services"
    pd.testing.assert_frame_equal(economy.Z_raw,z_old,check_exact=True)
    pd.testing.assert_series_equal(economy.x,x_old,check_exact=True)
    np.testing.assert_array_equal(economy.A_raw.to_numpy(), (z_old / x_old).to_numpy())


def test_builtin_alias_factories():
    assert Economy.psa_2018_io80().economy_fingerprint == Economy.default().economy_fingerprint
    assert Economy.psa_2018_io16().economy_fingerprint == Economy.builtin("io16").economy_fingerprint


def test_raw_properties_are_copy_out_not_mutable_identity():
    economy=Economy.default(); before=economy.transaction_fingerprint
    z=economy.Z_raw; z.iloc[0,0]=-999
    x=economy.x; x.iloc[0]=-1
    assert economy.Z_raw.iloc[0,0] > 0
    assert economy.x.iloc[0] > 0
    assert economy.transaction_fingerprint == before
    with pytest.raises(AttributeError): economy.economy_id="changed"


def test_fingerprints_separate_sector_and_numerical_identity():
    base=Economy.builtin("io16"); z=base.Z_raw; z.iloc[0,1]+=1
    changed=Economy(economy_id="changed", sectors=base.sectors, raw_transactions=z,total_output=base.x)
    assert changed.sector_fingerprint == base.sector_fingerprint
    assert changed.transaction_fingerprint != base.transaction_fingerprint
    assert changed.output_fingerprint == base.output_fingerprint
    assert changed.economy_fingerprint != base.economy_fingerprint


def _custom_dir(tmp_path, *, with_output=True, with_a=False):
    d=tmp_path/"eco"; d.mkdir(); codes=["01","02"]
    pd.DataFrame({"code":codes,"label":["One","Two"]}).to_csv(d/"sectors.csv",index=False)
    pd.DataFrame([[1.0,2.0],[3.0,4.0]],index=codes,columns=codes).rename_axis("sector").to_csv(d/"transactions.csv")
    if with_output: pd.DataFrame({"sector":codes,"total_output":[10.0,20.0]}).to_csv(d/"total_output.csv",index=False)
    if with_a: pd.DataFrame([[.1,.2],[.3,.4]],index=codes,columns=codes).rename_axis("sector").to_csv(d/"technical_coefficients.csv")
    (d/"economy.yml").write_text(yaml.safe_dump({"id":"custom-2","label":"Custom two-sector","version":"1","reference_year":2026,"sectors":{"file":"sectors.csv"},"transactions":{"file":"transactions.csv"}}),encoding="utf-8")
    return d


def test_custom_directory_preferred_z_over_x_path(tmp_path):
    d=_custom_dir(tmp_path)
    e=Economy.from_directory(d)
    assert e.economy_id=="custom-2" and e.reference_year==2026
    assert e.sectors.codes == ("01","02")
    np.testing.assert_allclose(e.A_raw.to_numpy(), [[.1,.1],[.3,.2]])
    assert e.coefficient_fingerprint is None
    assert e.provenance["resource_sha256"]["transactions"] == hashlib.sha256((d/"transactions.csv").read_bytes()).hexdigest()


def test_custom_directory_explicit_a_only_supported(tmp_path):
    d=_custom_dir(tmp_path,with_output=False,with_a=True)
    e=Economy.from_directory(d)
    assert e.x is None
    np.testing.assert_allclose(e.A_raw.to_numpy(), [[.1,.2],[.3,.4]])
    assert e.coefficient_fingerprint is not None


def test_custom_explicit_a_overrides_derived_a(tmp_path):
    d=_custom_dir(tmp_path,with_output=True,with_a=True)
    e=Economy.from_directory(d)
    np.testing.assert_allclose(e.A_raw.to_numpy(), [[.1,.2],[.3,.4]])
    assert e.x is not None


def test_custom_requires_output_or_explicit_a(tmp_path):
    d=_custom_dir(tmp_path,with_output=False,with_a=False)
    with pytest.raises(EconomyValidationError,match="requires total output"):
        Economy.from_directory(d)


def test_custom_axis_order_must_exactly_follow_sector_catalog(tmp_path):
    d=_custom_dir(tmp_path)
    pd.DataFrame([[1,2],[3,4]],index=["02","01"],columns=["02","01"]).rename_axis("sector").to_csv(d/"transactions.csv")
    with pytest.raises(EconomyValidationError,match="exactly match sectors.csv order"):
        Economy.from_directory(d)


def test_custom_rejects_negative_transactions(tmp_path):
    d=_custom_dir(tmp_path); p=d/"transactions.csv"; f=pd.read_csv(p,dtype=str,keep_default_na=False); f.iloc[0,1]="-1"; f.to_csv(p,index=False)
    with pytest.raises(EconomyValidationError,match="finite and non-negative"):
        Economy.from_directory(d)


def test_custom_rejects_duplicate_sector_labels(tmp_path):
    d=_custom_dir(tmp_path); pd.DataFrame({"code":["01","02"],"label":["Same","Same"]}).to_csv(d/"sectors.csv",index=False)
    with pytest.raises(EconomyValidationError,match="labels must be unique"):
        Economy.from_directory(d)


def test_custom_total_output_strictly_positive(tmp_path):
    d=_custom_dir(tmp_path); pd.DataFrame({"sector":["01","02"],"total_output":[10,0]}).to_csv(d/"total_output.csv",index=False)
    with pytest.raises(EconomyValidationError,match="strictly positive"):
        Economy.from_directory(d)


def test_legacy_builtin_adapter_is_builtin_parity():
    legacy=Economy.from_legacy_inputs("io16"); built=Economy.builtin("io16")
    pd.testing.assert_frame_equal(legacy.Z_raw,built.Z_raw,check_exact=True)
    pd.testing.assert_series_equal(legacy.x,built.x,check_exact=True)
    pd.testing.assert_frame_equal(legacy.A_raw,built.A_raw,check_exact=True)


def test_legacy_explicit_a_override_accepts_square_override(tmp_path):
    base=Economy.builtin("io16"); a=base.A_raw.copy(); a.iloc[0,1]=0.777
    p=tmp_path/"a.csv"; a.rename_axis("sector").to_csv(p)
    legacy=Economy.from_legacy_inputs("io16",technical_coefficients_path=p)
    assert legacy.A_raw.iloc[0,1] == pytest.approx(.777)
    pd.testing.assert_series_equal(legacy.x,base.x,check_exact=True)


def _write_presentation_workbook(path):
    n=16; codes=[f"{i:02d}" for i in range(1,n+1)]
    z=np.arange(1,n*n+1,dtype=float).reshape(n,n); x=z.sum(axis=0)+np.arange(1000.0,1000.0+n)
    raw=pd.DataFrame(np.nan,index=range(n+4),columns=range(2+n+4),dtype=object)
    raw.iloc[0,2:2+n]=codes; raw.iloc[1,1]="Description"; raw.iloc[1,2:2+n]=[f"Sector {c}" for c in codes]; toc=2+n+3; raw.iloc[1,toc]="Total Output"
    for row,code in enumerate(codes,start=2):
        raw.iloc[row,0]=code; raw.iloc[row,1]=f"Sector {code}"; raw.iloc[row,2:2+n]=z[row-2]; raw.iloc[row,toc]=x[row-2]
    raw.to_excel(path,index=False,header=False); return z,x


def test_legacy_transaction_workbook_derives_same_a(tmp_path):
    p=tmp_path/"full.xlsx"; z,x=_write_presentation_workbook(p)
    e=Economy.from_legacy_inputs("io16",transactions_override_path=p)
    np.testing.assert_allclose(e.Z_raw.to_numpy(),z)
    np.testing.assert_allclose(e.x.to_numpy(),x)
    np.testing.assert_allclose(e.A_raw.to_numpy(),z/x[None,:])



def test_custom_sector_codes_are_preserved_not_legacy_normalized(tmp_path):
    d=tmp_path/"plain-codes"; d.mkdir()
    pd.DataFrame({"code":["1","2"],"label":["One","Two"]}).to_csv(d/"sectors.csv",index=False)
    pd.DataFrame([[1.0,2.0],[3.0,4.0]],index=["1","2"],columns=["1","2"]).rename_axis("sector").to_csv(d/"transactions.csv")
    pd.DataFrame({"sector":["1","2"],"total_output":[10.0,20.0]}).to_csv(d/"total_output.csv",index=False)
    (d/"economy.yml").write_text("id: plain-codes\n",encoding="utf-8")
    e=Economy.from_directory(d)
    assert e.sectors.codes == ("1","2")
    assert list(e.Z_raw.index) == ["1","2"]

def test_normalize_sector_id_retained():
    assert normalize_sector_id("1.0")=="01"
    assert normalize_sector_id("12345678901234567890.0")=="12345678901234567890"

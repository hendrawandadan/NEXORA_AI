import pandas as pd
import pytest
from nexora_datahub.loader import discover_datasets,normalize_timeframe,load_bars
from nexora_datahub.audit import audit_file
@pytest.mark.parametrize("token,expected",[("M1","M1"),("M2","M2"),("M3","M3"),("M4","M4"),("M5","M5"),("M6","M6"),("M10","M10"),("M12","M12"),("M15","M15"),("M20","M20"),("M30","M30"),("H1","H1"),("H2","H2"),("H3","H3"),("H4","H4"),("H6","H6"),("H8","H8"),("H12","H12"),("D1","D1"),("W1","W1"),("MN1","MN1"),("Daily","D1"),("Weekly","W1"),("Monthly","MN1")])
def test_tokens(token,expected): assert normalize_timeframe(token)==expected
def write_csv(path,dates):
 pd.DataFrame({"<DATE>":[d.strftime("%Y.%m.%d") for d in dates],"<TIME>":[d.strftime("%H:%M:%S") for d in dates],"<OPEN>":[1.]*len(dates),"<HIGH>":[1.2]*len(dates),"<LOW>":[.8]*len(dates),"<CLOSE>":[1.1]*len(dates),"<TICKVOL>":[10]*len(dates)}).to_csv(path,index=False,sep="\t")
@pytest.mark.parametrize("token,dates",[("M5",pd.date_range("2024-01-01",periods=6,freq="5min")),("H2",pd.date_range("2024-01-01",periods=6,freq="2h")),("Daily",pd.date_range("2024-01-01",periods=6,freq="D")),("Weekly",pd.date_range("2024-01-07",periods=6,freq="7D")),("Monthly",pd.date_range("2024-01-01",periods=6,freq="MS"))])
def test_nested_timestamped_exports(tmp_path,token,dates):
 f=tmp_path/"EURUSD"/"nested"/f"EURUSD_{token}_202001020000_202611062155.csv"; f.parent.mkdir(parents=True); write_csv(f,dates)
 found=discover_datasets(tmp_path); assert len(found)==1 and found[0]["symbol"]=="EURUSD" and found[0]["timeframe"]==normalize_timeframe(token)
 assert len(load_bars(f))==6; r=audit_file(f,tmp_path/"reports"/"audit",found[0]["timeframe"]); assert r["schema_valid"] and r["interval_check"]["status"]=="PASS"
def test_wrong_interval_is_reported(tmp_path):
 f=tmp_path/"EURUSD_M5_202001020000_202611062155.csv"; write_csv(f,pd.date_range("2024-01-01",periods=6,freq="1min")); r=audit_file(f,tmp_path/"audit","M5"); assert r["status"]=="REVIEW" and r["interval_check"]["status"]=="MISMATCH"
def test_daily_labels_are_unambiguous():
 assert [normalize_timeframe(x) for x in ("Daily","Weekly","Monthly")]==["D1","W1","MN1"]
 assert normalize_timeframe("H1Daily") is None

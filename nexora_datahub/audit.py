import json
from pathlib import Path
import pandas as pd
from .loader import parse_time,read_export_csv,timeframe_minutes
def audit_file(path,out_dir,timeframe):
 if isinstance(timeframe,(int,float)):
  n=int(timeframe); timeframe={43200:"MN1",10080:"W1",1440:"D1",720:"H12",480:"H8",360:"H6",240:"H4",180:"H3",120:"H2",60:"H1"}.get(n,f"M{n}")
 raw=read_export_csv(path)
 if "time" not in raw: raise ValueError("Missing time column")
 ts=parse_time(raw.time); valid=raw.loc[ts.notna()].copy(); valid["ts"]=ts[ts.notna()].values
 duplicates=int(valid.duplicated("ts").sum()); valid=valid.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
 for c in ["open","high","low","close"]:
  if c not in valid: raise ValueError(f"Missing {c}")
  valid[c]=pd.to_numeric(valid[c],errors="coerce")
 q=valid[["open","high","low","close"]]; missing=int(q.isna().any(axis=1).sum()); nonpositive=int((q<=0).any(axis=1).sum())
 invalid=int(((valid.high<valid[["open","close","low"]].max(axis=1))|(valid.low>valid[["open","close","high"]].min(axis=1))).sum())
 expected=timeframe_minutes(timeframe); delta=valid.ts.diff().dropna(); delta=delta[delta>pd.Timedelta(0)]; seconds=delta.dt.total_seconds()
 common=seconds[seconds<=expected*180].mode(); observed=float(common.iloc[0]/60) if len(common) else (float(seconds.median()/60) if len(seconds) else None)
 interval="INSUFFICIENT_INTERVALS" if observed is None else "PASS" if abs(observed-expected)<=max(0.001,expected*.002) or (timeframe=="MN1" and 27*1440<=observed<=32*1440) else "MISMATCH"
 gaps=[]; dd=valid.ts.diff()
 for i in dd[dd>pd.Timedelta(minutes=expected*1.5)].index: gaps.append({"from":str(valid.ts.iloc[i-1]),"to":str(valid.ts.iloc[i]),"minutes":dd.iloc[i].total_seconds()/60})
 spread=None
 if "spread" in valid:
  s=pd.to_numeric(valid.spread,errors="coerce").dropna()
  if len(s): spread={"count":int(len(s)),"median_points":float(s.median()),"p95_points":float(s.quantile(.95)),"max_points":float(s.max())}
 schema=not ts.isna().any() and not missing
 report={"file":str(path),"timeframe":timeframe,"schema_columns":list(raw.columns),"schema_valid":schema,"rows_input":len(raw),"rows_valid_unique":len(valid),"invalid_timestamps":int(ts.isna().sum()),"duplicates":duplicates,"missing_ohlc":missing,"nonpositive_prices":nonpositive,"invalid_ohlc":invalid,"interval_check":{"expected_minutes":expected,"observed_minutes":observed,"status":interval},"gap_count":len(gaps),"first_bar":str(valid.ts.min()) if len(valid) else None,"last_bar":str(valid.ts.max()) if len(valid) else None,"spread_points":spread,"gap_examples":gaps[:300],"status":"REVIEW" if not schema or nonpositive or invalid or interval=="MISMATCH" else "BASIC_CHECKS_PASS","note":"Gap perlu ditafsirkan sesuai sesi dan kalender instrumen; audit tidak membuktikan histori lengkap."}
 od=Path(out_dir); od.mkdir(parents=True,exist_ok=True); (od/(Path(path).stem+".json")).write_text(json.dumps(report,indent=2),encoding="utf-8")
 norm=valid.copy(); norm["time"]=norm.ts.dt.strftime("%Y.%m.%d %H:%M"); norm.drop(columns="ts",inplace=True); dest=od.parent.parent/"data"/"processed"; dest.mkdir(parents=True,exist_ok=True); norm.to_csv(dest/(Path(path).stem+"_normalized.csv"),index=False)
 return report

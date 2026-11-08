from pathlib import Path
import re
import pandas as pd
TIME_FORMATS=("%Y.%m.%d %H:%M","%Y.%m.%d %H:%M:%S")
_NAME=re.compile(r"^(?P<symbol>.+)_(?P<tf>MN1|M\d+|H\d+|D1|W1|Daily|Weekly|Monthly)(?:_\d{12}_\d{12})?$",re.I)
_ALIAS={"DAILY":"D1","WEEKLY":"W1","MONTHLY":"MN1"}
def normalize_timeframe(token):
 t=token.strip().upper(); t=_ALIAS.get(t,t)
 return t if t=="MN1" or re.fullmatch(r"[MHDW]\d+",t) else None
def timeframe_minutes(tf):
 tf=normalize_timeframe(tf)
 if not tf: raise ValueError(f"Unsupported timeframe: {tf}")
 if tf=="MN1": return 43200
 if tf.startswith("M"): return int(tf[1:])
 if tf.startswith("H"): return int(tf[1:])*60
 return {"D1":1440,"W1":10080,"MN1":43200}[tf]
def parse_time(s):
 x=s.astype(str).str.strip(); y=pd.to_datetime(x,format=TIME_FORMATS[0],errors="coerce")
 m=y.isna()
 if m.any(): y.loc[m]=pd.to_datetime(x.loc[m],format=TIME_FORMATS[1],errors="coerce")
 m=y.isna()
 if m.any(): y.loc[m]=pd.to_datetime(x.loc[m],errors="coerce")
 return y
def read_export_csv(path):
 with open(path,"r",encoding="utf-8-sig",errors="replace") as fh: sample=fh.read(4096)
 line=next((x for x in sample.splitlines() if x.strip()),"")
 sep=max(["\t",",",";"],key=line.count)
 d=pd.read_csv(path,sep=sep,encoding="utf-8-sig")
 d.columns=[str(c).strip().strip("<>").strip().lower() for c in d.columns]
 if "date" in d and "time" in d:
  d["time"]=d["date"].astype(str).str.strip()+" "+d["time"].astype(str).str.strip(); d.drop(columns=["date"],inplace=True)
 for a,b in {"datetime":"time","date":"time","tick_volume":"volume","tickvol":"volume","vol":"volume"}.items():
  if a in d and b not in d: d.rename(columns={a:b},inplace=True)
 return d
def load_bars(path):
 d=read_export_csv(path); req=["time","open","high","low","close"]; miss=[x for x in req if x not in d]
 if miss: raise ValueError(f"Kolom wajib hilang {miss}: {path}")
 d["ts"]=parse_time(d.time)
 if d.ts.isna().any(): raise ValueError(f"Timestamp invalid: {path}")
 for c in ["open","high","low","close","volume","real_volume","spread"]:
  if c in d: d[c]=pd.to_numeric(d[c],errors="coerce")
 if "volume" not in d: d["volume"]=0.0
 d=d.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
 if d[["open","high","low","close"]].isna().any().any(): raise ValueError(f"OHLC NaN: {path}")
 return d
def discover_datasets(raw_dir):
 found=[]
 for p in Path(raw_dir).rglob("*.csv"):
  m=_NAME.fullmatch(p.stem)
  if m:
   tf=normalize_timeframe(m.group("tf"))
   if tf: found.append({"path":p,"symbol":m.group("symbol"),"timeframe":tf})
 return sorted(found,key=lambda x:(x["timeframe"],x["symbol"].casefold(),str(x["path"]).casefold()))


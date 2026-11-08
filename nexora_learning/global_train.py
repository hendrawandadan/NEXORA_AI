import json,joblib
import numpy as np,pandas as pd
from pathlib import Path
from nexora_core.config import ROOT,load_config
from nexora_datahub.loader import load_bars,timeframe_minutes
from nexora_vision.features import build_features
from nexora_intelligence.model import create_model
from nexora_evaluator.metrics import metrics

def train_global_group(group,tf,horizon,engine="auto",max_iter=300,seed=42):
    blocks=[]
    for ds in group:
        df=load_bars(ds["path"]); X=build_features(df)
        X["symbol_code"]=pd.Categorical([ds["symbol"]]*len(X),categories=sorted(x["symbol"] for x in group)).codes.astype(float)
        c=df.close.to_numpy(); fwd=np.full(len(df),np.nan); fwd[:-horizon]=c[horizon:]/c[:-horizon]-1
        y=(fwd>0).astype(int); mask=X.notna().all(axis=1).to_numpy() & np.isfinite(fwd)
        part=X.loc[mask].copy(); part["target"]=y[mask]; part["ts"]=df.ts[mask].values; part["symbol"]=ds["symbol"]
        blocks.append(part)
    all_df=pd.concat(blocks,ignore_index=True).sort_values("ts").reset_index(drop=True)
    unique_ts=np.sort(all_df.ts.unique()); n=len(unique_ts)
    cut1=unique_ts[int(n*.60)]; cut2=unique_ts[int(n*.80)]
    tr=all_df.ts<cut1
    va=(all_df.ts>=cut1+np.timedelta64(horizon*(timeframe_minutes(tf)),"m")) & (all_df.ts<cut2)
    te=all_df.ts>=cut2+np.timedelta64(horizon*(timeframe_minutes(tf)),"m")
    features=[c for c in all_df.columns if c not in ["target","ts","symbol"]]
    if min(int(tr.sum()),int(va.sum()),int(te.sum()))<300: raise ValueError("Insufficient pooled rows after time split")
    if all_df.loc[tr,"target"].nunique()<2: raise ValueError("Global train only one class")
    model,actual=create_model(engine,seed,max_iter); model.fit(all_df.loc[tr,features],all_df.loc[tr,"target"])
    pv=model.predict_proba(all_df.loc[va,features])[:,1]; pt=model.predict_proba(all_df.loc[te,features])[:,1]
    vm=metrics(all_df.loc[va,"target"].to_numpy(),pv); tm=metrics(all_df.loc[te,"target"].to_numpy(),pt)
    out=ROOT/"models"/"global"/tf/f"h{horizon}"; out.mkdir(parents=True,exist_ok=True)
    symbols=sorted(x["symbol"] for x in group)
    joblib.dump({"model":model,"features":features,"symbols":symbols,"timeframe":tf,"horizon":horizon,"engine":actual},out/"model.joblib")
    report={"kind":"global","timeframe":tf,"horizon_bars":horizon,"symbols":symbols,"engine":actual,
      "train_rows":int(tr.sum()),"validation_rows":int(va.sum()),"test_rows":int(te.sum()),
      "validation_metrics":vm,"test_metrics":tm,
      "warning":"Pooled global directional metrics; not a cost-aware portfolio backtest."}
    rd=ROOT/"reports"/"global"/tf/f"h{horizon}"; rd.mkdir(parents=True,exist_ok=True)
    (rd/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report

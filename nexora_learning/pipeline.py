from pathlib import Path
import json, joblib
import numpy as np
import pandas as pd
from nexora_datahub.loader import load_bars
from nexora_vision.features import build_features
from nexora_intelligence.model import create_model
from nexora_evaluator.metrics import metrics
from nexora_core.config import ROOT,load_config
from nexora_learning.targets import (
    TARGET_T1,TARGET_T3,VALID_TARGET_TYPES,
    get_target_spec,compute_target,build_target_mask,
)

def prepare(path,horizon,symbol,global_mode=False,target_type=TARGET_T1):
    """Build features and a single target.

    ``target_type`` is T1 (default; backward-compatible close->close) or T3
    (execution-aligned open[t+1] -> open[t+h+1]). Returns the same 5-tuple
    ``(df, X, y, fwd, mask)`` as before; only ``fwd``/``y``/``mask`` differ by
    target. The two targets never share a mutable vector.
    """
    tt=str(target_type).strip().upper()
    if tt not in VALID_TARGET_TYPES:
        raise ValueError(f"Unknown target_type: {target_type!r}")
    df=load_bars(path); X=build_features(df)
    if global_mode:
        # Explicit symbol identity for pooled model. Features remain ATR/return normalized.
        X["symbol_code"]=pd.Categorical([symbol]*len(X)).codes.astype(float)
    fwd,y=compute_target(df,horizon,tt)
    mask=build_target_mask(X,fwd,tt,horizon)
    return df,X,y,fwd,mask

def effective_horizon(horizon,target_type=TARGET_T1):
    """Target-specific information horizon used for purge/embargo (T1: h, T3: h+1)."""
    return get_target_spec(target_type,horizon).effective_horizon

def purge_bars(horizon,target_type=TARGET_T1,embargo_bars=24):
    """Conservative purge = max(effective_horizon, embargo_bars).

    T1 -> max(h, 24); T3 -> max(h+1, 24). Never reuse max(h,24) for T3.
    """
    return max(int(effective_horizon(horizon,target_type)),int(embargo_bars))

def split_indices(mask,horizon,train_frac=.6,valid_frac=.2,embargo=None,target_type=TARGET_T1):
    """Chronological holdout with a target-aware embargo.

    ``embargo`` defaults to the target's effective horizon; the applied gap is
    ``max(embargo, effective_horizon)`` so it can never be smaller than the
    label horizon (T1: h, T3: h+1).
    """
    eff=effective_horizon(horizon,target_type)
    if embargo is None: embargo=eff
    embargo=max(int(embargo),int(eff))
    idx=np.flatnonzero(mask); n=len(idx)
    a=int(n*train_frac); b=int(n*valid_frac)
    va_start=a+embargo
    va_end=va_start+b
    tr=idx[:a]; va=idx[va_start:va_end]; te=idx[va_end+embargo:]
    if min(len(tr),len(va),len(te))<100: raise ValueError("Insufficient rows after split/embargo")
    return tr,va,te

def walk_forward_scores(X,y,mask,horizon,engine,seed,max_iter,folds=3,purge=None,target_type=TARGET_T1):
    idx=np.flatnonzero(mask); n=len(idx); results=[]
    # Expanding-window folds; all splits chronological and purged.
    # purge=None preserves legacy behaviour but never goes below the target's
    # effective horizon. Callers pass purge=max(effective_horizon, embargo_bars).
    eff=effective_horizon(horizon,target_type)
    purge = eff if purge is None else max(int(purge), int(eff))
    initial=max(int(n*.50),1000)
    remaining=n-initial
    if remaining < folds*100: return results
    chunk=remaining//folds
    for k in range(folds):
        train_end=initial+k*chunk
        test_start=min(train_end+purge,n)
        test_end=n if k==folds-1 else min(test_start+chunk,n)
        tr=idx[:train_end]; te=idx[test_start:test_end]
        if len(te)<100 or len(np.unique(y[tr]))<2: continue
        model,eng=create_model(engine,seed,max_iter); model.fit(X.iloc[tr],y[tr])
        p=model.predict_proba(X.iloc[te])[:,1]
        m=metrics(y[te],p); m["fold"]=k+1; m["engine"]=eng
        results.append(m)
    return results

def target_artifact_root(target_type):
    """Namespaced artifact root component: 'T1'/'T3' -> 't1'/'t3'."""
    return str(target_type).strip().upper().lower()

def train_one(path,symbol,tf,horizon,kind="individual",engine="auto",max_iter=300,seed=42,margin=.03,target_type=TARGET_T1):
    """Train a single model for one (symbol,tf,horizon,target_type).

    Default ``target_type=T1`` reproduces the legacy behaviour. Artifacts and
    reports are namespaced by target type so T1 and T3 never overwrite each
    other. For T3 the realized-return column reflects the open->open execution
    return and is explicitly flagged gross.
    """
    tt=str(target_type).strip().upper()
    if tt not in VALID_TARGET_TYPES:
        raise ValueError(f"Unknown target_type: {target_type!r}")
    spec=get_target_spec(tt,horizon); eff=spec.effective_horizon
    df,X,y,fwd,mask=prepare(path,horizon,symbol,global_mode=(kind=="global"),target_type=tt)
    cfg=load_config()["training"]
    embargo=purge_bars(horizon,tt,cfg["embargo_bars"])
    tr,va,te=split_indices(mask,horizon,cfg["train_fraction"],cfg["validation_fraction"],embargo,target_type=tt)
    if len(np.unique(y[tr]))<2 or len(np.unique(y[va]))<2: raise ValueError("Train/validation hanya satu kelas")
    model,actual_engine=create_model(engine,seed,max_iter)
    model.fit(X.iloc[tr],y[tr])
    pv=model.predict_proba(X.iloc[va])[:,1]; pt=model.predict_proba(X.iloc[te])[:,1]
    vm=metrics(y[va],pv); tm=metrics(y[te],pt)
    wf_cfg=load_config().get("walk_forward",{})
    # Walk-forward purge = max(effective_horizon, embargo_bars); T3 uses h+1.
    wf_purge=purge_bars(horizon,tt,cfg.get("embargo_bars",eff))
    wf=walk_forward_scores(X,y,mask,horizon,engine,seed,max_iter,folds=wf_cfg.get("folds",cfg.get("walk_forward_folds",3)),purge=wf_purge,target_type=tt)
    ns=target_artifact_root(tt)
    base=Path("models")/ns/("individual" if kind=="individual" else "global")/symbol/tf/f"h{horizon}"
    if kind=="global": base=Path("models")/ns/"global"/tf/f"h{horizon}"
    model_dir=ROOT/base; model_dir.mkdir(parents=True,exist_ok=True)
    tver=spec.target_definition_version(horizon)
    joblib.dump({"model":model,"features":list(X.columns),"symbol":symbol,"timeframe":tf,
      "horizon":horizon,"engine":actual_engine,"kind":kind,
      "target_type":tt,"target_definition_version":tver["id"],"target_hash":tver["hash"],
      "effective_horizon":eff},model_dir/"model.joblib")
    sigdir=ROOT/"signals"/ns/symbol/tf/f"h{horizon}"; sigdir.mkdir(parents=True,exist_ok=True)
    direction=np.where(pt>=.5+margin,1,np.where(pt<=.5-margin,-1,0))
    pd.DataFrame({"time":df.ts.iloc[te].dt.strftime("%Y.%m.%d %H:%M").values,
      "prob_up":pt,"direction":direction,"realized_forward_return":fwd[te]}).to_csv(sigdir/f"{kind}_signals.csv",index=False)
    report={"kind":kind,"symbol":symbol,"timeframe":tf,"horizon_bars":horizon,"engine":actual_engine,
      "target_type":tt,"target_formula":spec.formula,"target_definition_version":tver["id"],
      "target_hash":tver["hash"],"effective_horizon":eff,
      "rows":len(df),"train_rows":len(tr),"validation_rows":len(va),"test_rows":len(te),
      "train_start":str(df.ts.iloc[tr[0]]),"test_start":str(df.ts.iloc[te[0]]),
      "validation_metrics":vm,"test_metrics":tm,"walk_forward":wf,
      "warning":"Directional ML evaluation, not a cost-aware execution backtest."}
    if tt==TARGET_T3:
        report["realized_return_field"]="realized_forward_return"
        report["realized_return_is_gross"]=True
    repdir=ROOT/"reports"/ns/kind/symbol/tf/f"h{horizon}"; repdir.mkdir(parents=True,exist_ok=True)
    (repdir/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report

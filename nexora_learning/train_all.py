import argparse,json,traceback
from pathlib import Path
import pandas as pd
from nexora_core.config import ROOT,load_config,ensure_dirs
from nexora_datahub.loader import discover_datasets
from nexora_datahub.audit import audit_file
from nexora_learning.pipeline import train_one

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--raw-dir",default=str(ROOT/"data"/"raw"))
    p.add_argument("--min-bars",type=int,default=5000)
    p.add_argument("--max-iter",type=int,default=300)
    p.add_argument("--horizons",default=None,help="Comma-separated bar horizons; default from config")
    p.add_argument("--engine",choices=["auto","lightgbm","sklearn"],default="auto")
    a=p.parse_args(); ensure_dirs(); cfg=load_config()
    horizons=[int(x) for x in a.horizons.split(",")] if a.horizons else cfg["training"]["horizons"]
    datasets=discover_datasets(a.raw_dir)
    if not datasets: raise SystemExit(f"Tidak ada CSV <SYMBOL>_<TF>.csv di {a.raw_dir}")
    audit_rows=[]; individual=[]; global_rows=[]; failures=[]
    # Audit each dataset, retain only basic-valid datasets with enough bars.
    usable=[]
    for ds in datasets:
        try:
            audit=audit_file(ds["path"],ROOT/"reports"/"audit",ds["timeframe"])
            audit_rows.append({**ds,"rows":audit["rows_valid_unique"],"status":audit["status"],"gaps":audit["gap_count"]})
            if audit["rows_valid_unique"]>=a.min_bars and audit["status"]!="REVIEW":
                usable.append(ds)
            else: failures.append({"dataset":str(ds["path"]),"stage":"audit/min_bars","error":"Review status or insufficient rows"})
        except Exception as e:
            failures.append({"dataset":str(ds["path"]),"stage":"audit","error":str(e)})
    # Individual model per symbol/timeframe/horizon.
    for ds in usable:
        for h in horizons:
            try:
                r=train_one(ds["path"],ds["symbol"],ds["timeframe"],h,"individual",a.engine,a.max_iter,cfg["training"]["seed"])
                individual.append(r)
            except Exception as e:
                failures.append({"dataset":str(ds["path"]),"stage":f"individual_h{h}","error":str(e)})
    # Global pooled model per timeframe/horizon. Concatenate each symbol's feature rows;
    # use timestamp split after pooling to prevent same timestamp leaking across symbols.
    # Here train_one is intentionally not reused: it accepts a single dataset. Global pooled
    # training is handled by global_train.py and called below.
    from nexora_learning.global_train import train_global_group
    for tf in sorted(set(x["timeframe"] for x in usable)):
        group=[x for x in usable if x["timeframe"]==tf]
        if len(group)<2: 
            failures.append({"dataset":tf,"stage":"global","error":"Global model skipped: need at least two symbols with usable data"})
            continue
        for h in horizons:
            try:
                r=train_global_group(group,tf,h,a.engine,a.max_iter,cfg["training"]["seed"])
                global_rows.append(r)
            except Exception as e:
                failures.append({"dataset":tf,"stage":f"global_h{h}","error":str(e)})
    # Write summaries and comparison.
    rep=ROOT/"reports"; rep.mkdir(exist_ok=True)
    pd.DataFrame(audit_rows).to_csv(rep/"data_audit.csv",index=False)
    pd.DataFrame([{k:r.get("test_metrics",{}).get(k) for k in ["auc","accuracy","balanced_accuracy","brier","log_loss"]} | {
        "symbol":r["symbol"],"timeframe":r["timeframe"],"horizon":r["horizon_bars"],"engine":r["engine"],"kind":"individual",
        "test_rows":r["test_rows"],"walk_forward_folds":len(r["walk_forward"])} for r in individual]).to_csv(rep/"individual_results.csv",index=False)
    pd.DataFrame([{**r["test_metrics"],"timeframe":r["timeframe"],"horizon":r["horizon_bars"],"engine":r["engine"],"kind":"global","symbols":r["symbols"]} for r in global_rows]).to_csv(rep/"global_results.csv",index=False)
    comp=[]
    for r in individual:
        comp.append({"kind":"individual","symbol":r["symbol"],"timeframe":r["timeframe"],"horizon":r["horizon_bars"],**r["test_metrics"]})
    for r in global_rows:
        comp.append({"kind":"global","symbol":"POOLED","timeframe":r["timeframe"],"horizon":r["horizon_bars"],**r["test_metrics"]})
    pd.DataFrame(comp).to_csv(rep/"model_comparison.csv",index=False)
    (rep/"run_summary.json").write_text(json.dumps({"datasets_found":len(datasets),"datasets_usable":len(usable),
      "individual_runs":len(individual),"global_runs":len(global_rows),"failures":failures},indent=2),encoding="utf-8")
    print(f"Dataset found={len(datasets)} usable={len(usable)} individual={len(individual)} global={len(global_rows)} failures={len(failures)}")
    print("Reports:",rep)
if __name__=="__main__": main()

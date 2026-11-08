import json
import pandas as pd
from nexora_core.config import ROOT,ensure_dirs
from nexora_datahub.loader import discover_datasets
from nexora_datahub.audit import audit_file
def main():
 ensure_dirs(); rows=[]; dslist=discover_datasets(ROOT/"data"/"raw")
 for ds in dslist:
  try:
   r=audit_file(ds["path"],ROOT/"reports"/"audit",ds["timeframe"]); r["symbol"]=ds["symbol"]
   (ROOT/"reports"/"audit"/(ds["path"].stem+".json")).write_text(json.dumps(r,indent=2),encoding="utf-8")
   rows.append({"symbol":ds["symbol"],"timeframe":ds["timeframe"],"rows":r["rows_valid_unique"],"status":r["status"],"interval_status":r["interval_check"]["status"],"expected_minutes":r["interval_check"]["expected_minutes"],"observed_minutes":r["interval_check"]["observed_minutes"],"gaps":r["gap_count"],"file":str(ds["path"])})
  except Exception as e: rows.append({"symbol":ds["symbol"],"timeframe":ds["timeframe"],"status":"ERROR","error":str(e),"file":str(ds["path"])})
 out=ROOT/"reports"; frame=pd.DataFrame(rows); frame.to_csv(out/"data_audit.csv",index=False)
 inventory={"datasets_detected":len(dslist),"symbols":sorted({d["symbol"] for d in dslist}),"timeframes":sorted({d["timeframe"] for d in dslist}),"dataset_count_by_timeframe":frame.groupby("timeframe").size().to_dict() if len(frame) else {},"status_counts":frame.status.value_counts().to_dict() if len(frame) else {},"report_csv":str(out/"data_audit.csv")}
 (out/"data_inventory.json").write_text(json.dumps(inventory,indent=2),encoding="utf-8"); print(frame.to_string(index=False) if len(frame) else "Tidak ada dataset ditemukan."); print("Inventory:",inventory)
if __name__=="__main__": main()

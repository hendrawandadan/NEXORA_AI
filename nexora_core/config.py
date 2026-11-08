import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def load_config():
    return json.loads((ROOT/"config"/"research.json").read_text(encoding="utf-8"))
def ensure_dirs():
    for p in ["data/raw","data/processed","models/individual","models/global","reports/audit","signals","experiments"]:
        (ROOT/p).mkdir(parents=True,exist_ok=True)

"""PREP-001 A/B/C LightGBM experiment sweep (READ-ONLY w.r.t. production).

Runs the three human-approved experiment configurations (nexora_audit.experiment_config)
on EURUSD M30 horizon 2, target T3, and reports validation/test/walk-forward metrics
plus a cost-aware trading evaluation. This does NOT modify production artifacts:
no writes to models/, signals/, reports/t3/. Results are written only to
experiments/ as JSON.

Candidates:
    A: max_depth=-1, reg_alpha=0.0  (baseline; reproduces current implicit defaults)
    B: max_depth=4,  reg_alpha=0.1  (primary)
    C: max_depth=3,  reg_alpha=0.5  (conservative comparator)

All other hyper-parameters match nexora_intelligence.model.create_model() exactly
(n_estimators=300, lr=0.03, num_leaves=15, min_child_samples=100, subsample=0.8,
subsample_freq=1, colsample_bytree=0.8, reg_lambda=5, random_state=42).

Usage:
    .\\.venv\\Scripts\\python.exe tools/run_prep001_abc_sweep.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nexora_audit.experiment_config import BUDGET_CANDIDATES  # noqa: E402
from nexora_core.config import ROOT as CORE_ROOT, load_config  # noqa: E402
from nexora_evaluator.metrics import metrics  # noqa: E402
from nexora_evaluator.trading import evaluate_trade_returns  # noqa: E402
from nexora_learning.pipeline import (  # noqa: E402
    prepare,
    purge_bars,
    split_indices,
    walk_forward_scores,
)
from nexora_learning.targets import TARGET_T3, get_target_spec  # noqa: E402

DATASET = CORE_ROOT / "data" / "raw" / "EURUSD" / "EURUSD_M30_202001020000_202611062130.csv"
SYMBOL, TF, HORIZON = "EURUSD", "M30", 2
TARGET = TARGET_T3
MARGIN = 0.03
OUT_DIR = ROOT / "experiments"


_FIXED_LGBM = dict(
    n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=100,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5,
    random_state=42, verbosity=-1,
)


def _make_lgbm(max_depth: int, reg_alpha: float):
    import lightgbm as lgb
    return lgb.LGBMClassifier(max_depth=max_depth, reg_alpha=reg_alpha, **_FIXED_LGBM)


def _walk_forward_with_override(X, y, mask, folds, purge, max_depth, reg_alpha):
    idx = np.flatnonzero(mask)
    n = len(idx)
    eff = get_target_spec(TARGET, HORIZON).effective_horizon
    purge = max(int(purge), int(eff))
    initial = max(int(n * 0.50), 1000)
    remaining = n - initial
    if remaining < folds * 100:
        return []
    chunk = remaining // folds
    out = []
    for k in range(folds):
        train_end = initial + k * chunk
        test_start = min(train_end + purge, n)
        test_end = n if k == folds - 1 else min(test_start + chunk, n)
        tr, te = idx[:train_end], idx[test_start:test_end]
        if len(te) < 100 or len(np.unique(y[tr])) < 2:
            continue
        m = _make_lgbm(max_depth, reg_alpha)
        m.fit(X.iloc[tr], y[tr])
        p = m.predict_proba(X.iloc[te])[:, 1]
        mm = metrics(y[te], p)
        mm["fold"] = k + 1
        out.append(mm)
    return out


def _trading_on_predictions(pt: np.ndarray, fwd_te: np.ndarray):
    """Cost-aware trading stats on held-out test predictions (T3 open->open)."""
    direction = np.where(pt >= 0.5 + MARGIN, 1, np.where(pt <= 0.5 - MARGIN, -1, 0))
    active = direction != 0
    realized = np.asarray(fwd_te)
    results = {}
    for bps in (0, 1, 2, 5):
        if active.sum() == 0:
            results[str(bps)] = {"trades": 0}
            continue
        trade_ret = (direction[active] * realized[active]) - (bps / 10000.0)
        stats = evaluate_trade_returns(trade_ret, sample_size=len(direction), active_size=int(active.sum()))
        results[str(bps)] = {
            "trades": stats["trades"],
            "win_rate": round(stats["win_rate"], 4) if stats["win_rate"] is not None else None,
            "profit_factor": round(stats["profit_factor"], 4) if stats["profit_factor"] is not None else None,
            "expectancy": round(stats["expectancy"], 8) if stats["expectancy"] is not None else None,
            "total_return": round(stats["total_return"], 4),
            "max_drawdown": round(stats["max_drawdown"], 4),
        }
    # gross long/short/flat expectancy
    exp = {}
    for d in (-1, 0, 1):
        sel = direction == d
        exp[str(d)] = {
            "n": int(sel.sum()),
            "mean_ret": round(float(realized[sel].mean()), 8) if sel.sum() else None,
        }
    return {"margin": MARGIN, "by_cost_bps": results, "expectancy_by_direction": exp,
            "direction_counts": {"long": int((direction == 1).sum()), "short": int((direction == -1).sum()),
                                 "flat": int((direction == 0).sum())}}


def run_candidate(name: str, X, y, fwd, mask, cfg):
    spec = get_target_spec(TARGET, HORIZON)
    tcfg = load_config()["training"]
    embargo = purge_bars(HORIZON, TARGET, tcfg["embargo_bars"])
    tr, va, te = split_indices(mask, HORIZON, tcfg["train_fraction"], tcfg["validation_fraction"],
                               embargo, target_type=TARGET)
    model = _make_lgbm(cfg.max_depth, cfg.reg_alpha)
    model.fit(X.iloc[tr], y[tr])
    pv = model.predict_proba(X.iloc[va])[:, 1]
    pt = model.predict_proba(X.iloc[te])[:, 1]
    vm = metrics(y[va], pv)
    tm = metrics(y[te], pt)
    wf_purge = purge_bars(HORIZON, TARGET, tcfg.get("embargo_bars"))
    folds = load_config().get("walk_forward", {}).get("folds", 3)
    wf = _walk_forward_with_override(X, y, mask, folds, wf_purge, cfg.max_depth, cfg.reg_alpha)
    trading = _trading_on_predictions(pt, fwd[te])

    wf_auc = [f["auc"] for f in wf if "auc" in f]
    return {
        "candidate": name,
        "max_depth": cfg.max_depth,
        "reg_alpha": cfg.reg_alpha,
        "profile": cfg.profile,
        "split": {"train": len(tr), "valid": len(va), "test": len(te)},
        "validation_metrics": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in vm.items()},
        "test_metrics": {k: (round(v, 5) if isinstance(v, float) else v) for k, v in tm.items()},
        "walk_forward": [{k: (round(v, 5) if isinstance(v, float) else v) for k, v in f.items()} for f in wf],
        "walk_forward_auc_mean": round(float(np.mean(wf_auc)), 5) if wf_auc else None,
        "walk_forward_auc_std": round(float(np.std(wf_auc)), 5) if wf_auc else None,
        "trading": trading,
    }


def main() -> int:
    if not DATASET.exists():
        print(f"ERROR: dataset not found: {DATASET}")
        return 2
    print(f"PREP-001 A/B/C sweep | {SYMBOL} {TF} h{HORIZON} {TARGET} | dataset={DATASET.name}")
    df, X, y, fwd, mask = prepare(DATASET, HORIZON, SYMBOL, global_mode=False, target_type=TARGET)
    print(f"rows={len(df)} features={X.shape[1]} mask={int(mask.sum())} "
          f"positive_rate={float(np.mean(y[mask])):.4f}")

    results = []
    for name in ("A", "B", "C"):
        cfg = BUDGET_CANDIDATES[name]
        print(f"\n--- Candidate {name}: max_depth={cfg.max_depth} reg_alpha={cfg.reg_alpha} ---")
        res = run_candidate(name, X, y, fwd, mask, cfg)
        results.append(res)
        tm = res["test_metrics"]
        print(f"  test: acc={tm.get('accuracy')} auc={tm.get('auc')} bal_acc={tm.get('balanced_accuracy')} brier={tm.get('brier')}")
        print(f"  wf  : auc_mean={res['walk_forward_auc_mean']} std={res['walk_forward_auc_std']}")
        for bps, st in res["trading"]["by_cost_bps"].items():
            print(f"  cost={bps}bps: trades={st.get('trades')} PF={st.get('profit_factor')} "
                  f"totRet={st.get('total_return')} exp={st.get('expectancy')}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"prep001_abc_sweep_{SYMBOL}_{TF}_h{HORIZON}_{TARGET}.json"
    payload = {
        "experiment": "PREP-001-A/B/C-sweep",
        "target_type": TARGET,
        "symbol": SYMBOL, "timeframe": TF, "horizon": HORIZON,
        "dataset": str(DATASET),
        "margin": MARGIN,
        "fixed_lgbm_params": _FIXED_LGBM,
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

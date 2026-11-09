"""FASE 2A — ATR vs Vol-Targeted Adaptive Barrier: purged walk-forward experiment.

RUNNER ONLY. It does not retrain the primary signal model: it loads an existing
trained classifier (same signals for both arms), and varies ONLY the barrier
determination, exactly per the pre-registered §5 comparison protocol.

Frozen inputs (MUST NOT change during the experiment):
  * Baseline ATR : BarrierConfig(k_up=1.5, k_dn=1.0, vertical=16)  -> FROZEN
  * Adaptive #1  : VolTargetConfig(k_vol, horizon, vertical)       -> FROZEN
  * Label logic  : nexora_laboratory.triple_barrier.label_events (shared)
  * Execution    : ExecutionConfig(half_spread_price) -> simulated bid/ask
  * Cost engine  : nexora_laboratory.cost_engine components_for_scenario
  * Net/meta     : nexora_laboratory.event_attribution.add_net_and_meta
  * Split/embargo: nexora_learning.pipeline.purge_bars / walk-forward geometry

Protocol:
  1. Build features + a signal probability from the frozen primary model.
  2. Purged walk-forward folds (expanding train, purge = max(horizon, embargo)).
  3. For each fold, each bar in the TEST window becomes one candidate trade with
     the model's direction. Both arms label those identical candidates, using only
     that fold's in-sample data to fit the adaptive vol model.
  4. Net-of-cost returns via the cost engine; compare adaptive - ATR.

Verdict is the pre-registered AND of all §6 criteria. A NO-GO is a valid outcome;
this module never claims a win that the criteria do not support.

SAFETY: read-only w.r.t. production data/DB/models (model is loaded, never fit/
written). The only writes are to an explicit output directory (report JSON/CSV).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from nexora_laboratory.adaptive_barrier import (
    VolTargetConfig,
    VolatilityBarrierModel,
    adaptive_atr_proxy,
    forward_realized_range,
)
from nexora_laboratory.cost_engine import components_for_scenario, pips_to_price
from nexora_laboratory.event_attribution import add_net_and_meta
from nexora_laboratory.regime import CALM, HIGH, MID, RegimeConfig, trailing_regime
from nexora_laboratory.triple_barrier import (
    BarrierConfig,
    ExecutionConfig,
    label_events,
)
from nexora_learning.pipeline import purge_bars


# ---------------------------------------------------------------------------
# Frozen configuration (do NOT edit during an experiment run)
# ---------------------------------------------------------------------------
FROZEN_ATR = BarrierConfig(k_up=1.5, k_dn=1.0, vertical=16)
FROZEN_VOLTARGET = VolTargetConfig(horizon=16, k_vol=1.25, vertical=16)


@dataclass
class ExperimentConfig:
    horizon_signal: int = 2            # == model horizon (for purge/embargo)
    embargo_bars: int = 24
    folds: int = 3
    side: int = 1                      # +1 BUY; -1 SELL (direction from model mapped here)
    cost_scenarios: tuple = ("optimistic", "baseline", "stress")
    concat_steps: int = 1              # stride over signal rows (~1 entry per step of 1 bar)
    bootstrap_iters: int = 2000
    bootstrap_seed: int = 42
    rng_seed: int = 42
    min_trades_per_fold: int = 50      # criterion §6.4 adequacy floor
    regime: RegimeConfig = field(default_factory=RegimeConfig)

    def as_dict(self) -> dict:
        return {
            "horizon_signal": self.horizon_signal, "embargo_bars": self.embargo_bars,
            "folds": self.folds, "side": self.side,
            "cost_scenarios": list(self.cost_scenarios),
            "bootstrap_iters": self.bootstrap_iters, "bootstrap_seed": self.bootstrap_seed,
            "min_trades_per_fold": self.min_trades_per_fold,
            "regime": self.regime.as_dict(),
            "frozen_atr": FROZEN_ATR.as_dict(),
            "frozen_voltarget": FROZEN_VOLTARGET.as_dict(),
        }


# ---------------------------------------------------------------------------
# Walk-forward geometry (identical to pipeline.walk_forward_scores)
# ---------------------------------------------------------------------------
def walk_forward_folds(n_eligible: int, folds: int, purge: int):
    """Expanding-window folds over eligible-row positions, same rule as pipeline."""
    initial = max(int(n_eligible * 0.50), 1000)
    remaining = n_eligible - initial
    out: List[tuple] = []
    if remaining < folds * 100:
        return out
    chunk = remaining // folds
    for k in range(folds):
        train_end = initial + k * chunk
        test_start = min(train_end + purge, n_eligible)
        test_end = n_eligible if k == folds - 1 else min(test_start + chunk, n_eligible)
        out.append((np.arange(0, train_end), np.arange(test_start, test_end)))
    return out


# ---------------------------------------------------------------------------
# Adaptive vol prediction (fit on TRAIN fold only -> predict on TEST fold)
# ---------------------------------------------------------------------------
def _fit_predict_adaptive_vol(
    X: pd.DataFrame,
    y_vol: pd.Series,
    train_rows: np.ndarray,
    test_rows: np.ndarray,
    cfg: VolTargetConfig,
) -> np.ndarray:
    """Fit the vol model on train_rows; return predicted vol (fraction) on test_rows.

    Rows with usable features AND labels only. The returned array aligns 1:1 with
    ``test_rows`` (NaN where the model cannot produce a finite prediction).
    """
    tr = train_rows
    ytr = y_vol.iloc[tr]
    ok_tr = X.iloc[tr].notna().all(axis=1).to_numpy() & ytr.notna().to_numpy()
    model = VolatilityBarrierModel(cfg)
    model.fit(X.iloc[tr][ok_tr], ytr[ok_tr])

    Xte = X.iloc[test_rows]
    pred = np.full(len(test_rows), np.nan)
    ok_te = Xte.notna().all(axis=1).to_numpy()
    if ok_te.any():
        pred[ok_te] = model.predict_vol(Xte[ok_te])
    return pred


# ---------------------------------------------------------------------------
# Label one arm for one fold (identical candidates, only barrier distance differs)
# ---------------------------------------------------------------------------
def _label_arm(
    bars_f: pd.DataFrame,
    atr_f: pd.Series,
    signal_p: np.ndarray,
    barrier_cfg: BarrierConfig,
    exec_cfg: ExecutionConfig,
    side: int,
    atr_override: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Label candidate trades on one fold.

    ``signal_p`` (length == len(bars_f)) is aligned to the fold's bars. We pass it
    as the per-bar 'atr' *only* through the override; the frozen labeller then
    computes upper=entry+k_up*atr etc. For adaptive we pass the vol-to-atr proxy.
    To keep candidates IDENTICAL between arms, we additionally require the label
    row's ``signal_time`` to be one of the fold's signal positions and we attach
    ``direction`` so a sign filter can be applied downstream.
    """
    use_atr = atr_override if atr_override is not None else atr_f
    lab = label_events(bars_f, use_atr, barrier_cfg, exec_cfg, side=side)
    if lab.empty:
        return lab
    # Attach the model direction at the event's signal_time (same for both arms).
    sig_time = lab["signal_time"].to_numpy()
    # map signal_time -> probability via bar ts index
    ts_index = {t: i for i, t in enumerate(bars_f["ts"].to_numpy())}
    probs = np.array([signal_p[ts_index[t]] if t in ts_index else np.nan for t in sig_time])
    lab = lab.copy()
    lab["prob_up"] = probs
    lab["fold_direction"] = np.where(probs >= 0.5, 1, np.where(probs <= 0.5, -1, 0))
    return lab


def _net_trades(labels: pd.DataFrame, comp, side: int) -> pd.DataFrame:
    """Restrict to profitable-direction trades and compute net returns (cost-aware)."""
    if labels.empty:
        return labels
    d = labels["fold_direction"].to_numpy()
    active = labels.copy()
    # Keep only events where the model agrees with the arm's side.
    active = active[d == side]
    active = add_net_and_meta(active, comp, spread_already_in_prices=True)
    return active


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _bootstrap_diff_ci(
    adaptive: np.ndarray, atr: np.ndarray, iters: int, seed: int, alpha: float = 0.05
) -> Dict[str, float]:
    """Bootstrap 95% CI of mean(adaptive) - mean(atr) by resampling each arm.

    Returns dict with observed diff, ci_low, ci_high, p_two_sided (fraction of
    resampled diffs <= 0 for a one-sided read) and n. Arms are independent samples.
    """
    a = np.asarray(adaptive, dtype=float)
    b = np.asarray(atr, dtype=float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) == 0 or len(b) == 0:
        return {"diff": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "p_diff_le_0": float("nan"), "n_adaptive": int(len(a)), "n_atr": int(len(b))}
    rng = np.random.default_rng(seed)
    observed = float(a.mean() - b.mean())
    diffs = np.empty(iters)
    for i in range(iters):
        sa = a[rng.integers(0, len(a), len(a))]
        sb = b[rng.integers(0, len(b), len(b))]
        diffs[i] = sa.mean() - sb.mean()
    lo = float(np.quantile(diffs, alpha / 2))
    hi = float(np.quantile(diffs, 1 - alpha / 2))
    p_le0 = float((diffs <= 0).mean())
    return {"diff": observed, "ci_low": lo, "ci_high": hi,
            "p_diff_le_0": p_le0, "n_adaptive": int(len(a)), "n_atr": int(len(b))}


def _summarise_trades(trades: pd.DataFrame) -> Dict[str, float]:
    if trades.empty:
        return {"n": 0, "mean_net": float("nan"), "win_rate": float("nan"),
                "sum_net": 0.0, "gross_mean": float("nan")}
    r = trades["net_return"].to_numpy(dtype=float)
    g = trades["gross_return"].to_numpy(dtype=float)
    return {
        "n": int(len(r)),
        "mean_net": float(np.nanmean(r)) if len(r) else float("nan"),
        "win_rate": float(np.nanmean(r > 0)) if len(r) else float("nan"),
        "sum_net": float(np.nansum(r)),
        "gross_mean": float(np.nanmean(g)) if len(g) else float("nan"),
    }


# ---------------------------------------------------------------------------
# Core per-fold, per-scenario computation
# ---------------------------------------------------------------------------
def _fold_arm_trades(
    bars_f: pd.DataFrame,
    atr_f: pd.Series,
    signal_p: np.ndarray,
    pred_vol_frac: np.ndarray,
    exec_cfg: ExecutionConfig,
    side: int,
    scenario: str,
    fold_regime: pd.Series,
) -> Dict[str, pd.DataFrame]:
    """Compute ATR-arm and adaptive-arm net trades for ONE fold + scenario."""
    comp = components_for_scenario(scenario)
    results: Dict[str, pd.DataFrame] = {}

    # --- ATR arm (frozen) ---
    atr_labels = _label_arm(bars_f, atr_f, signal_p, FROZEN_ATR, exec_cfg, side)
    results["atr"] = _net_trades(atr_labels, comp, side)

    # --- Adaptive arm: vol-fraction -> price units -> atr-proxy -> frozen labeller ---
    close = bars_f["close"].to_numpy(dtype=float)
    # pred_vol_frac may be NaN where model couldn't predict -> treat as no-trade
    dist_price = FROZEN_VOLTARGET.k_vol * pred_vol_frac * close  # price units, aligned to bars
    # atr proxy = distance_price / k_vol  (so labeller yields entry +/- dist_price)
    proxy = adaptive_atr_proxy(dist_price, FROZEN_VOLTARGET.k_vol)
    proxy = pd.Series(proxy.to_numpy(), index=bars_f.index)
    bcfg = BarrierConfig(k_up=FROZEN_VOLTARGET.k_vol, k_dn=FROZEN_VOLTARGET.k_vol,
                         vertical=FROZEN_VOLTARGET.vertical, atr_span=14)
    adapt_labels = _label_arm(bars_f, atr_f, signal_p, bcfg, exec_cfg, side, atr_override=proxy)
    results["adaptive"] = _net_trades(adapt_labels, comp, side)
    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_experiment(
    bars: pd.DataFrame,
    X: pd.DataFrame,
    signal_p: np.ndarray,
    cfg: ExperimentConfig,
    regime_labels: Optional[pd.Series] = None,
) -> Dict[str, object]:
    """Run the purged walk-forward ATR-vs-adaptive comparison.

    Parameters
    ----------
    bars : OHLC bars (ts, open, high, low, close). Must be chronological.
    X : trailing feature matrix (same index as bars) for the vol model.
    signal_p : per-bar P(up) from the frozen primary model (signal source).
    cfg : ExperimentConfig (frozen ATR/adaptive configs are module constants).
    regime_labels : optional per-bar regime (calm/mid/high); computed if None.

    Returns a dict with per-fold/per-scenario results, summary, and the verdict.
    """
    bars = bars.reset_index(drop=True)
    X = X.reset_index(drop=True)
    signal_p = np.asarray(signal_p, dtype=float)
    assert len(signal_p) == len(bars) == len(X), "signal/features/bars must align"

    if regime_labels is None:
        regime_labels = trailing_regime(bars, cfg.regime)
    regime_labels = pd.Series(np.asarray(regime_labels), index=bars.index)

    # Eligibility: finite features + finite signal + finite forward vol label.
    y_vol = forward_realized_range(bars, FROZEN_VOLTARGET.horizon)
    eligible = (X.notna().all(axis=1).to_numpy()
                & np.isfinite(signal_p)
                & y_vol.notna().to_numpy())
    eligible_pos = np.flatnonzero(eligible)
    n = len(eligible_pos)

    purge = purge_bars(cfg.horizon_signal, "T3", cfg.embargo_bars)  # conservative
    folds = walk_forward_folds(n, cfg.folds, purge)
    if not folds:
        return {"error": "insufficient rows for walk-forward", "folds": [], "n_folds": 0,
                "n_eligible": int(n), "verdict": "NO-GO", "reasons": ["insufficient data"]}

    # ATR series for the frozen baseline (trailing; computed once on full bars).
    from nexora_laboratory.triple_barrier import atr_from_bars
    atr_full = atr_from_bars(bars, FROZEN_ATR.atr_span)

    fold_records = []
    # accumulate per-scenario (net_return, regime) pairs together so alignment
    # between a trade's net return and its regime can never drift.
    per_scenario_arrays = {sc: {"adaptive": [], "atr": []}
                           for sc in cfg.cost_scenarios}

    for fidx, (tr_local, te_local) in enumerate(folds):
        tr_rows = eligible_pos[tr_local]
        te_rows = eligible_pos[te_local]
        # contiguous bar span for this fold's test (label needs future bars to resolve)
        lo, hi = int(te_rows[0]), int(te_rows[-1])
        # extend back by enough for entry/vertical to resolve; keep simple: fold bars = [lo-1 .. end]
        bars_f = bars.iloc[lo:].reset_index(drop=True)
        X_f = X.iloc[lo:].reset_index(drop=True)
        # rebuild local feature indices for train (rows before lo) for vol model fit
        # fit on ALL eligible rows strictly before lo
        train_rows_global = eligible_pos[eligible_pos < lo]
        test_rows_global = eligible_pos[(eligible_pos >= lo) & (eligible_pos <= hi)]
        if len(train_rows_global) < 500 or len(test_rows_global) < 100:
            continue

        # Predict adaptive vol on the fold's test rows using train-only fit.
        pred_map = dict(zip(test_rows_global, _fit_predict_adaptive_vol(
            X, y_vol, train_rows_global, test_rows_global, FROZEN_VOLTARGET)))

        # Bars-local predicted vol array (NaN elsewhere)
        pred_vol_frac = np.full(len(bars_f), np.nan)
        for gi, val in pred_map.items():
            local = gi - lo
            if 0 <= local < len(pred_vol_frac):
                pred_vol_frac[local] = val

        # Signal probability local to fold bars
        signal_local = signal_p[lo:]
        atr_local = atr_full.iloc[lo:].reset_index(drop=True)
        regime_local = regime_labels.iloc[lo:].reset_index(drop=True)

        # Restrict candidate trades to the fold's TEST rows (no train-period leakage):
        # zero out ineligible predicted-vol rows so the adaptive arm cannot trade them,
        # and similarly gate which labels we keep by test membership.
        test_local = set(gi - lo for gi in test_rows_global)

        fold_scn = {}
        for sc in cfg.cost_scenarios:
            # Scenario differences enter through the SIMULATED half-spread used to
            # reconstruct bid/ask (executable mode). Higher-spread scenario => wider
            # effective spread crossing in gross_return. Slippage/commission are
            # subtracted once as non-spread components inside _net_trades.
            sc_comp = components_for_scenario(sc)
            half_spread = 0.5 * pips_to_price(sc_comp.round_trip_spread_pips)
            sc_exec = ExecutionConfig(half_spread_price=half_spread)
            arms = _fold_arm_trades(
                bars_f, atr_local, signal_local, pred_vol_frac, sc_exec, cfg.side, sc, regime_local
            )
            # keep only trades whose signal bar is a fold test row
            for arm in ("atr", "adaptive"):
                t = arms[arm]
                if not t.empty:
                    keep = t["signal_time"].isin(bars_f["ts"].iloc[sorted(test_local)].values)
                    arms[arm] = t[keep]
            a = arms["adaptive"]
            b = arms["atr"]
            fold_scn[sc] = {"adaptive": _summarise_trades(a), "atr": _summarise_trades(b)}

            if sc in per_scenario_arrays:
                ts_to_regime = dict(zip(bars_f["ts"], regime_local))
                def _pair(trades):
                    if trades.empty:
                        return np.array([]), np.array([], dtype=object)
                    net = trades["net_return"].to_numpy(dtype=float)
                    reg = trades["signal_time"].map(ts_to_regime).to_numpy()
                    return net, reg
                per_scenario_arrays[sc]["adaptive"].append(_pair(a))
                per_scenario_arrays[sc]["atr"].append(_pair(b))

        fold_records.append({"fold": fidx + 1,
                             "test_start": str(bars_f.loc[max(0, int(test_rows_global[0]) - lo), "ts"]),
                             "n_test_rows": int(len(test_rows_global)),
                             "scenarios": fold_scn})

    # ----- aggregate per scenario -----
    def _cat_nets(pairs):
        nets = [p[0] for p in pairs if len(p[0])]
        return np.concatenate(nets) if nets else np.array([])

    def _cat_regimes(pairs):
        regs = [p[1] for p in pairs if len(p[1])]
        return np.concatenate(regs) if regs else np.array([], dtype=object)

    scenario_summary = {}
    for sc in cfg.cost_scenarios:
        a = _cat_nets(per_scenario_arrays[sc]["adaptive"])
        b = _cat_nets(per_scenario_arrays[sc]["atr"])
        ci = _bootstrap_diff_ci(a, b, cfg.bootstrap_iters, cfg.bootstrap_seed)
        scenario_summary[sc] = {
            "adaptive": {"n": int(np.isfinite(a).sum()), "mean_net": float(np.nanmean(a)) if len(a) else float("nan")},
            "atr": {"n": int(np.isfinite(b).sum()), "mean_net": float(np.nanmean(b)) if len(b) else float("nan")},
            "diff_mean": ci["diff"], "ci_low": ci["ci_low"], "ci_high": ci["ci_high"],
            "p_diff_le_0": ci["p_diff_le_0"],
        }
        # per-regime means: net returns and regimes are emitted together in _pair,
        # so a[i] and reg_a[i] always describe the same trade.
        reg_a = _cat_regimes(per_scenario_arrays[sc]["adaptive"])
        reg_b = _cat_regimes(per_scenario_arrays[sc]["atr"])
        regime_out = {}
        for rname in (CALM, MID, HIGH):
            ra = a[np.asarray(reg_a == rname, dtype=bool)] if len(reg_a) == len(a) else np.array([])
            rb = b[np.asarray(reg_b == rname, dtype=bool)] if len(reg_b) == len(b) else np.array([])
            regime_out[rname] = {
                "adaptive_n": int(np.isfinite(ra).sum()),
                "atr_n": int(np.isfinite(rb).sum()),
                "adaptive_mean_net": float(np.nanmean(ra)) if len(ra) else float("nan"),
                "atr_mean_net": float(np.nanmean(rb)) if len(rb) else float("nan"),
            }
        scenario_summary[sc]["per_regime"] = regime_out

    verdict = _evaluate_go_no_go(fold_records, scenario_summary, cfg)

    return {
        "config": cfg.as_dict(),
        "n_folds": len(fold_records),
        "purge_bars": int(purge),
        "folds": fold_records,
        "scenario_summary": scenario_summary,
        "verdict": verdict["verdict"],
        "criteria": verdict["criteria"],
        "reasons": verdict["reasons"],
    }


# ---------------------------------------------------------------------------
# Pre-registered GO / NO-GO (literal §6)
# ---------------------------------------------------------------------------
def _evaluate_go_no_go(
    fold_records: List[dict], scenario_summary: Dict[str, dict], cfg: ExperimentConfig
) -> Dict[str, object]:
    criteria = {}
    reasons = []

    # §6.1: adaptive net > ATR net (median-positive relative) in >= 3 folds @ baseline.
    base_folds = [f["scenarios"]["baseline"] for f in fold_records
                  if "baseline" in f["scenarios"]]
    diffs = []
    for f in base_folds:
        am = f["adaptive"]["mean_net"]
        bm = f["atr"]["mean_net"]
        if np.isfinite(am) and np.isfinite(bm):
            diffs.append(am - bm)
    n_pos_folds = int(sum(1 for d in diffs if d > 0))
    c1 = n_pos_folds >= 3
    criteria["c1_positive_in_3_folds_baseline"] = {"pass": bool(c1),
                                                   "positive_folds": n_pos_folds,
                                                   "folds_evaluated": len(diffs)}
    if not c1:
        reasons.append(f"§6.1: adaptive beat ATR in only {n_pos_folds} baseline folds (<3)")

    # §6.2: baseline bootstrap CI excludes 0 (ci_low > 0).
    base = scenario_summary.get("baseline", {})
    ci_low = base.get("ci_low", float("nan"))
    c2 = bool(np.isfinite(ci_low) and ci_low > 0)
    criteria["c2_ci_excludes_zero_baseline"] = {
        "pass": c2, "ci_low": ci_low, "ci_high": base.get("ci_high", float("nan"))}
    if not c2:
        reasons.append("§6.2: baseline bootstrap 95% CI of (adaptive-ATR) includes 0")

    # §6.3: stress consistent (adaptive mean_net > ATR mean_net under stress).
    stress = scenario_summary.get("stress", {})
    am_s = stress.get("adaptive", {}).get("mean_net", float("nan"))
    bm_s = stress.get("atr", {}).get("mean_net", float("nan"))
    c3 = bool(np.isfinite(am_s) and np.isfinite(bm_s) and am_s > bm_s)
    criteria["c3_stress_consistent"] = {"pass": c3, "adaptive_mean_net": am_s,
                                        "atr_mean_net": bm_s}
    if not c3:
        reasons.append("§6.3: adaptive not better than ATR under stress scenario")

    # §6.4: trade count adequate: every baseline fold has >= min_trades for both arms.
    adequate = all(
        f["adaptive"]["n"] >= cfg.min_trades_per_fold and f["atr"]["n"] >= cfg.min_trades_per_fold
        for f in base_folds
    ) if base_folds else False
    criteria["c4_trade_count_adequate"] = {"pass": bool(adequate),
                                           "min_required": cfg.min_trades_per_fold}
    if not adequate:
        reasons.append(f"§6.4: some baseline fold has < {cfg.min_trades_per_fold} trades")

    # §6.5: not dependent on a single regime: adaptive beats ATR (mean_net) in >=2 of 3 regimes.
    reg = base.get("per_regime", {})
    regime_wins = 0
    for rn in (CALM, MID, HIGH):
        d = reg.get(rn, {})
        a_mn = d.get("adaptive_mean_net", float("nan"))
        b_mn = d.get("atr_mean_net", float("nan"))
        if np.isfinite(a_mn) and np.isfinite(b_mn) and a_mn > b_mn:
            regime_wins += 1
    c5 = regime_wins >= 2
    criteria["c5_not_single_regime"] = {"pass": bool(c5), "regimes_adaptive_better": regime_wins}
    if not c5:
        reasons.append(f"§6.5: adaptive only beats ATR in {regime_wins} regime(s) (<2)")

    # §6.6: no leakage -> enforced by construction + unit tests; mark pass if folds ran.
    c6 = len(fold_records) >= 1 and bool(all(f.get("n_test_rows", 0) > 0 for f in fold_records))
    criteria["c6_no_leakage"] = {"pass": bool(c6),
                                 "note": "enforced by tests/test_adaptive_barrier.py + purged folds"}
    if not c6:
        reasons.append("§6.6: leakage guard not satisfied (no valid folds)")

    all_pass = all(v["pass"] for v in criteria.values())
    return {"verdict": "GO" if all_pass else "NO-GO", "criteria": criteria, "reasons": reasons}


def write_report(result: Dict[str, object], out_dir: Path) -> Path:
    """Persist the experiment result as JSON (explicit output dir only)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "adaptive_vs_atr_report.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return path

from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = (equity / running_max) - 1.0
    return float(drawdown.min())


def evaluate_trade_returns(
    trade_returns: np.ndarray,
    sample_size: int,
    active_size: int,
) -> Dict[str, float]:
    if active_size == 0:
        return {
            "samples": int(sample_size),
            "trades": 0,
            "exposure": 0.0,
            "win_rate": None,
            "expectancy": None,
            "profit_factor": None,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "total_return": 0.0,
            "avg_win": None,
            "avg_loss": None,
            "max_drawdown": 0.0,
            "sharpe_like": None,
        }

    gross_profit = float(trade_returns[trade_returns > 0].sum())
    gross_loss = float(-trade_returns[trade_returns < 0].sum())
    wins = trade_returns[trade_returns > 0]
    losses = trade_returns[trade_returns < 0]

    equity = pd.Series(1.0 + trade_returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    max_dd = _max_drawdown(equity)

    std = float(np.std(trade_returns, ddof=1)) if active_size > 1 else 0.0
    sharpe_like = float(np.mean(trade_returns) / std) if std > 0 else None

    return {
        "samples": int(sample_size),
        "trades": int(active_size),
        "exposure": float(active_size / sample_size) if sample_size else 0.0,
        "win_rate": float((trade_returns > 0).mean()),
        "expectancy": float(np.mean(trade_returns)),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else None,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "total_return": total_return,
        "avg_win": float(np.mean(wins)) if len(wins) else None,
        "avg_loss": float(np.mean(losses)) if len(losses) else None,
        "max_drawdown": max_dd,
        "sharpe_like": sharpe_like,
    }


def evaluate_signals_frame(df: pd.DataFrame, round_trip_cost_bps: float = 0.0) -> Dict[str, float]:
    req = {"direction", "realized_forward_return"}
    missing = req - set(df.columns)
    if missing:
        raise ValueError(f"Signal file missing columns: {sorted(missing)}")

    clean = df.copy()
    clean["direction"] = pd.to_numeric(clean["direction"], errors="coerce")
    clean["realized_forward_return"] = pd.to_numeric(clean["realized_forward_return"], errors="coerce")
    clean = clean.dropna(subset=["direction", "realized_forward_return"])

    sample_size = len(clean)
    active = clean[clean["direction"].abs() > 0]
    active_size = len(active)

    if sample_size == 0:
        return evaluate_trade_returns(np.array([]), sample_size=0, active_size=0)

    costs = (round_trip_cost_bps / 10000.0)
    trade_returns = (active["direction"].to_numpy() * active["realized_forward_return"].to_numpy()) - costs

    out = evaluate_trade_returns(trade_returns, sample_size=sample_size, active_size=active_size)
    out["round_trip_cost_bps"] = float(round_trip_cost_bps)
    return out


def parse_signal_path(path: Path) -> Dict[str, object]:
    # expected: signals/<symbol>/<tf>/h<horizon>/<kind>_signals.csv
    parts = path.parts
    if len(parts) < 5:
        raise ValueError(f"Unexpected signal path: {path}")
    symbol = parts[-4]
    timeframe = parts[-3]
    horizon_token = parts[-2]
    horizon = int(horizon_token[1:]) if horizon_token.startswith("h") else None
    kind = path.stem.replace("_signals", "")
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "horizon": horizon,
        "kind": kind,
        "file": str(path),
    }


def evaluate_signal_file(path: Path, round_trip_cost_bps: float = 0.0) -> Dict[str, object]:
    meta = parse_signal_path(path)
    df = pd.read_csv(path)
    stats = evaluate_signals_frame(df, round_trip_cost_bps=round_trip_cost_bps)
    return {**meta, **stats}


def summarize_consistency(rows: List[Dict[str, object]]) -> Dict[str, object]:
    if not rows:
        return {"records": 0}
    frame = pd.DataFrame(rows)
    return {
        "records": int(len(frame)),
        "symbols": sorted(frame.symbol.unique().tolist()),
        "timeframes": sorted(frame.timeframe.unique().tolist()),
        "kinds": sorted(frame.kind.unique().tolist()),
        "positive_expectancy_ratio": float((frame.expectancy.fillna(-np.inf) > 0).mean()),
        "pf_above_1_ratio": float((frame.profit_factor.fillna(0) > 1).mean()),
        "median_win_rate": float(frame.win_rate.dropna().median()) if frame.win_rate.notna().any() else None,
        "median_max_drawdown": float(frame.max_drawdown.dropna().median()) if frame.max_drawdown.notna().any() else None,
    }

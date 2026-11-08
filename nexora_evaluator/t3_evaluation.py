"""T3 execution-aligned GROSS evaluator.

`realized_forward_return` in a T3 signal frame is the open[t+1]->open[t+h+1]
return. Trade P&L = direction * realized_return. All figures are GROSS: no
spread, slippage, commission, or swap is applied (transaction cost DEFERRED),
so nothing here is a net-profitability claim.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from nexora_evaluator.trading import _max_drawdown, evaluate_trade_returns


def evaluate_t3_execution_gross(df: pd.DataFrame) -> Dict[str, object]:
    req = {"direction", "realized_forward_return"}
    missing = req - set(df.columns)
    if missing:
        raise ValueError("T3 signal frame missing columns: %s" % sorted(missing))

    clean = df.copy()
    clean["direction"] = pd.to_numeric(clean["direction"], errors="coerce")
    clean["realized_forward_return"] = pd.to_numeric(clean["realized_forward_return"], errors="coerce")
    clean = clean.dropna(subset=["direction", "realized_forward_return"])

    sample_size = int(len(clean))
    dirs = clean["direction"].to_numpy(dtype=float)
    long_n = int((dirs > 0).sum())
    short_n = int((dirs < 0).sum())
    neutral_n = int((dirs == 0).sum())

    active = clean[clean["direction"].abs() > 0]
    active_size = int(len(active))

    common = {
        "target_type": "T3",
        "is_gross": True,
        "transaction_cost_status": "DEFERRED",
        "samples": sample_size,
        "signal_count": active_size,
        "long_count": long_n,
        "short_count": short_n,
        "neutral_count": neutral_n,
        "long_fraction": float(long_n / sample_size) if sample_size else 0.0,
        "short_fraction": float(short_n / sample_size) if sample_size else 0.0,
        "neutral_fraction": float(neutral_n / sample_size) if sample_size else 0.0,
    }

    if sample_size == 0 or active_size == 0:
        base = evaluate_trade_returns(np.array([]), sample_size=sample_size, active_size=0)
        common.update(base)
        common.update(
            {
                "gross_expectancy": None,
                "gross_profit_factor": None,
                "gross_max_drawdown": 0.0,
                "total_return_gross": 0.0,
                "exposure": 0.0,
            }
        )
        return common

    gross_pnl = active["direction"].to_numpy(dtype=float) * active["realized_forward_return"].to_numpy(dtype=float)
    equity = pd.Series(1.0 + gross_pnl).cumprod()
    total_gross_return = float(equity.iloc[-1] - 1.0)
    max_dd_gross = _max_drawdown(equity)

    stats = evaluate_trade_returns(gross_pnl, sample_size=sample_size, active_size=active_size)
    common.update(stats)
    common.update(
        {
            "gross_expectancy": stats.get("expectancy"),
            "gross_profit_factor": stats.get("profit_factor"),
            "gross_win_rate": stats.get("win_rate"),
            "gross_max_drawdown": max_dd_gross,
            "total_return_gross": total_gross_return,
            "exposure": float(active_size / sample_size) if sample_size else 0.0,
        }
    )
    return common

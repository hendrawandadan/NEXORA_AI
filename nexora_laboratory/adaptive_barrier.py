"""FASE 2A - Adaptive (vol-targeted) barrier: EXPERIMENT MODULE (design #1).

Separate experiment vs the FROZEN ATR baseline. This module NEVER modifies
`triple_barrier.py`. It predicts forward volatility from information <= t, then
builds barriers as a multiple of that prediction:

    pred_vol_frac_t    = model(features <= t)          # forward range / close
    barrier_distance_t = k_vol * pred_vol_frac_t * close_t   # PRICE UNITS
    upper = entry + barrier_distance_t        (BUY profit / SELL loss)
    lower = entry - barrier_distance_t        (BUY loss   / SELL profit)  [symmetric]

The `* close_t` step is essential: pred_vol is a fraction; the labeller needs
price units. Use ``VolatilityBarrierModel.barrier_distance(X, ref_price=close)``
to get price-unit distances.

To guarantee an apple-to-apple comparison, labeling is performed by the SAME
core function used by the baseline (`triple_barrier.label_events`) by passing
`predicted_vol / k` as the per-bar "atr" series and `k_up = k_dn = k_vol`. Thus
execution (executable bid/ask), status logic, vertical exit, and cost application
are byte-for-byte the baseline; only the barrier distance source differs.

Anti-leakage:
  - Features at bar t use only bars <= t (built upstream, trailing).
  - The volatility TARGET used to fit the model is the forward realized range over
    the next H bars (known only in hindsight) and is ALWAYS computed from the
    past/training region only. The model at prediction time never sees the target.
  - A strict unit test verifies that predicting barrier distances for bar t does
    not change when bars > t are altered.

Status: design/implementation + tests only. No training, no experiment run here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class VolTargetConfig:
    horizon: int = 16          # forecast realized range over next H bars
    k_vol: float = 1.25        # barrier distance = k_vol * predicted_vol
    vertical: int = 16         # vertical barrier aligned to horizon by default
    lgbm_params: dict = field(default_factory=lambda: dict(
        n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=100,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5,
        verbosity=-1,
    ))

    def as_dict(self) -> dict:
        return {"horizon": self.horizon, "k_vol": self.k_vol,
                "vertical": self.vertical, "lgbm_params": self.lgbm_params}


def forward_realized_range(bars: pd.DataFrame, horizon: int) -> pd.Series:
    """Forward realized range over the next `horizon` bars (TRAINING TARGET).

    Value at t = (max(high[t+1..t+H]) - min(low[t+1..t+H])) / close[t].
    This is HINDSIGHT by construction; it is ONLY used as a supervised target and
    must never be available to the predictor for the same row it labels.
    The last `horizon` rows are NaN (no future available).
    """
    hi = bars["high"].to_numpy(dtype=float)
    lo = bars["low"].to_numpy(dtype=float)
    cl = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    out = np.full(n, np.nan)
    for t in range(n - horizon):
        window_hi = hi[t + 1: t + 1 + horizon].max()
        window_lo = lo[t + 1: t + 1 + horizon].min()
        out[t] = (window_hi - window_lo) / cl[t]
    return pd.Series(out, index=bars.index, name="fwd_realized_range")


class VolatilityBarrierModel:
    """Predicts forward realized range (volatility) -> adaptive barrier distance."""

    def __init__(self, cfg: Optional[VolTargetConfig] = None):
        self.cfg = cfg or VolTargetConfig()
        self._reg = None
        self.feature_names_: Optional[list] = None

    def fit(self, X: pd.DataFrame, y_range: pd.Series):
        import lightgbm as lgb
        self.feature_names_ = list(X.columns)
        reg = lgb.LGBMRegressor(**self.cfg.lgbm_params)
        reg.fit(X, y_range)
        self._reg = reg
        return self

    def predict_vol(self, X: pd.DataFrame) -> np.ndarray:
        """Predicted forward realized RANGE as a price FRACTION (range / close)."""
        if self._reg is None:
            raise RuntimeError("model not fitted")
        return self._reg.predict(X)

    def barrier_distance(self, X: pd.DataFrame, ref_price=None) -> np.ndarray:
        """Per-bar barrier distance in PRICE UNITS = k_vol * pred_vol_frac * ref_price.

        ``pred_vol`` is a FRACTION (range/close). To express the barrier in the same
        price units as OHLC, multiply by the reference price at the same bar
        (e.g. close_t, known at signal time). If ``ref_price`` is omitted, the
        returned value is in FRACTION units and the caller MUST scale it by a
        reference price before handing it to the labeller.
        """
        frac = self.predict_vol(X)
        if ref_price is None:
            return self.cfg.k_vol * frac
        return self.cfg.k_vol * frac * np.asarray(ref_price, dtype=float)


def adaptive_atr_proxy(predicted_vol_price: np.ndarray, k_vol: float) -> pd.Series:
    """Feeds the frozen baseline: passing atr = predicted_vol_price / k_vol with
    k_up=k_dn=k_vol reproduces upper/lower = entry ± k_vol*predicted_vol_price.
    """
    return pd.Series(np.asarray(predicted_vol_price) / float(k_vol))


def label_with_adaptive_barrier(
    bars: pd.DataFrame,
    predicted_vol_price: np.ndarray,
    cfg: VolTargetConfig,
    exec_cfg,
    side: int,
    m1: Optional[pd.DataFrame] = None,
):
    """Run the FROZEN baseline labeler using adaptive symmetric barriers.

    Reuses `triple_barrier.label_events` unchanged: pass ``atr = predicted_vol_price/k``
    and ``BarrierConfig(k_up=k_dn=k_vol, vertical=cfg.vertical)``. Because baseline
    sets upper=entry+k_up*atr and lower=entry-k_dn*atr, this yields
    upper/lower = entry ± k_vol*predicted_vol_price. Execution/cost identical.
    """
    from nexora_laboratory.triple_barrier import BarrierConfig, label_events

    proxy = adaptive_atr_proxy(predicted_vol_price, cfg.k_vol)
    # align proxy to bars index
    proxy.index = bars.index if len(proxy) == len(bars) else proxy.index
    bcfg = BarrierConfig(k_up=cfg.k_vol, k_dn=cfg.k_vol, vertical=cfg.vertical,
                         atr_span=14)
    return label_events(bars, proxy, bcfg, exec_cfg, side=side, m1=m1)

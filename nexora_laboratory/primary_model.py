"""FASE 2A - Layer 1: Kronos-inspired ensemble forecast (NO torch).

Conceptually inspired by Kronos (probabilistic K-line forecasting) but implemented
with the existing LightGBM/sklearn stack:

    - Ensemble of N LightGBM classifiers with different seeds -> mean prob (forecast)
      and dispersion (std across seeds) = uncertainty/confidence signal.
    - Quantile LightGBM regressors -> forecast return distribution (q_low/q_high)
      to estimate directional magnitude + range.
    - Probability calibration (isotonic on validation) so that the reported
      'prob_up' can be interpreted as a calibrated probability (NOT raw output).

Outputs per row (for meta-labeling and Gate 0):
    prob_up_raw, prob_up_cal, direction, confidence, dispersion,
    q_return_mean, q_return_lo, q_return_hi, q_range

Design notes:
    - Calibration and seed-ensemble fitting must be done on TRAIN data only;
      calibration on the VALIDATION fold (never test). This module exposes
      fit()/predict() so the runner controls the split honestly.
    - No future information: features are built from trailing windows upstream
      (nexora_vision.features) and targets are forward returns computed upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from sklearn.isotonic import IsotonicRegression


@dataclass
class PrimaryModelConfig:
    n_seeds: int = 5
    base_seed: int = 42
    horizon: int = 4
    quantiles: tuple = (0.1, 0.5, 0.9)
    lgbm_params: dict = field(default_factory=lambda: dict(
        n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=100,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5,
        verbosity=-1,
    ))

    def as_dict(self) -> dict:
        return {
            "n_seeds": self.n_seeds, "base_seed": self.base_seed, "horizon": self.horizon,
            "quantiles": list(self.quantiles), "lgbm_params": self.lgbm_params,
        }


class PrimaryModel:
    """Kronos-inspired ensemble forecaster (classifier ensemble + quantile regressors)."""

    def __init__(self, cfg: Optional[PrimaryModelConfig] = None):
        self.cfg = cfg or PrimaryModelConfig()
        self._clfs: List = []
        self._qregs: dict = {}
        self._calibrator: Optional[IsotonicRegression] = None
        self.feature_names_: Optional[List[str]] = None

    # -- fitting ---------------------------------------------------------
    def fit(self, X: pd.DataFrame, y: pd.Series, X_cal: pd.DataFrame, y_cal: pd.Series):
        """Fit ensemble + quantile regressors on train; calibrate on a validation fold."""
        import lightgbm as lgb
        self.feature_names_ = list(X.columns)
        self._clfs = []
        for i in range(self.cfg.n_seeds):
            params = dict(self.cfg.lgbm_params)
            params["random_state"] = self.cfg.base_seed + i
            clf = lgb.LGBMClassifier(**params)
            clf.fit(X, y)
            self._clfs.append(clf)

        # Quantile regressors on the forward return (needs a return target column).
        # We fit them if the caller supplies a return series via fit_quantiles().
        # Calibration: isotonic on held-out validation probabilities
        raw_cal = self._predict_prob_raw(X_cal)
        iso = IsotonicRegression(out_of_bounds="clip")
        y_cal_arr = y_cal.to_numpy() if hasattr(y_cal, "to_numpy") else np.asarray(y_cal)
        iso.fit(raw_cal, y_cal_arr)
        self._calibrator = iso
        return self

    def fit_quantiles(self, X: pd.DataFrame, r: pd.Series):
        """Fit quantile regressors on forward return r (same feature matrix)."""
        import lightgbm as lgb
        self._qregs = {}
        for q in self.cfg.quantiles:
            params = dict(self.cfg.lgbm_params)
            params["objective"] = "quantile"
            params["alpha"] = q
            reg = lgb.LGBMRegressor(**params)
            reg.fit(X, r)
            self._qregs[q] = reg
        return self

    # -- prediction ------------------------------------------------------
    def _predict_prob_raw(self, X: pd.DataFrame) -> np.ndarray:
        preds = np.vstack([clf.predict_proba(X)[:, 1] for clf in self._clfs])
        return preds.mean(axis=0)

    def _predict_dispersion(self, X: pd.DataFrame) -> np.ndarray:
        preds = np.vstack([clf.predict_proba(X)[:, 1] for clf in self._clfs])
        return preds.std(axis=0)

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        raw = self._predict_prob_raw(X)
        disp = self._predict_dispersion(X)
        cal = self._calibrator.predict(raw) if self._calibrator is not None else raw
        out = pd.DataFrame({
            "prob_up_raw": raw,
            "prob_up_cal": cal,
            "dispersion": disp,
        }, index=X.index)
        out["direction"] = np.where(out["prob_up_cal"] >= 0.5, 1, -1)
        out["confidence"] = (out["prob_up_cal"] - 0.5).abs()
        if self._qregs:
            q_low = self._qregs[self.cfg.quantiles[0]].predict(X)
            q_med = self._qregs[self.cfg.quantiles[1]].predict(X)
            q_high = self._qregs[self.cfg.quantiles[-1]].predict(X)
            out["q_return_lo"] = q_low
            out["q_return_mean"] = q_med
            out["q_return_hi"] = q_high
            out["q_range"] = q_high - q_low
        return out

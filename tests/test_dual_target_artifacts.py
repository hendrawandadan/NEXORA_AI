"""End-to-end dual-target artifact isolation via pipeline.train_one (synthetic).

SAFETY: writes only to a TemporaryDirectory. Patches nexora_learning.pipeline.ROOT
to the temp root so models/signals/reports land under tmp. Never touches the
production dataset, model, signals, or backup. Trains small sklearn models on
synthetic bars (fast, no LightGBM dependency required).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nexora_learning.pipeline as P


def _write_synthetic_csv(path: Path, n: int = 1200, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    close = 1.1 + np.cumsum(rng.normal(0, 1e-4, n))
    open_ = close - 1e-5
    ts = pd.date_range("2021-01-01", periods=n, freq="30min")
    df = pd.DataFrame({
        "time": ts.strftime("%Y.%m.%d %H:%M"),
        "open": open_,
        "high": close + 2e-4,
        "low": close - 2e-4,
        "close": close,
        "volume": rng.integers(1, 100, n),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def test_train_one_t1_and_t3_write_isolated_artifacts(tmp_path, monkeypatch):
    data = tmp_path / "EURUSD_M30_synthetic.csv"
    _write_synthetic_csv(data)

    # Redirect pipeline artifact root to the temp dir.
    monkeypatch.setattr(P, "ROOT", tmp_path)

    common = dict(path=data, symbol="EURUSD", tf="M30", horizon=2, kind="individual",
                  engine="sklearn", max_iter=50, seed=42)
    rep_t1 = P.train_one(target_type="T1", **common)
    rep_t3 = P.train_one(target_type="T3", **common)

    # Reports carry distinct target identity.
    assert rep_t1["target_type"] == "T1"
    assert rep_t3["target_type"] == "T3"
    assert rep_t1["target_hash"] != rep_t3["target_hash"]
    assert rep_t1["effective_horizon"] == 2 and rep_t3["effective_horizon"] == 3
    assert rep_t3.get("realized_return_is_gross") is True
    assert "realized_return_is_gross" not in rep_t1

    # Artifacts are namespaced t1/ vs t3/ and do not overwrite each other.
    t1_model = tmp_path / "models" / "t1" / "individual" / "EURUSD" / "M30" / "h2" / "model.joblib"
    t3_model = tmp_path / "models" / "t3" / "individual" / "EURUSD" / "M30" / "h2" / "model.joblib"
    assert t1_model.is_file()
    assert t3_model.is_file()
    assert t1_model != t3_model

    # Both signal files exist in separate namespaces.
    t1_sig = tmp_path / "signals" / "t1" / "EURUSD" / "M30" / "h2" / "individual_signals.csv"
    t3_sig = tmp_path / "signals" / "t3" / "EURUSD" / "M30" / "h2" / "individual_signals.csv"
    assert t1_sig.is_file() and t3_sig.is_file()

    # Reports on disk match namespace and target.
    t1_rep = json.loads((tmp_path / "reports" / "t1" / "individual" / "EURUSD" / "M30" / "h2" / "report.json").read_text())
    t3_rep = json.loads((tmp_path / "reports" / "t3" / "individual" / "EURUSD" / "M30" / "h2" / "report.json").read_text())
    assert t1_rep["target_type"] == "T1" and t3_rep["target_type"] == "T3"
    assert t1_rep["target_hash"] != t3_rep["target_hash"]


def test_train_one_rejects_unknown_target(tmp_path, monkeypatch):
    data = tmp_path / "EURUSD_M30_synthetic.csv"
    _write_synthetic_csv(data, n=300)
    monkeypatch.setattr(P, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        P.train_one(path=data, symbol="EURUSD", tf="M30", horizon=2, kind="individual",
                    engine="sklearn", max_iter=50, target_type="T9")


def test_runner_path_builders_isolate_by_target():
    import batch1_execution_runner as r

    row_t1 = {"symbol": "EURUSD", "timeframe": "M30", "horizon": "2", "target_type": "T1"}
    row_t3 = {"symbol": "EURUSD", "timeframe": "M30", "horizon": "2", "target_type": "T3"}
    root = Path("X")

    p1 = r.expected_paths(root, row_t1)
    p3 = r.expected_paths(root, row_t3)
    assert p1["model"] != p3["model"]
    assert "t1" in p1["model"].parts and "t3" in p3["model"].parts

    b1 = r.build_promotion_targets(row_t1, root)
    b3 = r.build_promotion_targets(row_t3, root)
    assert b1["model"] != b3["model"]
    assert "t1" in b1["model"].parts and "t3" in b3["model"].parts


def test_runner_default_target_is_t1_when_absent():
    import batch1_execution_runner as r

    row = {"symbol": "EURUSD", "timeframe": "M30", "horizon": "2"}  # no target_type
    p = r.expected_paths(Path("X"), row)
    assert "t1" in p["model"].parts

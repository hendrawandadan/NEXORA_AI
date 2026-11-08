"""Regression tests for PREP-001 baseline implementation (B1/B2 + dead code).

Read-only; no training, no model.fit, no production DB writes. Verifies:
* T3 dead code removed and T3 formula numerically unchanged (vs explicit formula).
* Effective LightGBM runtime config matches the frozen owner-approved baseline.
* Timing contract: bar-open convention, T3 entry Open[t+1] / exit Open[t+h+1],
  no look-ahead (decision at start of t+1), costs deferred, gross.
* Per-target freeze identity (T1 vs T3) is isolated and complete.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd

import nexora_learning.targets as T
from nexora_audit.configuration_freeze import (
    build_frozen_manifest,
    build_target_freeze_identity,
)
from nexora_audit.timing_contract import OWNER_APPROVED, build_timing_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _bars(n=600, seed=11):
    rng = np.random.default_rng(seed)
    close = 1.1 + np.cumsum(rng.normal(0, 1e-4, n))
    op = close - 1e-5
    ts = pd.date_range("2021-01-01", periods=n, freq="30min")
    return pd.DataFrame({"ts": ts, "open": op, "high": close + 2e-4,
                         "low": close - 2e-4, "close": close,
                         "volume": rng.integers(1, 100, n)})


# --------------------------------------------------------------------------
# TASK C: dead code removed, T3 formula unchanged
# --------------------------------------------------------------------------
def test_t3_dead_code_removed():
    src = inspect.getsource(T.compute_return_t3)
    assert "if False" not in src
    assert "else np.nan" not in src


def test_t3_formula_unchanged_matches_explicit_definition():
    df = _bars()
    op = df["open"].to_numpy(float)
    n = len(op)
    for h in (1, 2, 4, 24):
        f3 = T.compute_return_t3(df, h)
        # Valid region: exactly Open[t+h+1]/Open[t+1]-1
        for t in range(0, n - (h + 1)):
            exp = op[t + 1 + h] / op[t + 1] - 1.0
            assert np.isclose(f3[t], exp), (h, t, f3[t], exp)
        # Trailing h+1 rows have no label.
        assert np.isnan(f3[-(h + 1):]).all()


def test_t1_formula_unchanged():
    df = _bars()
    close = df["close"].to_numpy(float)
    n = len(close)
    h = 2
    f1 = T.compute_return_t1(df, h)
    for t in range(0, n - h):
        assert np.isclose(f1[t], close[t + h] / close[t] - 1.0)
    assert np.isnan(f1[-h:]).all()


def test_t3_effective_horizon_is_h_plus_one():
    for h in (1, 2, 4, 24):
        spec = T.get_target_spec("T3", h)
        assert spec.effective_horizon == h + 1
        assert T.get_target_spec("T1", h).effective_horizon == h


# --------------------------------------------------------------------------
# B1: effective runtime model config matches frozen baseline
# --------------------------------------------------------------------------
def test_effective_lightgbm_config_matches_frozen_baseline():
    from nexora_intelligence.model import create_model
    model, engine = create_model("auto", seed=42, max_iter=300)
    assert engine == "lightgbm"
    assert model.n_estimators == 300
    assert model.learning_rate == 0.03
    assert model.num_leaves == 15
    assert model.min_child_samples == 100
    assert model.colsample_bytree == 0.8
    assert model.subsample == 0.8
    assert model.subsample_freq == 1
    assert model.reg_lambda == 5
    # B1 approved baseline: explicit-effective defaults
    assert model.reg_alpha == 0.0
    assert model.max_depth == -1
    assert model.random_state == 42


def test_frozen_manifest_matches_effective_runtime():
    from nexora_intelligence.model import create_model
    model, _ = create_model("auto", seed=42, max_iter=300)
    manifest = build_frozen_manifest(PROJECT_ROOT)
    assert manifest.frozen_value("max_depth") == model.max_depth
    assert manifest.frozen_value("l1_regularization") == model.reg_alpha
    assert manifest.frozen_value("l2_regularization") == model.reg_lambda
    assert manifest.frozen_value("num_leaves") == model.num_leaves
    assert manifest.frozen_value("learning_rate") == model.learning_rate
    assert manifest.frozen_value("min_child_samples") == model.min_child_samples
    assert manifest.frozen_value("feature_fraction") == model.colsample_bytree
    assert manifest.frozen_value("bagging_fraction") == model.subsample
    assert manifest.frozen_value("n_estimators") == model.n_estimators
    assert manifest.frozen_value("random_seed") == model.random_state


def test_freeze_complete_and_deterministic():
    a = build_frozen_manifest(PROJECT_ROOT).config_hash()
    b = build_frozen_manifest(PROJECT_ROOT).config_hash()
    assert a["hash"] == b["hash"]
    assert a["complete"] is True
    assert a["requires_decision"] == []


def test_decision_time_policy_frozen_bar_open():
    manifest = build_frozen_manifest(PROJECT_ROOT)
    assert manifest.is_frozen("decision_time_policy")
    assert manifest.frozen_value("decision_time_policy") == "bar_open"


# --------------------------------------------------------------------------
# B2: timing contract owner-approved values + no look-ahead
# --------------------------------------------------------------------------
def test_timing_owner_approved_values():
    c = build_timing_contract(horizon=2, timeframe="M30")
    assert c.field("decision_timestamp").value == "bar_t+1_open"
    assert c.field("earliest_executable_timestamp").value == "bar_t+1_open"
    assert c.field("execution_price_model").value == "open_price"
    assert c.field("spread_usage").value == "deferred"
    assert c.field("slippage_usage").value == "deferred"
    assert c.field("cost_usage").value == "deferred"
    for name in ("decision_timestamp", "earliest_executable_timestamp",
                 "execution_price_model", "spread_usage", "slippage_usage", "cost_usage"):
        f = c.field(name)
        assert f.status == OWNER_APPROVED
        assert f.owner_approval == OWNER_APPROVED


def test_timing_owner_approved_but_not_human_ratified():
    info = build_timing_contract().contract_hash()
    assert info["owner_approved"] is True
    assert info["ratified"] is False   # no HMAC sign-off created
    assert info["new_design_fields"] == []


def test_timing_no_look_ahead_decision_not_before_bar_t1_starts():
    # Decision timestamp is the START of bar t+1, using features from bar t (known at
    # close of t). The Open[t+1] price is not assumed known before bar t+1 begins,
    # so decision_time (bar t+1 open) >= feature availability (bar t close). No look-ahead.
    c = build_timing_contract(horizon=2, timeframe="M30")
    assert c.field("feature_availability_timestamp").status == "PROVEN"
    assert c.field("decision_timestamp").value == "bar_t+1_open"
    # bar t+1 open is strictly after bar t close -> not earlier than feature availability.
    assert c.field("earliest_executable_timestamp").value == "bar_t+1_open"
    # No same-bar execution: decision/entry is bar t+1, not bar t.
    assert "bar_t+1" in c.field("decision_timestamp").value


def test_t3_entry_exit_match_owner_contract():
    df = _bars()
    op = df["open"].to_numpy(float)
    h = 2
    f3 = T.compute_return_t3(df, h)
    # entry Open[t+1], exit Open[t+h+1]
    t = 100
    assert np.isclose(f3[t], op[t + 1 + h] / op[t + 1] - 1.0)


def test_costs_deferred_t3_is_gross_not_net():
    c = build_timing_contract()
    for name in ("spread_usage", "slippage_usage", "cost_usage"):
        assert c.field(name).value == "deferred"
    # No cost subtraction anywhere in compute_return_t3.
    src = inspect.getsource(T.compute_return_t3)
    assert "spread" not in src.lower()
    assert "commission" not in src.lower()
    assert "slippage" not in src.lower()


# --------------------------------------------------------------------------
# TASK E: per-target freeze identity isolated + complete
# --------------------------------------------------------------------------
def test_target_freeze_identity_t1_t3_isolated_and_complete():
    t1 = build_target_freeze_identity(PROJECT_ROOT, "T1", "A")
    t3 = build_target_freeze_identity(PROJECT_ROOT, "T3", "A")
    # Distinct identity / target hash / namespace / split.
    assert t1["experiment_id"] == "PREP-001-T1-A"
    assert t3["experiment_id"] == "PREP-001-T3-A"
    assert t1["target_hash"] != t3["target_hash"]
    assert t1["artifact_namespace"] == "t1"
    assert t3["artifact_namespace"] == "t3"
    assert t1["split_policy_version"] != t3["split_policy_version"]
    assert t1["effective_horizon"] == 2
    assert t3["effective_horizon"] == 3
    # Both complete / frozen config, shared feature+dataset+timing, both NOT signed.
    for idt in (t1, t3):
        assert idt["config_hash_complete"] is True
        assert idt["config_hash"] == t1["config_hash"]
        assert idt["feature_set_version"] == t1["feature_set_version"]
        assert idt["dataset_hash"] == t1["dataset_hash"]
        assert idt["timing_owner_approved"] is True
        assert idt["timing_human_ratified"] is False
        assert idt["signoff_present"] is False
    # Fixed target hashes preserved (Task D).
    assert t1["target_hash"].startswith("414c2147")
    assert t3["target_hash"].startswith("d5f2c434")

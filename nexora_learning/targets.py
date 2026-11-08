"""Dual target definitions for PREP-001 (T1 statistical + T3 execution-aligned).

This module is the single source of truth for target construction. It is pure
(no I/O, no database, no training) and deterministic.

T1 (statistical direction target):
    return_t1[t] = Close[t+h] / Close[t] - 1
    y_t1[t]      = 1 if return_t1[t] > 0 else 0
    effective_horizon = h   (label known at close of bar t+h)

T3 (execution-aligned target):
    return_t3[t] = Open[t+h+1] / Open[t+1] - 1
    y_t3[t]      = 1 if return_t3[t] > 0 else 0
    effective_horizon = h+1 (label known at open of bar t+h+1)

Both targets are built independently from the SAME feature matrix; there is NO
shared mutable target vector. Every target gets its own version id and hash so
artifacts and experiments cannot collide.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

TARGET_HASH_VERSION = "nexora-target-v1"
TIMESTAMP_CONVENTION = "bar-open"

# HASH DOMAIN NOTE (Task D):
#   This module defines the canonical *TargetSpec* hash domain (nexora-target-v1).
#   It produces the hashes that AUTHORIZATION binds to:
#     T1 -> 414c2147b5d59e11...  (TargetSpec hash)
#     T3 -> d5f2c43434aa7c41...  (TargetSpec hash)
#   nexora_audit.configuration_freeze.target_definition_version() uses a SEPARATE
#   legacy domain (nexora-cfg-freeze-v2) producing a different T1 hash
#   (b9c8f231d7fb8dbe...) purely for the freeze manifest's backward-compatible id.
#   The two domains must NOT be unified: authorization/experiment identity use the
#   TargetSpec hash here; the freeze manifest keeps the legacy id for continuity.
#   See reports/retraining/PREP001_BASELINE_IMPLEMENTATION_FINAL_AUDIT.md §Hash Domain.

TARGET_T1 = "T1"
TARGET_T3 = "T3"
VALID_TARGET_TYPES = (TARGET_T1, TARGET_T3)


def canonical_json(payload: Dict[str, Any]) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TargetSpec:
    """Immutable description of a single target definition."""

    target_type: str
    formula: str
    required_columns: Tuple[str, ...]
    effective_horizon: int
    label_rule: str

    # ------------------------------------------------------------------
    # Version / hash
    # ------------------------------------------------------------------
    def version_payload(self, horizon: int) -> Dict[str, Any]:
        return {
            "target_type": self.target_type,
            "formula": self.formula,
            "horizon": int(horizon),
            "effective_horizon": int(self.effective_horizon),
            "timestamp_convention": TIMESTAMP_CONVENTION,
            "label_rule": self.label_rule,
            "required_columns": list(self.required_columns),
            "hash_version": TARGET_HASH_VERSION,
        }

    def target_hash(self, horizon: int) -> str:
        return _sha256_hex(canonical_json(self.version_payload(horizon)))

    def target_definition_version(self, horizon: int) -> Dict[str, Any]:
        digest = self.target_hash(horizon)
        return {
            "id": f"target-{self.target_type.lower()}-{digest[:16]}",
            "hash": digest,
            "target_type": self.target_type,
            "definition": self.version_payload(horizon),
            "supported": True,
        }


def _build_t1(horizon: int) -> TargetSpec:
    return TargetSpec(
        target_type=TARGET_T1,
        formula="close_to_close",
        required_columns=("close",),
        effective_horizon=int(horizon),
        label_rule="y[t]=1 if Close[t+h]/Close[t]-1 > 0 else 0",
    )


def _build_t3(horizon: int) -> TargetSpec:
    return TargetSpec(
        target_type=TARGET_T3,
        formula="open_to_open",
        required_columns=("open",),
        effective_horizon=int(horizon) + 1,
        label_rule="y[t]=1 if Open[t+h+1]/Open[t+1]-1 > 0 else 0",
    )


def get_target_spec(target_type: str, horizon: int) -> TargetSpec:
    """Return the immutable spec for ``target_type`` at ``horizon``."""
    tt = str(target_type).strip().upper()
    if tt == TARGET_T1:
        return _build_t1(horizon)
    if tt == TARGET_T3:
        return _build_t3(horizon)
    raise ValueError(f"Unknown target_type: {target_type!r} (expected one of {VALID_TARGET_TYPES})")


def _finite_positive(series: np.ndarray) -> np.ndarray:
    return np.isfinite(series) & (series > 0)


def compute_return_t1(df: pd.DataFrame, horizon: int) -> np.ndarray:
    """T1 forward return: Close[t+h]/Close[t]-1. Future-labelled NaN tail."""
    if "close" not in df:
        raise ValueError("T1 requires 'close' column")
    close = df["close"].to_numpy(dtype=float)
    n = len(close)
    fwd = np.full(n, np.nan, dtype=float)
    if horizon < n:
        fwd[:-horizon] = close[horizon:] / close[:-horizon] - 1.0
    return fwd


def compute_return_t3(df: pd.DataFrame, horizon: int) -> np.ndarray:
    """T3 forward return: Open[t+h+1]/Open[t+1]-1.

    Requires the open of bar t+1 (entry) and bar t+h+1 (exit); the last h+1
    rows therefore have no label.
    """
    if "open" not in df:
        raise ValueError("T3 requires 'open' column")
    op = df["open"].to_numpy(dtype=float)
    n = len(op)
    fwd = np.full(n, np.nan, dtype=float)
    span = horizon + 1
    # Valid labels exist only where t+1 and t+h+1 (== t+span) are both in range.
    # This explicit loop is the single source of truth for the T3 return:
    #   return_t3[t] = Open[t+1+horizon] / Open[t+1] - 1
    for t in range(0, n - span):
        entry = op[t + 1]
        exit_ = op[t + 1 + horizon]
        if np.isfinite(entry) and np.isfinite(exit_) and entry > 0 and exit_ > 0:
            fwd[t] = exit_ / entry - 1.0
    return fwd


def compute_target(df: pd.DataFrame, horizon: int, target_type: str) -> Tuple[np.ndarray, np.ndarray]:
    """Return (signed_return, binary_label) for the requested target.

    The binary label is NaN (excluded via caller mask) where the return is not
    finite; callers mask on ``np.isfinite(return)``.
    """
    tt = str(target_type).strip().upper()
    if tt == TARGET_T1:
        fwd = compute_return_t1(df, horizon)
    elif tt == TARGET_T3:
        fwd = compute_return_t3(df, horizon)
    else:
        raise ValueError(f"Unknown target_type: {target_type!r}")
    # Binary label where return is finite; use -1 sentinel masked out by caller.
    y = np.full(len(fwd), -1, dtype=int)
    finite = np.isfinite(fwd)
    y[finite] = (fwd[finite] > 0).astype(int)
    return fwd, y


def build_target_mask(features: pd.DataFrame, fwd: np.ndarray, target_type: str,
                      horizon: int) -> np.ndarray:
    """Independent target mask: valid features AND a usable label for the target.

    T1 needs Close[t+h]; T3 needs Open[t+1], Open[t+h+1]. The finite-return
    check already enforces the correct trailing-row exclusion per target, and
    zero/negative prices are already excluded from the return.
    """
    feature_ok = features.notna().all(axis=1).to_numpy() & np.isfinite(fwd)
    return feature_ok


def required_trailing_unlabelled(target_type: str, horizon: int) -> int:
    """Number of trailing rows that cannot carry a label for this target."""
    spec = get_target_spec(target_type, horizon)
    return spec.effective_horizon

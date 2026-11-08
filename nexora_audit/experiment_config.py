"""PREP-001 LightGBM experiment configurations A/B/C (human-approved).

These are EXPERIMENT-ONLY configurations. They are NOT a production freeze and
are NOT wired into nexora_intelligence.model.create_model by default; that
wiring must be an explicit, later, human-approved step after the sweep.

Approved values (PREP-001 Decision Review, Phase 2):
    A: max_depth=-1, reg_alpha=0.0  (baseline; reproduces implicit defaults)
    B: max_depth=4,  reg_alpha=0.1  (primary candidate)
    C: max_depth=3,  reg_alpha=0.5  (conservative comparator)

max_depth=-1 / reg_alpha=0.0 are LightGBM defaults, so A is behaviour-neutral.
All shared fixed params come from create_model() (num_leaves=15, lr=0.03,
min_child_samples=100, colsample 0.8, subsample 0.8, reg_lambda=5).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

EXPERIMENT_ONLY = True  # sentinel: never freezes production


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    max_depth: int
    reg_alpha: float
    profile: str
    production_freeze: bool = False  # always False for experiments

    def as_overrides(self) -> Dict[str, object]:
        """Params to merge onto create_model()'s fixed kwargs for the sweep."""
        return {"max_depth": self.max_depth, "reg_alpha": self.reg_alpha}


BUDGET_CANDIDATES: Dict[str, ExperimentConfig] = {
    "A": ExperimentConfig(
        name="A", max_depth=-1, reg_alpha=0.0,
        profile="baseline: reproduces current implicit defaults; zero behaviour change",
    ),
    "B": ExperimentConfig(
        name="B", max_depth=4, reg_alpha=0.1,
        profile="primary: depth 4 (~16 leaves) aligns with num_leaves=15; mild L1",
    ),
    "C": ExperimentConfig(
        name="C", max_depth=3, reg_alpha=0.5,
        profile="conservative comparator: depth 3 caps below num_leaves=15 (higher underfit risk)",
    ),
}

ALLOWED_NAMES = frozenset(BUDGET_CANDIDATES)


def get_candidate(name: str) -> ExperimentConfig:
    key = (name or "").strip().upper()
    if key not in BUDGET_CANDIDATES:
        raise KeyError(f"unknown candidate {name!r}; allowed: {sorted(ALLOWED_NAMES)}")
    return BUDGET_CANDIDATES[key]


def validate_all() -> Dict[str, bool]:
    """Structural sanity checks that all candidates are experiment-only."""
    checks = {}
    for key, cfg in BUDGET_CANDIDATES.items():
        checks[f"{key}_is_experiment"] = cfg.production_freeze is False
        checks[f"{key}_depth_int"] = isinstance(cfg.max_depth, int)
        checks[f"{key}_alpha_float"] = isinstance(cfg.reg_alpha, float)
    return checks


def summary() -> Dict[str, Dict[str, object]]:
    return {
        k: {
            "max_depth": v.max_depth,
            "reg_alpha": v.reg_alpha,
            "profile": v.profile,
            "production_freeze": v.production_freeze,
        }
        for k, v in BUDGET_CANDIDATES.items()
    }


# ---------------------------------------------------------------------------------
# Dual-target experiment identity (T1 statistical / T3 execution-aligned)
# ---------------------------------------------------------------------------------
import hashlib
import json

from nexora_learning.targets import (
    VALID_TARGET_TYPES,
    get_target_spec,
)

EXECUTION_ID = "PREP-001"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def model_config_hash(candidate: str) -> str:
    """Deterministic hash of a candidate's overrides (candidate + identity)."""
    cfg = get_candidate(candidate)
    payload = {"candidate": cfg.name, "overrides": cfg.as_overrides()}
    return _sha256_hex(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def experiment_id(target_type: str, candidate: str) -> str:
    """``PREP-001-{T1|T3}-{A|B|C}`` -- unique per (target, candidate)."""
    tt = (target_type or "").strip().upper()
    if tt not in VALID_TARGET_TYPES:
        raise ValueError(f"unknown target_type {target_type!r}; allowed: {VALID_TARGET_TYPES}")
    cand = get_candidate(candidate).name  # validates A/B/C
    return f"{EXECUTION_ID}-{tt}-{cand}"


def build_experiment_identity(
    target_type: str,
    candidate: str,
    horizon: int,
    *,
    feature_set_version: str | None = None,
    split_policy_version: str | None = None,
    timing_contract_version: str | None = None,
    dataset_hash: str | None = None,
    instrument: str = "EURUSD",
    timeframe: str = "M30",
) -> Dict[str, object]:
    """Assemble a fully isolated experiment identity for one target/candidate.

    T1 and T3 identities are never merged: ``target_type``, target version and
    target hash differ, so experiment_id / artifact namespaces cannot collide.
    """
    tt = (target_type or "").strip().upper()
    if tt not in VALID_TARGET_TYPES:
        raise ValueError(f"unknown target_type {target_type!r}; allowed: {VALID_TARGET_TYPES}")
    spec = get_target_spec(tt, horizon)
    tver = spec.target_definition_version(horizon)
    return {
        "experiment_id": experiment_id(tt, candidate),
        "execution_id": EXECUTION_ID,
        "target_type": tt,
        "target_definition_version": tver["id"],
        "target_hash": tver["hash"],
        "feature_set_version": feature_set_version,
        "split_policy_version": split_policy_version,
        "timing_contract_version": timing_contract_version,
        "model_config_hash": model_config_hash(candidate),
        "dataset_hash": dataset_hash,
        "instrument": instrument,
        "timeframe": timeframe,
        "horizon": int(horizon),
        "effective_horizon": spec.effective_horizon,
        "artifact_namespace": tt.lower(),  # T1->t1, T3->t3
    }


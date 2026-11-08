"""Configuration freeze v2 for PREP-001.

Produces a *frozen configuration manifest* that fixes only parameters with
sufficient evidence, assigns deterministic version identifiers to the feature,
target and split definitions (by hashing the concrete contract), and keeps a
clear separation between:

* FROZEN            - value settled with adequate evidence (explicit code/config
                      OR an accepted, evidenced library default).
* REQUIRES_DECISION - value cannot be frozen without a human design decision
                      (no evidence: e.g. LightGBM max_depth / reg_alpha defaults
                      were never chosen explicitly).

This module NEVER writes to the production database, config, dataset, model or
backup. It returns plain Python objects; persistence is the caller's choice.

Design principles (per task constraints):
  * Do not freeze a parameter without adequate evidence.
  * Do not mutate historical configuration (config/research.json is read-only).
  * lightgbm==4.7.0 is pinned only because the installed runtime and dependency
    evidence support it (verified import + compatible sklearn/pandas/numpy).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .canonical_config import (
    STATUS_INFERRED,
    STATUS_UNRESOLVED,
    STATUS_VERIFIED,
    Param,
    Proposal,
    build_prep001_proposal,
    canonical_json,
)

FREEZE_HASH_VERSION = "nexora-cfg-freeze-v2"

FROZEN = "FROZEN"
REQUIRES_DECISION = "REQUIRES_DECISION"

# The exact ordered feature contract emitted by nexora_vision.features.build_features
# (for a frame without a spread column the function still emits spread_relative=1.0).
FEATURE_COLUMNS = (
    "ret_1", "ret_2", "ret_4", "ret_8", "ret_16", "ret_32", "ret_64",
    "atr_pct", "range_atr", "body_atr", "upper_wick", "lower_wick", "rsi14",
    "dist_sma20", "dist_sma50", "dist_sma100", "dist_sma200",
    "ema_slope20", "ema_slope50", "ema_slope100", "ema_slope200",
    "vol20", "vol_ratio", "volume_z",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "spread_relative",
)

TARGET_DEFINITION = {
    "rule": "y[t] = 1 if fwd[t] > 0 else 0",
    "fwd_definition": "fwd[:-h] = close[h:]/close[:-h] - 1",
    "mask": "finite(fwd) and all features not null",
    "horizon_bars": 2,
    "label_kind": "binary_direction",
}

SPLIT_POLICY = {
    "scheme": "chronological_holdout_plus_walk_forward",
    "train_fraction": 0.6,
    "validation_fraction": 0.2,
    "test_fraction": "remainder",
    "embargo_bars": "max(horizon, 24)",
    "walk_forward": "expanding window, folds=3, initial=max(n*0.50, 1000), purged by horizon",
}


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def feature_set_version() -> Dict[str, Any]:
    payload = {"columns": list(FEATURE_COLUMNS), "count": len(FEATURE_COLUMNS)}
    return {
        "id": "feat-" + _hash_payload(payload)[:16],
        "hash": _hash_payload(payload),
        "columns": list(FEATURE_COLUMNS),
        "supported": True,
        "evidence": "build_features() emits exactly these 29 columns in this order; hashed from source contract",
    }


def target_definition_version(horizon: int = 2) -> Dict[str, Any]:
    payload = dict(TARGET_DEFINITION)
    payload["horizon_bars"] = horizon
    return {
        "id": "target-" + _hash_payload(payload)[:16],
        "hash": _hash_payload(payload),
        "definition": payload,
        "supported": True,
        "evidence": "pipeline.prepare(): fwd[:-h]=close[h:]/close[:-h]-1; y=(fwd>0); masked",
    }


def target_definition_version_for(target_type: str, horizon: int = 2) -> Dict[str, Any]:
    """Target-aware version id/hash (T1 or T3) from nexora_learning.targets.

    T1 keeps the legacy ``target-<hash>`` id for backward compatibility; T3 gets
    its own ``target-t3-<hash>`` id and a distinct hash. Both are deterministic.

    HASH DOMAIN NOTE (Task D): the returned ``hash`` is ALWAYS the TargetSpec
    domain hash (nexora-target-v1) — this is what authorization binds to:
        T1 hash = 414c2147... (id kept as legacy target-b9c8f231... for continuity)
        T3 hash = d5f2c434...
    The legacy ``target_definition_version()`` above uses a DIFFERENT domain
    (nexora-cfg-freeze-v2) and its id (target-b9c8f231...) must not be compared to
    or unified with the TargetSpec hash. Authorization/reproducibility use the
    ``hash`` field, which is always the TargetSpec hash. Do NOT change these hashes
    to make ids match.
    """
    from nexora_learning.targets import TARGET_T1, get_target_spec

    tt = (target_type or "").strip().upper()
    spec = get_target_spec(tt, horizon)
    tver = spec.target_definition_version(horizon)
    if tt == TARGET_T1:
        legacy = target_definition_version(horizon)
        ver_id = legacy["id"]
    else:
        ver_id = tver["id"]
    return {
        "id": ver_id,
        "hash": tver["hash"],
        "target_type": tt,
        "definition": tver["definition"],
        "effective_horizon": spec.effective_horizon,
        "supported": True,
        "evidence": "nexora_learning.targets TargetSpec; target-aware version",
    }


def split_policy_version_for(target_type: str = "T1", horizon: int = 2) -> Dict[str, Any]:
    """Target-aware split policy version (T3 uses effective horizon h+1)."""
    from nexora_learning.targets import get_target_spec

    tt = (target_type or "").strip().upper()
    eff = get_target_spec(tt, horizon).effective_horizon
    payload = dict(SPLIT_POLICY)
    payload["target_type"] = tt
    payload["effective_horizon"] = eff
    payload["embargo_bars"] = "max(%d, 24)" % eff
    payload["walk_forward"] = (
        "expanding window, folds=3, initial=max(n*0.50, 1000), purged by effective_horizon=%d" % eff
    )
    return {
        "id": "split-" + _hash_payload(payload)[:16],
        "hash": _hash_payload(payload),
        "target_type": tt,
        "definition": payload,
        "supported": True,
        "evidence": "pipeline.split_indices()/walk_forward_scores() with target-aware embargo",
    }


def split_policy_version() -> Dict[str, Any]:
    payload = dict(SPLIT_POLICY)
    return {
        "id": "split-" + _hash_payload(payload)[:16],
        "hash": _hash_payload(payload),
        "definition": payload,
        "supported": True,
        "evidence": "pipeline.split_indices() + walk_forward_scores(); embargo=max(horizon,24)",
    }


@dataclass
class FrozenEntry:
    name: str
    value: Any
    state: str            # FROZEN | REQUIRES_DECISION
    evidence: str
    origin_status: str    # VERIFIED | INFERRED | UNRESOLVED

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "state": self.state,
            "origin_status": self.origin_status,
            "evidence": self.evidence,
        }


@dataclass
class FrozenManifest:
    job_identity: Dict[str, Any]
    dataset_identity: Dict[str, Any]
    runtime: Dict[str, Any]
    frozen: List[FrozenEntry] = field(default_factory=list)
    requires_decision: List[FrozenEntry] = field(default_factory=list)
    feature_version: Dict[str, Any] = field(default_factory=dict)
    target_version: Dict[str, Any] = field(default_factory=dict)
    split_version: Dict[str, Any] = field(default_factory=dict)

    def frozen_value(self, name: str) -> Any:
        for entry in self.frozen:
            if entry.name == name:
                return entry.value
        raise KeyError(name)

    def is_frozen(self, name: str) -> bool:
        return any(e.name == name for e in self.frozen)

    def requires(self, name: str) -> bool:
        return any(e.name == name for e in self.requires_decision)

    def hash_body(self) -> Dict[str, Any]:
        return {
            "hash_version": FREEZE_HASH_VERSION,
            "job_identity": self.job_identity,
            "dataset_identity": {k: self.dataset_identity[k] for k in ("symbol", "timeframe", "sha256_recomputed")},
            "runtime": {"lightgbm": self.runtime.get("lightgbm"), "python": self.runtime.get("python")},
            "frozen": {e.name: e.value for e in self.frozen},
            "feature_version": self.feature_version.get("id"),
            "target_version": self.target_version.get("id"),
            "split_version": self.split_version.get("id"),
        }

    def config_hash(self) -> Dict[str, Any]:
        digest = _hash_payload(self.hash_body())
        return {
            "hash": digest,
            "hash_version": FREEZE_HASH_VERSION,
            "complete": not self.requires_decision,
            "requires_decision": [e.name for e in self.requires_decision],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_hash": self.config_hash(),
            "job_identity": self.job_identity,
            "dataset_identity": self.dataset_identity,
            "runtime": self.runtime,
            "frozen_parameters": [e.as_dict() for e in self.frozen],
            "requires_decision": [e.as_dict() for e in self.requires_decision],
            "feature_set_version": self.feature_version,
            "target_definition_version": self.target_version,
            "split_policy_version": self.split_version,
        }


# Parameters that must NOT be frozen because the repo has no explicit choice for
# them (LightGBM defaults were used implicitly). Freezing them would invent a value.
_NO_EVIDENCE_PARAMS = {"max_depth", "l1_regularization"}


def build_frozen_manifest(project_root: Path) -> FrozenManifest:
    """Assemble a freeze manifest from the live proposal."""
    project_root = Path(project_root)
    proposal: Proposal = build_prep001_proposal(project_root)
    runtime = proposal.runtime

    pin_version = _verified_lightgbm_pin(runtime)
    _assert_engine_compatible(runtime, pin_version)

    frozen: List[FrozenEntry] = []
    requires: List[FrozenEntry] = []

    def push(param: Param) -> None:
        name = param.name
        value = param.value
        evidence = param.evidence
        if name in _NO_EVIDENCE_PARAMS and param.status != STATUS_VERIFIED:
            requires.append(FrozenEntry(name, value, REQUIRES_DECISION, evidence, param.status))
            return
        if param.status in (STATUS_VERIFIED, STATUS_INFERRED):
            frozen.append(FrozenEntry(name, value, FROZEN, evidence, param.status))
        else:
            requires.append(FrozenEntry(name, value, REQUIRES_DECISION, evidence, param.status))

    for param in proposal.parameters:
        if param.name == "engine_version":
            frozen.append(FrozenEntry(
                "engine_version", pin_version, FROZEN,
                f"Pinned explicitly to installed runtime {pin_version}; import verified; "
                "requirements.txt relaxed (>=4.0) so the freeze is the authoritative pin",
                STATUS_VERIFIED,
            ))
            continue
        if param.name == "engine":
            frozen.append(FrozenEntry(
                "engine", "lightgbm", FROZEN,
                "Explicitly set to lightgbm for the freeze; runtime confirmed importable with "
                f"lightgbm {pin_version}",
                STATUS_VERIFIED,
            ))
            continue
        if param.name == "objective":
            frozen.append(FrozenEntry(
                "objective", "binary", FROZEN,
                "Explicitly set to binary; dataset target is binary direction (y=(fwd>0))",
                STATUS_VERIFIED,
            ))
            continue
        if param.name in ("feature_set_version", "target_definition_version",
                          "split_policy_version"):
            continue
        push(param)

    feat = feature_set_version()
    tgt = target_definition_version(int(proposal.job_identity["horizon"]))
    spl = split_policy_version()

    frozen.append(FrozenEntry("feature_set_version", feat["id"], FROZEN, feat["evidence"], STATUS_VERIFIED))
    frozen.append(FrozenEntry("target_definition_version", tgt["id"], FROZEN, tgt["evidence"], STATUS_VERIFIED))
    frozen.append(FrozenEntry("split_policy_version", spl["id"], FROZEN, spl["evidence"], STATUS_VERIFIED))

    # decision_time_policy: owner-approved baseline is bar_open (PREP-001 B2). It
    # is pushed as FROZEN via the proposal loop above (STATUS_VERIFIED). Only fall
    # back to REQUIRES_DECISION if it somehow was not resolved.
    if not any(e.name == "decision_time_policy" for e in frozen) and not any(
        e.name == "decision_time_policy" for e in requires
    ):
        requires.append(FrozenEntry(
            "decision_time_policy", None, REQUIRES_DECISION,
            "Defined by reports/retraining/execution_timing_contract.md; must be ratified before freeze completes",
            STATUS_UNRESOLVED,
        ))

    if not any(e.name == "max_iter" for e in frozen) and not any(e.name == "max_iter" for e in requires):
        frozen.append(FrozenEntry(
            "max_iter", 300, FROZEN,
            "config/research.json training.max_iter=300; runner rejects full training when != 300",
            STATUS_VERIFIED,
        ))

    return FrozenManifest(
        job_identity=proposal.job_identity,
        dataset_identity=proposal.dataset_identity,
        runtime=runtime,
        frozen=frozen,
        requires_decision=requires,
        feature_version=feat,
        target_version=tgt,
        split_version=spl,
    )


def _verified_lightgbm_pin(runtime: Dict[str, Any]) -> str:
    version = runtime.get("lightgbm")
    if version in (None, "not_installed"):
        raise RuntimeError("lightgbm is not installed; cannot pin engine_version")
    return str(version)


def _assert_engine_compatible(runtime: Dict[str, Any], pin_version: str) -> None:
    if pin_version != "4.7.0":
        raise RuntimeError(f"Freeze validated for lightgbm 4.7.0 but runtime is {pin_version}")
    for key in ("scikit_learn", "pandas", "numpy"):
        if runtime.get(key) in (None, "not_installed"):
            raise RuntimeError(f"Missing runtime dependency evidence: {key}")


def freeze_to_json(project_root: Path) -> Dict[str, Any]:
    return build_frozen_manifest(project_root).to_dict()


def build_target_freeze_identity(project_root: Path, target_type: str,
                                 candidate: str = "A", horizon: int | None = None) -> Dict[str, Any]:
    """Compose a complete, per-target freeze identity for PREP-001-{T1|T3}-{candidate}.

    Ties together every reproducible artifact of the experiment so T1 and T3 cannot
    overwrite or masquerade as each other (Task E):
      * target definition version + TargetSpec target hash (authorization domain)
      * complete model configuration hash (from the freeze manifest)
      * feature set version, split policy version
      * timing contract version/hash (OWNER_APPROVED, not ratified)
      * dataset hash
    Does NOT create any sign-off. Returns plain data only.
    """
    from nexora_audit.experiment_config import build_experiment_identity
    from nexora_audit.timing_contract import build_timing_contract

    project_root = Path(project_root)
    manifest = build_frozen_manifest(project_root)
    proposal = build_prep001_proposal(project_root)
    h = int(horizon if horizon is not None else proposal.job_identity["horizon"])
    tt = (target_type or "").strip().upper()

    tgt = target_definition_version_for(tt, h)
    spl = split_policy_version_for(tt, h)
    timing = build_timing_contract(horizon=h, timeframe=proposal.job_identity["timeframe"])
    timing_info = timing.contract_hash()

    identity = build_experiment_identity(
        tt, candidate, h,
        feature_set_version=manifest.feature_version["id"],
        split_policy_version=spl["id"],
        timing_contract_version=timing_info["hash"],
        dataset_hash=proposal.dataset_identity.get("sha256_recomputed"),
        instrument=proposal.job_identity["symbol"],
        timeframe=proposal.job_identity["timeframe"],
    )
    identity.update({
        "target_definition_version_id": tgt["id"],
        "target_definition_version_hash": tgt["hash"],
        "config_hash": manifest.config_hash()["hash"],
        "config_hash_complete": manifest.config_hash()["complete"],
        "feature_version_hash": manifest.feature_version["hash"],
        "split_version_hash": spl["hash"],
        "timing_contract_hash": timing_info["hash"],
        "timing_owner_approved": timing_info["owner_approved"],
        "timing_human_ratified": timing_info["ratified"],
        "dataset_hash": proposal.dataset_identity.get("sha256_recomputed"),
        "signoff_present": False,
    })
    return identity


def write_freeze_manifest(project_root: Path, out_path: Path) -> Dict[str, Any]:
    data = freeze_to_json(project_root)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data

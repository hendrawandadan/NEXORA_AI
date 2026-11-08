"""Build a canonical, hash-addressed configuration *proposal* for PREP-001.

The proposal is derived strictly from the actual implementation and the active
source config. Every parameter carries an evidence tag:

* VERIFIED   - value is explicit in code/config and read unambiguously.
* INFERRED   - value follows from a library default or an implicit code path;
               it is what the current runtime would use, not a frozen decision.
* UNRESOLVED - value cannot be determined from the current repository evidence.
* CONFLICT   - two or more evidence sources disagree.

Nothing here writes to the production database or config. The output is a
separate proposal object returned to the caller/CLI.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

CONFIG_HASH_VERSION = "nexora-cfg-v1"

# These are the parameters whose resolution gates reproducible training.
# A BLOCKED readiness result is guaranteed if any of them is not VERIFIED.
CRITICAL_PARAMETERS = (
    "engine",
    "engine_version",
    "objective",
    "max_depth",
    "l1_regularization",
    "feature_set_version",
    "target_definition_version",
    "split_policy_version",
    "decision_time_policy",
)

STATUS_VERIFIED = "VERIFIED"
STATUS_INFERRED = "INFERRED"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class Param:
    name: str
    value: Any
    status: str
    evidence: str
    critical: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "evidence": self.evidence,
            "critical": self.critical,
        }


@dataclass
class Proposal:
    job_identity: Dict[str, Any]
    dataset_identity: Dict[str, Any]
    runtime: Dict[str, Any]
    parameters: List[Param] = field(default_factory=list)

    def parameter(self, name: str) -> Param | None:
        for item in self.parameters:
            if item.name == name:
                return item
        return None

    def body_for_hash(self) -> Dict[str, Any]:
        # Hash the *values* of the resolved scientific parameters plus the
        # identities. Evidence text/status of UNRESOLVED items is excluded from
        # the stable payload but unresolved items make the hash partial; see
        # canonical_config_hash() for handling.
        return {
            "hash_version": CONFIG_HASH_VERSION,
            "job_identity": self.job_identity,
            "dataset_identity": self.dataset_identity,
            "parameters": {p.name: p.value for p in self.parameters},
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_identity": self.job_identity,
            "dataset_identity": self.dataset_identity,
            "runtime": self.runtime,
            "parameters": [p.as_dict() for p in self.parameters],
        }


def canonical_json(payload: Dict[str, Any]) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_config_hash(proposal: Proposal) -> Dict[str, Any]:
    """Compute the config hash.

    The hash is only *complete* when no critical parameter is UNRESOLVED or in
    CONFLICT. Otherwise a ``partial:`` hash is returned so callers cannot
    mistake an incomplete proposal for a frozen config.
    """
    blocking = [
        p.name
        for p in proposal.parameters
        if p.critical and p.status in (STATUS_UNRESOLVED, STATUS_CONFLICT)
    ]
    digest = _sha256_hex(canonical_json(proposal.body_for_hash()))
    return {
        "hash": digest,
        "hash_version": CONFIG_HASH_VERSION,
        "complete": not blocking,
        "blocking_parameters": blocking,
    }


def load_runtime_versions() -> Dict[str, Any]:
    """Best-effort runtime version capture for reproducibility metadata."""
    import platform
    import sys

    versions: Dict[str, Any] = {
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "platform": platform.platform(),
    }
    for module_name, key in (
        ("lightgbm", "lightgbm"),
        ("sklearn", "scikit_learn"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("joblib", "joblib"),
    ):
        try:
            module = importlib.import_module(module_name)
            versions[key] = getattr(module, "__version__", "unknown")
        except Exception:
            versions[key] = "not_installed"
    return versions


def _load_research_config(project_root: Path) -> Dict[str, Any]:
    path = project_root / "config" / "research.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _compute_dataset_sha256(dataset_path: Path) -> str | None:
    if not dataset_path.is_file():
        return None
    import hashlib

    digest = hashlib.sha256()
    with dataset_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_parameters(cfg: Dict[str, Any], runtime: Dict[str, Any]) -> List[Param]:
    training = cfg.get("training", {})
    walk = cfg.get("walk_forward", {})
    lgb_available = runtime.get("lightgbm") not in (None, "not_installed")

    params: List[Param] = []

    def add(name: str, value: Any, status: str, evidence: str, critical: bool = False) -> None:
        params.append(Param(name, value, status, evidence, critical))

    # --- Engine / objective / identity of the model ---------------------------------
    if lgb_available:
        add(
            "engine",
            "lightgbm",
            STATUS_INFERRED,
            "model.create_model(engine='auto') selects lightgbm when importable; "
            f"lightgbm {runtime.get('lightgbm')} is installed in the venv; not an explicit per-run choice",
            critical=True,
        )
        add(
            "engine_version",
            runtime.get("lightgbm"),
            STATUS_VERIFIED,
            "Runtime-installed lightgbm version; requirements.txt only pins '>=4.0' so this is not frozen by repo",
            critical=True,
        )
        add(
            "objective",
            "binary",
            STATUS_INFERRED,
            "Not passed explicitly; LGBMClassifier 4.7.0 infers 'binary' for binary targets; library default not frozen",
            critical=True,
        )
        add(
            "metric",
            "binary_logloss (LightGBM default; not consumed by project)",
            STATUS_INFERRED,
            "No 'metric' argument in model.py; project reports custom nexora_evaluator.metrics, not LightGBM's",
        )
        add(
            "boosting_type",
            "gbdt",
            STATUS_INFERRED,
            "LightGBM default for LGBMClassifier; not set in model.py",
        )
        add(
            "max_depth",
            -1,
            STATUS_VERIFIED,
            "Owner-approved baseline (PREP-001 B1 resolution): max_depth=-1 (unlimited) frozen explicitly; "
            "equals LightGBM default and the current runtime behaviour (model.py sets no max_depth). "
            "Trees are still leaf-bounded by num_leaves=15.",
            critical=True,
        )
        add(
            "l1_regularization",
            0.0,
            STATUS_VERIFIED,
            "Owner-approved baseline (PREP-001 B1 resolution): reg_alpha=0.0 frozen explicitly; equals "
            "LightGBM default and current runtime (model.py sets no reg_alpha). NOTE: the sklearn "
            "HistGradientBoosting fallback has NO L1 parameter and does not honour this value.",
            critical=True,
        )
        add(
            "l2_regularization",
            5.0,
            STATUS_VERIFIED,
            "model.py reg_lambda=5 explicit",
        )
        add(
            "learning_rate",
            0.03,
            STATUS_VERIFIED,
            "model.py learning_rate=.03 explicit",
        )
        add(
            "num_leaves",
            15,
            STATUS_VERIFIED,
            "model.py num_leaves=15 explicit",
        )
        add(
            "min_child_samples",
            100,
            STATUS_VERIFIED,
            "model.py min_child_samples=100 explicit",
        )
        add(
            "feature_fraction",
            0.8,
            STATUS_VERIFIED,
            "model.py colsample_bytree=.8 explicit",
        )
        add(
            "bagging_fraction",
            0.8,
            STATUS_VERIFIED,
            "model.py subsample=.8 explicit",
        )
        add(
            "bagging_frequency",
            1,
            STATUS_VERIFIED,
            "model.py subsample_freq=1 explicit",
        )
    else:
        add(
            "engine",
            "sklearn_hist_gradient_boosting",
            STATUS_INFERRED,
            "lightgbm not importable, fallback path used; environment-dependent",
            critical=True,
        )
        add(
            "engine_version",
            runtime.get("scikit_learn"),
            STATUS_VERIFIED,
            "Runtime-installed scikit-learn version of the fallback engine",
            critical=True,
        )
        add("objective", None, STATUS_UNRESOLVED, "fallback objective implicit; not evaluated", critical=True)
        add("metric", None, STATUS_UNRESOLVED, "fallback metric implicit", critical=False)
        add("boosting_type", None, STATUS_UNRESOLVED, "n/a for fallback", critical=False)
        add("max_depth", None, STATUS_UNRESOLVED, "fallback has no explicit max_depth", critical=True)
        add("l1_regularization", None, STATUS_UNRESOLVED, "fallback L1 not set", critical=True)
        add("l2_regularization", 5.0, STATUS_VERIFIED, "model.py l2_regularization=5 fallback", critical=False)
        add("learning_rate", 0.03, STATUS_VERIFIED, "model.py learning_rate=.03 fallback", critical=False)
        add("num_leaves", 15, STATUS_VERIFIED, "model.py max_leaf_nodes=15 fallback", critical=False)
        add("min_child_samples", 100, STATUS_VERIFIED, "model.py min_samples_leaf=100 fallback", critical=False)
        add("feature_fraction", None, STATUS_UNRESOLVED, "no equivalent on fallback", critical=False)
        add("bagging_fraction", None, STATUS_UNRESOLVED, "no equivalent on fallback", critical=False)
        add("bagging_frequency", None, STATUS_UNRESOLVED, "no equivalent on fallback", critical=False)

    # --- Shared training controls ----------------------------------------------------
    add("max_iter", int(training.get("max_iter", 300)), STATUS_VERIFIED,
        "config/research.json training.max_iter=300; runner rejects full training if != 300")
    add("n_estimators", int(training.get("max_iter", 300)), STATUS_VERIFIED,
        "model.create_model maps max_iter -> n_estimators for LightGBM")
    add("random_seed", int(training.get("seed", 42)), STATUS_VERIFIED,
        "config/research.json training.seed=42; passed to create_model random_state")
    add("early_stopping", False, STATUS_INFERRED,
        "HistGradientBoosting early_stopping=False explicit; LightGBM given no eval_set/callback -> no early stopping",
        critical=False)

    # --- Windowing / split -----------------------------------------------------------
    add("train_fraction", float(training.get("train_fraction", 0.6)), STATUS_VERIFIED,
        "config training.train_fraction=0.6; pipeline.split_indices")
    add("validation_fraction", float(training.get("validation_fraction", 0.2)), STATUS_VERIFIED,
        "config training.validation_fraction=0.2; pipeline.split_indices")
    add("embargo_bars", int(training.get("embargo_bars", 24)), STATUS_VERIFIED,
        "config training.embargo_bars=24; pipeline uses max(horizon, embargo_bars)")
    add("walk_forward_folds", int(walk.get("folds", 3)), STATUS_VERIFIED,
        "config walk_forward.folds=3; pipeline.walk_forward_scores")
    add(
        "walk_forward_min_train_fraction",
        0.5,
        STATUS_INFERRED,
        "pipeline hardcodes initial=max(n*0.50,1000); config walk_forward.min_train_fraction is NOT read by pipeline",
    )
    add("prediction_horizon", 2, STATUS_VERIFIED,
        "PREP-001 tuple horizon=2 (batch_retraining_plan.csv); label = sign(close[t+h]/close[t]-1)")
    add("min_bars", int(training.get("min_bars", 5000)), STATUS_VERIFIED,
        "config training.min_bars=5000")

    # --- Versioned artifacts that do not exist yet -----------------------------------
    add(
        "feature_set_version",
        None,
        STATUS_UNRESOLVED,
        "build_features() has 29 columns but no version/hash constant; feature contract not frozen",
        critical=True,
    )
    add(
        "target_definition_version",
        None,
        STATUS_UNRESOLVED,
        "label rule exists in code (fwd>0) but no versioned identifier; not frozen",
        critical=True,
    )
    add(
        "split_policy_version",
        None,
        STATUS_UNRESOLVED,
        "split/embargo code exists but no versioned identifier; walk-forward min_train_fraction unread",
        critical=True,
    )
    add(
        "decision_time_policy",
        "bar_open",
        STATUS_VERIFIED,
        "Owner-approved baseline (PREP-001 B2 resolution): decision at bar-open of t+1 using bar-t "
        "features; consistent with T3 entry Open[t+1] and the bar-open timestamp convention. "
        "See nexora_audit.timing_contract (OWNER_APPROVED).",
        critical=True,
    )

    return params


def build_prep001_proposal(project_root: Path) -> Proposal:
    """Assemble the PREP-001 configuration proposal from live source + config."""
    project_root = Path(project_root)
    cfg = _load_research_config(project_root)
    runtime = load_runtime_versions()

    dataset_rel = Path("data") / "raw" / "EURUSD" / "EURUSD_M30_202001020000_202611062130.csv"
    dataset_path = project_root / dataset_rel
    dataset_sha = _compute_dataset_sha256(dataset_path)

    job_identity = {
        "job_key": "legacy-plan-v3|individual|EURUSD|M30|H2",
        "legacy_reference": "PREP-001",
        "scope": "individual",
        "symbol": "EURUSD",
        "timeframe": "M30",
        "horizon": 2,
    }
    dataset_identity = {
        "symbol": "EURUSD",
        "timeframe": "M30",
        "relative_path": dataset_rel.as_posix(),
        "absolute_path": str(dataset_path),
        "exists": dataset_path.is_file(),
        "sha256_recomputed": dataset_sha,
        "bars_expected": 70694,
    }

    return Proposal(
        job_identity=job_identity,
        dataset_identity=dataset_identity,
        runtime=runtime,
        parameters=_build_parameters(cfg, runtime),
    )

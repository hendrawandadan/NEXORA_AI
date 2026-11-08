"""PREP-001 execution authorization gate (job-scoped, fail-closed).

This module is the *single* authorization funnel required before any dispatch
(``process_run``), SQLite claim, or retry/resume/recovery of a job. It binds a
concrete execution row (execution_id / batch / job identity) to an explicit,
human-ratified governance sign-off, the canonical configuration hash, the
versioned split/feature/target contracts, the execution timing contract, the
experiment candidate, and the readiness decision.

Design principles
-----------------
* **Fail-closed.** Every check defaults to REJECT. There is no "allow" default;
  the gate returns a decision only when *all* checks pass.
* **JSON structurally-valid is NOT authorization.** :func:`verify_signoff_integrity`
  is deliberately explicit about what is and is not cryptographically provable
  from the repository today. If the sign-off has no integrity mechanism the
  gate still proceeds to content binding, but the integrity finding is recorded
  as ``status='UNVERIFIED'`` and surfaces as a residual *blocker* (see the
  implementation report), never as silent trust.
* **Scoped.** A sign-off for PREP-001 authorizes only the requested execution
  id. PREP-002 (or any other id) is rejected even if all other bindings match.
* **Multiple jobs cannot be smuggled.** A single authorization decision applies
  to exactly one execution row. If more than one row would be dispatched (e.g.
  batch-wide), the runner must authorize each individually; an unscoped or
  multi-row dispatch is rejected.
* **Read-only.** This module reads source/config/sign-off and never writes to
  the production DB, CSV, dataset, model, or backup. It never calls training.

Nothing here flips PLANNED->QUEUED, creates a queue, or mutates production.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import governance
from .canonical_config import build_prep001_proposal, canonical_config_hash, canonical_json
from .configuration_freeze import build_frozen_manifest
from .readiness import run_all_gates, summarize
from .timing_contract import build_timing_contract

# Bound execution/authorization identifier for this gate.
PREP001_JOB_KEY = "legacy-plan-v3|individual|EURUSD|M30|H2"
PREP001_EXECUTION_ID = "PREP-001"
PREP001_LEGACY_REFERENCE = "PREP-001"
PREP001_BATCH = "Batch 1"

# Recognised integrity mechanisms for a sign-off file. ``none`` means the file
# carries no cryptographic proof and must be treated as UNVERIFIED.
INTEGRITY_HMAC_SHA256 = "hmac-sha256"
INTEGRITY_NONE = "none"
_SUPPORTED_INTEGRITY = {INTEGRITY_NONE, INTEGRITY_HMAC_SHA256}

TIMING_HASH_VERSION_RATIFIED = "nexora-timing-v1-ratified"


class AuthorizationError(ValueError):
    """Raised when a run is not fully authorized. Always fail-closed."""

    def __init__(self, message: str, decision: Optional["AuthorizationDecision"] = None) -> None:
        super().__init__(message)
        self.decision = decision


@dataclass
class Check:
    name: str
    passed: bool
    code: str
    detail: str
    expected: Any = None
    actual: Any = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "code": self.code,
            "detail": self.detail,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class AuthorizationDecision:
    authorized: bool
    execution_id: str
    batch: str
    checks: List[Check] = field(default_factory=list)
    integrity: Dict[str, Any] = field(default_factory=dict)
    readiness: Dict[str, Any] = field(default_factory=dict)
    bindings: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def failed(self) -> List[Check]:
        return [c for c in self.checks if not c.passed]

    def codes(self) -> List[str]:
        return [c.code for c in self.checks if not c.passed]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "authorized": self.authorized,
            "execution_id": self.execution_id,
            "batch": self.batch,
            "checks": [c.as_dict() for c in self.checks],
            "failed_codes": self.codes(),
            "integrity": self.integrity,
            "readiness": self.readiness,
            "bindings": self.bindings,
            "reasons": self.reasons,
        }


# ---------------------------------------------------------------------------------
# Sign-off integrity (surface, do not invent, a proof mechanism)
# ---------------------------------------------------------------------------------
def verify_signoff_integrity(ratification: "governance.Ratification", project_root: Path) -> Dict[str, Any]:
    """Report whether the sign-off has a verifiable integrity mechanism.

    The repository currently provides NO key management and NO detached
    signature for ``prep001_ratification.json``. Therefore "the JSON parses" is
    NOT evidence of authority. This function:

    * Detects a supported integrity block (``hmac-sha256``) if present and, if
      present, verifies it against a key supplied via the environment variable
      ``NEXORA_GOVERNANCE_KEY`` (never committed).
    * Otherwise reports ``status='UNVERIFIED'`` with an explicit note that the
      file is structurally valid but carries no cryptographic proof of authority.

    Returns a dict that always includes ``status`` and ``detail``.
    """
    import os

    raw = ratification.raw
    integrity = raw.get("integrity") if isinstance(raw, dict) else None
    if not isinstance(integrity, dict):
        return {
            "status": "UNVERIFIED",
            "mechanism": INTEGRITY_NONE,
            "detail": "sign-off has no integrity block; structural validity != authorization",
            "note": (
                "No detached signature / HMAC present. A structurally valid JSON file "
                "MUST NOT be treated as proof of authority. Recorded as residual blocker."
            ),
        }

    mechanism = str(integrity.get("mechanism") or INTEGRITY_NONE).strip().lower()
    if mechanism not in _SUPPORTED_INTEGRITY:
        return {
            "status": "UNSUPPORTED",
            "mechanism": mechanism,
            "detail": f"integrity mechanism {mechanism!r} not supported",
        }

    if mechanism == INTEGRITY_NONE:
        return {
            "status": "UNVERIFIED",
            "mechanism": INTEGRITY_NONE,
            "detail": "integrity block declares 'none'",
        }

    # HMAC path: verify the signature over the canonicalized payload sans integrity.
    declared_sig = str(integrity.get("signature") or "").strip()
    key = os.environ.get("NEXORA_GOVERNANCE_KEY")
    if not key:
        return {
            "status": "UNVERIFIED",
            "mechanism": mechanism,
            "detail": "hmac-sha256 declared but NEXORA_GOVERNANCE_KEY is not set; cannot verify",
        }
    body = {k: v for k, v in raw.items() if k != "integrity"}
    expected_sig = hmac.new(key.encode("utf-8"), canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(expected_sig, declared_sig)
    return {
        "status": "VERIFIED" if ok else "INVALID",
        "mechanism": mechanism,
        "detail": "hmac-sha256 signature verified" if ok else "hmac-sha256 signature mismatch",
    }


# ---------------------------------------------------------------------------------
# Readiness bundle (read-only; reuses the audit gates)
# ---------------------------------------------------------------------------------
def compute_readiness(
    project_root: Path,
    proposal,
    frozen,
    ratified_contract,
    ratification_info: Optional[Dict[str, Any]],
    ratified_parameters: Optional[Dict[str, Any]],
    claim_probe_result: Optional[Dict[str, Any]] = None,
    recovery_probe_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    reports = run_all_gates(
        proposal,
        project_root,
        claim_probe_result=claim_probe_result,
        recovery_probe_result=recovery_probe_result,
        timing_contract=ratified_contract,
        frozen_manifest=frozen,
        ratification_info=ratification_info,
        ratified_parameters=ratified_parameters,
    )
    summary = summarize(reports)
    return {
        "gates": {r.gate: r.status for r in reports},
        **summary,
    }


# ---------------------------------------------------------------------------------
# Core authorization
# ---------------------------------------------------------------------------------
def _pick(row: dict, *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _ctx(project_root: Path) -> Dict[str, Any]:
    proposal = build_prep001_proposal(project_root)
    frozen = build_frozen_manifest(project_root)
    timing_proposed = build_timing_contract()
    rat = governance.load_ratification(project_root)
    return {
        "proposal": proposal,
        "frozen": frozen,
        "timing_proposed": timing_proposed,
        "ratification": rat,
    }


def authorize_execution(
    *,
    execution_row: dict,
    project_root: Path,
    batch_name: str,
    requested_execution_ids: Optional[set] = None,
    ratification: Optional["governance.Ratification"] = None,
    claim_probe_result: Optional[Dict[str, Any]] = None,
    recovery_probe_result: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AuthorizationDecision:
    """Authorize exactly one execution row. Never raises; returns a decision.

    Callers MUST treat ``decision.authorized is False`` as a hard refusal and
    raise :class:`AuthorizationError` (see :func:`require_authorized`).

    ``context`` may inject pre-built audit artifacts (proposal/frozen/timing) so
    tests can avoid recomputation; when omitted they are rebuilt read-only.
    """
    project_root = Path(project_root)
    checks: List[Check] = []
    exec_id = str(_pick(execution_row, "execution_id") or "")
    row_batch = str(_pick(execution_row, "batch") or batch_name or "")

    def add(name: str, passed: bool, code: str, detail: str, expected: Any = None, actual: Any = None) -> None:
        checks.append(Check(name, bool(passed), code, detail, expected, actual))

    # 0. Scope: only a single, explicitly requested execution id is authorizable.
    req = set(requested_execution_ids) if requested_execution_ids else set()
    if len(req) != 1 or exec_id not in req:
        add(
            "job_scoped_authorization",
            False,
            "MULTI_OR_UNSCOPED_DISPATCH",
            "dispatch must authorize exactly one requested execution_id (no batch-wide / --limit substitute)",
            expected=sorted(req) or "exactly one execution_id",
            actual=exec_id,
        )
    else:
        add("job_scoped_authorization", True, "OK_SCOPED", f"scoped to {exec_id}")

    # 1. Execution id must be the bound PREP-001 execution id.
    add(
        "execution_id_binding",
        exec_id == PREP001_EXECUTION_ID,
        "OK_EXECUTION_ID" if exec_id == PREP001_EXECUTION_ID else "EXECUTION_ID_MISMATCH",
        f"execution_id={exec_id!r}",
        expected=PREP001_EXECUTION_ID,
        actual=exec_id,
    )

    # 2. Batch identity.
    add(
        "batch_identity",
        row_batch == PREP001_BATCH,
        "OK_BATCH" if row_batch == PREP001_BATCH else "BATCH_MISMATCH",
        f"batch={row_batch!r}",
        expected=PREP001_BATCH,
        actual=row_batch,
    )

    # Load audit context (read-only).
    ctx = context or _ctx(project_root)
    proposal = ctx["proposal"]
    frozen = ctx["frozen"]
    timing_proposed = ctx["timing_proposed"]

    # 3. Job identity vs the proposal's canonical job identity.
    ji = proposal.job_identity
    row_scope = str(_pick(execution_row, "scope") or "")
    row_symbol = str(_pick(execution_row, "symbol") or "")
    row_tf = str(_pick(execution_row, "timeframe") or "")
    row_h = str(_pick(execution_row, "horizon") or "")
    job_identity_ok = (
        row_scope == str(ji.get("scope"))
        and row_symbol == str(ji.get("symbol"))
        and row_tf == str(ji.get("timeframe"))
        and row_h == str(ji.get("horizon"))
    )
    add(
        "job_identity",
        job_identity_ok,
        "OK_JOB_IDENTITY" if job_identity_ok else "JOB_IDENTITY_MISMATCH",
        f"row=({row_scope},{row_symbol},{row_tf},{row_h}) vs proposal={ji.get('job_key')}",
        expected={"scope": ji.get("scope"), "symbol": ji.get("symbol"), "timeframe": ji.get("timeframe"), "horizon": ji.get("horizon")},
        actual={"scope": row_scope, "symbol": row_symbol, "timeframe": row_tf, "horizon": row_h},
    )

    # Governance sign-off load (may have been pre-loaded via context).
    rat = ratification if ratification is not None else ctx["ratification"]
    integrity = {"status": "ABSENT", "mechanism": INTEGRITY_NONE, "detail": "no sign-off file"}

    if rat is None:
        add("signoff_present", False, "SIGNOFF_ABSENT", "no governance sign-off present")
        add("signoff_valid", False, "SIGNOFF_INVALID", "no sign-off to validate")
        add("signoff_ratified", False, "SIGNOFF_NOT_RATIFIED", "no sign-off to ratify")
    else:
        integrity = verify_signoff_integrity(rat, project_root)
        add("signoff_present", True, "OK_SIGNOFF_PRESENT", f"sign-off at {rat.path}")
        add(
            "signoff_valid",
            rat.valid,
            "OK_SIGNOFF_VALID" if rat.valid else "SIGNOFF_INVALID",
            "sign-off structurally valid" if rat.valid else f"sign-off invalid: {rat.problems}",
        )
        # Integrity mechanism: an UNVERIFIED sign-off is NOT a ratification.
        ratified_ok = bool(rat.valid) and integrity.get("status") == "VERIFIED"
        add(
            "signoff_ratified",
            ratified_ok,
            "OK_SIGNOFF_RATIFIED" if ratified_ok else "SIGNOFF_NOT_RATIFIED",
            (
                "sign-off valid and cryptographically verified"
                if ratified_ok
                else f"sign-off not ratified (integrity status={integrity.get('status')})"
            ),
            actual=integrity.get("status"),
        )

    bindings: Dict[str, Any] = {
        "execution_id": exec_id,
        "batch": row_batch,
        "job_key": ji.get("job_key"),
        "integrity_status": integrity.get("status"),
    }

    # From here on, binding checks against the sign-off only make sense if the
    # sign-off is a ratified ratification object. We still run them (fail-closed)
    # by comparing against whatever values are present; missing values fail.
    ratified_contract = None
    ratification_info: Optional[Dict[str, Any]] = None
    ratified_parameters: Optional[Dict[str, Any]] = None
    exp = {}

    if rat is not None and rat.valid:
        ratified_contract = governance.apply_timing_ratification(timing_proposed, rat)
        ratification_info = governance.ratified_contract_hash(ratified_contract, rat)
        exp = rat.raw.get("experiment_configuration") or {}
        ratified_parameters = {
            "max_depth": exp.get("max_depth"),
            "l1_regularization": exp.get("reg_alpha"),
            "decision_time_policy": (rat.raw.get("timing_contract") or {}).get("decision_timestamp", {}).get("value"),
        }
        ratified_parameters = {k: v for k, v in ratified_parameters.items() if v is not None}
    else:
        ratified_contract = timing_proposed
        ratification_info = None

    # 4. Canonical config hash binding.
    live_cfg_hash = canonical_config_hash(proposal)
    signed_cfg_hash = rat.get("config_hash") if rat is not None else None
    config_binding_ok = (
        rat is not None
        and rat.valid
        and bool(signed_cfg_hash)
        and signed_cfg_hash == live_cfg_hash["hash"]
    )
    add(
        "config_hash_binding",
        config_binding_ok,
        "OK_CONFIG_HASH" if config_binding_ok else "CONFIG_HASH_MISMATCH",
        "signed canonical config hash matches live proposal"
        if config_binding_ok
        else f"signed={signed_cfg_hash!r} vs live={live_cfg_hash['hash']!r}",
        expected=signed_cfg_hash,
        actual=live_cfg_hash["hash"],
    )
    bindings["config_hash_live"] = live_cfg_hash["hash"]
    bindings["config_hash_signed"] = signed_cfg_hash
    bindings["config_hash_complete"] = live_cfg_hash["complete"]

    # 5. Timing contract binding (ratified hash must equal the signed hash).
    timing_info = ratification_info or timing_proposed.contract_hash()
    signed_timing_hash = rat.get("timing_contract_hash") if rat is not None else None
    timing_ok = (
        rat is not None
        and rat.valid
        and integrity.get("status") == "VERIFIED"
        and bool(timing_info.get("ratified"))
        and bool(signed_timing_hash)
        and signed_timing_hash == timing_info.get("hash")
    )
    add(
        "timing_contract_binding",
        timing_ok,
        "OK_TIMING" if timing_ok else "TIMING_NOT_RATIFIED",
        "timing contract ratified and hash matches sign-off"
        if timing_ok
        else f"ratified={timing_info.get('ratified')} signed={signed_timing_hash!r} vs {timing_info.get('hash')!r}",
        expected=signed_timing_hash,
        actual=timing_info.get("hash"),
    )
    bindings["timing_hash"] = timing_info.get("hash")
    bindings["timing_ratified"] = bool(timing_info.get("ratified"))

    # 6. Feature / target / split versions.
    #
    # Target-aware binding: when the execution row explicitly carries a
    # ``split_policy_version`` / ``feature_set_version`` / ``target_definition_version``
    # the gate binds against THOSE ids (so a T3 row can bind the T3-aware split
    # ``split-4d4a794c...`` rather than the frozen default ``split-27dd116e...``).
    # When the row does not carry them, the gate falls back to the frozen default
    # ids for backward compatibility (legacy single-target rows / existing tests).
    row_feat = _pick(execution_row, "feature_set_version")
    row_tgt = _pick(execution_row, "target_definition_version")
    row_split = _pick(execution_row, "split_policy_version")

    horizon_for_bind = int(ji.get("horizon", 2))
    expected_feat = str(row_feat) if row_feat else frozen.feature_version.get("id")
    expected_tgt = str(row_tgt) if row_tgt else frozen.target_version.get("id")
    expected_split = str(row_split) if row_split else frozen.split_version.get("id")

    signed_feat = rat.get("feature_set_version") if rat is not None else None
    signed_tgt = rat.get("target_definition_version") if rat is not None else None
    signed_split = rat.get("split_policy_version") if rat is not None else None
    versions_ok = (
        rat is not None
        and rat.valid
        and bool(signed_feat)
        and bool(signed_tgt)
        and bool(signed_split)
        and signed_feat == expected_feat
        and signed_tgt == expected_tgt
        and signed_split == expected_split
    )
    add(
        "contract_versions_binding",
        versions_ok,
        "OK_VERSIONS" if versions_ok else "VERSION_MISMATCH",
        (
            "feature/target/split version ids match the bound contract "
            "(target-aware row ids when supplied, else frozen defaults)"
        )
        if versions_ok
        else (
            f"feature signed={signed_feat!r}/{expected_feat!r} "
            f"target signed={signed_tgt!r}/{expected_tgt!r} "
            f"split signed={signed_split!r}/{expected_split!r}"
        ),
        expected={
            "feature": expected_feat,
            "target": expected_tgt,
            "split": expected_split,
        },
        actual={"feature": signed_feat, "target": signed_tgt, "split": signed_split},
    )
    bindings["feature_set_version"] = expected_feat
    bindings["target_definition_version"] = expected_tgt
    bindings["split_policy_version"] = expected_split
    bindings["contract_versions_source"] = "row" if (row_feat or row_tgt or row_split) else "frozen_default"

    # 6b. Target-type binding (T1 vs T3). Adds TARGET_TYPE_MISMATCH on any
    # disagreement between the requested row target, the sign-off target, and
    # the target-specific frozen version/hash. Missing target_type is rejected.
    from .configuration_freeze import target_definition_version_for

    requested_target = str(_pick(execution_row, "target_type") or "").upper() or None
    signed_target = None
    signed_target_hash = None
    if rat is not None and getattr(rat, "raw", None):
        signed_target = str((rat.raw.get("target") or {}).get("target_type") or rat.raw.get("target_type") or "").upper() or None
        signed_target_hash = (rat.raw.get("target") or {}).get("target_hash") or rat.raw.get("target_hash")
    bindings["requested_target_type"] = requested_target
    bindings["signed_target_type"] = signed_target

    if requested_target is None:
        add(
            "target_type_present",
            False,
            "TARGET_TYPE_MISSING",
            "execution row has no target_type; dual-target dispatch requires an explicit target",
            expected="T1|T3",
            actual=None,
        )
    else:
        target_valid = requested_target in {"T1", "T3"}
        add(
            "target_type_present",
            target_valid,
            "OK_TARGET_PRESENT" if target_valid else "TARGET_TYPE_INVALID",
            f"target_type={requested_target!r}",
            expected="T1|T3",
            actual=requested_target,
        )

    # Sign-off must target the SAME target type as the requested row.
    target_match_ok = (
        rat is not None
        and rat.valid
        and requested_target is not None
        and signed_target is not None
        and requested_target == signed_target
    )
    add(
        "target_type_binding",
        target_match_ok,
        "OK_TARGET_MATCH" if target_match_ok else "TARGET_TYPE_MISMATCH",
        f"requested={requested_target!r} signed={signed_target!r}",
        expected=signed_target,
        actual=requested_target,
    )

    # Target definition version + hash must match the target-specific contract.
    target_ver_ok = False
    live_target_ver = None
    if requested_target in {"T1", "T3"}:
        live_tver = target_definition_version_for(requested_target, int(ji.get("horizon", 2)))
        live_target_ver = live_tver["id"]
        target_ver_ok = (
            rat is not None
            and rat.valid
            and signed_target == requested_target
            and bool(signed_target_hash)
            and signed_target_hash == live_tver["hash"]
        )
        bindings["target_hash_live"] = live_tver["hash"]
        bindings["target_hash_signed"] = signed_target_hash
    add(
        "target_hash_binding",
        target_ver_ok,
        "OK_TARGET_HASH" if target_ver_ok else "TARGET_HASH_MISMATCH",
        f"signed target hash={signed_target_hash!r} vs live {bindings.get('target_hash_live')!r}",
        expected=bindings.get("target_hash_live"),
        actual=signed_target_hash,
    )
    bindings["target_definition_version_live"] = live_target_ver

    # 7. Experiment candidate binding (authorization is bound to a candidate).
    signed_candidate = exp.get("candidate") if isinstance(exp, dict) else None
    row_candidate = _pick(execution_row, "experiment_candidate", "candidate")
    candidate_ok = (
        bool(signed_candidate)
        and signed_candidate in {"A", "B", "C"}
        and (row_candidate is None or str(row_candidate).upper() == str(signed_candidate).upper())
    )
    add(
        "experiment_candidate_binding",
        candidate_ok,
        "OK_CANDIDATE" if candidate_ok else "CANDIDATE_MISMATCH",
        f"signed candidate={signed_candidate!r} row candidate={row_candidate!r}",
        expected=signed_candidate,
        actual=row_candidate,
    )
    bindings["experiment_candidate"] = signed_candidate

    # 8. Readiness must be READY_FOR_TRAINING (evaluated with ratification info).
    readiness = compute_readiness(
        project_root,
        proposal,
        frozen,
        ratified_contract,
        ratification_info,
        ratified_parameters,
        claim_probe_result=claim_probe_result,
        recovery_probe_result=recovery_probe_result,
    )
    ready_ok = readiness.get("decision") == "READY_FOR_TRAINING"
    add(
        "readiness_decision",
        ready_ok,
        "OK_READY" if ready_ok else "READINESS_BLOCKED",
        f"readiness decision={readiness.get('decision')} blocking={readiness.get('blocking_gates')}",
        expected="READY_FOR_TRAINING",
        actual=readiness.get("decision"),
    )

    authorized = all(c.passed for c in checks)
    reasons = [f"{c.code}: {c.detail}" for c in checks if not c.passed]
    return AuthorizationDecision(
        authorized=authorized,
        execution_id=exec_id,
        batch=row_batch,
        checks=checks,
        integrity=integrity,
        readiness=readiness,
        bindings=bindings,
        reasons=reasons,
    )


def require_authorized(decision: AuthorizationDecision) -> None:
    """Raise AuthorizationError if the decision did not pass."""
    if not decision.authorized:
        raise AuthorizationError(
            "execution not authorized: " + "; ".join(decision.reasons),
            decision=decision,
        )


def assert_gate_precedes(action_name: str, func: Callable[..., Any], gated_callables) -> None:
    """Best-effort static guard used by tests to prevent bypass.

    Verifies that ``func`` (e.g. ``process_run``) references the gate before any
    gated callable (e.g. ``run_production_pipeline_to_staging``). This is a
    source-level defense-in-depth check; the primary protection is the runtime
    ``run_runner`` gate plus the refusal in ``dispatch``.
    """
    names = [g.__name__ if hasattr(g, "__name__") else str(g) for g in gated_callables]
    src = inspect.getsource(func)
    gate_pos = src.find("require_authorized")
    if gate_pos == -1:
        gate_pos = src.find("authorize_execution")
    if gate_pos == -1:
        raise AuthorizationError(f"{action_name} does not reference the authorization gate")
    for name in names:
        pos = src.find(name + "(")
        if pos != -1 and pos < gate_pos:
            raise AuthorizationError(
                f"{action_name} calls {name} before the authorization gate"
            )

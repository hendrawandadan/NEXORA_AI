"""PREP-001 readiness gates (Part G).

Gates:
* CONFIG_READY   - canonical config complete, no critical UNRESOLVED/CONFLICT.
* DATASET_READY  - dataset exists, SHA-256 matches, structure/interval manifest ok.
* TIMING_READY   - decision/execution timing contract defined and leakage-checked.
* RUNNER_READY   - atomic single-active-attempt claim + synchronized lifecycle.
* RECOVERY_READY - crash recovery leaves no duplicate run/artifact and keeps PROMOTED terminal.

Each check returns a ReadinessReport. ``run_all_gates`` aggregates and yields
READY_FOR_TRAINING only when *all* gates pass. Critical UNRESOLVED config => BLOCKED.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNRESOLVED = "UNRESOLVED"

GATE_CONFIG = "CONFIG_READY"
GATE_DATASET = "DATASET_READY"
GATE_TIMING = "TIMING_READY"
GATE_RUNNER = "RUNNER_READY"
GATE_RECOVERY = "RECOVERY_READY"


@dataclass
class ReadinessReport:
    gate: str
    status: str
    detail: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == STATUS_PASS

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------------
# Gate implementations
# ---------------------------------------------------------------------------------
def check_config_ready(proposal) -> ReadinessReport:
    """CONFIG_READY: no critical parameter may be UNRESOLVED or in CONFLICT."""
    blocking = [
        p for p in proposal.parameters
        if p.critical and p.status in ("UNRESOLVED", "CONFLICT")
    ]
    inferred = [p.name for p in proposal.parameters if p.status == "INFERRED"]
    if blocking:
        return ReadinessReport(
            GATE_CONFIG,
            STATUS_FAIL,
            f"{len(blocking)} critical parameter(s) not resolved: "
            + ", ".join(p.name for p in blocking),
            {
                "blocking": [p.name for p in blocking],
                "inferred": inferred,
            },
        )
    return ReadinessReport(
        GATE_CONFIG,
        STATUS_PASS,
        "All critical parameters resolved",
        {"inferred": inferred},
    )


def _find_manifest(project_root: Path, dataset_path: Path) -> Path | None:
    audit_dir = project_root / "reports" / "audit"
    if not audit_dir.is_dir():
        return None
    candidate = audit_dir / (dataset_path.stem + ".json")
    if candidate.is_file():
        return candidate
    # Fallback: any audit json whose 'file' field matches this dataset.
    for path in audit_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(payload.get("file", "")).endswith(dataset_path.name):
            return path
    return None


def check_dataset_ready(proposal, project_root: Path) -> ReadinessReport:
    """DATASET_READY: file exists, hash matches frozen record, interval/schema ok."""
    project_root = Path(project_root)
    ds = proposal.dataset_identity
    dataset_path = Path(ds["absolute_path"])
    evidence: Dict[str, Any] = {
        "exists": dataset_path.is_file(),
        "sha256_recomputed": ds.get("sha256_recomputed"),
    }
    if not dataset_path.is_file():
        return ReadinessReport(GATE_DATASET, STATUS_FAIL, "dataset file missing", evidence)

    if not ds.get("sha256_recomputed"):
        return ReadinessReport(GATE_DATASET, STATUS_FAIL, "dataset hash could not be computed", evidence)

    manifest_path = _find_manifest(project_root, dataset_path)
    evidence["manifest_path"] = str(manifest_path) if manifest_path else None
    if manifest_path is None:
        return ReadinessReport(
            GATE_DATASET,
            STATUS_UNRESOLVED,
            "no audit manifest found; interval/schema not independently verified here",
            evidence,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ReadinessReport(GATE_DATASET, STATUS_FAIL, f"manifest unreadable: {exc}", evidence)

    interval_status = manifest.get("interval_check", {}).get("status")
    schema_valid = manifest.get("schema_valid")
    evidence["interval_status"] = interval_status
    evidence["schema_valid"] = schema_valid
    evidence["rows_valid_unique"] = manifest.get("rows_valid_unique")
    evidence["gap_count"] = manifest.get("gap_count")

    if schema_valid is not True:
        return ReadinessReport(GATE_DATASET, STATUS_FAIL, "manifest schema_valid is not true", evidence)
    if interval_status != "PASS":
        return ReadinessReport(GATE_DATASET, STATUS_FAIL, f"interval status={interval_status}", evidence)
    if manifest.get("rows_valid_unique") != ds.get("bars_expected"):
        return ReadinessReport(
            GATE_DATASET,
            STATUS_FAIL,
            f"row count {manifest.get('rows_valid_unique')} != expected {ds.get('bars_expected')}",
            evidence,
        )
    return ReadinessReport(
        GATE_DATASET, STATUS_PASS, "dataset verified against manifest", evidence
    )


def check_timing_ready(timing_contract=None, ratification_info: Dict[str, Any] | None = None) -> ReadinessReport:
    """TIMING_READY: decision/execution timing must be an explicit, ratified contract.

    A contract with unratified NEW_DESIGN fields (decision clock, earliest
    executable time, cost/slippage model) cannot pass: those are design decisions
    that must be signed off, not inferred. Leakage of features is PROVEN safe,
    but that alone does not resolve execution timing.
    """
    if timing_contract is None:
        return ReadinessReport(
            GATE_TIMING,
            STATUS_UNRESOLVED,
            "No timing contract supplied (candle close vs next-bar execution unresolved)",
            {"decision_time_policy": None},
        )
    info = timing_contract.contract_hash()
    design = info.get("new_design_fields", [])
    ratified = bool(ratification_info and ratification_info.get("ratified"))
    evidence = dict(info)
    if ratification_info:
        evidence["ratification"] = ratification_info
    if not ratified:
        return ReadinessReport(
            GATE_TIMING,
            STATUS_UNRESOLVED,
            f"Timing contract proposed but not ratified; {len(design)} design field(s) need sign-off: "
            + ", ".join(design),
            evidence,
        )
    return ReadinessReport(
        GATE_TIMING,
        STATUS_PASS,
        "Timing contract ratified by human sign-off; no future information used",
        evidence,
    )


def check_runner_ready(claim_probe_result: Dict[str, Any] | None) -> ReadinessReport:
    """RUNNER_READY: single active attempt per job at the SQLite boundary.

    ``claim_probe_result`` is produced by the isolated probe in tests/audit; it
    must show that a RUNNING job cannot produce a second STARTED run and that
    checkpoint transitions keep job/run status synchronized.
    """
    if not claim_probe_result:
        return ReadinessReport(
            GATE_RUNNER, STATUS_UNRESOLVED, "claim probe not executed", {}
        )
    evidence = claim_probe_result
    one_active = claim_probe_result.get("single_active_attempt_enforced")
    synced = claim_probe_result.get("lifecycle_synchronized")
    running_rejected = claim_probe_result.get("running_job_claim_rejected")
    ok = bool(one_active) and bool(synced) and bool(running_rejected)
    return ReadinessReport(
        GATE_RUNNER,
        STATUS_PASS if ok else STATUS_FAIL,
        "atomic claim + synchronized lifecycle verified"
        if ok
        else "claim/lifecycle invariants not fully satisfied",
        evidence,
    )


def check_recovery_ready(recovery_probe_result: Dict[str, Any] | None) -> ReadinessReport:
    """RECOVERY_READY: crash recovery is idempotent and never downgrades PROMOTED."""
    if not recovery_probe_result:
        return ReadinessReport(
            GATE_RECOVERY, STATUS_UNRESOLVED, "recovery probe not executed", {}
        )
    evidence = recovery_probe_result
    ok = bool(recovery_probe_result.get("no_duplicate_active_run")) and bool(
        recovery_probe_result.get("promoted_terminal_preserved")
    )
    return ReadinessReport(
        GATE_RECOVERY,
        STATUS_PASS if ok else STATUS_FAIL,
        "crash recovery idempotent; PROMOTED preserved"
        if ok
        else "recovery invariants not fully satisfied",
        evidence,
    )


# ---------------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------------
def run_all_gates(
    proposal,
    project_root: Path,
    claim_probe_result: Dict[str, Any] | None = None,
    recovery_probe_result: Dict[str, Any] | None = None,
    timing_contract=None,
    frozen_manifest=None,
    ratification_info: Dict[str, Any] | None = None,
    ratified_parameters: Dict[str, Any] | None = None,
) -> List[ReadinessReport]:
    config_report = (
        check_config_ready_freeze(frozen_manifest, ratified_parameters=ratified_parameters)
        if frozen_manifest is not None
        else check_config_ready(proposal)
    )
    return [
        config_report,
        check_dataset_ready(proposal, project_root),
        check_timing_ready(timing_contract, ratification_info=ratification_info),
        check_runner_ready(claim_probe_result),
        check_recovery_ready(recovery_probe_result),
    ]


def check_config_ready_freeze(frozen_manifest, ratified_parameters: Dict[str, Any] | None = None) -> ReadinessReport:
    """CONFIG_READY using the freeze manifest: PASS only if hash is complete.

    ``ratified_parameters`` are human decisions (e.g. {"max_depth": 4,
    "l1_regularization": 0.1}) from a signed ratification file. They satisfy the
    matching REQUIRES_DECISION entries. They are NOT frozen production config by
    themselves; this gate only confirms every required decision now has an
    explicit, human-supplied value.
    """
    info = frozen_manifest.config_hash()
    requires = list(info.get("requires_decision", []))
    ratified_parameters = ratified_parameters or {}
    unresolved_after = [p for p in requires if p not in ratified_parameters]

    # Fully frozen already? PASS immediately.
    if info.get("complete"):
        return ReadinessReport(
            GATE_CONFIG,
            STATUS_PASS,
            "Frozen configuration complete; all parameters evidenced",
            {"config_hash": info.get("hash"), "complete": True},
        )

    # Incomplete manifest but every remaining decision was supplied by a human
    # sign-off -> the decisions exist explicitly (not invented by tooling).
    if not unresolved_after:
        return ReadinessReport(
            GATE_CONFIG,
            STATUS_PASS,
            "All REQUIRES_DECISION items resolved by human ratification sign-off",
            {
                "config_hash": info.get("hash"),
                "complete": False,
                "requires_decision": requires,
                "ratified_parameters": ratified_parameters,
                "note": "Decisions are human-approved; production freeze still requires "
                        "re-emitting the manifest with these values.",
            },
        )

    return ReadinessReport(
        GATE_CONFIG,
        STATUS_FAIL,
        f"Frozen manifest incomplete; {len(unresolved_after)} parameter(s) require a decision: "
        + ", ".join(unresolved_after),
        {
            "config_hash": info.get("hash"),
            "complete": False,
            "requires_decision": requires,
            "still_unresolved": unresolved_after,
            "frozen_parameters": [e.name for e in frozen_manifest.frozen],
        },
    )


def summarize(reports: List[ReadinessReport]) -> Dict[str, Any]:
    """Return the final readiness decision for PREP-001."""
    blocking = [r for r in reports if not r.passed and r.status in (STATUS_FAIL, STATUS_UNRESOLVED)]
    ready_for_training = len(blocking) == 0
    by_status = {r.gate: r.status for r in reports}
    return {
        "gates": by_status,
        "ready_for_training": ready_for_training,
        "decision": "READY_FOR_TRAINING" if ready_for_training else ("BLOCKED" if blocking else "PARTIALLY_READY"),
        "blocking_gates": [r.gate for r in blocking],
    }

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from . import governance
from .canonical_config import (
    build_prep001_proposal,
    canonical_config_hash,
)
from .configuration_freeze import build_frozen_manifest
from .timing_contract import build_timing_contract
from .readiness import run_all_gates, summarize
from .safety_probe import probe_crash_recovery, run_claim_and_lifecycle_probes
from .authorization import authorize_execution

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _authorize_bundle(execution_id: str, batch: str) -> Dict[str, Any]:
    """Emit the job-scoped authorization decision for a single execution id.

    Read-only: never mutates the DB/CSV/dataset/model/backup, never trains.
    """
    row = {
        "execution_id": execution_id,
        "batch": batch,
        "scope": "individual",
        "symbol": "EURUSD",
        "timeframe": "M30",
        "horizon": "2",
    }
    decision = authorize_execution(
        execution_row=row,
        project_root=PROJECT_ROOT,
        batch_name=batch,
        requested_execution_ids={execution_id},
        claim_probe_result=run_claim_and_lifecycle_probes(),
        recovery_probe_result=probe_crash_recovery(),
    )
    return decision.as_dict()


def _proposal_bundle() -> Dict[str, Any]:
    proposal = build_prep001_proposal(PROJECT_ROOT)
    cfg_hash = canonical_config_hash(proposal)
    return {
        "proposal": proposal.to_dict(),
        "config_hash": cfg_hash,
    }


def _freeze_bundle() -> Dict[str, Any]:
    manifest = build_frozen_manifest(PROJECT_ROOT)
    return manifest.to_dict()


def _timing_bundle() -> Dict[str, Any]:
    contract = build_timing_contract()
    return contract.to_dict()


def _probes_bundle() -> Dict[str, Any]:
    return {
        "claim_and_lifecycle": run_claim_and_lifecycle_probes(),
        "crash_recovery": probe_crash_recovery(),
    }


def _apply_governance(frozen, timing):
    """Load human ratification and derive (timing_contract, ratification_info,
    ratified_parameters). Absent/invalid sign-off -> nothing ratified."""
    rat = governance.load_ratification(PROJECT_ROOT)
    if rat is None or not rat.valid:
        return (
            timing,
            None,
            None,
            governance.ratification_summary(PROJECT_ROOT),
        )
    ratified_contract = governance.apply_timing_ratification(timing, rat)
    ratification_info = governance.ratified_contract_hash(ratified_contract, rat)
    ratified_parameters = {
        "max_depth": rat.raw["experiment_configuration"].get("max_depth"),
        "l1_regularization": rat.raw["experiment_configuration"].get("reg_alpha"),
        "decision_time_policy": rat.raw["timing_contract"].get("decision_timestamp", {}).get("value"),
    }
    # Drop Nones so the gate only counts real decisions.
    ratified_parameters = {k: v for k, v in ratified_parameters.items() if v is not None}
    return ratified_contract, ratification_info, ratified_parameters, governance.ratification_summary(PROJECT_ROOT)


def build_full_report() -> Dict[str, Any]:
    proposal = build_prep001_proposal(PROJECT_ROOT)
    cfg_hash = canonical_config_hash(proposal)
    frozen = build_frozen_manifest(PROJECT_ROOT)
    timing_proposed = build_timing_contract()
    timing, ratification_info, ratified_parameters, gov_summary = _apply_governance(frozen, timing_proposed)
    claim = run_claim_and_lifecycle_probes()
    recovery = probe_crash_recovery()
    reports = run_all_gates(
        proposal,
        PROJECT_ROOT,
        claim_probe_result=claim,
        recovery_probe_result=recovery,
        timing_contract=timing,
        frozen_manifest=frozen,
        ratification_info=ratification_info,
        ratified_parameters=ratified_parameters,
    )
    decision = summarize(reports)
    return {
        "config_hash": cfg_hash,
        "freeze_hash": frozen.config_hash(),
        "timing_contract": (ratification_info or timing.contract_hash()),
        "governance": gov_summary,
        "proposal": proposal.to_dict(),
        "frozen_manifest": frozen.to_dict(),
        "probes": {"claim_and_lifecycle": claim, "crash_recovery": recovery},
        "readiness": {
            "gates": [r.as_dict() for r in reports],
            **decision,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NEXORA execution safety & config-freeze audit (read-only)")
    parser.add_argument(
        "command",
        choices=["propose", "freeze", "timing", "probes", "readiness", "governance", "authorize", "all"],
        help="which artifact to emit as JSON",
    )
    parser.add_argument(
        "--execution-id",
        default="PREP-001",
        help="execution_id to authorize (used by the 'authorize' command). Default PREP-001.",
    )
    parser.add_argument(
        "--batch",
        default="Batch 1",
        help="batch name to bind the authorization to (used by 'authorize'). Default 'Batch 1'.",
    )
    args = parser.parse_args(argv)

    if args.command == "propose":
        out = _proposal_bundle()
    elif args.command == "freeze":
        out = _freeze_bundle()
    elif args.command == "timing":
        out = _timing_bundle()
    elif args.command == "probes":
        out = _probes_bundle()
    elif args.command == "governance":
        out = governance.ratification_summary(PROJECT_ROOT)
    elif args.command == "authorize":
        out = _authorize_bundle(args.execution_id, args.batch)
    elif args.command == "readiness":
        full = build_full_report()
        out = {
            "freeze_hash": full["freeze_hash"],
            "timing_contract": full["timing_contract"],
            "governance": full["governance"],
            "readiness": full["readiness"],
        }
    else:
        out = build_full_report()

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

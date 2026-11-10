"""Manual activation CLI for the NEXORA research scheduler (Item 2.5).

MANUAL ACTIVATION ONLY. Running the scheduler is an explicit human action: this CLI does
nothing unless a subcommand is invoked. There is NO auto-start, NO daemonization, and NO
cron/background integration added here.

Safety posture:
  * Default mode is ``--dry-run`` (nothing persisted to research memory).
  * Discovery-only: the scheduler can never train/tune/promote/live-trade/reopen.
  * ``--require-consent`` must be passed to actually run (in addition to dry-run being
    the default); this makes accidental activation harder.

Usage examples (run with the project's interpreter):

    python -m nexora_scheduler.cli status
    python -m nexora_scheduler.cli enqueue --kind RESEARCH_CYCLE --instrument EURUSD
    python -m nexora_scheduler.cli run --dry-run --require-consent --max-ticks 1
    python -m nexora_scheduler.cli kill            # engage the kill switch (safety)
    python -m nexora_scheduler.cli unkill
    python -m nexora_scheduler.cli history --job-id 3
    python -m nexora_scheduler.cli audit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from . import config as cfg
from .job_queue import ResearchJobQueue
from .kill_switch import KillSwitch
from . import observability as obs
from .scheduler import ResearchScheduler


def _build_queue(args) -> ResearchJobQueue:
    db = Path(args.db) if getattr(args, "db", None) else cfg.SCHEDULER_DATABASE_PATH
    return ResearchJobQueue(db)


def _build_scheduler(queue: ResearchJobQueue, args) -> ResearchScheduler:
    kill = KillSwitch()
    config = cfg.SchedulerConfig(dry_run=not getattr(args, "no_dry_run", False))
    store = None
    if not config.dry_run:
        from nexora_research.store import ResearchMemoryStore
        store = ResearchMemoryStore(cfg.RESEARCH_DB_PATH, bootstrap=True)
    return ResearchScheduler(queue, config=config, kill_switch=kill,
                             research_store=store)


def cmd_status(args) -> int:
    q = _build_queue(args)
    snap = obs.snapshot(q, kill_switch_engaged=KillSwitch().is_engaged())
    if args.json:
        print(json.dumps(snap.as_dict(), indent=2, default=str))
    else:
        print(obs.format_status_text(snap))
    return 0


def cmd_enqueue(args) -> int:
    q = _build_queue(args)
    payload = {}
    if getattr(args, "instrument", None):
        payload["instrument"] = args.instrument
    jid = q.enqueue(kind=args.kind, payload=payload, trigger_source="MANUAL")
    print(json.dumps({"enqueued_job_id": jid, "kind": args.kind, "payload": payload}))
    return 0


def cmd_run(args) -> int:
    if not args.require_consent:
        print("REFUSED: --require-consent is mandatory to run the scheduler "
              "(manual activation only).", file=sys.stderr)
        return 2
    q = _build_queue(args)
    sched = _build_scheduler(q, args)
    report = sched.run(max_ticks=args.max_ticks, run_forever=args.run_forever)
    print(json.dumps(report.as_dict(), indent=2, default=str))
    return 0


def cmd_kill(args) -> int:
    ks = KillSwitch()
    ks.engage(reason="cli", write_file=True)
    print(json.dumps({"kill_switch": "engaged", "path": str(ks.path)}))
    return 0


def cmd_unkill(args) -> int:
    ks = KillSwitch()
    ks.disengage()
    print(json.dumps({"kill_switch": "disengaged"}))
    return 0


def cmd_history(args) -> int:
    q = _build_queue(args)
    print(json.dumps(obs.job_history(q, args.job_id), indent=2, default=str))
    return 0


def cmd_audit(args) -> int:
    q = _build_queue(args)
    print(json.dumps(obs.audit_report(q), indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nexora_scheduler",
        description="NEXORA Autonomous Research Scheduler (DISCOVERY-ONLY, manual "
                    "activation). Never trains/promotes/live-trades/reopens a lane.")
    p.add_argument("--db", help="override scheduler DB path (default: isolated)")
    p.add_argument("--json", action="store_true", help="JSON output where applicable")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("status", help="show queue + governance status")
    sp.add_argument("--json", action="store_true", help="JSON output")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("enqueue", help="enqueue a discovery job")
    sp.add_argument("--kind", required=True, choices=list(cfg.JOB_KINDS))
    sp.add_argument("--instrument")
    sp.set_defaults(func=cmd_enqueue)

    sp = sub.add_parser("run", help="run the worker loop (manual activation only)")
    sp.add_argument("--max-ticks", type=int, default=None)
    sp.add_argument("--run-forever", action="store_true")
    sp.add_argument("--dry-run", action="store_true", default=True)
    sp.add_argument("--no-dry-run", action="store_true",
                    help="persist research artefacts (still discovery-only)")
    sp.add_argument("--require-consent", action="store_true",
                    help="mandatory acknowledgement to actually run")
    sp.set_defaults(func=cmd_run)

    sub.add_parser("kill", help="engage the kill switch (refuse all work)").set_defaults(
        func=cmd_kill)
    sub.add_parser("unkill", help="disengage the kill switch").set_defaults(func=cmd_unkill)

    sp = sub.add_parser("history", help="full history for one job")
    sp.add_argument("--job-id", type=int, required=True)
    sp.set_defaults(func=cmd_history)

    sub.add_parser("audit", help="audit report").set_defaults(func=cmd_audit)

    return p


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

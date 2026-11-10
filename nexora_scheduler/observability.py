"""Observability for the research scheduler (Item 2.5, Phase 4).

Read-only operational views: status, queue, history, retry history, provider health, and
an audit report. Everything here reads the isolated scheduler DB; nothing mutates
research memory, production state, or governance.

CLI usage (see cli.py) prints these as JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config as cfg
from .job_queue import JobRecord, ResearchJobQueue


def queue_status(queue: ResearchJobQueue) -> Dict[str, object]:
    """Aggregate queue health: counts by status + oldest queued + active retries."""
    counts = queue.count_by_status()
    with queue.manager.open() as conn:
        oldest = conn.execute(
            "SELECT id, kind, created_at FROM scheduler_jobs WHERE status='QUEUED' "
            "ORDER BY id LIMIT 1").fetchone()
        oldest_active = conn.execute(
            "SELECT id, kind, started_at FROM scheduler_jobs WHERE status='RUNNING' "
            "ORDER BY id LIMIT 1").fetchone()
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "due_retries": queue.due_retry_count(),
        "oldest_queued": dict(oldest) if oldest else None,
        "oldest_running": dict(oldest_active) if oldest_active else None,
    }


@dataclass
class SchedulerSnapshot:
    queue: Dict[str, object]
    provider_health: Dict[str, object]
    last_successful_run: Optional[Dict[str, object]]
    kill_switch_engaged: bool
    governance: Dict[str, object]
    config: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "queue": self.queue,
            "provider_health": self.provider_health,
            "last_successful_run": self.last_successful_run,
            "kill_switch_engaged": self.kill_switch_engaged,
            "governance": self.governance,
            "config": self.config,
        }


def _governance_snapshot() -> Dict[str, object]:
    try:
        from nexora_laboratory.governance.lane_suspension import is_suspended, lane_status
        return {"price_derived_status": lane_status(),
                "price_derived_suspended": bool(is_suspended())}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}


def snapshot(queue: ResearchJobQueue, *, kill_switch_engaged: bool = False,
             config: cfg.SchedulerConfig = cfg.DEFAULT_CONFIG) -> SchedulerSnapshot:
    return SchedulerSnapshot(
        queue=queue_status(queue),
        provider_health=queue.provider_health(),
        last_successful_run=queue.last_successful_run(),
        kill_switch_engaged=kill_switch_engaged,
        governance=_governance_snapshot(),
        config=config.as_dict(),
    )


def job_history(queue: ResearchJobQueue, job_id: int) -> Dict[str, object]:
    """Full history for one job: record + executions + retries + audit."""
    rec = queue.get(job_id)
    if rec is None:
        return {"job_id": job_id, "error": "not found"}
    return {
        "job": rec.as_dict(),
        "executions": queue.executions(job_id),
        "retries": queue.retries(job_id),
        "audit": queue.audit(entity_id=job_id),
    }


def audit_report(queue: ResearchJobQueue) -> Dict[str, object]:
    """Aggregate audit report over all jobs: per-status, per-kind, recent audit rows."""
    counts = queue.count_by_status()
    with queue.manager.open() as conn:
        by_kind = {r["kind"]: int(r["n"]) for r in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM scheduler_jobs GROUP BY kind")}
        recent = [dict(r) for r in conn.execute(
            "SELECT * FROM audit_trail ORDER BY id DESC LIMIT 50")]
    return {
        "by_status": counts,
        "by_kind": by_kind,
        "recent_audit": recent,
        "governance": _governance_snapshot(),
    }


def format_status_text(snap: SchedulerSnapshot) -> str:
    q = snap.queue
    counts = q["counts"]
    lines = [
        "NEXORA Research Scheduler — status",
        "=" * 40,
        f"  kill switch engaged : {snap.kill_switch_engaged}",
        f"  price-derived lane   : {snap.governance.get('price_derived_status', '?')}",
        f"  total jobs           : {q['total']}",
        "  by status:",
    ]
    for s in cfg.JOB_STATUSES:
        lines.append(f"    {s:<12}: {counts.get(s, 0)}")
    lines.append(f"  due retries          : {q['due_retries']}")
    oldest = q["oldest_queued"]
    if oldest:
        lines.append(f"  oldest queued        : id={oldest['id']} kind={oldest['kind']}")
    if snap.provider_health:
        lines.append("  provider health:")
        for pid, h in snap.provider_health.items():
            lines.append(f"    {pid:<14}: {h['status']}")
    lr = snap.last_successful_run
    if lr:
        lines.append(f"  last completed       : id={lr['id']} kind={lr['kind']}")
    return "\n".join(lines)

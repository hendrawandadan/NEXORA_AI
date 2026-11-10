"""Autonomous Research Scheduler core (Item 2.5, Phase 3).

Orchestrates DISCOVERY-ONLY research jobs on a durable queue. Responsibilities:

  * Interval scheduling — enqueue periodic jobs for each enabled cadence
    (``interval_research_cycle_s`` / ``interval_info_acquisition_s`` /
    ``interval_strategy_evolution_s``).
  * Event trigger — an external caller can push an event (e.g. "new CPI release") that
    enqueues a targeted job. Events are idempotent per (kind, payload).
  * Worker loop — claims one job at a time (concurrency guard), runs a safety preflight,
    then the handler, then records COMPLETED / FAILED (-> retry) / BLOCKED.
  * Recovery — on start, re-queue jobs left RUNNING by a crashed run (checkpoint).
  * Graceful shutdown — cooperative stop flag; the current job finishes, then the loop
    exits. Retry/backoff survives restart via the durable queue.
  * Kill switch — when engaged, enqueues nothing and executes nothing.

The scheduler NEVER trains/tunes/promotes/live-trades/reopens a lane. It only reads the
governance registry and writes research artefacts (and its own queue DB).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config as cfg
from . import jobs as job_handlers
from .job_queue import ResearchJobQueue
from .kill_switch import KillSwitch
from .provider_limits import ProviderRateLimiter
from .safety import SafetyDecision, combined_preflight

log = logging.getLogger("nexora_scheduler")


@dataclass
class TickResult:
    """Outcome of a single scheduler tick (one claim attempt or one enqueue wave)."""
    enqueued: List[int] = field(default_factory=list)
    claimed_job_id: Optional[int] = None
    final_status: Optional[str] = None
    safety: Optional[Dict[str, object]] = None
    kill_switch: bool = False


@dataclass
class SchedulerReport:
    ticks: int = 0
    jobs_enqueued: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    jobs_blocked: int = 0
    jobs_retried: int = 0
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "ticks": self.ticks, "jobs_enqueued": self.jobs_enqueued,
            "jobs_completed": self.jobs_completed, "jobs_failed": self.jobs_failed,
            "jobs_blocked": self.jobs_blocked, "jobs_retried": self.jobs_retried,
            "notes": list(self.notes),
        }


class ResearchScheduler:
    def __init__(
        self,
        queue: ResearchJobQueue,
        *,
        config: cfg.SchedulerConfig = cfg.DEFAULT_CONFIG,
        kill_switch: Optional[KillSwitch] = None,
        research_store=None,
        external_repo=None,
        policy_block_non_pit: bool = False,
        clock=time.monotonic,
    ) -> None:
        self.queue = queue
        self.config = config
        self.kill_switch = kill_switch or KillSwitch(config=config)
        self.research_store = research_store
        self.external_repo = external_repo
        self.policy_block_non_pit = policy_block_non_pit
        self.rate_limiter = ProviderRateLimiter(config)
        self._clock = clock
        self._stop = False
        self._last_interval_run: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Shutdown / kill switch.
    # ------------------------------------------------------------------ #
    def request_stop(self) -> None:
        """Cooperative graceful shutdown: finish the current job, then exit the loop."""
        self._stop = True

    def request_resume(self) -> None:
        """Clear a previous stop request so a subsequent ``run()`` can execute work."""
        self._stop = False

    def is_stopped(self) -> bool:
        return self._stop

    def _blocked_by_kill_switch(self) -> bool:
        return self.kill_switch.is_engaged()

    # ------------------------------------------------------------------ #
    # Recovery.
    # ------------------------------------------------------------------ #
    def recover(self) -> int:
        """Re-queue jobs left RUNNING by a crashed run. Returns count recovered."""
        n = self.queue.recover_running_jobs()
        if n:
            log.info("recovered %d RUNNING job(s) after restart", n)
        return n

    # ------------------------------------------------------------------ #
    # Interval scheduling.
    # ------------------------------------------------------------------ #
    def _interval_due(self, key: str, interval_s: float) -> bool:
        if interval_s <= 0:
            return False
        now = self._clock()
        last = self._last_interval_run.get(key)
        if last is None or (now - last) >= interval_s:
            self._last_interval_run[key] = now
            return True
        return False

    def enqueue_interval_jobs(self) -> List[int]:
        """Enqueue the interval-configured jobs that are due. Idempotent per cadence
        window (a job already active for the same window is not duplicated)."""
        if self._blocked_by_kill_switch():
            return []
        enqueued: List[int] = []
        specs = [
            (cfg.JOB_RESEARCH_CYCLE, self.config.interval_research_cycle_s,
             {"instrument": "EURUSD"}),
            (cfg.JOB_INFO_ACQUISITION, self.config.interval_info_acquisition_s,
             {"instrument": "EURUSD"}),
            (cfg.JOB_STRATEGY_EVOLUTION, self.config.interval_strategy_evolution_s, {}),
        ]
        for kind, interval, payload in specs:
            if not self._interval_due(kind, interval):
                continue
            try:
                jid = self.queue.enqueue(
                    kind=kind, payload=payload, trigger_source="INTERVAL")
                enqueued.append(jid)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("interval enqueue failed for %s: %s", kind, exc)
        return enqueued

    # ------------------------------------------------------------------ #
    # Event trigger.
    # ------------------------------------------------------------------ #
    def submit_event(self, *, kind: str, payload: Dict[str, object],
                     event_id: Optional[str] = None) -> int:
        """Enqueue an event-triggered job (idempotent per kind+payload[+event_id])."""
        if self._blocked_by_kill_switch():
            raise RuntimeError("kill switch engaged: refusing to enqueue")
        p = dict(payload)
        if event_id:
            p = {**p, "_event_id": event_id}
        return self.queue.enqueue(kind=kind, payload=p, trigger_source="EVENT")

    # ------------------------------------------------------------------ #
    # Execution of a single claimed job.
    # ------------------------------------------------------------------ #
    def _run_one(self, job) -> str:
        # Build a preflight payload from the job's stored payload.
        payload = dict(job.payload or {})
        safety: SafetyDecision = combined_preflight(
            job_kind=job.kind, payload=payload,
            policy_block_non_pit=self.policy_block_non_pit)

        if not safety.allowed:
            self.queue.mark_blocked(job.id, reason="; ".join(safety.reasons))
            return cfg.STATUS_BLOCKED

        # Kill switch re-check immediately before doing work.
        if self._blocked_by_kill_switch():
            # Do not execute: return the job to QUEUED by failing without retry budget
            # consumption is impossible via state machine; instead block with reason.
            self.queue.mark_blocked(job.id, reason="kill switch engaged before execution")
            return cfg.STATUS_BLOCKED

        try:
            result = job_handlers.dispatch(
                job.kind, payload, dry_run=self.config.dry_run,
                store=self.research_store,
                use_mock_provider=self.config.use_mock_provider,
                external_repo=self.external_repo, rate_limiter=self.rate_limiter)
        except Exception as exc:  # handler error -> FAILED (+retry)
            log.warning("job %s (%s) failed: %s", job.id, job.kind, exc)
            return self.queue.mark_failed(job.id, error=f"{type(exc).__name__}: {exc}")

        # A handler may surface a governance/PIT block as a structured result.
        if isinstance(result, dict) and result.get("_blocked"):
            self.queue.mark_blocked(job.id, reason=str(result["_blocked"]))
            return cfg.STATUS_BLOCKED

        # Attach the safety verdict to the result for auditability.
        result = dict(result)
        result["_safety"] = safety.as_dict()
        self.queue.mark_completed(job.id, result=result)
        return cfg.STATUS_COMPLETED

    def tick(self, *, enqueue_intervals: bool = True) -> TickResult:
        """One scheduler tick: (optionally enqueue interval jobs) then run one job."""
        tr = TickResult()
        if self._blocked_by_kill_switch():
            tr.kill_switch = True
            return tr
        if enqueue_intervals:
            tr.enqueued = self.enqueue_interval_jobs()
        job = self.queue.claim_next()
        if job is None:
            return tr
        tr.claimed_job_id = job.id
        tr.final_status = self._run_one(job)
        return tr

    # ------------------------------------------------------------------ #
    # Worker loop.
    # ------------------------------------------------------------------ #
    def run(self, *, max_ticks: Optional[int] = None,
            run_forever: bool = False) -> SchedulerReport:
        """Run the worker loop.

        * ``max_ticks`` bounds the number of ticks (used by tests).
        * ``run_forever`` runs until ``request_stop()`` or the kill switch engages.
        Recovery is performed once at start. A stop requested *before* ``run()`` is
        honoured (nothing is executed); call ``request_resume()`` to run afterwards.
        """
        self.recover()
        report = SchedulerReport()
        ticks = 0
        while True:
            if self._stop:
                report.notes.append("stopped by request")
                break
            if self._blocked_by_kill_switch():
                report.notes.append("stopped: kill switch engaged")
                break
            tr = self.tick()
            ticks += 1
            report.ticks = ticks
            report.jobs_enqueued += len(tr.enqueued)
            if tr.claimed_job_id is not None:
                if tr.final_status == cfg.STATUS_COMPLETED:
                    report.jobs_completed += 1
                elif tr.final_status == cfg.STATUS_FAILED:
                    report.jobs_failed += 1
                elif tr.final_status == cfg.STATUS_RETRY_WAIT:
                    report.jobs_retried += 1
                elif tr.final_status == cfg.STATUS_BLOCKED:
                    report.jobs_blocked += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            if not run_forever and tr.claimed_job_id is None and not tr.enqueued:
                # No work and not asked to run forever -> return (bounded drain).
                break
            if tr.claimed_job_id is None:
                time.sleep(self.config.poll_interval_s)
        return report

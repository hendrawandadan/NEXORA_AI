"""NEXORA Autonomous Research Scheduler (Item 2.5).

A DISCOVERY-ONLY orchestrator that schedules *research* work — the research control
loop, external-intelligence acquisition, and strategy evolution — on a durable,
observable, recoverable job queue.

It is NOT a training runner, a promotion engine, or a trading executor. It can never
train, tune, promote a model, enable live trading, or reopen a suspended lane. All of
those actions are structurally impossible here (forbidden job kinds are rejected in the
application layer AND by a database trigger, and every job passes the canonical
governance + PIT gates before it runs).

Key invariants (see reports/economic_opportunity_discovery/STAGE_2_5_* and the tests):

  * Persistent job queue with a guarded state machine.
  * Idempotent enqueue + duplicate-job prevention.
  * Configurable provider rate limits.
  * Exponential-backoff retries.
  * Manual / interval / event-driven scheduling (no auto-start; CLI is manual).
  * Governance + PIT preflight on every job; PRICE_DERIVED stays SUSPENDED.
  * Kill switch, graceful shutdown, restart (checkpoint) recovery.
  * Observability: status / queue / history / retries / provider health / audit.
  * Dedicated isolated DB; production DB and research/external DBs are never opened here.

Public entry points::

    from nexora_scheduler import ResearchJobQueue, ResearchScheduler, SchedulerConfig
    q = ResearchJobQueue()                       # isolated scheduler DB
    s = ResearchScheduler(q)                      # discovery-only, dry-run by default
    s.run(max_ticks=1)
"""

from .config import (
    SchedulerConfig, DEFAULT_CONFIG, JOB_KINDS, JOB_STATUSES, FORBIDDEN_JOB_KINDS,
    JOB_RESEARCH_CYCLE, JOB_INFO_ACQUISITION, JOB_STRATEGY_EVOLUTION,
    SCHEDULER_DATABASE_PATH,
)
from .job_queue import (
    ResearchJobQueue, JobRecord, DuplicateJobError, IllegalTransition,
    make_idempotency_key,
)
from .kill_switch import KillSwitch
from .provider_limits import ProviderRateLimiter
from .safety import (
    combined_preflight, preflight_governance, preflight_pit, SafetyDecision,
)
from .scheduler import ResearchScheduler, SchedulerReport, TickResult
from . import observability

__all__ = [
    "SchedulerConfig", "DEFAULT_CONFIG", "JOB_KINDS", "JOB_STATUSES",
    "FORBIDDEN_JOB_KINDS", "JOB_RESEARCH_CYCLE", "JOB_INFO_ACQUISITION",
    "JOB_STRATEGY_EVOLUTION", "SCHEDULER_DATABASE_PATH",
    "ResearchJobQueue", "JobRecord", "DuplicateJobError", "IllegalTransition",
    "make_idempotency_key", "KillSwitch", "ProviderRateLimiter",
    "combined_preflight", "preflight_governance", "preflight_pit", "SafetyDecision",
    "ResearchScheduler", "SchedulerReport", "TickResult", "observability",
]

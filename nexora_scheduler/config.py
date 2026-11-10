"""Configuration for the NEXORA Autonomous Research Scheduler (Item 2.5).

DISCOVERY-ONLY. The scheduler orchestrates *research* work (control loop, external
intelligence acquisition, strategy evolution). It NEVER trains, tunes, promotes a
model, enables live trading, or reopens a suspended lane.

Path isolation (deliberate, mirrors the existing research/external modules):
  * Production DB:  database/nexora_state.db          (NEVER touched here)
  * Research DB:    database/nexora_research.db        (Knowledge Memory; only written
                                                         by ResearchMemoryStore via jobs)
  * External DB:    database/nexora_external_intel.db  (external intelligence provenance)
  * Scheduler DB:   database/nexora_research_scheduler.db  (THIS module's job queue)

The scheduler's own persistent state (jobs / executions / retries / audit) lives in a
DEDICATED database so it can never corrupt research memory or production state. The
scheduler never opens the production DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIRECTORY = PROJECT_ROOT / "database"

# Dedicated, isolated scheduler database + migrations directory.
SCHEDULER_DATABASE_PATH = DATABASE_DIRECTORY / "nexora_research_scheduler.db"
SCHEDULER_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Protected databases we must never open with the scheduler queue.
PRODUCTION_DB_PATH = DATABASE_DIRECTORY / "nexora_state.db"
RESEARCH_DB_PATH = DATABASE_DIRECTORY / "nexora_research.db"
EXTERNAL_INTEL_DB_PATH = DATABASE_DIRECTORY / "nexora_external_intel.db"

# The governance registry paths that jobs MAY read (never write).
GOVERNANCE_REGISTRY_PATH = PROJECT_ROOT / "config" / "governance" / \
    "price_derived_lane_suspension.json"

# Kill-switch sentinel file (its presence = scheduler refuses to run any job).
KILL_SWITCH_FILE = DATABASE_DIRECTORY / "nexora_scheduler.KILL"

# ----------------------------------------------------------------------------- #
# Job kinds (closed set). All are DISCOVERY-ONLY.
# ----------------------------------------------------------------------------- #
JOB_RESEARCH_CYCLE = "RESEARCH_CYCLE"                # one instrument through control loop
JOB_INFO_ACQUISITION = "INFO_ACQUISITION_ACQUIRE"    # external intelligence acquisition
JOB_STRATEGY_EVOLUTION = "STRATEGY_EVOLUTION"        # derive evolution proposals

JOB_KINDS = (JOB_RESEARCH_CYCLE, JOB_INFO_ACQUISITION, JOB_STRATEGY_EVOLUTION)

# Explicitly forbidden job kinds — the queue will HARD-REFUSE to create these so a
# scheduler can never become a back-door training/promotion engine.
FORBIDDEN_JOB_KINDS = (
    "TRAIN", "TRAINING", "HYPERPARAMETER_TUNE", "TUNE", "PROMOTE_MODEL",
    "PROMOTION", "ENABLE_LIVE_TRADING", "LIVE_TRADING", "REOPEN_LANE",
    "AUTO_REOPEN", "PRODUCTION_WRITE",
)

# ----------------------------------------------------------------------------- #
# Job statuses (lifecycle). Ordered set is fixed by spec.
# ----------------------------------------------------------------------------- #
STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_RETRY_WAIT = "RETRY_WAIT"
STATUS_BLOCKED = "BLOCKED"
STATUS_CANCELLED = "CANCELLED"

JOB_STATUSES = (
    STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED,
    STATUS_RETRY_WAIT, STATUS_BLOCKED, STATUS_CANCELLED,
)

# Legal lifecycle transitions (fail-closed: anything else is rejected).
JOB_TRANSITIONS = {
    STATUS_QUEUED: {STATUS_RUNNING, STATUS_BLOCKED, STATUS_CANCELLED},
    STATUS_RUNNING: {STATUS_COMPLETED, STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED},
    STATUS_FAILED: {STATUS_RETRY_WAIT, STATUS_CANCELLED},   # retry or give up
    STATUS_RETRY_WAIT: {STATUS_RUNNING, STATUS_CANCELLED},
    STATUS_BLOCKED: set(),     # terminal (needs human review / governance change)
    STATUS_COMPLETED: set(),   # terminal
    STATUS_CANCELLED: set(),   # terminal
}

# Statuses considered "active" (occupy the single-execution slot / prevent duplicates).
ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_RETRY_WAIT)


@dataclass(frozen=True)
class SchedulerConfig:
    """Immutable scheduler configuration (safe defaults = DISCOVERY-ONLY, offline)."""

    # ---- Concurrency & timeouts ---------------------------------------------
    max_concurrent_jobs: int = 1          # single worker by default (safe)
    job_timeout_s: float = 300.0          # per-job execution timeout
    poll_interval_s: float = 1.0          # worker idle poll cadence

    # ---- Retry (exponential backoff) ----------------------------------------
    max_retries: int = 3
    retry_base_delay_s: float = 5.0       # delay = base * 2**attempt
    retry_max_delay_s: float = 600.0      # cap

    # ---- Provider rate limits (per provider, requests/min) ------------------
    provider_rate_limit_per_min: dict = field(default_factory=lambda: {
        "default": 30,
        "mock": 600,
    })

    # ---- Operating mode ------------------------------------------------------
    dry_run: bool = True                  # jobs persist nothing unless authorized
    use_mock_provider: bool = True        # tests use a mock provider
    kill_switch_engaged: bool = False     # checked in addition to the sentinel file

    # ---- Scheduling intervals (seconds). 0 disables interval scheduling. -----
    interval_research_cycle_s: float = 0.0
    interval_info_acquisition_s: float = 0.0
    interval_strategy_evolution_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "job_timeout_s": self.job_timeout_s,
            "poll_interval_s": self.poll_interval_s,
            "max_retries": self.max_retries,
            "retry_base_delay_s": self.retry_base_delay_s,
            "retry_max_delay_s": self.retry_max_delay_s,
            "provider_rate_limit_per_min": dict(self.provider_rate_limit_per_min),
            "dry_run": self.dry_run,
            "use_mock_provider": self.use_mock_provider,
            "kill_switch_engaged": self.kill_switch_engaged,
            "interval_research_cycle_s": self.interval_research_cycle_s,
            "interval_info_acquisition_s": self.interval_info_acquisition_s,
            "interval_strategy_evolution_s": self.interval_strategy_evolution_s,
        }


DEFAULT_CONFIG = SchedulerConfig()


def assert_isolated_path(db_path: Path) -> Path:
    """Refuse to open a protected production/research/external DB as the scheduler DB."""
    resolved = Path(db_path).resolve()
    protected = {
        Path(PRODUCTION_DB_PATH).resolve(),
        Path(RESEARCH_DB_PATH).resolve(),
        Path(EXTERNAL_INTEL_DB_PATH).resolve(),
    }
    if resolved in protected:
        raise ValueError(
            f"refusing to use protected database as scheduler queue: {resolved}")
    return resolved

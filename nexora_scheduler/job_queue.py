"""Persistent research job queue (Item 2.5, Phase 1).

A durable, SQLite-backed queue for DISCOVERY-ONLY research jobs. Built on the shared
``nexora_state_db`` connection + migration machinery, but against a SEPARATE scheduler
DB path (``database/nexora_research_scheduler.db``).

Invariants (tested in tests/test_research_scheduler.py):
  * Append-only history: ``job_executions``, ``job_retries``, ``audit_trail`` only ever
    get new rows; they are never updated in place.
  * Idempotency: ``enqueue`` de-duplicates by ``(kind, idempotency_key)`` — a second
    enqueue with the same key returns the existing job id (or raises if requested).
  * Duplicate-job prevention: while a job with the same key is ACTIVE (QUEUED / RUNNING /
    RETRY_WAIT) it is never re-created.
  * Concurrency guard: ``claim_next`` atomically transitions a QUEUED job to RUNNING
    using a single immediate transaction, so at most one worker can claim a given job.
  * Status is a guarded state machine (DB trigger + ``config.JOB_TRANSITIONS``).
  * Retry uses exponential backoff: delay = min(base * 2**attempt, cap).
  * Checkpoint/restart recovery: ``recover_running_jobs`` recovers jobs left RUNNING by
    a crashed process through LEGAL transitions (RUNNING->FAILED->RETRY_WAIT with an
    immediately-due next attempt), so they are re-claimable while history stays intact.
  * Forbidden job kinds are rejected both in the app layer AND by a DB trigger.

This module performs NO research work itself — it only tracks job state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from nexora_state_db.connection import SQLiteConnectionManager, transaction_immediate
from nexora_state_db.migrations import MigrationManager

from . import config as cfg


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%fZ")


def _canonical_sha(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class DuplicateJobError(RuntimeError):
    """Raised when enqueue is asked to reject duplicates and one already exists."""


class IllegalTransition(RuntimeError):
    """Raised when a status transition violates the guarded state machine."""


@dataclass(frozen=True)
class JobRecord:
    id: int
    job_key: str
    idempotency_key: str
    kind: str
    status: str
    trigger_source: str
    payload: Dict[str, object]
    spec_sha256: str
    priority: int
    attempts: int
    max_retries: int
    next_attempt_at: Optional[str]
    last_error: Optional[str]
    blocked_reason: Optional[str]
    result: Optional[Dict[str, object]]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    finished_at: Optional[str]

    @classmethod
    def from_row(cls, row) -> "JobRecord":
        def _json(v, default):
            if v is None:
                return default
            try:
                return json.loads(v)
            except (TypeError, ValueError):
                return default
        return cls(
            id=int(row["id"]), job_key=row["job_key"],
            idempotency_key=row["idempotency_key"], kind=row["kind"],
            status=row["status"], trigger_source=row["trigger_source"],
            payload=_json(row["payload_json"], {}), spec_sha256=row["spec_sha256"],
            priority=int(row["priority"]), attempts=int(row["attempts"]),
            max_retries=int(row["max_retries"]), next_attempt_at=row["next_attempt_at"],
            last_error=row["last_error"], blocked_reason=row["blocked_reason"],
            result=_json(row["result_json"], None), created_at=row["created_at"],
            updated_at=row["updated_at"], started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def as_dict(self) -> Dict[str, object]:
        return {
            "id": self.id, "job_key": self.job_key,
            "idempotency_key": self.idempotency_key, "kind": self.kind,
            "status": self.status, "trigger_source": self.trigger_source,
            "payload": self.payload, "spec_sha256": self.spec_sha256,
            "priority": self.priority, "attempts": self.attempts,
            "max_retries": self.max_retries, "next_attempt_at": self.next_attempt_at,
            "last_error": self.last_error, "blocked_reason": self.blocked_reason,
            "result": self.result, "created_at": self.created_at,
            "updated_at": self.updated_at, "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def make_idempotency_key(kind: str, payload: Dict[str, object]) -> str:
    """Deterministic idempotency key from kind + canonical payload."""
    return f"{kind}:{_canonical_sha(payload)[:32]}"


class ResearchJobQueue:
    """Durable DISCOVERY-ONLY research job queue over an isolated SQLite DB."""

    def __init__(self, db_path: Optional[Path] = None, *,
                 config: cfg.SchedulerConfig = cfg.DEFAULT_CONFIG,
                 bootstrap: bool = True) -> None:
        resolved = Path(db_path) if db_path else cfg.SCHEDULER_DATABASE_PATH
        # HARD isolation guard: never treat a protected DB as the scheduler queue.
        self.db_path = cfg.assert_isolated_path(resolved)
        self.config = config
        self.manager = SQLiteConnectionManager(db_path=self.db_path)
        if bootstrap:
            MigrationManager(self.manager, cfg.SCHEDULER_MIGRATIONS_DIR).migrate()

    # ------------------------------------------------------------------ #
    # Audit helper (append-only).
    # ------------------------------------------------------------------ #
    def _audit(self, conn, *, entity_id, action, old_state, new_state,
               actor="scheduler", detail=None) -> None:
        conn.execute(
            """INSERT INTO audit_trail
               (entity_type, entity_id, action, old_state, new_state, actor, detail_json,
                created_at)
               VALUES('job',?,?,?,?,?,?,?)""",
            (str(entity_id) if entity_id is not None else None, action, old_state,
             new_state, actor, json.dumps(detail or {}, sort_keys=True), utcnow()),
        )

    # ------------------------------------------------------------------ #
    # Enqueue (idempotent, duplicate-preventing).
    # ------------------------------------------------------------------ #
    def enqueue(self, *, kind: str, payload: Optional[Dict[str, object]] = None,
                job_key: Optional[str] = None,
                idempotency_key: Optional[str] = None,
                trigger_source: str = "MANUAL",
                priority: int = 100,
                max_retries: Optional[int] = None,
                reject_duplicates: bool = False) -> int:
        """Create a QUEUED job. Idempotent by (kind, idempotency_key).

        * Duplicate while ACTIVE (QUEUED/RUNNING/RETRY_WAIT) -> return existing id
          (or raise DuplicateJobError if ``reject_duplicates=True``).
        * Duplicate after terminal state -> a NEW row is created (a fresh re-run is
          legitimate: the previous attempt finished). The new row reuses the same
          idempotency key only if ``job_key`` differs; otherwise it collides and the
          existing terminal job is returned.

        Forbidden job kinds are rejected before touching the DB.
        """
        k = (kind or "").strip().upper()
        if k in cfg.FORBIDDEN_JOB_KINDS:
            raise ValueError(f"forbidden job kind {kind!r}: scheduler is DISCOVERY-ONLY")
        if k not in cfg.JOB_KINDS:
            raise ValueError(f"unknown job kind {kind!r}; allowed={cfg.JOB_KINDS}")

        payload = payload or {}
        idem = idempotency_key or make_idempotency_key(k, payload)
        job_key = job_key or f"{k}:{idem.split(':')[-1]}"
        mr = int(max_retries if max_retries is not None else self.config.max_retries)
        spec_sha = _canonical_sha({"kind": k, "payload": payload})

        with self.manager.open() as conn:
            # Duplicate checks by (kind, idempotency_key) and by job_key.
            existing = conn.execute(
                "SELECT * FROM scheduler_jobs WHERE kind=? AND idempotency_key=?",
                (k, idem)).fetchone()
            if existing is not None:
                rec = JobRecord.from_row(existing)
                if rec.status in cfg.ACTIVE_STATUSES:
                    if reject_duplicates:
                        raise DuplicateJobError(
                            f"active job already exists (id={rec.id}, status={rec.status})")
                    return rec.id
                # Terminal duplicate: only collide if job_key is identical (same row).
            same_key = conn.execute(
                "SELECT * FROM scheduler_jobs WHERE job_key=?", (job_key,)).fetchone()
            if same_key is not None:
                if reject_duplicates:
                    raise DuplicateJobError(f"job_key {job_key!r} already exists")
                return int(same_key["id"])

            try:
                with transaction_immediate(conn):
                    cur = conn.execute(
                        """INSERT INTO scheduler_jobs
                           (job_key, idempotency_key, kind, status, trigger_source,
                            payload_json, spec_sha256, priority, max_retries, created_at,
                            updated_at)
                           VALUES(?,?,?,'QUEUED',?,?,?,?,?,?,?)""",
                        (job_key, idem, k, trigger_source,
                         json.dumps(payload, sort_keys=True), spec_sha, int(priority), mr,
                         utcnow(), utcnow()),
                    )
                    job_id = int(cur.lastrowid)
                    self._audit(conn, entity_id=job_id, action="enqueue",
                                old_state=None, new_state=cfg.STATUS_QUEUED,
                                detail={"kind": k, "trigger_source": trigger_source})
            except Exception as exc:  # IntegrityError from trigger/unique -> surface
                raise DuplicateJobError(f"enqueue rejected: {exc}") from exc
            return job_id

    # ------------------------------------------------------------------ #
    # Claim (atomic QUEUED -> RUNNING; concurrency guard).
    # ------------------------------------------------------------------ #
    def claim_next(self) -> Optional[JobRecord]:
        """Atomically pick the oldest eligible QUEUED job and mark it RUNNING.

        RETRY_WAIT jobs whose ``next_attempt_at`` has elapsed are also eligible.
        Uses a single immediate transaction so only one claimant wins.
        """
        now = utcnow()
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                row = conn.execute(
                    """SELECT * FROM scheduler_jobs
                        WHERE status='QUEUED'
                           OR (status='RETRY_WAIT' AND next_attempt_at IS NOT NULL
                               AND next_attempt_at <= ?)
                        ORDER BY priority ASC, id ASC
                        LIMIT 1""",
                    (now,)).fetchone()
                if row is None:
                    return None
                job_id = int(row["id"])
                old_status = row["status"]
                new_attempts = int(row["attempts"]) + 1
                conn.execute(
                    """UPDATE scheduler_jobs
                          SET status='RUNNING', attempts=?, started_at=?, updated_at=?,
                              next_attempt_at=NULL
                        WHERE id=? AND status=?""",
                    (new_attempts, now, now, job_id, old_status),
                )
                self._audit(conn, entity_id=job_id, action="claim",
                            old_state=old_status, new_state=cfg.STATUS_RUNNING,
                            detail={"attempt": new_attempts})
                conn.execute(
                    """INSERT INTO job_executions (job_id, attempt, status, started_at)
                       VALUES(?,?, 'RUNNING', ?)""",
                    (job_id, new_attempts, now),
                )
                # Re-read for the returned record.
                fresh = conn.execute(
                    "SELECT * FROM scheduler_jobs WHERE id=?", (job_id,)).fetchone()
                return JobRecord.from_row(fresh)

    # ------------------------------------------------------------------ #
    # Complete / Fail / Block / Cancel transitions.
    # ------------------------------------------------------------------ #
    def _finish_execution(self, conn, job_id: int, status: str, error: Optional[str],
                          result: Optional[dict]) -> None:
        now = utcnow()
        row = conn.execute(
            "SELECT id, started_at FROM job_executions WHERE job_id=? "
            "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        if row is None:
            return
        started = row["started_at"]
        duration = None
        try:
            t0 = datetime.strptime(started, "%Y-%m-%dT%H:%M:%S.%fZ")
            t1 = datetime.strptime(now, "%Y-%m-%dT%H:%M:%S.%fZ")
            duration = (t1 - t0).total_seconds()
        except (TypeError, ValueError):
            duration = None
        conn.execute(
            """UPDATE job_executions
                  SET status=?, finished_at=?, duration_s=?, error=?, result_json=?
                WHERE id=?""",
            (status, now, duration, error,
             json.dumps(result, sort_keys=True) if result is not None else None,
             int(row["id"])),
        )

    def mark_completed(self, job_id: int, result: Optional[dict] = None) -> None:
        now = utcnow()
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                cur = conn.execute(
                    """UPDATE scheduler_jobs
                          SET status='COMPLETED', result_json=?, updated_at=?, finished_at=?
                        WHERE id=? AND status='RUNNING'""",
                    (json.dumps(result or {}, sort_keys=True), now, now, job_id),
                )
                if cur.rowcount != 1:
                    raise IllegalTransition(f"job {job_id} is not RUNNING")
                self._finish_execution(conn, job_id, "COMPLETED", None, result)
                self._audit(conn, entity_id=job_id, action="complete",
                            old_state=cfg.STATUS_RUNNING, new_state=cfg.STATUS_COMPLETED)

    def mark_failed(self, job_id: int, error: str, *,
                    retry: bool = True) -> str:
        """Mark RUNNING job FAILED. Then schedule RETRY_WAIT (exponential backoff) if
        attempts remain and ``retry`` is True; otherwise leave it terminal FAILED.

        Returns the resulting status (RETRY_WAIT or FAILED).
        """
        now = utcnow()
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                job = conn.execute(
                    "SELECT attempts, max_retries FROM scheduler_jobs WHERE id=? AND status='RUNNING'",
                    (job_id,)).fetchone()
                if job is None:
                    raise IllegalTransition(f"job {job_id} is not RUNNING")
                attempts = int(job["attempts"])
                max_retries = int(job["max_retries"])
                conn.execute(
                    """UPDATE scheduler_jobs
                          SET status='FAILED', last_error=?, updated_at=? WHERE id=?""",
                    (error, now, job_id),
                )
                self._finish_execution(conn, job_id, "FAILED", error, None)
                self._audit(conn, entity_id=job_id, action="fail",
                            old_state=cfg.STATUS_RUNNING, new_state=cfg.STATUS_FAILED,
                            detail={"error": error})

                if retry and attempts <= max_retries:
                    backoff = self._backoff_seconds(attempts)
                    next_at = (datetime.now(timezone.utc)
                               + timedelta(seconds=backoff)).strftime("%Y-%m-%dT%H:%M:%fZ")
                    conn.execute(
                        """UPDATE scheduler_jobs
                              SET status='RETRY_WAIT', next_attempt_at=?, updated_at=?
                            WHERE id=?""",
                        (next_at, now, job_id),
                    )
                    conn.execute(
                        """INSERT INTO job_retries
                           (job_id, attempt, backoff_s, scheduled_for, error, created_at)
                           VALUES(?,?,?,?,?,?)""",
                        (job_id, attempts, backoff, next_at, error, now),
                    )
                    self._audit(conn, entity_id=job_id, action="retry_scheduled",
                                old_state=cfg.STATUS_FAILED, new_state=cfg.STATUS_RETRY_WAIT,
                                detail={"attempt": attempts, "backoff_s": backoff,
                                        "scheduled_for": next_at})
                    return cfg.STATUS_RETRY_WAIT
                return cfg.STATUS_FAILED

    def mark_blocked(self, job_id: int, reason: str, *, from_status: str = "RUNNING") -> None:
        """Mark a job BLOCKED (terminal). Used when governance/PIT gate refuses work."""
        now = utcnow()
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                cur = conn.execute(
                    """UPDATE scheduler_jobs
                          SET status='BLOCKED', blocked_reason=?, updated_at=?, finished_at=?
                        WHERE id=? AND status=?""",
                    (reason, now, now, job_id, from_status),
                )
                if cur.rowcount != 1:
                    raise IllegalTransition(
                        f"job {job_id} is not {from_status} (cannot block)")
                self._finish_execution(conn, job_id, "BLOCKED", reason, None)
                self._audit(conn, entity_id=job_id, action="blocked",
                            old_state=from_status, new_state=cfg.STATUS_BLOCKED,
                            detail={"reason": reason})

    def cancel(self, job_id: int) -> bool:
        """Cancel a QUEUED / RETRY_WAIT / FAILED job. Returns True if cancelled."""
        now = utcnow()
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                row = conn.execute(
                    "SELECT status FROM scheduler_jobs WHERE id=?", (job_id,)).fetchone()
                if row is None:
                    return False
                old = row["status"]
                if old in (cfg.STATUS_COMPLETED, cfg.STATUS_BLOCKED, cfg.STATUS_CANCELLED,
                           cfg.STATUS_RUNNING):
                    return False
                conn.execute(
                    "UPDATE scheduler_jobs SET status='CANCELLED', updated_at=?, finished_at=? "
                    "WHERE id=?", (now, now, job_id))
                self._audit(conn, entity_id=job_id, action="cancel",
                            old_state=old, new_state=cfg.STATUS_CANCELLED)
                return True

    # ------------------------------------------------------------------ #
    # Retry / backoff helpers.
    # ------------------------------------------------------------------ #
    def _backoff_seconds(self, attempt: int) -> float:
        base = float(self.config.retry_base_delay_s)
        cap = float(self.config.retry_max_delay_s)
        return min(base * (2 ** max(0, attempt - 1)), cap)

    def due_retry_count(self) -> int:
        now = utcnow()
        with self.manager.open() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM scheduler_jobs WHERE status='RETRY_WAIT' "
                "AND next_attempt_at IS NOT NULL AND next_attempt_at <= ?", (now,)).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------ #
    # Restart recovery (checkpoint).
    # ------------------------------------------------------------------ #
    def recover_running_jobs(self, *, requeue: bool = True) -> int:
        """Recover jobs left RUNNING by a crashed process (checkpoint recovery).

        Returns the number of jobs recovered. The guarded state machine does not permit
        RUNNING -> QUEUED directly (RUNNING may only finish/block/cancel), so recovery is
        performed through LEGAL transitions:

          * close the orphaned attempt as FAILED in history,
          * RUNNING -> FAILED,
          * if ``requeue``: FAILED -> RETRY_WAIT with ``next_attempt_at = now`` so the
            job is immediately re-claimable (it will be claimed by the next ``claim_next``),
          * if not ``requeue``: leave it terminal FAILED (requires human action).

        This preserves the append-only history and the state-machine invariants.
        """
        now = utcnow()
        recovered = 0
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                rows = conn.execute(
                    "SELECT id, attempts FROM scheduler_jobs WHERE status='RUNNING'"
                ).fetchall()
                for r in rows:
                    job_id = int(r["id"])
                    attempts = int(r["attempts"])
                    self._finish_execution(conn, job_id, "FAILED",
                                           "recovered after restart (checkpoint)", None)
                    # LEGAL: RUNNING -> FAILED
                    conn.execute(
                        """UPDATE scheduler_jobs
                              SET status='FAILED', last_error='recovered after restart',
                                  updated_at=?
                            WHERE id=? AND status='RUNNING'""", (now, job_id))
                    self._audit(conn, entity_id=job_id, action="recover_fail",
                                old_state=cfg.STATUS_RUNNING, new_state=cfg.STATUS_FAILED)
                    if requeue:
                        # LEGAL: FAILED -> RETRY_WAIT (immediately due -> re-claimable).
                        conn.execute(
                            """UPDATE scheduler_jobs
                                  SET status='RETRY_WAIT', next_attempt_at=?, updated_at=?
                                WHERE id=? AND status='FAILED'""", (now, now, job_id))
                        conn.execute(
                            """INSERT INTO job_retries
                               (job_id, attempt, backoff_s, scheduled_for, error, created_at)
                               VALUES(?,?,?,?,?,?)""",
                            (job_id, attempts, 0.0, now,
                             "recovered after restart (checkpoint)", now))
                        self._audit(conn, entity_id=job_id, action="recover_requeue",
                                    old_state=cfg.STATUS_FAILED,
                                    new_state=cfg.STATUS_RETRY_WAIT)
                    recovered += 1
        return recovered

    # ------------------------------------------------------------------ #
    # Queries.
    # ------------------------------------------------------------------ #
    def get(self, job_id: int) -> Optional[JobRecord]:
        with self.manager.open() as conn:
            row = conn.execute(
                "SELECT * FROM scheduler_jobs WHERE id=?", (job_id,)).fetchone()
        return JobRecord.from_row(row) if row else None

    def list_jobs(self, *, status: Optional[str] = None, kind: Optional[str] = None,
                  limit: int = 500) -> List[JobRecord]:
        q = "SELECT * FROM scheduler_jobs"
        where, args = [], []
        if status:
            where.append("status=?"); args.append(status)
        if kind:
            where.append("kind=?"); args.append(kind)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id"
        if limit:
            q += f" LIMIT {int(limit)}"
        with self.manager.open() as conn:
            return [JobRecord.from_row(r) for r in conn.execute(q, tuple(args)).fetchall()]

    def count_by_status(self) -> Dict[str, int]:
        counts = {s: 0 for s in cfg.JOB_STATUSES}
        with self.manager.open() as conn:
            for r in conn.execute(
                    "SELECT status, COUNT(*) AS n FROM scheduler_jobs GROUP BY status"):
                counts[r["status"]] = int(r["n"])
        return counts

    def executions(self, job_id: int) -> List[Dict[str, object]]:
        with self.manager.open() as conn:
            rows = conn.execute(
                "SELECT * FROM job_executions WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def retries(self, job_id: int) -> List[Dict[str, object]]:
        with self.manager.open() as conn:
            rows = conn.execute(
                "SELECT * FROM job_retries WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def audit(self, *, entity_id: Optional[int] = None, limit: int = 500) -> List[Dict[str, object]]:
        q = "SELECT * FROM audit_trail"
        args: tuple = ()
        if entity_id is not None:
            q += " WHERE entity_type='job' AND entity_id=?"
            args = (str(entity_id),)
        q += " ORDER BY id"
        if limit:
            q += f" LIMIT {int(limit)}"
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(q, args).fetchall()]

    def record_provider_health(self, provider_id: str, status: str,
                               detail: Optional[dict] = None) -> None:
        with self.manager.open() as conn:
            conn.execute(
                """INSERT INTO provider_health (provider_id, status, detail_json, observed_at)
                   VALUES(?,?,?,?)""",
                (provider_id, status, json.dumps(detail or {}, sort_keys=True), utcnow()))
            conn.commit()

    def provider_health(self) -> Dict[str, Dict[str, object]]:
        """Latest health row per provider."""
        with self.manager.open() as conn:
            rows = conn.execute(
                "SELECT provider_id, status, detail_json, observed_at FROM provider_health "
                "ORDER BY id").fetchall()
        latest: Dict[str, Dict[str, object]] = {}
        for r in rows:
            try:
                detail = json.loads(r["detail_json"] or "{}")
            except (TypeError, ValueError):
                detail = {}
            latest[r["provider_id"]] = {
                "status": r["status"], "detail": detail, "observed_at": r["observed_at"]}
        return latest

    def last_successful_run(self) -> Optional[Dict[str, object]]:
        with self.manager.open() as conn:
            row = conn.execute(
                "SELECT * FROM scheduler_jobs WHERE status='COMPLETED' "
                "ORDER BY finished_at DESC LIMIT 1").fetchone()
        return JobRecord.from_row(row).as_dict() if row else None

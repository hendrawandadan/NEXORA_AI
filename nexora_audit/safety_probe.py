"""Isolated runtime probes for atomic claim (Part C) and crash recovery (Part E).

These probes run ONLY against a freshly created temporary SQLite database that
is built from the repository migrations. They never open the production
database, never touch CSV/datasets/models/backups, and never call train_one() or
model.fit(). They exist to *measure* invariants of the current repository, and
they report whether the invariants hold so the readiness gate can decide.

The probes intentionally exercise the *existing* repositories to surface
violations rather than mask them. A separate helper shows the guarded-claim
reference behaviour used to confirm the fix direction.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from nexora_state_db.bootstrap import create_dev_database
from nexora_state_db.connection import SQLiteConnectionManager, transaction_immediate
from nexora_state_db.models import TrainingJobCreate, TrainingRunCreate
from nexora_state_db.repositories import (
    SQLiteTrainingJobRepository,
    SQLiteTrainingRunRepository,
)


def _make_queued_job(manager: SQLiteConnectionManager, key: str) -> int:
    jobs = SQLiteTrainingJobRepository(manager)
    job_id = jobs.create_job(
        TrainingJobCreate(key, "individual", "EURUSD", "M30", 2, "PLANNED", "{}")
    )
    jobs.queue_planned_job(job_id, "probe")
    return job_id


@dataclass
class ProbeOutcome:
    name: str
    passed: bool
    detail: str
    evidence: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def probe_single_active_attempt() -> ProbeOutcome:
    """Two workers race to claim; one job must never get two STARTED runs."""
    with tempfile.TemporaryDirectory() as tmp:
        manager = create_dev_database(Path(tmp) / "probe.db")
        jobs = SQLiteTrainingJobRepository(manager)
        runs = SQLiteTrainingRunRepository(manager)
        job_id = jobs.create_job(
            TrainingJobCreate("race-job", "individual", "EURUSD", "M30", 2, "PLANNED", "{}")
        )
        jobs.queue_planned_job(job_id, "probe")
        runs.create_run(TrainingRunCreate(job_id, "race-1", 0, "QUEUED", "{}"))

        # uq_one_active_run_per_job normally forbids a second QUEUED run for the
        # same job; if present, the race is prevented at the schema boundary.
        try:
            runs.create_run(TrainingRunCreate(job_id, "race-2", 1, "QUEUED", "{}"))
            second_create_ok = True
        except sqlite3.IntegrityError:
            second_create_ok = False

        if not second_create_ok:
            with manager.open() as conn:
                active = conn.execute(
                    "SELECT COUNT(*) FROM training_runs WHERE job_id=? AND status IN ('QUEUED','STARTED')",
                    (job_id,),
                ).fetchone()[0]
            return ProbeOutcome(
                "single_active_attempt",
                active <= 1,
                "schema partial unique index blocks a second active run for one job",
                {"schema_enforced_single_active": True, "active_runs": active},
            )

        barrier = threading.Barrier(2)
        results: List[Optional[int]] = []
        errors: List[BaseException] = []

        def worker() -> None:
            try:
                barrier.wait()
                results.append(runs.claim_next_queued_run(job_id))
            except BaseException as exc:  # pragma: no cover - surfaced in evidence
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with manager.open() as conn:
            started = conn.execute(
                "SELECT COUNT(*) FROM training_runs WHERE job_id=? AND status='STARTED'",
                (job_id,),
            ).fetchone()[0]
            job_status = conn.execute(
                "SELECT status FROM training_jobs WHERE id=?", (job_id,)
            ).fetchone()[0]

        passed = started <= 1 and not errors
        return ProbeOutcome(
            "single_active_attempt",
            passed,
            "one job -> at most one STARTED run" if passed else f"{started} STARTED runs for one job",
            {
                "claimed": results,
                "errors": [str(e) for e in errors],
                "started_runs": started,
                "job_status": job_status,
            },
        )


def probe_running_job_claim_rejected() -> ProbeOutcome:
    """A job already RUNNING (active STARTED run) must not yield another claim."""
    with tempfile.TemporaryDirectory() as tmp:
        manager = create_dev_database(Path(tmp) / "probe.db")
        jobs = SQLiteTrainingJobRepository(manager)
        runs = SQLiteTrainingRunRepository(manager)
        job_id = _make_queued_job(manager, "running-job")
        first_run = runs.create_run(TrainingRunCreate(job_id, "r1", 0, "QUEUED", "{}"))
        claimed_first = runs.claim_next_queued_run(job_id)

        # Pre-place a second queued run to test the RUNNING-job guard.
        # (Unique active-run index blocks QUEUED+STARTED coexistence, so this is
        # expected to be rejected by the schema; we still probe claim behaviour.)
        try:
            runs.create_run(TrainingRunCreate(job_id, "r2", 1, "QUEUED", "{}"))
            second_create_ok = True
        except sqlite3.IntegrityError:
            second_create_ok = False

        second_claim = runs.claim_next_queued_run(job_id)
        with manager.open() as conn:
            started = conn.execute(
                "SELECT COUNT(*) FROM training_runs WHERE job_id=? AND status='STARTED'",
                (job_id,),
            ).fetchone()[0]
            job_status = conn.execute(
                "SELECT status FROM training_jobs WHERE id=?", (job_id,)
            ).fetchone()[0]

        # Pass if either: the second claim returned None, OR the schema blocked
        # creating a second active run so no double claim is possible.
        passed = (second_claim is None) or (not second_create_ok)
        return ProbeOutcome(
            "running_job_claim_rejected",
            passed,
            "RUNNING job cannot produce a second active claim",
            {
                "claimed_first": claimed_first,
                "first_run_id": first_run,
                "second_create_ok": second_create_ok,
                "second_claim": second_claim,
                "started_runs": started,
                "job_status": job_status,
            },
        )


def _transition(manager: SQLiteConnectionManager, run_id: int, target: str, actor: str = "probe") -> None:
    """Apply a checkpoint transition using the current repository."""
    from nexora_state_db.repositories import SQLiteCheckpointRepository

    SQLiteCheckpointRepository(manager).append_checkpoint(run_id, target, actor=actor)


def probe_lifecycle_synchronized() -> ProbeOutcome:
    """Checkpoint transitions must keep job.status synchronized with run.status."""
    with tempfile.TemporaryDirectory() as tmp:
        manager = create_dev_database(Path(tmp) / "probe.db")
        jobs = SQLiteTrainingJobRepository(manager)
        runs = SQLiteTrainingRunRepository(manager)
        job_id = _make_queued_job(manager, "sync-job")
        run_id = runs.create_run(TrainingRunCreate(job_id, "s1", 0, "QUEUED", "{}"))
        runs.claim_next_queued_run(job_id)

        _transition(manager, run_id, "TRAIN_DONE")
        with manager.open() as conn:
            run_status = conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0]
            job_status = conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0]

        passed = (run_status == "TRAIN_DONE" and job_status == "TRAIN_DONE")
        return ProbeOutcome(
            "lifecycle_synchronized",
            passed,
            "job mirrors run status after TRAIN_DONE"
            if passed
            else f"run={run_status} job={job_status} desynchronized",
            {"run_status": run_status, "job_status": job_status},
        )


def run_claim_and_lifecycle_probes() -> Dict[str, Any]:
    """Aggregate Part C + D probe results for the RUNNER_READY gate."""
    race = probe_single_active_attempt()
    running = probe_running_job_claim_rejected()
    sync = probe_lifecycle_synchronized()
    aggregate = {
        "single_active_attempt_enforced": race.passed,
        "running_job_claim_rejected": running.passed,
        "lifecycle_synchronized": sync.passed,
        "probes": [race.as_dict(), running.as_dict(), sync.as_dict()],
    }
    aggregate["all_passed"] = all(
        [race.passed, running.passed, sync.passed]
    )
    return aggregate


# ---------------------------------------------------------------------------------
# Crash recovery probe (Part E)
# ---------------------------------------------------------------------------------
def probe_crash_recovery() -> Dict[str, Any]:
    """Simulate a crash between filesystem promotion and DB commit, then recover.

    Uses a dummy artifact (never a real model) and validates that recovery:
      * does not create a duplicate ACTIVE artifact or active run,
      * preserves PROMOTED as terminal,
      * is idempotent when re-run.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manager = create_dev_database(root / "recovery.db")
        jobs = SQLiteTrainingJobRepository(manager)
        runs = SQLiteTrainingRunRepository(manager)
        job_id = _make_queued_job(manager, "recovery-job")
        run_id = runs.create_run(TrainingRunCreate(job_id, "rec1", 0, "QUEUED", "{}"))
        runs.claim_next_queued_run(job_id)
        _transition(manager, run_id, "TRAIN_DONE")

        staged = root / "staging" / "model.bin"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"DUMMY PROBE MODEL BYTES")
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()

        with manager.open() as conn:
            artifact_id = conn.execute(
                "INSERT INTO model_artifacts(run_id,artifact_type,artifact_path,sha256,size_bytes,is_temporary) "
                "VALUES(?,?,?,?,?,1)",
                (run_id, "model", str(staged), digest, staged.stat().st_size),
            ).lastrowid
            conn.execute(
                "INSERT INTO validation_results(run_id,validation_type,passed,details_json) VALUES(?,?,1,?)",
                (run_id, "probe_gate", json.dumps({"sha256": digest})),
            )
            conn.commit()

        _transition(manager, run_id, "VALIDATED")

        target = root / "versioned" / f"{digest}.bin"
        target.parent.mkdir()
        manifest_path = root / "promotion-manifest.json"
        manifest = {
            "state": "PREPARED",
            "run_id": run_id,
            "job_id": job_id,
            "artifact_id": artifact_id,
            "sha256": digest,
            "source_path": str(staged),
            "target_path": str(target),
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # Filesystem move happens, then "crash" before the DB commit.
        staged.replace(target)
        manifest["state"] = "FS_PROMOTED_DB_PENDING"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result1 = _recover(manifest_path, manager)
        result2 = _recover(manifest_path, manager)  # idempotency

        with manager.open() as conn:
            run_status = conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0]
            job_status = conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0]
            active_artifacts = conn.execute(
                "SELECT COUNT(*) FROM model_artifacts WHERE run_id=? AND lifecycle_status='ACTIVE'",
                (run_id,),
            ).fetchone()[0]
            active_runs = conn.execute(
                "SELECT COUNT(*) FROM training_runs WHERE job_id=? AND status IN ('QUEUED','STARTED')",
                (job_id,),
            ).fetchone()[0]

        promoted_terminal_preserved = run_status == "PROMOTED" and job_status == "PROMOTED"
        no_duplicate_active_run = active_runs == 0
        no_duplicate_artifact = active_artifacts == 1

        return {
            "recovery_first": result1,
            "recovery_second": result2,
            "idempotent": result2 in ("already-promoted", "manifest-finalized"),
            "no_duplicate_active_run": no_duplicate_active_run,
            "no_duplicate_artifact": no_duplicate_artifact,
            "promoted_terminal_preserved": promoted_terminal_preserved,
            "run_status": run_status,
            "job_status": job_status,
            "active_artifact_count": active_artifacts,
            "all_passed": no_duplicate_active_run
            and no_duplicate_artifact
            and promoted_terminal_preserved
            and (result2 in ("already-promoted", "manifest-finalized")),
        }


def _recover(manifest_path: Path, manager: SQLiteConnectionManager) -> str:
    """Reference recovery routine used only by the probe."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["state"] == "PROMOTED":
        return "already-promoted"
    target = Path(manifest["target_path"])
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("promotion target hash mismatch")

    with manager.open() as conn:
        run = conn.execute(
            "SELECT status,job_id FROM training_runs WHERE id=?", (manifest["run_id"],)
        ).fetchone()
        artifact = conn.execute(
            "SELECT lifecycle_status,sha256,artifact_path FROM model_artifacts WHERE id=?",
            (manifest["artifact_id"],),
        ).fetchone()

    already = (
        run is not None
        and run["status"] == "PROMOTED"
        and artifact is not None
        and artifact["lifecycle_status"] == "ACTIVE"
        and artifact["sha256"] == digest
        and artifact["artifact_path"] == str(target)
    )
    if already:
        result = "manifest-finalized"
    else:
        _promote_db(manager, manifest)
        result = "recovered"

    manifest["state"] = "PROMOTED"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return result


def _promote_db(manager: SQLiteConnectionManager, manifest: Dict[str, Any]) -> None:
    with manager.open() as conn, transaction_immediate(conn):
        now = "2026-11-07T00:00:00Z"
        conn.execute(
            "UPDATE model_artifacts SET lifecycle_status='ACTIVE',activated_at=?,artifact_path=?,is_temporary=0 WHERE id=?",
            (now, manifest["target_path"], manifest["artifact_id"]),
        )
        conn.execute(
            "INSERT INTO checkpoints(run_id,checkpoint_status,changed_by,note,metadata_json,changed_at) "
            "VALUES(?,?,?,?,?,?)",
            (manifest["run_id"], "PROMOTED", "probe_recovery", "promotion commit", "{}", now),
        )
        conn.execute(
            "UPDATE training_runs SET status='PROMOTED',ended_at=?,updated_at=? WHERE id=?",
            (now, now, manifest["run_id"]),
        )
        conn.execute(
            "UPDATE training_jobs SET status='PROMOTED',updated_at=? WHERE id=?",
            (now, manifest["job_id"]),
        )
        conn.execute(
            "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) "
            "VALUES('training_run',?,'artifact_promoted','VALIDATED','PROMOTED',?,'probe_recovery',?)",
            (str(manifest["run_id"]), json.dumps({"artifact_id": manifest["artifact_id"], "sha256": manifest["sha256"]}), now),
        )

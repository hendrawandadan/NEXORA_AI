from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest

from nexora_state_db.bootstrap import create_dev_database
from nexora_state_db.connection import SQLiteConnectionManager, transaction_immediate
from nexora_state_db.models import TrainingJobCreate, TrainingRunCreate
from nexora_state_db.repositories import SQLiteTrainingJobRepository, SQLiteTrainingRunRepository


def _seed_queued(manager: SQLiteConnectionManager, key: str = "prep-001") -> tuple[int, int]:
    jobs = SQLiteTrainingJobRepository(manager)
    job_id = jobs.create_job(TrainingJobCreate(key, "individual", "EURUSD", "M30", 2, "PLANNED", "{}"))
    jobs.queue_planned_job(job_id, "integration-test")
    run_id = SQLiteTrainingRunRepository(manager).create_run(
        TrainingRunCreate(job_id, f"{key}-attempt-1", 0, "QUEUED", "{}")
    )
    return job_id, run_id


def _transition(manager: SQLiteConnectionManager, run_id: int, target: str, actor: str = "test") -> None:
    allowed = {
        "QUEUED": {"STARTED", "FAILED"},
        "STARTED": {"TRAIN_DONE", "FAILED"},
        "TRAIN_DONE": {"VALIDATED", "FAILED"},
        "VALIDATED": {"PROMOTED", "FAILED"},
        "FAILED": {"RETRY_PENDING"},
        "RETRY_PENDING": {"STARTED"},
    }
    job_state = {
        "QUEUED": "QUEUED", "STARTED": "RUNNING", "TRAIN_DONE": "TRAIN_DONE",
        "VALIDATED": "VALIDATED", "PROMOTED": "PROMOTED", "FAILED": "FAILED",
        "RETRY_PENDING": "RETRY_PENDING",
    }
    with manager.open() as conn, transaction_immediate(conn):
        run = conn.execute("SELECT job_id,status FROM training_runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(run_id)
        current = run["status"]
        if current == "PROMOTED":
            raise ValueError("PROMOTED is terminal")
        if target not in allowed.get(current, set()):
            raise ValueError(f"invalid transition {current}->{target}")
        now = "2026-11-07T00:00:00Z"
        conn.execute(
            "INSERT INTO checkpoints(run_id,checkpoint_status,changed_by,note,metadata_json,changed_at) VALUES(?,?,?,?,?,?)",
            (run_id, target, actor, "integration transition", "{}", now),
        )
        conn.execute(
            "UPDATE training_runs SET status=?,started_at=CASE WHEN ?='STARTED' THEN COALESCE(started_at,?) ELSE started_at END,ended_at=CASE WHEN ? IN ('FAILED','PROMOTED') THEN ? ELSE ended_at END,updated_at=? WHERE id=?",
            (target, target, now, target, now, now, run_id),
        )
        job = conn.execute("SELECT status FROM training_jobs WHERE id=?", (run["job_id"],)).fetchone()
        conn.execute("UPDATE training_jobs SET status=?,updated_at=? WHERE id=?", (job_state[target], now, run["job_id"]))
        conn.execute(
            "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) VALUES('training_run',?,?,?,?,?,?,?)",
            (str(run_id), "runner_transition", current, target,
             json.dumps({"job_id": run["job_id"], "job_old_state": job["status"], "job_new_state": job_state[target]}), actor, now),
        )


def _promote_db(manager: SQLiteConnectionManager, run_id: int, artifact_id: int, target_path: Path) -> None:
    with manager.open() as conn, transaction_immediate(conn):
        run = conn.execute("SELECT job_id,status FROM training_runs WHERE id=?", (run_id,)).fetchone()
        if run["status"] != "VALIDATED":
            raise ValueError("only VALIDATED runs can be promoted")
        validation = conn.execute(
            "SELECT count(*) AS total, sum(CASE WHEN passed=1 THEN 1 ELSE 0 END) AS passed, sum(CASE WHEN passed=0 THEN 1 ELSE 0 END) AS failed FROM validation_results WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not validation["total"] or validation["failed"]:
            raise ValueError("validation gate has not passed")
        _hash = conn.execute("SELECT sha256,lifecycle_status FROM model_artifacts WHERE id=? AND run_id=?", (artifact_id, run_id)).fetchone()
        if _hash is None or _hash["lifecycle_status"] != "STAGED":
            raise ValueError("staged artifact missing")
        now = "2026-11-07T00:00:01Z"
        conn.execute("UPDATE model_artifacts SET lifecycle_status='ACTIVE',activated_at=?,artifact_path=?,is_temporary=0 WHERE id=?",
                     (now, str(target_path), artifact_id))
        conn.execute("INSERT INTO checkpoints(run_id,checkpoint_status,changed_by,note,metadata_json,changed_at) VALUES(?,?,?,?,?,?)",
                     (run_id, "PROMOTED", "recovery", "promotion commit", "{}", now))
        conn.execute("UPDATE training_runs SET status='PROMOTED',ended_at=?,updated_at=? WHERE id=?", (now, now, run_id))
        conn.execute("UPDATE training_jobs SET status='PROMOTED',updated_at=? WHERE id=?", (now, run["job_id"]))
        conn.execute("INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) VALUES('training_run',?,'artifact_promoted','VALIDATED','PROMOTED',?,'recovery',?)",
                     (str(run_id), json.dumps({"artifact_id": artifact_id, "sha256": _hash["sha256"]}), now))


def _recover_promotion(manifest_path: Path, manager: SQLiteConnectionManager) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["state"] == "PROMOTED":
        return "already-promoted"
    target = Path(manifest["target_path"])
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("promotion target hash mismatch")
    with manager.open() as conn:
        run = conn.execute("SELECT status FROM training_runs WHERE id=?", (manifest["run_id"],)).fetchone()
        artifact = conn.execute("SELECT lifecycle_status,sha256,artifact_path FROM model_artifacts WHERE id=?", (manifest["artifact_id"],)).fetchone()
    if run and run["status"] == "PROMOTED" and artifact and artifact["lifecycle_status"] == "ACTIVE" and artifact["sha256"] == digest and artifact["artifact_path"] == str(target):
        result = "manifest-finalized"
    else:
        _promote_db(manager, manifest["run_id"], manifest["artifact_id"], target)
        result = "recovered"
    manifest["state"] = "PROMOTED"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return result


def test_explicit_queue_atomic_concurrent_claim_and_consistency(tmp_path: Path) -> None:
    manager = create_dev_database(tmp_path / "runner.db")
    jobs = SQLiteTrainingJobRepository(manager)
    runs = SQLiteTrainingRunRepository(manager)
    job_id = jobs.create_job(TrainingJobCreate("planned", "individual", "EURUSD", "M30", 2, "PLANNED", "{}"))
    assert runs.claim_next_queued_run(job_id) is None
    jobs.queue_planned_job(job_id, "operator")
    run_id = runs.create_run(TrainingRunCreate(job_id, "attempt-1", 0, "QUEUED", "{}"))
    barrier = threading.Barrier(2)
    claimed: list[int | None] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            claimed.append(runs.claim_next_queued_run(job_id))
        except BaseException as exc:
            errors.append(exc)

    workers = [threading.Thread(target=worker) for _ in range(2)]
    for worker_thread in workers: worker_thread.start()
    for worker_thread in workers: worker_thread.join()
    assert errors == []
    assert claimed.count(run_id) == 1 and claimed.count(None) == 1
    with manager.open() as conn:
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "RUNNING"
        assert conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0] == "STARTED"
        assert conn.execute("SELECT checkpoint_status FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()[0] == "STARTED"
        assert conn.execute("SELECT count(*) FROM audit_logs WHERE entity_type='training_job' AND action='explicit_queue'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM audit_logs WHERE entity_type='training_run' AND action='claim'").fetchone()[0] == 1


def test_failure_retry_history_and_job_run_state_transitions(tmp_path: Path) -> None:
    manager = create_dev_database(tmp_path / "retry.db")
    job_id, first_run = _seed_queued(manager, "retry-job")
    assert SQLiteTrainingRunRepository(manager).claim_next_queued_run(job_id) == first_run
    _transition(manager, first_run, "FAILED")
    _transition(manager, first_run, "RETRY_PENDING")
    # v4: a retry re-queues the job RETRY_PENDING -> QUEUED only via an explicit
    # retry_queue audit, and a run can be created only while the job is QUEUED.
    with manager.open() as conn, transaction_immediate(conn):
        conn.execute(
            "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) "
            "VALUES('training_job',?,'retry_queue','RETRY_PENDING','QUEUED','{}','retry-operator','2026-11-07T00:00:00Z')",
            (str(job_id),),
        )
        conn.execute(
            "UPDATE training_jobs SET status='QUEUED',queued_at='2026-11-07T00:00:00Z',queued_by='retry-operator' WHERE id=?",
            (job_id,),
        )
    retry_run = SQLiteTrainingRunRepository(manager).create_run(
        TrainingRunCreate(job_id, "retry-job-attempt-2", 1, "QUEUED", "{}")
    )
    assert SQLiteTrainingRunRepository(manager).claim_next_queued_run(job_id) == retry_run
    _transition(manager, retry_run, "TRAIN_DONE")
    with manager.open() as conn:
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "TRAIN_DONE"
        assert [r[0] for r in conn.execute("SELECT status FROM training_runs WHERE job_id=? ORDER BY run_index", (job_id,))] == ["RETRY_PENDING", "TRAIN_DONE"]
        assert conn.execute("SELECT count(*) FROM audit_logs WHERE action='runner_transition'").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM checkpoints WHERE run_id=?", (first_run,)).fetchone()[0] == 3


def test_dummy_artifact_hash_validation_and_promotion_recovery(tmp_path: Path) -> None:
    manager = create_dev_database(tmp_path / "artifact.db")
    job_id, run_id = _seed_queued(manager, "artifact-job")
    assert SQLiteTrainingRunRepository(manager).claim_next_queued_run(job_id) == run_id

    # Test-only dummy trainer: writes fixture bytes and never imports/calls train_one.
    staging = tmp_path / "staging"
    staging.mkdir()
    staged_file = staging / "model.bin"
    staged_file.write_bytes(b"DUMMY MODEL; NOT A TRAINED ARTIFACT")
    digest = hashlib.sha256(staged_file.read_bytes()).hexdigest()
    with manager.open() as conn:
        artifact_id = conn.execute(
            "INSERT INTO model_artifacts(run_id,artifact_type,artifact_path,sha256,size_bytes,is_temporary) VALUES(?,?,?,?,?,1)",
            (run_id, "model", str(staged_file), digest, staged_file.stat().st_size),
        ).lastrowid
        conn.commit()
    assert hashlib.sha256(Path(staged_file).read_bytes()).hexdigest() == digest
    _transition(manager, run_id, "TRAIN_DONE")
    with manager.open() as conn:
        conn.execute("INSERT INTO validation_results(run_id,validation_type,passed,details_json) VALUES(?,?,0,?)",
                     (run_id, "fixture_gate", json.dumps({"sha256": digest})))
        conn.commit()
    _transition(manager, run_id, "VALIDATED")
    target = tmp_path / "versioned" / f"{digest}.bin"
    with pytest.raises(ValueError, match="validation gate"):
        _promote_db(manager, run_id, artifact_id, target)
    with manager.open() as conn:
        conn.execute("UPDATE validation_results SET passed=1 WHERE run_id=?", (run_id,))
        conn.commit()

    target.parent.mkdir()
    manifest_path = tmp_path / "promotion-manifest.json"
    manifest = {"state": "PREPARED", "run_id": run_id, "artifact_id": artifact_id,
                "sha256": digest, "source_path": str(staged_file), "target_path": str(target)}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    os.replace(staged_file, target)
    manifest["state"] = "FS_PROMOTED_DB_PENDING"  # crash point: file moved, SQLite not committed
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert _recover_promotion(manifest_path, manager) == "recovered"
    manifest["state"] = "FS_PROMOTED_DB_PENDING"  # crash point after DB commit but before manifest finalize
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert _recover_promotion(manifest_path, manager) == "manifest-finalized"
    assert _recover_promotion(manifest_path, manager) == "already-promoted"
    with manager.open() as conn:
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "PROMOTED"
        assert conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0] == "PROMOTED"
        assert conn.execute("SELECT lifecycle_status FROM model_artifacts WHERE id=?", (artifact_id,)).fetchone()[0] == "ACTIVE"
        assert conn.execute("SELECT artifact_path,is_temporary FROM model_artifacts WHERE id=?", (artifact_id,)).fetchone()[:] == (str(target), 0)
        assert conn.execute("SELECT count(*) FROM validation_results WHERE run_id=? AND passed=1", (run_id,)).fetchone()[0] == 1
    assert json.loads(manifest_path.read_text())["state"] == "PROMOTED"
    with pytest.raises(ValueError, match="terminal"):
        _transition(manager, run_id, "PROMOTED")


def test_transition_rollback_reopen_and_fk_integrity(tmp_path: Path) -> None:
    db_path = tmp_path / "rollback.db"
    manager = create_dev_database(db_path)
    job_id, run_id = _seed_queued(manager, "rollback-job")
    assert SQLiteTrainingRunRepository(manager).claim_next_queued_run(job_id) == run_id
    with manager.open() as conn:
        conn.execute("CREATE TRIGGER reject_runner_audit BEFORE INSERT ON audit_logs WHEN NEW.action='runner_transition' BEGIN SELECT RAISE(ABORT,'audit blocked'); END")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="audit blocked"):
        _transition(manager, run_id, "TRAIN_DONE")
    reopened = SQLiteConnectionManager(db_path)
    with reopened.open() as conn:
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "RUNNING"
        assert conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0] == "STARTED"
        assert conn.execute("SELECT count(*) FROM checkpoints WHERE run_id=? AND checkpoint_status='TRAIN_DONE'", (run_id,)).fetchone()[0] == 0
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO training_job_datasets(job_id,dataset_id) VALUES(?,?)", (job_id, 999999))

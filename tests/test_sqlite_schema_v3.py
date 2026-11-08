from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from nexora_state_db.bootstrap import create_dev_database
from nexora_state_db.connection import SQLiteConnectionManager
from nexora_state_db.migrations import MigrationManager
from nexora_state_db.models import TrainingJobCreate, TrainingRunCreate
from nexora_state_db.repositories import SQLiteTrainingJobRepository, SQLiteTrainingRunRepository


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "nexora_state_db" / "migrations"


def _job(manager: SQLiteConnectionManager, key: str = "planned", status: str = "PLANNED") -> int:
    return SQLiteTrainingJobRepository(manager).create_job(
        TrainingJobCreate(key, "individual", "EURUSD", "M30", 2, status, "{}",
                          "MISSING", "TRAIN", "PREP-1", "legacy.csv", "a" * 64)
    )


def test_planned_job_does_not_become_queued_or_claimable(tmp_path: Path) -> None:
    manager = create_dev_database(tmp_path / "v3.db")
    job_id = _job(manager)
    with manager.open() as conn:
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "PLANNED"
        assert conn.execute("SELECT id FROM training_runs WHERE job_id=?", (job_id,)).fetchone() is None
    assert SQLiteTrainingRunRepository(manager).claim_next_queued_run(job_id) is None
    # v4 replaced the PLANNED-only run guard with training_runs_insert_guard,
    # which blocks any run unless its job is QUEUED (PLANNED included).
    with pytest.raises(sqlite3.IntegrityError, match="queued only for a QUEUED job"):
        SQLiteTrainingRunRepository(manager).create_run(TrainingRunCreate(job_id, "fake", 0, "QUEUED", "{}"))
    with manager.open() as conn, pytest.raises(sqlite3.IntegrityError, match="explicit queue"):
        conn.execute("UPDATE training_jobs SET status='QUEUED' WHERE id=?", (job_id,))
    with manager.open() as conn, pytest.raises(sqlite3.IntegrityError, match="explicit queue"):
        conn.execute("UPDATE training_jobs SET status='QUEUED',queued_at='2026-01-01T00:00:00Z',queued_by='forged' WHERE id=?", (job_id,))


def test_explicit_queue_and_atomic_claim_require_run(tmp_path: Path) -> None:
    manager = create_dev_database(tmp_path / "v3.db")
    jobs = SQLiteTrainingJobRepository(manager)
    runs = SQLiteTrainingRunRepository(manager)
    job_id = _job(manager)
    with manager.open() as conn, pytest.raises(sqlite3.IntegrityError, match="explicit queue"):
        conn.execute("UPDATE training_jobs SET status='RUNNING' WHERE id=?", (job_id,))
    jobs.queue_planned_job(job_id, "operator")
    with manager.open() as conn, pytest.raises(sqlite3.IntegrityError, match="STARTED training run"):
        conn.execute("UPDATE training_jobs SET status='RUNNING' WHERE id=?", (job_id,))
    run_id = runs.create_run(TrainingRunCreate(job_id, "run-real", 0, "QUEUED", "{}"))
    assert runs.claim_next_queued_run(job_id) == run_id
    with manager.open() as conn:
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "RUNNING"
        assert conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0] == "STARTED"
        # v4 claim writes two training_job audits: explicit_queue (from queue_planned_job)
        # and claim (QUEUED -> RUNNING). Both are required for the synchronized lifecycle.
        assert conn.execute("SELECT count(*) FROM audit_logs WHERE entity_type='training_job' AND entity_id=?", (str(job_id),)).fetchone()[0] == 2


def test_promoted_job_is_terminal_even_for_replay(tmp_path: Path) -> None:
    manager = create_dev_database(tmp_path / "v3.db")
    job_id = _job(manager, "promoted", "QUEUED")
    runs = SQLiteTrainingRunRepository(manager)
    with manager.open() as conn:
        conn.execute("UPDATE training_jobs SET status='FAILED' WHERE id=?", (job_id,))
        conn.execute("UPDATE training_jobs SET status='RETRY_PENDING' WHERE id=?", (job_id,))
        conn.commit()
    # v4: a retry re-queues the job RETRY_PENDING -> QUEUED only via an explicit
    # retry_queue audit, and a run can be created only while the job is QUEUED.
    with manager.open() as conn, pytest.raises(sqlite3.IntegrityError, match="retry requires explicit retry_queue audit"):
        conn.execute("UPDATE training_jobs SET status='QUEUED',queued_at='2026-01-01T00:00:00Z',queued_by='op' WHERE id=?", (job_id,))
    with manager.open() as conn:
        conn.execute(
            "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) "
            "VALUES('training_job',?,'retry_queue','RETRY_PENDING','QUEUED','{}','op','2026-01-01T00:00:00Z')",
            (str(job_id),),
        )
        conn.execute("UPDATE training_jobs SET status='QUEUED',queued_at='2026-01-01T00:00:00Z',queued_by='op' WHERE id=?", (job_id,))
        conn.commit()
    run_id = runs.create_run(TrainingRunCreate(job_id, "retry-run", 0, "QUEUED", "{}"))
    assert runs.claim_next_queued_run(job_id) == run_id
    with manager.open() as conn:
        conn.execute("UPDATE training_jobs SET status='TRAIN_DONE' WHERE id=?", (job_id,))
        conn.execute("UPDATE training_jobs SET status='VALIDATED' WHERE id=?", (job_id,))
        conn.execute("UPDATE training_jobs SET status='PROMOTED' WHERE id=?", (job_id,))
        conn.commit()
    for status in ("PROMOTED", "FAILED", "QUEUED"):
        with manager.open() as conn, pytest.raises(sqlite3.IntegrityError, match="PROMOTED job is terminal"):
            conn.execute("UPDATE training_jobs SET status=? WHERE id=?", (status, job_id))
    with manager.open() as conn:
        conn.execute("UPDATE training_runs SET status='TRAIN_DONE' WHERE id=?", (run_id,))
        conn.execute("UPDATE training_runs SET status='VALIDATED' WHERE id=?", (run_id,))
        conn.execute("UPDATE training_runs SET status='PROMOTED' WHERE id=?", (run_id,))
        conn.commit()
    for status in ("PROMOTED", "FAILED", "QUEUED"):
        with manager.open() as conn, pytest.raises(sqlite3.IntegrityError, match="PROMOTED run is terminal"):
            conn.execute("UPDATE training_runs SET status=? WHERE id=?", (status, run_id))


def _make_v2_database(path: Path) -> SQLiteConnectionManager:
    v2_dir = path.parent / "migrations_v2"
    v2_dir.mkdir()
    shutil.copy2(MIGRATIONS / "001__initial_schema.sql", v2_dir)
    shutil.copy2(MIGRATIONS / "002__sqlite_foundation_hardening.sql", v2_dir)
    manager = SQLiteConnectionManager(path)
    MigrationManager(manager, v2_dir).migrate()
    return manager


def test_v2_migration_preserves_rows_and_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "upgrade.db"
    manager = _make_v2_database(db_path)
    with manager.open() as conn:
        job = conn.execute("INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status) VALUES('old','individual','EURUSD','H1',2,'QUEUED')").lastrowid
        ds = conn.execute("INSERT INTO datasets(symbol,timeframe,source_path,bars_count) VALUES('EURUSD','H1','d.csv',10)").lastrowid
        run = conn.execute("INSERT INTO training_runs(job_id,run_uid,run_index,status) VALUES(?, 'old-run',0,'QUEUED')", (job,)).lastrowid
        conn.execute("INSERT INTO training_job_datasets(job_id,dataset_id) VALUES(?,?)", (job, ds))
        conn.execute("INSERT INTO checkpoints(run_id,checkpoint_status,changed_by) VALUES(?,'QUEUED','fixture')", (run,))
        conn.execute("INSERT INTO model_artifacts(run_id,artifact_type,artifact_path,sha256,size_bytes) VALUES(?,'model','m.bin',?,1)", (run, "b" * 64))
        conn.execute("INSERT INTO audit_logs(entity_type,entity_id,action,actor) VALUES('training_job',?,'fixture','test')", (str(job),))
        conn.commit()
    MigrationManager(manager, MIGRATIONS).migrate()
    with manager.open() as conn:
        assert conn.execute("SELECT job_key,status FROM training_jobs WHERE id=?", (job,)).fetchone()[:] == ("old", "QUEUED")
        assert conn.execute("SELECT run_uid FROM training_runs WHERE id=?", (run,)).fetchone()[0] == "old-run"
        assert conn.execute("SELECT count(*) FROM training_job_datasets WHERE job_id=?", (job,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM checkpoints WHERE run_id=?", (run,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM model_artifacts WHERE run_id=?", (run,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 5
        cols = {r[1] for r in conn.execute("PRAGMA table_info(training_jobs)")}
        assert {"legacy_status", "legacy_action", "legacy_reference", "legacy_source", "migration_source_hash", "queued_at", "queued_by"} <= cols


def test_v3_migration_is_idempotent_and_checksum_mismatch_rejected(tmp_path: Path) -> None:
    manager = create_dev_database(tmp_path / "v3.db")
    assert MigrationManager(manager, MIGRATIONS).migrate() == []
    with manager.open() as conn:
        conn.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=3")
        conn.commit()
    with pytest.raises(ValueError, match="checksum mismatch"):
        MigrationManager(manager, MIGRATIONS).migrate()


def test_v3_migration_failure_rolls_back_schema_and_version(tmp_path: Path) -> None:
    manager = _make_v2_database(tmp_path / "rollback.db")
    broken = tmp_path / "broken"
    broken.mkdir()
    shutil.copy2(MIGRATIONS / "001__initial_schema.sql", broken)
    shutil.copy2(MIGRATIONS / "002__sqlite_foundation_hardening.sql", broken)
    failed_v3 = (MIGRATIONS / "003__planned_job_lifecycle.sql").read_text(encoding="utf-8") + "\nSELECT * FROM missing_table;\n"
    (broken / "003__planned_job_lifecycle.sql").write_text(failed_v3, encoding="utf-8")
    with pytest.raises(sqlite3.OperationalError):
        MigrationManager(manager, broken).migrate()
    with manager.open() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(training_jobs)")}
        assert "legacy_status" not in cols
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


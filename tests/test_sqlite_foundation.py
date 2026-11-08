from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

from nexora_state_db.bootstrap import create_dev_database
from nexora_state_db.connection import SQLiteConnectionManager, transaction_immediate
from nexora_state_db.interfaces import (
    ArtifactRepository,
    AuditLogRepository,
    CheckpointRepository,
    TrainingJobRepository,
    TrainingRunRepository,
)
from nexora_state_db.migrations import MigrationManager
from nexora_state_db.models import ArtifactCreate, AuditLogCreate, TrainingJobCreate, TrainingRunCreate
from nexora_state_db.repositories import (
    SQLiteArtifactRepository,
    SQLiteAuditLogRepository,
    SQLiteCheckpointRepository,
    SQLiteTrainingJobRepository,
    SQLiteTrainingRunRepository,
)


@pytest.fixture
def temp_db_path() -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "nexora_state.db"


@pytest.fixture
def prepared_manager(temp_db_path: Path) -> SQLiteConnectionManager:
    manager = create_dev_database(temp_db_path)
    return manager


def _new_job_repo(manager: SQLiteConnectionManager) -> SQLiteTrainingJobRepository:
    return SQLiteTrainingJobRepository(manager)


def _new_run_repo(manager: SQLiteConnectionManager) -> SQLiteTrainingRunRepository:
    return SQLiteTrainingRunRepository(manager)


def _seed_job_and_run(manager: SQLiteConnectionManager) -> tuple[int, int]:
    jobs = _new_job_repo(manager)
    runs = _new_run_repo(manager)
    job_id = jobs.create_job(
        TrainingJobCreate(
            job_key="job-eurusd-m30-h2",
            scope="individual",
            symbol="EURUSD",
            timeframe="M30",
            horizon=2,
            status="QUEUED",
            config_json='{"mode":"full"}',
        )
    )
    run_id = runs.create_run(
        TrainingRunCreate(
            job_id=job_id,
            run_uid="run-001",
            run_index=0,
            status="QUEUED",
            training_config_json='{"max_iter":300}',
        )
    )
    return job_id, run_id


def test_01_database_creation(prepared_manager: SQLiteConnectionManager) -> None:
    with prepared_manager.open() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {row["name"] for row in rows}
    expected = {
        "schema_migrations",
        "datasets",
        "training_jobs",
        "training_job_datasets",
        "training_runs",
        "checkpoints",
        "model_artifacts",
        "validation_results",
        "strategy_experiments",
        "audit_logs",
        "legacy_imports",
    }
    assert expected.issubset(names)


def test_02_schema_versioning(prepared_manager: SQLiteConnectionManager) -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "nexora_state_db" / "migrations"
    mm = MigrationManager(prepared_manager, migrations_dir)
    first = mm.get_applied_versions()
    executed_again = mm.migrate()
    second = mm.get_applied_versions()
    assert len(first) >= 1
    assert executed_again == []
    assert first == second


def test_03_foreign_key_integrity(prepared_manager: SQLiteConnectionManager) -> None:
    artifact_repo = SQLiteArtifactRepository(prepared_manager)
    with pytest.raises(sqlite3.IntegrityError):
        artifact_repo.create_artifact(
            ArtifactCreate(
                run_id=99999,
                artifact_type="model",
                path="/tmp/nope.joblib",
                sha256="a" * 64,
                size_bytes=1,
                is_temporary=True,
            )
        )


def test_04_duplicate_job_prevention(prepared_manager: SQLiteConnectionManager) -> None:
    jobs = _new_job_repo(prepared_manager)
    payload = TrainingJobCreate(
        job_key="dup-key",
        scope="individual",
        symbol="EURUSD",
        timeframe="M15",
        horizon=1,
        status="QUEUED",
        config_json="{}",
    )
    jobs.create_job(payload)
    with pytest.raises(ValueError):
        jobs.create_job(payload)


def test_05_transaction_commit(prepared_manager: SQLiteConnectionManager) -> None:
    with prepared_manager.open() as conn:
        with transaction_immediate(conn):
            conn.execute(
                "INSERT INTO legacy_imports(source_name,source_path,rows_imported,notes) VALUES(?,?,?,?)",
                ("csv", "a.csv", 10, "commit"),
            )

    with prepared_manager.open() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM legacy_imports WHERE source_path='a.csv'").fetchone()["c"]
    assert count == 1


def test_06_transaction_rollback(prepared_manager: SQLiteConnectionManager) -> None:
    with pytest.raises(RuntimeError):
        with prepared_manager.open() as conn:
            with transaction_immediate(conn):
                conn.execute(
                    "INSERT INTO legacy_imports(source_name,source_path,rows_imported,notes) VALUES(?,?,?,?)",
                    ("csv", "rollback.csv", 11, "rollback"),
                )
                raise RuntimeError("force rollback")

    with prepared_manager.open() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM legacy_imports WHERE source_path='rollback.csv'").fetchone()["c"]
    assert count == 0


def test_07_checkpoint_transition_validation(prepared_manager: SQLiteConnectionManager) -> None:
    job_id, run_id = _seed_job_and_run(prepared_manager)
    cp = SQLiteCheckpointRepository(prepared_manager)

    # v4 requires the run to be claimed so the job reaches RUNNING before
    # STARTED -> TRAIN_DONE can synchronize job and run status.
    assert _new_run_repo(prepared_manager).claim_next_queued_run(job_id) == run_id
    cp.append_checkpoint(run_id, "TRAIN_DONE", actor="tester")

    with pytest.raises(ValueError):
        cp.append_checkpoint(run_id, "QUEUED", actor="tester")


def test_08_promoted_terminal_state(prepared_manager: SQLiteConnectionManager) -> None:
    job_id, run_id = _seed_job_and_run(prepared_manager)
    cp = SQLiteCheckpointRepository(prepared_manager)

    assert _new_run_repo(prepared_manager).claim_next_queued_run(job_id) == run_id
    cp.append_checkpoint(run_id, "TRAIN_DONE", actor="tester")
    cp.append_checkpoint(run_id, "VALIDATED", actor="tester")
    cp.append_checkpoint(run_id, "PROMOTED", actor="tester")

    with pytest.raises(ValueError):
        cp.append_checkpoint(run_id, "FAILED", actor="tester")
    with pytest.raises(ValueError):
        cp.append_checkpoint(run_id, "PROMOTED", actor="tester")


def test_09_busy_timeout(prepared_manager: SQLiteConnectionManager) -> None:
    with prepared_manager.open() as conn:
        timeout_ms = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    assert int(timeout_ms) == 10_000


def test_10_wal_configuration(prepared_manager: SQLiteConnectionManager) -> None:
    with prepared_manager.open() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert str(mode).lower() == "wal"
    assert int(sync) == 2  # FULL
    assert int(fk) == 1


def test_11_crash_reopen_simulation(temp_db_path: Path) -> None:
    manager = create_dev_database(temp_db_path)
    jobs = _new_job_repo(manager)
    job_id = jobs.create_job(
        TrainingJobCreate(
            job_key="crash-reopen-job",
            scope="individual",
            symbol="EURUSD",
            timeframe="H1",
            horizon=4,
            status="QUEUED",
            config_json="{}",
        )
    )
    assert job_id > 0

    reopened = SQLiteConnectionManager(temp_db_path)
    with reopened.open() as conn:
        row = conn.execute("SELECT job_key FROM training_jobs WHERE id=?", (job_id,)).fetchone()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    assert row["job_key"] == "crash-reopen-job"
    assert integrity == "ok"


def test_12_audit_log_integrity(prepared_manager: SQLiteConnectionManager) -> None:
    job_id, run_id = _seed_job_and_run(prepared_manager)
    cp = SQLiteCheckpointRepository(prepared_manager)

    # v4: claim writes the STARTED checkpoint+audit and moves the job to RUNNING,
    # so STARTED -> TRAIN_DONE can synchronize both run and job.
    assert _new_run_repo(prepared_manager).claim_next_queued_run(job_id) == run_id
    cp.append_checkpoint(run_id, "TRAIN_DONE", actor="tester", metadata_json='{"step":2}')

    with prepared_manager.open() as conn:
        logs = conn.execute(
            "SELECT action, old_state, new_state, actor FROM audit_logs WHERE entity_type='training_run' AND entity_id=? ORDER BY id",
            (str(run_id),),
        ).fetchall()
    assert len(logs) == 2
    assert logs[0]["new_state"] == "STARTED"
    assert logs[1]["new_state"] == "TRAIN_DONE"


def test_13_global_job_two_datasets(prepared_manager: SQLiteConnectionManager) -> None:
    jobs = _new_job_repo(prepared_manager)
    job_id = jobs.create_job(
        TrainingJobCreate(
            job_key="global-h1-h2",
            scope="global",
            symbol=None,
            timeframe="H1",
            horizon=2,
            status="QUEUED",
            config_json='{"symbols":["EURUSD","XAUUSD"]}',
        )
    )
    ds1 = jobs.create_dataset("EURUSD", "H1", "data/raw/eurusd_h1.csv", 12000, "usable")
    ds2 = jobs.create_dataset("XAUUSD", "H1", "data/raw/xauusd_h1.csv", 11000, "usable")
    jobs.link_job_dataset(job_id, ds1, role="train")
    jobs.link_job_dataset(job_id, ds2, role="train")

    with prepared_manager.open() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM training_job_datasets WHERE job_id=?", (job_id,)).fetchone()["c"]
    assert count == 2


def test_14_repository_interface_compatibility(prepared_manager: SQLiteConnectionManager) -> None:
    jobs = SQLiteTrainingJobRepository(prepared_manager)
    runs = SQLiteTrainingRunRepository(prepared_manager)
    cps = SQLiteCheckpointRepository(prepared_manager)
    arts = SQLiteArtifactRepository(prepared_manager)
    audits = SQLiteAuditLogRepository(prepared_manager)

    assert isinstance(jobs, TrainingJobRepository)
    assert isinstance(runs, TrainingRunRepository)
    assert isinstance(cps, CheckpointRepository)
    assert isinstance(arts, ArtifactRepository)
    assert isinstance(audits, AuditLogRepository)


def test_migration_failure_rolls_back_schema_and_version(temp_db_path: Path) -> None:
    migration_dir = temp_db_path.parent / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001__broken.sql").write_text(
        "CREATE TABLE should_rollback(id INTEGER PRIMARY KEY);\nSELECT * FROM missing_table;\n", encoding="utf-8"
    )
    manager = SQLiteConnectionManager(temp_db_path)
    with pytest.raises(sqlite3.OperationalError):
        MigrationManager(manager, migration_dir).migrate()
    with manager.open() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='should_rollback'").fetchone() is None
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_migration_checksum_mismatch_is_rejected(prepared_manager: SQLiteConnectionManager) -> None:
    migration_dir = Path(__file__).resolve().parents[1] / "nexora_state_db" / "migrations"
    with prepared_manager.open() as conn:
        conn.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=1")
        conn.commit()
    with pytest.raises(ValueError, match="checksum mismatch"):
        MigrationManager(prepared_manager, migration_dir).migrate()


def test_claim_is_atomic_and_writes_checkpoint_audit_and_job_state(prepared_manager: SQLiteConnectionManager) -> None:
    job_id, run_id = _seed_job_and_run(prepared_manager)
    with prepared_manager.open() as conn:
        conn.execute("CREATE TRIGGER reject_claim_audit BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit blocked'); END")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _new_run_repo(prepared_manager).claim_next_queued_run(job_id)
    with prepared_manager.open() as conn:
        assert conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0] == "QUEUED"
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "QUEUED"
        assert conn.execute("SELECT COUNT(*) FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()[0] == 0


def test_concurrent_claim_never_claims_same_run_twice(prepared_manager: SQLiteConnectionManager) -> None:
    job_id, run_id = _seed_job_and_run(prepared_manager)
    barrier = threading.Barrier(2)
    results: list[int | None] = []
    errors: list[BaseException] = []

    def claim() -> None:
        try:
            barrier.wait()
            results.append(_new_run_repo(prepared_manager).claim_next_queued_run(job_id))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert errors == []
    assert results.count(run_id) == 1
    assert results.count(None) == 1


def test_schema_hardening_metadata_unique_tuple_and_artifact_digest(prepared_manager: SQLiteConnectionManager) -> None:
    jobs = _new_job_repo(prepared_manager)
    job = TrainingJobCreate("tuple-1", "individual", "EURUSD", "M30", 2, "QUEUED", "{}")
    jobs.create_job(job)
    with pytest.raises(ValueError):
        jobs.create_job(TrainingJobCreate("tuple-2", "individual", "EURUSD", "M30", 2, "QUEUED", "{}"))
    with prepared_manager.open() as conn:
        dataset_cols = {row["name"] for row in conn.execute("PRAGMA table_info(datasets)")}
        legacy_cols = {row["name"] for row in conn.execute("PRAGMA table_info(legacy_imports)")}
        artifact_cols = {row["name"] for row in conn.execute("PRAGMA table_info(model_artifacts)")}
    assert {"content_sha256", "time_start", "time_end"}.issubset(dataset_cols)
    assert {"source_sha256", "audit_id", "completed_at", "status"}.issubset(legacy_cols)
    assert {"lifecycle_status", "activated_at", "retired_at"}.issubset(artifact_cols)


def test_claim_can_set_running_job_status(prepared_manager: SQLiteConnectionManager) -> None:
    job_id, _ = _seed_job_and_run(prepared_manager)
    _new_run_repo(prepared_manager).claim_next_queued_run(job_id)
    with prepared_manager.open() as conn:
        assert conn.execute("SELECT status FROM training_jobs WHERE id=?", (job_id,)).fetchone()[0] == "RUNNING"


def test_checkpoint_audit_failure_rolls_back_transition(prepared_manager: SQLiteConnectionManager) -> None:
    _, run_id = _seed_job_and_run(prepared_manager)
    cp = SQLiteCheckpointRepository(prepared_manager)
    with prepared_manager.open() as conn:
        conn.execute("CREATE TRIGGER reject_transition_audit BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit blocked'); END")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        cp.append_checkpoint(run_id, "STARTED", actor="tester")
    with prepared_manager.open() as conn:
        assert conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()[0] == "QUEUED"
        assert conn.execute("SELECT COUNT(*) FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()[0] == 0


def test_dataset_and_artifact_hash_validation(prepared_manager: SQLiteConnectionManager) -> None:
    jobs = _new_job_repo(prepared_manager)
    with pytest.raises(ValueError, match="Dataset sha256"):
        jobs.create_dataset("EURUSD", "H1", "x.csv", 1, "usable", content_sha256="bad")
    with pytest.raises(ValueError, match="Artifact sha256"):
        SQLiteArtifactRepository(prepared_manager).create_artifact(
            ArtifactCreate(999, "model", "m.bin", "bad", 1, False)
        )

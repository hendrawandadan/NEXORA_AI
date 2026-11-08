from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from nexora_state_db.bootstrap import create_dev_database
from nexora_state_db.connection import SQLiteConnectionManager, transaction_immediate
from nexora_state_db.models import ArtifactCreate, TrainingJobCreate, TrainingRunCreate
from nexora_state_db.repositories import (
    SQLiteArtifactRepository,
    SQLiteCheckpointRepository,
    SQLiteTrainingJobRepository,
    SQLiteTrainingRunRepository,
)


def test_integration_end_to_end_global_flow() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "integration_state.db"
        manager = create_dev_database(db_path)

        jobs = SQLiteTrainingJobRepository(manager)
        runs = SQLiteTrainingRunRepository(manager)
        checkpoints = SQLiteCheckpointRepository(manager)
        artifacts = SQLiteArtifactRepository(manager)

        job_id = jobs.create_job(
            TrainingJobCreate(
                job_key="global-m30-h4",
                scope="global",
                symbol=None,
                timeframe="M30",
                horizon=4,
                status="QUEUED",
                config_json='{"symbols":["EURUSD","XAUUSD"],"mode":"full"}',
            )
        )
        ds_eur = jobs.create_dataset("EURUSD", "M30", "data/raw/eurusd_m30.csv", 25000, "usable")
        ds_xau = jobs.create_dataset("XAUUSD", "M30", "data/raw/xauusd_m30.csv", 18000, "usable")
        jobs.link_job_dataset(job_id, ds_eur)
        jobs.link_job_dataset(job_id, ds_xau)

        run_id = runs.create_run(
            TrainingRunCreate(
                job_id=job_id,
                run_uid="global-run-1",
                run_index=0,
                status="QUEUED",
                training_config_json='{"max_iter":300,"engine":"auto"}',
            )
        )

        claimed = runs.claim_next_queued_run(job_id=job_id)
        assert claimed == run_id

        checkpoints.append_checkpoint(run_id, "TRAIN_DONE", actor="integration")
        checkpoints.append_checkpoint(run_id, "VALIDATED", actor="integration")
        checkpoints.append_checkpoint(run_id, "PROMOTED", actor="integration")

        artifact_id = artifacts.create_artifact(
            ArtifactCreate(
                run_id=run_id,
                artifact_type="model",
                path="models/global/M30/h4/model.joblib",
                sha256="d" * 64,
                size_bytes=1024,
                is_temporary=False,
            )
        )
        assert artifact_id > 0

        with manager.open() as conn:
            run = conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()
            linked = conn.execute("SELECT COUNT(*) c FROM training_job_datasets WHERE job_id=?", (job_id,)).fetchone()
            audits = conn.execute(
                "SELECT COUNT(*) c FROM audit_logs WHERE entity_type='training_run' AND entity_id=?",
                (str(run_id),),
            ).fetchone()

        assert run["status"] == "PROMOTED"
        assert linked["c"] == 2
        assert audits["c"] >= 3


def test_integration_busy_timeout_behavior() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "busy_timeout.db"
        manager = create_dev_database(db_path)

        conn1 = manager.connect()
        conn2 = SQLiteConnectionManager(db_path=db_path, busy_timeout_ms=300).connect()

        try:
            conn1.execute("BEGIN IMMEDIATE")
            conn1.execute("INSERT INTO legacy_imports(source_name,source_path,rows_imported,notes) VALUES(?,?,?,?)", ("a", "b", 1, "hold"))

            started = time.perf_counter()
            try:
                conn2.execute("INSERT INTO legacy_imports(source_name,source_path,rows_imported,notes) VALUES(?,?,?,?)", ("c", "d", 2, "blocked"))
                conn2.commit()
                assert False, "Expected lock timeout"
            except sqlite3.OperationalError as exc:
                elapsed = time.perf_counter() - started
                assert "database is locked" in str(exc).lower()
                assert elapsed >= 0.20
        finally:
            conn1.rollback()
            conn1.close()
            conn2.close()

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .connection import SQLiteConnectionManager, transaction_immediate
from .constants import CHECKPOINT_FLOW, CHECKPOINT_STATUSES
from .interfaces import (
    ArtifactRepository,
    AuditLogRepository,
    CheckpointRepository,
    TrainingJobRepository,
    TrainingRunRepository,
)
from .models import ArtifactCreate, AuditLogCreate, TrainingJobCreate, TrainingRunCreate

UTC = timezone.utc


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SQLiteTrainingJobRepository(TrainingJobRepository):
    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self.manager = manager

    def create_job(self, job: TrainingJobCreate) -> int:
        with self.manager.open() as conn:
            try:
                                cursor = conn.execute(
                    """
                    INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status,config_json,
                                              legacy_status,legacy_action,legacy_reference,legacy_source,migration_source_hash,
                                              target_type)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (job.job_key, job.scope, job.symbol, job.timeframe, job.horizon, job.status, job.config_json,
                     job.legacy_status, job.legacy_action, job.legacy_reference, job.legacy_source,
                     job.migration_source_hash, job.target_type),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Duplicate/invalid training job: {job.job_key}") from exc
            conn.commit()
            return int(cursor.lastrowid)

    def queue_planned_job(self, job_id: int, actor: str) -> None:
        if not actor or not actor.strip():
            raise ValueError("Queue action requires a non-empty actor")
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                now = _now_iso()
                conn.execute(
                    "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("training_job", str(job_id), "explicit_queue", "PLANNED", "QUEUED", "{}", actor.strip(), now),
                )
                updated = conn.execute(
                    "UPDATE training_jobs SET status='QUEUED',queued_at=?,queued_by=?,updated_at=? WHERE id=? AND status='PLANNED'",
                    (now, actor.strip(), now, job_id),
                )
                if updated.rowcount != 1:
                    raise ValueError(f"Job {job_id} is not PLANNED and cannot be queued")

    def create_dataset(
        self, symbol: str, timeframe: str, path: str, bars: int, status: str,
        content_sha256: Optional[str] = None, time_start: Optional[str] = None, time_end: Optional[str] = None,
    ) -> int:
        if content_sha256 is not None and (
            len(content_sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in content_sha256)
        ):
            raise ValueError("Dataset sha256 must be a 64-character hexadecimal digest")
        if time_start is not None and time_end is not None and time_start > time_end:
            raise ValueError("Dataset time_start must not be later than time_end")
        with self.manager.open() as conn:
            cursor = conn.execute(
                """
                INSERT INTO datasets(symbol,timeframe,source_path,bars_count,status,updated_at,content_sha256,time_start,time_end)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (symbol, timeframe, path, bars, status, _now_iso(), content_sha256, time_start, time_end),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def link_job_dataset(self, job_id: int, dataset_id: int, role: str = "train") -> None:
        with self.manager.open() as conn:
            conn.execute(
                "INSERT INTO training_job_datasets(job_id,dataset_id,role) VALUES(?,?,?)",
                (job_id, dataset_id, role),
            )
            conn.commit()


class SQLiteTrainingRunRepository(TrainingRunRepository):
    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self.manager = manager

    def create_run(self, run: TrainingRunCreate) -> int:
        with self.manager.open() as conn:
            cursor = conn.execute(
                """
                INSERT INTO training_runs(job_id,run_uid,run_index,status,training_config_json,updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (run.job_id, run.run_uid, run.run_index, run.status, run.training_config_json, _now_iso()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def claim_next_queued_run(self, job_id: Optional[int] = None) -> Optional[int]:
        with self.manager.open() as conn:
            with transaction_immediate(conn):
                if job_id is None:
                    row = conn.execute(
                        "SELECT r.id FROM training_runs r JOIN training_jobs j ON j.id=r.job_id WHERE r.status='QUEUED' AND j.status='QUEUED' AND NOT EXISTS (SELECT 1 FROM training_runs a WHERE a.job_id=r.job_id AND a.status='STARTED') ORDER BY r.id LIMIT 1"
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT r.id FROM training_runs r JOIN training_jobs j ON j.id=r.job_id WHERE r.status='QUEUED' AND r.job_id=? AND j.status='QUEUED' AND NOT EXISTS (SELECT 1 FROM training_runs a WHERE a.job_id=r.job_id AND a.status='STARTED') ORDER BY r.id LIMIT 1",
                        (job_id,),
                    ).fetchone()
                if row is None:
                    return None
                run_id = int(row["id"])
                now = _now_iso()
                run = conn.execute("SELECT job_id FROM training_runs WHERE id=? AND status='QUEUED'", (run_id,)).fetchone()
                if run is None:
                    return None
                owner_job_id = int(run["job_id"])
                updated = conn.execute(
                    "UPDATE training_runs SET status='STARTED',started_at=?,updated_at=? WHERE id=? AND status='QUEUED'",
                    (now, now, run_id),
                )
                if updated.rowcount != 1:
                    return None
                conn.execute(
                    "INSERT INTO checkpoints(run_id,checkpoint_status,changed_by,note,metadata_json,changed_at) VALUES(?,?,?,?,?,?)",
                    (run_id, "STARTED", "sqlite_claim", "Claimed for execution", "{}", now),
                )
                conn.execute(
                    "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("training_run", str(run_id), "claim", "QUEUED", "STARTED", "{}", "sqlite_claim", now),
                )
                job_update = conn.execute(
                    "UPDATE training_jobs SET status='RUNNING',updated_at=? WHERE id=? AND status='QUEUED'",
                    (now, owner_job_id),
                )
                if job_update.rowcount != 1:
                    raise ValueError(f"Job {owner_job_id} cannot be claimed from its current status")
                conn.execute(
                    "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("training_job", str(owner_job_id), "claim", "QUEUED", "RUNNING", "{}", "sqlite_claim", now),
                )
                return run_id


class SQLiteAuditLogRepository(AuditLogRepository):
    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self.manager = manager

    def create_audit_log(self, log: AuditLogCreate) -> int:
        with self.manager.open() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor)
                VALUES(?,?,?,?,?,?,?)
                """,
                (log.entity_type, log.entity_id, log.action, log.old_state, log.new_state, log.payload_json, log.actor),
            )
            conn.commit()
            return int(cursor.lastrowid)


class SQLiteCheckpointRepository(CheckpointRepository):
    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self.manager = manager

    def append_checkpoint(
        self,
        run_id: int,
        to_status: str,
        actor: str,
        note: str = "",
        metadata_json: str = "{}",
    ) -> int:
        if to_status not in CHECKPOINT_STATUSES:
            raise ValueError(f"Unknown checkpoint status: {to_status}")

        with self.manager.open() as conn:
            with transaction_immediate(conn):
                run = conn.execute("SELECT status FROM training_runs WHERE id=?", (run_id,)).fetchone()
                if run is None:
                    raise KeyError(f"Run not found: {run_id}")

                current = str(run["status"])
                if current == "PROMOTED":
                    raise ValueError("PROMOTED run is terminal; no further transitions or replays are allowed")
                if to_status != current:
                    allowed = CHECKPOINT_FLOW.get(current, set())
                    if to_status not in allowed:
                        raise ValueError(f"Invalid transition: {current} -> {to_status}")

                changed_at = _now_iso()
                cursor = conn.execute(
                    """
                    INSERT INTO checkpoints(run_id,checkpoint_status,changed_by,note,metadata_json,changed_at)
                    VALUES(?,?,?,?,?,?)
                    """,
                    (run_id, to_status, actor, note, metadata_json, changed_at),
                )

                started_at = changed_at if (to_status == "STARTED") else None
                ended_at = changed_at if (to_status in {"PROMOTED", "FAILED"}) else None
                conn.execute(
                    """
                    UPDATE training_runs
                    SET status=?,
                        started_at=COALESCE(started_at, ?),
                        ended_at=CASE WHEN ? IS NULL THEN ended_at ELSE ? END,
                        updated_at=?
                    WHERE id=?
                    """,
                    (to_status, started_at, ended_at, ended_at, changed_at, run_id),
                )

                run_job = conn.execute("SELECT job_id FROM training_runs WHERE id=?", (run_id,)).fetchone()
                job_id = int(run_job["job_id"])
                job_target = {"TRAIN_DONE": "TRAIN_DONE", "VALIDATED": "VALIDATED", "PROMOTED": "PROMOTED", "FAILED": "FAILED", "RETRY_PENDING": "RETRY_PENDING"}.get(to_status)
                if job_target is not None:
                    job_update = conn.execute(
                        "UPDATE training_jobs SET status=?,updated_at=? WHERE id=? AND status=?",
                        (job_target, changed_at, job_id, current if current in {"TRAIN_DONE", "VALIDATED", "FAILED"} else ("RUNNING" if current == "STARTED" else current)),
                    )
                    if job_update.rowcount != 1:
                        raise ValueError(f"Job {job_id} is not synchronized with run transition {current} -> {to_status}")
                    conn.execute(
                        "INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        ("training_job", str(job_id), "run_lifecycle_sync", current, job_target, metadata_json, actor, changed_at),
                    )

                conn.execute(
                    """
                    INSERT INTO audit_logs(entity_type,entity_id,action,old_state,new_state,payload_json,actor,created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        "training_run",
                        str(run_id),
                        "checkpoint_transition",
                        current,
                        to_status,
                        metadata_json,
                        actor,
                        changed_at,
                    ),
                )

                return int(cursor.lastrowid)


class SQLiteArtifactRepository(ArtifactRepository):
    def __init__(self, manager: SQLiteConnectionManager) -> None:
        self.manager = manager

    def create_artifact(self, artifact: ArtifactCreate) -> int:
        if len(artifact.sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in artifact.sha256):
            raise ValueError("Artifact sha256 must be a 64-character hexadecimal digest")
        with self.manager.open() as conn:
            cursor = conn.execute(
                """
                INSERT INTO model_artifacts(run_id,artifact_type,artifact_path,sha256,size_bytes,is_temporary)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    artifact.run_id,
                    artifact.artifact_type,
                    artifact.path,
                    artifact.sha256,
                    artifact.size_bytes,
                    int(artifact.is_temporary),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

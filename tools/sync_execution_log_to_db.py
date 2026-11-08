"""Sync the batch execution CSV log into the NEXORA state SQLite database.

The execution runner (``batch1_execution_runner.py``) is the *write model*: it
records run state in ``reports/retraining/batch_execution_log.csv``. The SQLite
state database (``database/nexora_state.db``) is the *read model* consumed by the
dashboard. This tool bridges the two: it reads the CSV (read-only) and populates
``training_jobs`` / ``training_runs`` / ``checkpoints`` / ``datasets`` /
``model_artifacts`` / ``validation_results`` via the existing repositories.

Design notes
------------
* The CSV is never modified.
* The tool is idempotent: a row whose ``job_key`` already exists in the DB is
  skipped (use ``--replace`` to delete and re-sync a single job's run graph).
* Schema migrations are applied first (idempotent, non-destructive) so the DB
  is upgraded to the expected version before any INSERT.
* Only rows that reached a terminal PROMOTED/VALIDATED state are imported by
  default; ``--all-statuses`` imports every row.
* Artifacts are imported only when the referenced file exists on disk (the
  artifact repository requires a real sha256 + size).

Usage
-----
    .\\.venv\\Scripts\\python.exe tools/sync_execution_log_to_db.py --dry-run
    .\\.venv\\Scripts\\python.exe tools/sync_execution_log_to_db.py
    .\\.venv\\Scripts\\python.exe tools/sync_execution_log_to_db.py --execution-id PREP-001 --replace
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Make repo root importable when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from batch_checkpoint_manager import read_csv_rows  # noqa: E402
from nexora_state_db import (  # noqa: E402
    SQLiteConnectionManager,
    SQLiteArtifactRepository,
    SQLiteCheckpointRepository,
    SQLiteTrainingJobRepository,
    SQLiteTrainingRunRepository,
    MigrationManager,
)
from nexora_state_db.config import PRODUCTION_DATABASE_PATH  # noqa: E402
from nexora_state_db.models import (  # noqa: E402
    ArtifactCreate,
    TrainingJobCreate,
    TrainingRunCreate,
)

DEFAULT_LOG = ROOT / "reports" / "retraining" / "batch_execution_log.csv"
MIGRATIONS_DIR = ROOT / "nexora_state_db" / "migrations"

# Transition order used to replay a run's lifecycle into the checkpoint table so
# the DB state machine (CHECKPOINT_FLOW) stays consistent with the final status.
TRANSITION_LADDER: Dict[str, List[str]] = {
    "QUEUED": ["QUEUED"],
    "STARTED": ["QUEUED", "STARTED"],
    "TRAIN_DONE": ["QUEUED", "STARTED", "TRAIN_DONE"],
    "VALIDATED": ["QUEUED", "STARTED", "TRAIN_DONE", "VALIDATED"],
    "PROMOTED": ["QUEUED", "STARTED", "TRAIN_DONE", "VALIDATED", "PROMOTED"],
    "FAILED": ["QUEUED", "STARTED", "FAILED"],
    "RETRY_PENDING": ["QUEUED", "STARTED", "FAILED", "RETRY_PENDING"],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_target_type(row: dict) -> str:
    """Infer T1/T3 from the execution row, preferring explicit config/path."""
    cfg_raw = row.get("training_config") or ""
    try:
        cfg = json.loads(cfg_raw) if cfg_raw else {}
    except json.JSONDecodeError:
        cfg = {}
    explicit = str(cfg.get("target_type") or "").strip().upper()
    if explicit in {"T1", "T3"}:
        return explicit
    marker = "\\t3\\" if "\\" in str(row.get("final_model_path", "")) else "/t3/"
    for key in ("final_model_path", "model_path", "temp_model_path"):
        p = str(row.get(key, "")).replace("\\", "/")
        if "/t3/" in p:
            return "T3"
        if "/t1/" in p:
            return "T1"
    return "T1"


def _job_exists(job_repo: SQLiteTrainingJobRepository, job_key: str) -> Optional[int]:
    with job_repo.manager.open() as conn:
        found = conn.execute("SELECT id FROM training_jobs WHERE job_key=?", (job_key,)).fetchone()
    return int(found["id"]) if found else None


def _delete_job_graph(manager: SQLiteConnectionManager, job_id: int) -> None:
    """Remove a job and its dependent run graph (for --replace)."""
    with manager.open() as conn:
        run_ids = [int(r["id"]) for r in conn.execute("SELECT id FROM training_runs WHERE job_id=?", (job_id,))]
        for run_id in run_ids:
            conn.execute("DELETE FROM model_artifacts WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM validation_results WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM checkpoints WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM training_runs WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM training_job_datasets WHERE job_id=?", (job_id,))
        conn.execute("DELETE FROM training_jobs WHERE id=?", (job_id,))
        conn.commit()


def import_row(
    manager: SQLiteConnectionManager,
    job_repo: SQLiteTrainingJobRepository,
    run_repo: SQLiteTrainingRunRepository,
    cp_repo: SQLiteCheckpointRepository,
    art_repo: SQLiteArtifactRepository,
    row: dict,
    dry_run: bool,
) -> str:
    execution_id = row["execution_id"]
    status = (row.get("checkpoint_status") or "QUEUED").strip().upper()
    target_type = detect_target_type(row)

    existing = _job_exists(job_repo, execution_id)
    if existing is not None:
        return f"SKIP (job exists id={existing})"

    if dry_run:
        return f"WOULD IMPORT status={status} target={target_type}"

    # 1) Job
    job_id = job_repo.create_job(
        TrainingJobCreate(
            job_key=execution_id,
            scope=row.get("scope") or "individual",
            symbol=row.get("symbol"),
            timeframe=row.get("timeframe") or "",
            horizon=int(row.get("horizon") or 0),
            status="QUEUED",
            config_json=row.get("training_config") or "{}",
            target_type=target_type,
        )
    )

    # 2) Dataset link (best-effort, from dataset_rows + source path)
    try:
        ds_path = row.get("final_model_path") or row.get("model_path") or ""
        # datasets.status CHECK constraint allows: usable/insufficient/invalid/archived
        ds_status = "usable" if int(row.get("dataset_rows") or 0) > 0 else "insufficient"
        dataset_id = job_repo.create_dataset(
            symbol=row.get("symbol") or "",
            timeframe=row.get("timeframe") or "",
            path=str(ds_path),
            bars=int(row.get("dataset_rows") or 0),
            status=ds_status,
        )
        job_repo.link_job_dataset(job_id, dataset_id, role="train")
    except Exception as exc:
        print(f"  warning: dataset link skipped for {execution_id}: {exc}")

    # 3) Run
    run_id = run_repo.create_run(
        TrainingRunCreate(
            job_id=job_id,
            run_uid=row.get("run_id") or execution_id,
            run_index=1,
            status="QUEUED",
            training_config_json=row.get("training_config") or "{}",
        )
    )

    # 4) Replay lifecycle so checkpoints + run/job status match the final state.
    #    The QUEUED -> STARTED step must go through claim_next_queued_run() so the
    #    job status is synced to RUNNING (append_checkpoint then expects RUNNING
    #    when moving STARTED -> TRAIN_DONE).
    ladder = TRANSITION_LADDER.get(status, [status])
    claimed = False
    for step in ladder:
        if step == "QUEUED":
            continue  # run already created as QUEUED
        if step == "STARTED" and not claimed:
            claimed_run = run_repo.claim_next_queued_run(job_id=job_id)
            if claimed_run is None:
                raise RuntimeError(f"Could not claim queued run for job {job_id} ({execution_id})")
            claimed = True
            continue
        cp_repo.append_checkpoint(run_id, step, actor="csv_sync", note=f"sync from CSV ({execution_id})")

    # 5) Artifacts (only when files exist)
    artifacts = [
        ("model", row.get("final_model_path") or row.get("model_path")),
        ("report", row.get("final_report_path") or row.get("report_path")),
        ("signals", row.get("final_signals_path") or row.get("signals_path")),
        ("metadata", row.get("final_metadata_path") or row.get("temp_metadata_path")),
    ]
    for art_type, path_str in artifacts:
        if not path_str:
            continue
        p = Path(path_str)
        if not p.exists():
            continue
        art_repo.create_artifact(
            ArtifactCreate(
                run_id=run_id,
                artifact_type=art_type,
                path=str(p),
                size_bytes=p.stat().st_size,
                sha256=sha256_file(p),
                is_temporary=False,
            )
        )

    # 6) Validation result summary
    passed = all(
        str(row.get(k, "")).upper() == "PASS"
        for k in ("metadata_match", "config_match", "artifact_sync")
    )
    details = {
        "engine": row.get("engine"),
        "train_rows": row.get("train_rows"),
        "validation_rows": row.get("validation_rows"),
        "test_rows": row.get("test_rows"),
        "metadata_match": row.get("metadata_match"),
        "config_match": row.get("config_match"),
        "artifact_sync": row.get("artifact_sync"),
    }
    with manager.open() as conn:
        conn.execute(
            "INSERT INTO validation_results(run_id,validation_type,passed,details_json) VALUES(?,?,?,?)",
            (run_id, "staging_sync", int(passed), json.dumps(details)),
        )
        conn.commit()

    return f"IMPORTED job_id={job_id} run_id={run_id} status={status} target={target_type}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync execution CSV log into NEXORA SQLite state DB")
    parser.add_argument("--log", default=str(DEFAULT_LOG), help="Path to batch_execution_log.csv")
    parser.add_argument("--database-path", default=str(PRODUCTION_DATABASE_PATH), help="Target SQLite DB path")
    parser.add_argument("--execution-id", default=None, help="Only sync this execution_id")
    parser.add_argument("--all-statuses", action="store_true", help="Import every row, not just PROMOTED/VALIDATED")
    parser.add_argument("--replace", action="store_true", help="Delete + re-sync existing job(s)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        print(f"ERROR: log not found: {log_path}")
        return 2

    db_path = Path(args.database_path)
    manager = SQLiteConnectionManager(db_path=db_path)

    # Ensure schema is up to date (idempotent, non-destructive).
    if not args.dry_run:
        MigrationManager(manager=manager, migrations_dir=MIGRATIONS_DIR).migrate()

    job_repo = SQLiteTrainingJobRepository(manager)
    run_repo = SQLiteTrainingRunRepository(manager)
    cp_repo = SQLiteCheckpointRepository(manager)
    art_repo = SQLiteArtifactRepository(manager)

    _, rows = read_csv_rows(log_path)
    target_ids = {x.strip() for x in (args.execution_id or "").split(",") if x.strip()}

    imported = skipped = 0
    for row in rows:
        eid = row.get("execution_id")
        if not eid:
            continue
        if target_ids and eid not in target_ids:
            continue
        status = (row.get("checkpoint_status") or "QUEUED").strip().upper()
        if not args.all_statuses and status not in {"PROMOTED", "VALIDATED"}:
            continue

        if args.replace and not args.dry_run:
            existing = _job_exists(job_repo, eid)
            if existing is not None:
                _delete_job_graph(manager, existing)

        result = import_row(manager, job_repo, run_repo, cp_repo, art_repo, row, args.dry_run)
        tag = "DRY" if args.dry_run else "OK "
        print(f"[{tag}] {eid}: {result}")
        if result.startswith("SKIP"):
            skipped += 1
        else:
            imported += 1

    print(f"\nSummary: imported={imported} skipped={skipped} db={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

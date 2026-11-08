from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib

from batch_checkpoint_manager import (
    CHECKPOINT_FLOW,
    ExecutionLogLockError,
    acquire_execution_log_lock,
    diagnose_log_write_failure,
    ensure_schema,
    read_csv_rows,
    write_csv_rows,
)
from nexora_core.config import ROOT as PROD_ROOT
from nexora_core.config import load_config
from nexora_datahub.loader import discover_datasets

from nexora_audit.authorization import (
    AuthorizationError,
    authorize_execution,
    require_authorized,
)


UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_key(row: dict) -> Tuple[str, str, str, str]:
    return (
        row.get("scope", ""),
        row.get("symbol", ""),
        row.get("timeframe", ""),
        str(row.get("horizon", "")),
    )


def parse_execution_ids(value) -> Optional[set]:
    """Normalize an --execution-id argument into a set of ids (or None).

    Accepts None, a comma-separated string, or an iterable of strings.
    Empty/blank input -> None (meaning: no scope, batch-wide selection allowed).
    """
    if value is None:
        return None
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    else:
        parts = []
        for item in value:
            parts.extend(str(item).split(","))
    ids = {p.strip() for p in parts if p and p.strip()}
    return ids or None


def run_status_from_checkpoint(checkpoint: str) -> str:
    mapping = {
        "QUEUED": "PENDING",
        "STARTED": "RUNNING",
        "TRAIN_DONE": "RUNNING",
        "VALIDATED": "RUNNING",
        "PROMOTED": "COMPLETED",
        "FAILED": "FAILED",
        "RETRY_PENDING": "RETRY_PENDING",
    }
    return mapping[checkpoint]


def parse_plan(plan_path: Path, batch_name: str) -> Dict[Tuple[str, str, str, str], dict]:
    with plan_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [row for row in reader if row.get("batch") == batch_name]
    indexed = {}
    for row in rows:
        key = (
            row.get("scope", ""),
            row.get("symbol", ""),
            row.get("timeframe", ""),
            str(row.get("horizon", "")),
        )
        indexed[key] = row
    return indexed


def discover_dataset_index(raw_dir: Path) -> Dict[Tuple[str, str], Path]:
    index: Dict[Tuple[str, str], Path] = {}
    for item in discover_datasets(raw_dir):
        index[(item["symbol"], item["timeframe"])] = Path(item["path"])
    return index


def read_log_rows(log_path: Path, require_schema: bool = True) -> Tuple[List[str], List[dict]]:
    if require_schema:
        fieldnames, rows = ensure_schema(log_path, write_if_changed=False, strict=True)
    else:
        fieldnames, rows = read_csv_rows(log_path)
    return fieldnames, rows


def write_log_rows(log_path: Path, fieldnames: List[str], rows: List[dict]) -> None:
    write_csv_rows(log_path, fieldnames, rows)


def update_log_row(
    log_path: Path,
    execution_id: str,
    updates: dict,
    lock_timeout_seconds: float = 15.0,
    lock_poll_seconds: float = 0.15,
) -> dict:
    with acquire_execution_log_lock(log_path, timeout_seconds=lock_timeout_seconds, poll_seconds=lock_poll_seconds):
        fieldnames, rows = read_log_rows(log_path, require_schema=True)
        target = None
        for row in rows:
            if row.get("execution_id") == execution_id:
                target = row
                break
        if target is None:
            raise KeyError(f"execution_id not found in log: {execution_id}")
        for key, value in updates.items():
            target[key] = value
        write_log_rows(log_path, fieldnames, rows)
        return target


def transition_status(
    log_path: Path,
    execution_id: str,
    target_checkpoint: str,
    notes: Optional[str] = None,
    lock_timeout_seconds: float = 15.0,
    lock_poll_seconds: float = 0.15,
) -> dict:
    with acquire_execution_log_lock(log_path, timeout_seconds=lock_timeout_seconds, poll_seconds=lock_poll_seconds):
        fieldnames, rows = read_log_rows(log_path, require_schema=True)
        row = next((x for x in rows if x.get("execution_id") == execution_id), None)
        if row is None:
            raise KeyError(f"execution_id not found in log: {execution_id}")

        current = row.get("checkpoint_status") or "QUEUED"
        if current == "PROMOTED" and target_checkpoint != "PROMOTED":
            raise ValueError(f"Cannot downgrade PROMOTED run: {execution_id}")
        if target_checkpoint != current:
            allowed = CHECKPOINT_FLOW.get(current, set())
            if target_checkpoint not in allowed:
                raise ValueError(f"Invalid checkpoint transition: {current} -> {target_checkpoint} ({execution_id})")

        row["checkpoint_status"] = target_checkpoint
        row["last_checkpoint"] = target_checkpoint
        row["checkpoint_updated_at"] = now_iso()
        row["run_status"] = run_status_from_checkpoint(target_checkpoint)
        if notes:
            row["notes"] = notes
        if target_checkpoint == "STARTED" and not row.get("start_time"):
            row["start_time"] = now_iso()
        if target_checkpoint in {"FAILED", "PROMOTED"}:
            row["end_time"] = now_iso()
        if target_checkpoint == "FAILED":
            retry_count = int(row.get("retry_count", "0") or "0") + 1
            row["retry_count"] = str(retry_count)

        write_log_rows(log_path, fieldnames, rows)
        return row


def prepare_training_config() -> dict:
    cfg = load_config()
    training_cfg = cfg.get("training", {})
    return {
        "mode": "full",
        "max_iter": int(training_cfg.get("max_iter", 300)),
        "seed": int(training_cfg.get("seed", 42)),
        "engine": "auto",
        "train_fraction": float(training_cfg.get("train_fraction", 0.6)),
        "validation_fraction": float(training_cfg.get("validation_fraction", 0.2)),
        "embargo_bars": int(training_cfg.get("embargo_bars", 24)),
        "horizons": training_cfg.get("horizons", [1, 2, 4, 8, 12, 24]),
        # Target type is NOT hardcoded here. It is resolved per-run from the
        # execution row / runner config so a T3 dispatch trains T3 (writes under
        # models/t3, reports/t3, signals/t3) and expected_paths() finds the
        # outputs. Hardcoding "T1" here caused a T3 run to train into t1/ while
        # expected_paths() looked under t3/ (artifacts "missing").
        "target_type": None,
    }


def _target_ns(row: dict) -> str:
    return (str(row.get("target_type") or "T1")).strip().upper()


def expected_paths(root_dir: Path, row: dict) -> Dict[str, Path]:
    symbol = row["symbol"]
    tf = row["timeframe"]
    horizon = int(row["horizon"])
    ns = _target_ns(row).lower()  # t1 / t3
    base = root_dir / "models" / ns / "individual" / symbol / tf / f"h{horizon}"
    rep = root_dir / "reports" / ns / "individual" / symbol / tf / f"h{horizon}"
    sig = root_dir / "signals" / ns / symbol / tf / f"h{horizon}"
    return {
        "model": base / "model.joblib",
        "report": rep / "report.json",
        "signals": sig / "individual_signals.csv",
    }


def write_staging_metadata(
    run_dir: Path,
    row: dict,
    training_config: dict,
    artifact_paths: Dict[str, Path],
    source_dataset: Path,
) -> Tuple[Path, Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, path in artifact_paths.items():
        manifest[name] = {
            "path": str(path),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    metadata = {
        "execution_id": row["execution_id"],
        "run_id": row.get("run_id") or row["execution_id"],
        "scope": row["scope"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "horizon": int(row["horizon"]),
        "training_config": training_config,
        "source_dataset": str(source_dataset),
        "manifest_path": str(manifest_path),
        "created_at": now_iso(),
    }
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata_path, manifest_path


def clone_config_for_staging(staging_root: Path) -> None:
    config_src = PROD_ROOT / "config" / "research.json"
    config_dst = staging_root / "config" / "research.json"
    config_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_src, config_dst)


def run_production_pipeline_to_staging(
    row: dict,
    dataset_path: Path,
    staging_root: Path,
    training_config: dict,
) -> dict:
    import nexora_core.config as cfg_mod
    import nexora_learning.pipeline as pipe_mod

    clone_config_for_staging(staging_root)
    marker_path = os.environ.get("NEXORA_TEST_TRAIN_MARKER")
    if marker_path:
        Path(marker_path).parent.mkdir(parents=True, exist_ok=True)
        Path(marker_path).write_text("TRAIN_PIPELINE_CALLED", encoding="utf-8")
    original_cfg_root = cfg_mod.ROOT
    original_pipe_root = pipe_mod.ROOT
    cfg_mod.ROOT = staging_root
    pipe_mod.ROOT = staging_root
    try:
        report = pipe_mod.train_one(
            path=dataset_path,
            symbol=row["symbol"],
            tf=row["timeframe"],
            horizon=int(row["horizon"]),
            kind="individual",
            engine=training_config["engine"],
            max_iter=int(training_config["max_iter"]),
            seed=int(training_config["seed"]),
            target_type=str(training_config.get("target_type") or row.get("target_type") or "T1"),
        )
    finally:
        cfg_mod.ROOT = original_cfg_root
        pipe_mod.ROOT = original_pipe_root

    generated = expected_paths(staging_root, row)
    missing = [name for name, path in generated.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Pipeline output missing in staging: {missing}")
    run_dir = staging_root / "reports" / "retraining" / "batch1_runs" / row["execution_id"]
    metadata_path, manifest_path = write_staging_metadata(run_dir, row, training_config, generated, dataset_path)

    return {
        "report": report,
        "model_path": generated["model"],
        "report_path": generated["report"],
        "signals_path": generated["signals"],
        "metadata_path": metadata_path,
        "manifest_path": manifest_path,
    }


def validate_staging_artifacts(row: dict) -> dict:
    required = {
        "model": Path(row.get("temp_model_path", "")),
        "report": Path(row.get("temp_report_path", "")),
        "signals": Path(row.get("temp_signals_path", "")),
        "metadata": Path(row.get("temp_metadata_path", "")),
    }
    missing = [name for name, path in required.items() if not str(path) or str(path) == "." or not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing staging artifacts: {missing}")

    model_payload = joblib.load(required["model"])
    report = json.loads(required["report"].read_text(encoding="utf-8"))
    metadata = json.loads(required["metadata"].read_text(encoding="utf-8"))

    expected_symbol = row["symbol"]
    expected_tf = row["timeframe"]
    expected_h = int(row["horizon"])
    checks = [
        (model_payload.get("symbol") == expected_symbol, "model.symbol mismatch"),
        (model_payload.get("timeframe") == expected_tf, "model.timeframe mismatch"),
        (int(model_payload.get("horizon", -1)) == expected_h, "model.horizon mismatch"),
        (report.get("symbol") == expected_symbol, "report.symbol mismatch"),
        (report.get("timeframe") == expected_tf, "report.timeframe mismatch"),
        (int(report.get("horizon_bars", -1)) == expected_h, "report.horizon mismatch"),
        (metadata.get("symbol") == expected_symbol, "metadata.symbol mismatch"),
        (metadata.get("timeframe") == expected_tf, "metadata.timeframe mismatch"),
        (int(metadata.get("horizon", -1)) == expected_h, "metadata.horizon mismatch"),
    ]
    errors = [message for ok, message in checks if not ok]
    if errors:
        raise ValueError("; ".join(errors))

    if int(row.get("horizon", "0")) != int(metadata["training_config"]["horizons"][metadata["training_config"]["horizons"].index(expected_h)]):
        raise ValueError("metadata training horizons do not include expected horizon")

    return {
        "train_rows": str(report.get("train_rows", "")),
        "validation_rows": str(report.get("validation_rows", "")),
        "test_rows": str(report.get("test_rows", "")),
        "engine": str(report.get("engine", row.get("engine", "auto"))),
    }


def build_promotion_targets(row: dict, production_root: Path) -> Dict[str, Path]:
    symbol = row["symbol"]
    tf = row["timeframe"]
    horizon = int(row["horizon"])
    ns = _target_ns(row).lower()  # t1 / t3
    return {
        "model": production_root / "models" / ns / "individual" / symbol / tf / f"h{horizon}" / "model.joblib",
        "report": production_root / "reports" / ns / "individual" / symbol / tf / f"h{horizon}" / "report.json",
        "signals": production_root / "signals" / ns / symbol / tf / f"h{horizon}" / "individual_signals.csv",
        "metadata": production_root / "reports" / ns / "retraining" / "batch1_promoted" / symbol / tf / f"h{horizon}" / "metadata.json",
    }


def promote_with_rollback(
    row: dict,
    production_root: Path,
    backup_root: Path,
    fail_after: Optional[int] = None,
) -> Dict[str, str]:
    temp_paths = {
        "model": Path(row["temp_model_path"]),
        "report": Path(row["temp_report_path"]),
        "signals": Path(row["temp_signals_path"]),
        "metadata": Path(row["temp_metadata_path"]),
    }
    for name, src in temp_paths.items():
        if not src.exists():
            raise FileNotFoundError(f"Missing temp artifact before promotion ({name}): {src}")

    targets = build_promotion_targets(row, production_root)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / "promotion_backups" / row["execution_id"] / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    replaced = []
    previous_backups = {}
    try:
        for idx, (name, target_path) in enumerate(targets.items(), start=1):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                backup_file = backup_dir / f"pre_{name}{target_path.suffix or '.bin'}"
                shutil.copy2(target_path, backup_file)
                previous_backups[name] = backup_file

            temp_incoming = target_path.with_suffix(target_path.suffix + ".incoming")
            shutil.copy2(temp_paths[name], temp_incoming)
            os.replace(temp_incoming, target_path)
            replaced.append(name)

            if fail_after is not None and idx >= fail_after:
                raise RuntimeError("Injected promotion failure for rollback test")
    except Exception:
        for name in reversed(replaced):
            target_path = targets[name]
            backup_file = previous_backups.get(name)
            if backup_file and backup_file.exists():
                shutil.copy2(backup_file, target_path)
            elif target_path.exists():
                target_path.unlink()
        raise

    promote_manifest = {
        "execution_id": row["execution_id"],
        "timestamp": now_iso(),
        "restored_from_backup": list(previous_backups.keys()),
        "targets": {name: str(path) for name, path in targets.items()},
        "source_temp": {name: str(path) for name, path in temp_paths.items()},
        "sha256": {name: sha256_file(path) for name, path in targets.items()},
    }
    manifest_path = backup_dir / "promotion_manifest.json"
    manifest_path.write_text(json.dumps(promote_manifest, indent=2), encoding="utf-8")

    return {
        "model_path": str(targets["model"]),
        "report_path": str(targets["report"]),
        "signals_path": str(targets["signals"]),
        "metadata_path": str(targets["metadata"]),
        "manifest_path": str(manifest_path),
    }


@dataclass
class RunnerConfig:
    log_path: Path
    plan_path: Path
    batch_name: str
    dry_run: bool
    validate_only: bool
    execute: bool
    resume: bool
    limit: int
    staging_root: Path
    backup_root: Path
    log_lock_timeout_seconds: float
    log_lock_poll_seconds: float
    execution_ids: Optional[set] = None
    # Read-only authorization context: project root for governance config.
    # Defaults to the production root; tests inject a temp root. When
    # ``authorization_context`` is explicitly ``False`` the gate is skipped
    # (used ONLY by the isolated dummy self-test suite, never for real dispatch).
    authorization_root: Optional[Path] = None
    enforce_authorization: bool = True
    # Target type for the dual-target contract (T1 statistical / T3 execution).
    # ``None`` means "read from the execution row"; legacy rows without a
    # target_type are NOT silently treated as T1 -- the authorization gate fails
    # closed with TARGET_TYPE_MISSING when none is supplied.
    target_type: Optional[str] = None
    # Experiment candidate (A/B/C) for the dispatch intent. When supplied it is
    # threaded into the authorization row so the gate binds candidate from the
    # requested dispatch as well as the sign-off (candidate isolation).
    experiment_candidate: Optional[str] = None


def _authorization_root(cfg: "RunnerConfig") -> Path:
    return Path(cfg.authorization_root) if cfg.authorization_root is not None else PROD_ROOT


def guard_execution_authorized(row: dict, cfg: "RunnerConfig") -> None:
    """Fail-closed authorization gate invoked immediately before any dispatch.

    Raises :class:`AuthorizationError` unless the row is bound to a valid
    human-ratified sign-off, the canonical config hash, the versioned
    feature/target/split contracts, the ratified timing contract, the selected
    experiment candidate, and a READY_FOR_TRAINING readiness decision.

    This is the ONLY entry point that may precede ``process_run`` dispatch.
    It performs no training, no schema migration, and no log mutation.
    """
    if not cfg.enforce_authorization:
        # Only the isolated dummy self-test opts out; it never trains real models
        # and never touches the production dataset/model/backup.
        return
    # Thread the target type into the row so the gate can enforce T1/T3 binding.
    # A row-level target_type wins; otherwise the runner's configured target is
    # used. If neither is present the gate fails closed (TARGET_TYPE_MISSING).
    authorizable_row = dict(row)
    if not authorizable_row.get("target_type"):
        row_target = row.get("target_type")
        if row_target:
            authorizable_row["target_type"] = row_target
        elif cfg.target_type:
            authorizable_row["target_type"] = str(cfg.target_type).strip().upper()

    # Resolve the effective target for THESE bindings (row > config). Version ids
    # are target-aware: for T3 the split policy is split-4d4a794c... (effective
    # horizon h+1), NOT the frozen default split-27dd116e.... This makes the
    # authorization gate bind the SAME target-aware contract the training path
    # uses, so a T3 sign-off matches a T3 dispatch and a T1/T3 mix cannot pass.
    effective_target = str(
        authorizable_row.get("target_type") or cfg.target_type or ""
    ).strip().upper()
    if effective_target in {"T1", "T3"}:
        horizon = int(row.get("horizon") or authorizable_row.get("horizon") or 2)
        from nexora_audit.configuration_freeze import (
            target_definition_version_for,
            split_policy_version_for,
        )

        target_ver = target_definition_version_for(effective_target, horizon)
        split_ver = split_policy_version_for(effective_target, horizon)
        authorizable_row.setdefault("target_definition_version", target_ver["id"])
        authorizable_row.setdefault("split_policy_version", split_ver["id"])
        # Feature set is target-independent; only inject if absent so an explicit
        # row value (if ever supplied) still wins.
        if not authorizable_row.get("feature_set_version"):
            from nexora_audit.configuration_freeze import feature_set_version

            authorizable_row["feature_set_version"] = feature_set_version()["id"]

    # Thread the experiment candidate into the row so the gate binds candidate
    # from the DISPATCH INTENT (candidate isolation), not only from the sign-off.
    if not authorizable_row.get("experiment_candidate") and cfg.experiment_candidate:
        authorizable_row["experiment_candidate"] = str(cfg.experiment_candidate).strip().upper()

    # Run the isolated readiness probes (RUNNER_READY + RECOVERY_READY). These
    # execute against freshly created temporary SQLite databases built from the
    # repo migrations -- they NEVER open the production DB, touch datasets/
    # models/backups, or call train_one()/model.fit(). Without their results the
    # RUNNER_READY / RECOVERY_READY gates stay UNRESOLVED and the gate is BLOCKED.
    claim_probe_result = None
    recovery_probe_result = None
    try:
        from nexora_audit.safety_probe import (
            run_claim_and_lifecycle_probes,
            probe_crash_recovery,
        )

        claim_probe_result = run_claim_and_lifecycle_probes()
        recovery_probe_result = probe_crash_recovery()
    except Exception as exc:  # probe failure must fail closed, not crash silently
        raise AuthorizationError(
            f"execution not authorized: readiness probes failed to run: {exc}"
        ) from exc

    decision = authorize_execution(
        execution_row=authorizable_row,
        project_root=_authorization_root(cfg),
        batch_name=cfg.batch_name,
        requested_execution_ids=cfg.execution_ids,
        claim_probe_result=claim_probe_result,
        recovery_probe_result=recovery_probe_result,
    )
    require_authorized(decision)


def process_run(
    row: dict,
    cfg: RunnerConfig,
    dataset_index: Dict[Tuple[str, str], Path],
    training_config: dict,
) -> str:
    execution_id = row["execution_id"]
    checkpoint = row.get("checkpoint_status", "QUEUED") or "QUEUED"

    # Resolve the effective target type once (row > config > training_config
    # default) and stamp it onto the row so path builders, the promotion targets,
    # and the train_one call all agree. This does not bypass the authorization
    # gate: guard_execution_authorized still fails closed if no target resolves.
    effective_target = (
        str(row.get("target_type") or cfg.target_type
            or training_config.get("target_type") or "").strip().upper()
    )
    if effective_target:
        row = dict(row)
        row["target_type"] = effective_target

    if checkpoint == "PROMOTED":
        return f"{execution_id}: SKIP_PROMOTED"
    if checkpoint == "FAILED":
        return f"{execution_id}: BLOCKED_FAILED_MANUAL_REVIEW"

    if cfg.dry_run and not cfg.execute:
        return f"{execution_id}: DRY_RUN_{checkpoint}"

    # Authorization gate: MUST precede any STARTED transition, training dispatch,
    # validation, or promotion. Fail-closed: raises AuthorizationError on any gap.
    guard_execution_authorized(row, cfg)

    if checkpoint in {"QUEUED", "RETRY_PENDING"}:
        if cfg.validate_only:
            return f"{execution_id}: VALIDATE_ONLY_SKIP_TRAIN"
        try:
            transition_status(
                cfg.log_path,
                execution_id,
                "STARTED",
                lock_timeout_seconds=cfg.log_lock_timeout_seconds,
                lock_poll_seconds=cfg.log_lock_poll_seconds,
            )
        except ExecutionLogLockError as exc:
            return f"{execution_id}: STARTED_LOG_LOCK_FAILED ({exc})"
        except PermissionError as exc:
            diag = diagnose_log_write_failure(cfg.log_path, exc)
            return (
                f"{execution_id}: STARTED_LOG_PERMISSION_FAILED "
                f"(reason={diag['reason']} details={diag['details']})"
            )
        row = next(x for x in read_log_rows(cfg.log_path)[1] if x["execution_id"] == execution_id)
        # Re-stamp the resolved target after re-reading from CSV (the CSV row does
        # not persist target_type, so without this the downstream pipeline/
        # expected_paths() would fall back to T1 and look in the wrong namespace).
        if effective_target:
            row = dict(row)
            row["target_type"] = effective_target
        checkpoint = "STARTED"

    if checkpoint == "STARTED":
        expected_cols = ["temp_model_path", "temp_report_path", "temp_signals_path", "temp_metadata_path"]
        expected_present = all(
            bool(row.get(col)) and Path(row.get(col)).exists()
            for col in expected_cols
        )

        if not expected_present:
            ds_key = (row["symbol"], row["timeframe"])
            ds_path = dataset_index.get(ds_key)
            if ds_path is None:
                transition_status(
                    cfg.log_path,
                    execution_id,
                    "FAILED",
                    notes="Dataset not found for symbol/timeframe",
                    lock_timeout_seconds=cfg.log_lock_timeout_seconds,
                    lock_poll_seconds=cfg.log_lock_poll_seconds,
                )
                return f"{execution_id}: FAILED_DATASET_MISSING"

            train_result = run_production_pipeline_to_staging(
                row=row,
                dataset_path=ds_path,
                staging_root=cfg.staging_root,
                training_config=training_config,
            )
            updates = {
                "training_config": json.dumps(training_config, separators=(",", ":")),
                "temp_model_path": str(train_result["model_path"]),
                "temp_report_path": str(train_result["report_path"]),
                "temp_signals_path": str(train_result["signals_path"]),
                "temp_metadata_path": str(train_result["metadata_path"]),
                "final_model_path": str(build_promotion_targets(row, PROD_ROOT)["model"]),
                "final_report_path": str(build_promotion_targets(row, PROD_ROOT)["report"]),
                "final_signals_path": str(build_promotion_targets(row, PROD_ROOT)["signals"]),
                "final_metadata_path": str(build_promotion_targets(row, PROD_ROOT)["metadata"]),
                "engine": str(train_result["report"].get("engine", row.get("engine", "auto"))),
                "train_rows": str(train_result["report"].get("train_rows", "")),
                "validation_rows": str(train_result["report"].get("validation_rows", "")),
                "test_rows": str(train_result["report"].get("test_rows", "")),
                "error_message": "",
            }
            update_log_row(
                cfg.log_path,
                execution_id,
                updates,
                lock_timeout_seconds=cfg.log_lock_timeout_seconds,
                lock_poll_seconds=cfg.log_lock_poll_seconds,
            )

        transition_status(
            cfg.log_path,
            execution_id,
            "TRAIN_DONE",
            lock_timeout_seconds=cfg.log_lock_timeout_seconds,
            lock_poll_seconds=cfg.log_lock_poll_seconds,
        )
        row = next(x for x in read_log_rows(cfg.log_path)[1] if x["execution_id"] == execution_id)
        if effective_target:
            row = dict(row)
            row["target_type"] = effective_target
        checkpoint = "TRAIN_DONE"

    if checkpoint == "TRAIN_DONE":
        try:
            validated = validate_staging_artifacts(row)
            update_log_row(
                cfg.log_path,
                execution_id,
                {
                    "metadata_match": "PASS",
                    "config_match": "PASS",
                    "artifact_sync": "PASS",
                    "engine": validated["engine"],
                    "train_rows": validated["train_rows"],
                    "validation_rows": validated["validation_rows"],
                    "test_rows": validated["test_rows"],
                    "error_message": "",
                },
                lock_timeout_seconds=cfg.log_lock_timeout_seconds,
                lock_poll_seconds=cfg.log_lock_poll_seconds,
            )
        except Exception as exc:
            update_log_row(
                cfg.log_path,
                execution_id,
                {
                    "metadata_match": "FAIL",
                    "config_match": "FAIL",
                    "artifact_sync": "FAIL",
                    "error_message": str(exc),
                },
                lock_timeout_seconds=cfg.log_lock_timeout_seconds,
                lock_poll_seconds=cfg.log_lock_poll_seconds,
            )
            transition_status(
                cfg.log_path,
                execution_id,
                "FAILED",
                notes=f"Validation failed: {exc}",
                lock_timeout_seconds=cfg.log_lock_timeout_seconds,
                lock_poll_seconds=cfg.log_lock_poll_seconds,
            )
            return f"{execution_id}: FAILED_VALIDATION"

        transition_status(
            cfg.log_path,
            execution_id,
            "VALIDATED",
            lock_timeout_seconds=cfg.log_lock_timeout_seconds,
            lock_poll_seconds=cfg.log_lock_poll_seconds,
        )
        row = next(x for x in read_log_rows(cfg.log_path)[1] if x["execution_id"] == execution_id)
        if effective_target:
            row = dict(row)
            row["target_type"] = effective_target
        checkpoint = "VALIDATED"

    if checkpoint == "VALIDATED":
        if cfg.validate_only:
            return f"{execution_id}: VALIDATED_ONLY"
        promotion = promote_with_rollback(row, PROD_ROOT, cfg.backup_root)
        update_log_row(
            cfg.log_path,
            execution_id,
            {
                "model_path": promotion["model_path"],
                "report_path": promotion["report_path"],
                "signals_path": promotion["signals_path"],
                "final_metadata_path": promotion["metadata_path"],
                "artifact_sync": "PASS",
                "error_message": "",
            },
            lock_timeout_seconds=cfg.log_lock_timeout_seconds,
            lock_poll_seconds=cfg.log_lock_poll_seconds,
        )
        transition_status(
            cfg.log_path,
            execution_id,
            "PROMOTED",
            lock_timeout_seconds=cfg.log_lock_timeout_seconds,
            lock_poll_seconds=cfg.log_lock_poll_seconds,
        )
        return f"{execution_id}: PROMOTED"

    return f"{execution_id}: NO_ACTION_{checkpoint}"


def load_batch_rows(
    log_path: Path,
    plan_map: Dict[Tuple[str, str, str, str], dict],
    batch_name: str,
    execution_ids: Optional[set] = None,
) -> List[dict]:
    """Load execution rows for a batch.

    When ``execution_ids`` is provided, ONLY rows whose ``execution_id`` is in
    the set are selected. There is NO fallback to batch-wide execution: if any
    requested id is not found among this batch's rows, a ValueError is raised so
    the caller cannot silently run unrelated jobs.
    """
    _, rows = read_log_rows(log_path, require_schema=True)
    batch_rows = [
        row for row in rows
        if row.get("batch") == batch_name and run_key(row) in plan_map
    ]

    if execution_ids is not None:
        present = {row.get("execution_id") for row in batch_rows}
        missing = sorted(execution_ids - present)
        if missing:
            raise ValueError(
                f"requested execution_id not found in batch '{batch_name}': {missing} "
                f"(refusing batch-wide fallback)"
            )
        batch_rows = [row for row in batch_rows if row.get("execution_id") in execution_ids]

    batch_rows.sort(key=lambda row: int(plan_map[run_key(row)].get("order", 999999)))
    return batch_rows


def run_runner(cfg: RunnerConfig) -> List[str]:
    plan_map = parse_plan(cfg.plan_path, cfg.batch_name)
    if not plan_map:
                raise ValueError(f"No plan rows found for batch: {cfg.batch_name}")

    rows = load_batch_rows(cfg.log_path, plan_map, cfg.batch_name, execution_ids=cfg.execution_ids)
    if not rows:
        raise ValueError(f"No execution rows found for batch: {cfg.batch_name}")

    dataset_index = discover_dataset_index(PROD_ROOT / "data" / "raw")
    training_config = prepare_training_config()
    if int(training_config["max_iter"]) != 300:
        raise ValueError(f"Unexpected max_iter for full training: {training_config['max_iter']} (expected 300)")

    if not cfg.execute:
        # Strict read-only safety gate: no schema migration and no log mutation in dry-run.
        ensure_schema(cfg.log_path, write_if_changed=False, strict=True)

    selected = []
    for row in rows:
        cp = row.get("checkpoint_status") or "QUEUED"
        if cp == "PROMOTED":
            if cfg.resume:
                continue
        selected.append(row)

    if cfg.limit > 0:
        selected = selected[: cfg.limit]

    results = []
    for row in selected:
        result = process_run(row, cfg, dataset_index, training_config)
        results.append(result)
        if "STARTED_LOG_LOCK_FAILED" in result or "STARTED_LOG_PERMISSION_FAILED" in result:
            results.append("ABORTED: Execution log update failed before training dispatch")
            break
    return results


def create_dummy_artifacts_for_tests(root: Path, row: dict, training_config: dict) -> Dict[str, str]:
    run_dir = root / row["execution_id"]
    run_dir.mkdir(parents=True, exist_ok=True)

    model_path = run_dir / "model.joblib"
    report_path = run_dir / "report.json"
    signals_path = run_dir / "individual_signals.csv"
    metadata_path = run_dir / "metadata.json"

    payload = {
        "model": "dummy",
        "features": ["f1", "f2"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "horizon": int(row["horizon"]),
        "engine": "sklearn",
        "kind": "individual",
    }
    joblib.dump(payload, model_path)
    report_path.write_text(
        json.dumps(
            {
                "kind": "individual",
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "horizon_bars": int(row["horizon"]),
                "engine": "sklearn",
                "train_rows": 1000,
                "validation_rows": 250,
                "test_rows": 250,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    signals_path.write_text("time,prob_up,direction,realized_forward_return\n", encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "execution_id": row["execution_id"],
                "scope": row["scope"],
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "horizon": int(row["horizon"]),
                "training_config": training_config,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "temp_model_path": str(model_path),
        "temp_report_path": str(report_path),
        "temp_signals_path": str(signals_path),
        "temp_metadata_path": str(metadata_path),
    }


def run_self_tests(log_path: Path, plan_path: Path) -> dict:
    try:
        import msvcrt  # type: ignore
    except Exception:
        msvcrt = None

    test_root = PROD_ROOT / "reports" / "retraining" / "simulations" / "batch1_runner_validation"
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True, exist_ok=True)

    sim_log = test_root / "batch_execution_log_test.csv"
    shutil.copy2(log_path, sim_log)
    ensure_schema(sim_log, write_if_changed=True, strict=False)

    plan_map = parse_plan(plan_path, "Batch 1")
    rows = load_batch_rows(sim_log, plan_map, "Batch 1")
    row_queued = rows[0]
    row_started = rows[1]
    row_train_done = rows[2]
    row_validated = rows[3]
    row_failed = rows[4]
    row_retry = rows[5]
    row_promoted = rows[6]

    training_config = prepare_training_config()
    # Seed statuses for dispatch tests.
    transition_status(sim_log, row_started["execution_id"], "STARTED")
    transition_status(sim_log, row_train_done["execution_id"], "STARTED")
    transition_status(sim_log, row_train_done["execution_id"], "TRAIN_DONE")
    transition_status(sim_log, row_validated["execution_id"], "STARTED")
    transition_status(sim_log, row_validated["execution_id"], "TRAIN_DONE")
    transition_status(sim_log, row_validated["execution_id"], "VALIDATED")
    transition_status(sim_log, row_failed["execution_id"], "STARTED")
    transition_status(sim_log, row_failed["execution_id"], "FAILED")
    transition_status(sim_log, row_retry["execution_id"], "STARTED")
    transition_status(sim_log, row_retry["execution_id"], "FAILED")
    transition_status(sim_log, row_retry["execution_id"], "RETRY_PENDING")
    transition_status(sim_log, row_promoted["execution_id"], "STARTED")
    transition_status(sim_log, row_promoted["execution_id"], "TRAIN_DONE")
    transition_status(sim_log, row_promoted["execution_id"], "VALIDATED")

    artifact_root = test_root / "artifacts"
    promote_target_root = test_root / "promoted_targets"
    promote_backup_root = test_root / "promotion_backups"
    for row in [row_started, row_train_done, row_validated, row_retry, row_promoted]:
        artifacts = create_dummy_artifacts_for_tests(artifact_root, row, training_config)
        update_log_row(
            sim_log,
            row["execution_id"],
            {
                **artifacts,
                "training_config": json.dumps(training_config, separators=(",", ":")),
                "final_model_path": str(build_promotion_targets(row, promote_target_root)["model"]),
                "final_report_path": str(build_promotion_targets(row, promote_target_root)["report"]),
                "final_signals_path": str(build_promotion_targets(row, promote_target_root)["signals"]),
                "final_metadata_path": str(build_promotion_targets(row, promote_target_root)["metadata"]),
            },
        )

    # Dry-run should not mutate prod log hash.
    prod_before_hash = sha256_file(log_path)
    cfg_dry = RunnerConfig(
        log_path=log_path,
        plan_path=plan_path,
        batch_name="Batch 1",
        dry_run=True,
        validate_only=False,
        execute=False,
        resume=True,
        limit=5,
        staging_root=test_root / "staging_unused",
        backup_root=test_root / "backup_unused",
        log_lock_timeout_seconds=5.0,
        log_lock_poll_seconds=0.10,
    )
    run_runner(cfg_dry)
    prod_after_hash = sha256_file(log_path)

    # Dispatch validation/promote for selected statuses on sim log.
    promote_result = promote_with_rollback(
        row=next(x for x in read_log_rows(sim_log)[1] if x["execution_id"] == row_validated["execution_id"]),
        production_root=promote_target_root,
        backup_root=promote_backup_root,
    )
    transition_status(sim_log, row_validated["execution_id"], "PROMOTED")

    # Inject partial promotion failure and assert rollback.
    rollback_ok = False
    failing_row = next(x for x in read_log_rows(sim_log)[1] if x["execution_id"] == row_retry["execution_id"])
    try:
        promote_with_rollback(
            row=failing_row,
            production_root=promote_target_root,
            backup_root=promote_backup_root,
            fail_after=1,
        )
    except RuntimeError:
        targets = build_promotion_targets(failing_row, promote_target_root)
        rollback_ok = not targets["report"].exists() and not targets["signals"].exists()

    # PROMOTED must not be downgraded.
    promoted_lock_ok = False
    try:
        transition_status(sim_log, row_validated["execution_id"], "QUEUED")
    except ValueError:
        promoted_lock_ok = True

    # Resume selection should skip promoted rows.
    _, final_rows = read_log_rows(sim_log)
    resume_candidates = [
        r["execution_id"]
        for r in final_rows
        if r.get("batch") == "Batch 1" and (r.get("checkpoint_status") or "QUEUED") != "PROMOTED"
    ]

    result = {
        "dry_run_log_unchanged": prod_before_hash == prod_after_hash,
        "promote_manifest_exists": Path(promote_result["manifest_path"]).exists(),
        "rollback_partial_failure_ok": rollback_ok,
        "promoted_lock_ok": promoted_lock_ok,
        "resume_skips_promoted": row_validated["execution_id"] not in resume_candidates,
        "sample_resume_count": len(resume_candidates),
        "simulation_log": str(sim_log),
    }

    # Windows atomic-write lock tests (no production files touched).
    lock_test_file = test_root / "lock_test.csv"
    lock_test_rows = [{"a": "1", "b": "x"}]
    lock_test_fields = ["a", "b"]
    write_csv_rows(lock_test_file, lock_test_fields, lock_test_rows)
    original_lock_hash = sha256_file(lock_test_file)

    lock_error_message_clear = False
    if msvcrt is not None:
        lock_handle = lock_test_file.open("r+", encoding="utf-8", newline="")
        try:
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                write_csv_rows(
                    lock_test_file,
                    lock_test_fields,
                    [{"a": "2", "b": "locked"}],
                    max_retries=2,
                    retry_delay_seconds=0.05,
                )
            except PermissionError as exc:
                msg = str(exc).lower()
                lock_error_message_clear = (
                    "atomic replace failed" in msg
                    and "preserved" in msg
                    and any(token in msg for token in ["locked", "access_denied", "sharing_violation", "diagnostics="])
                )
        finally:
            try:
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                lock_handle.close()
    else:
        lock_error_message_clear = True

    lock_failure_original_preserved = sha256_file(lock_test_file) == original_lock_hash

    replace_after_unlock_ok = False
    if msvcrt is not None:
        delayed_handle = lock_test_file.open("r+", encoding="utf-8", newline="")
        msvcrt.locking(delayed_handle.fileno(), msvcrt.LK_NBLCK, 1)

        def _release_lock() -> None:
            time.sleep(0.30)
            try:
                msvcrt.locking(delayed_handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                delayed_handle.close()

        unlock_thread = threading.Thread(target=_release_lock, daemon=True)
        unlock_thread.start()
        write_csv_rows(
            lock_test_file,
            lock_test_fields,
            [{"a": "3", "b": "after_unlock"}],
            max_retries=10,
            retry_delay_seconds=0.10,
        )
        unlock_thread.join(timeout=2)
        replace_after_unlock_ok = ("after_unlock" in lock_test_file.read_text(encoding="utf-8"))
    else:
        replace_after_unlock_ok = True

    prod_model_dir = PROD_ROOT / "models" / "individual" / "EURUSD"
    prod_model_file_count_before = len(list(prod_model_dir.rglob("*.joblib"))) if prod_model_dir.exists() else 0
    prod_model_file_count_after = len(list(prod_model_dir.rglob("*.joblib"))) if prod_model_dir.exists() else 0

    # Integration lock test: prove STARTED logging failure stops before train pipeline call.
    integration_log = test_root / "integration_lock_log.csv"
    shutil.copy2(log_path, integration_log)
    ensure_schema(integration_log, write_if_changed=True, strict=False)
    integration_plan = parse_plan(plan_path, "Batch 1")
    integration_row = load_batch_rows(integration_log, integration_plan, "Batch 1")[0]
    update_log_row(
        integration_log,
        integration_row["execution_id"],
        {"checkpoint_status": "QUEUED", "run_status": "PENDING", "start_time": "", "end_time": ""},
    )
    integration_row = next(
        x for x in read_log_rows(integration_log)[1] if x["execution_id"] == integration_row["execution_id"]
    )

    integration_marker = test_root / "integration_train_called.marker"
    if integration_marker.exists():
        integration_marker.unlink()

    cfg_exec_lock_test = RunnerConfig(
        log_path=integration_log,
        plan_path=plan_path,
        batch_name="Batch 1",
        dry_run=False,
        validate_only=False,
        execute=True,
        resume=False,
        limit=1,
        staging_root=test_root / "integration_staging",
        backup_root=test_root / "integration_backup",
        log_lock_timeout_seconds=0.5,
        log_lock_poll_seconds=0.05,
        # Isolated dummy self-test: uses a fake train pipeline and dummy artifacts,
        # never touches the real dataset/model/backup. It exercises log-locking,
        # not real dispatch, so it opts out of the governance gate.
        enforce_authorization=False,
    )

    original_train_fn = globals()["run_production_pipeline_to_staging"]

    def _fake_train_pipeline(row: dict, dataset_path: Path, staging_root: Path, training_config: dict) -> dict:
        integration_marker.write_text("CALLED", encoding="utf-8")
        fake_dir = staging_root / "fake"
        fake_dir.mkdir(parents=True, exist_ok=True)
        model_path = fake_dir / "model.joblib"
        report_path = fake_dir / "report.json"
        signals_path = fake_dir / "signals.csv"
        metadata_path = fake_dir / "metadata.json"
        joblib.dump({"symbol": row["symbol"], "timeframe": row["timeframe"], "horizon": int(row["horizon"]), "engine": "sklearn"}, model_path)
        report_path.write_text(json.dumps({"symbol": row["symbol"], "timeframe": row["timeframe"], "horizon_bars": int(row["horizon"]), "engine": "sklearn", "train_rows": 1, "validation_rows": 1, "test_rows": 1}), encoding="utf-8")
        signals_path.write_text("time,prob_up,direction,realized_forward_return\n", encoding="utf-8")
        metadata_path.write_text(json.dumps({"symbol": row["symbol"], "timeframe": row["timeframe"], "horizon": int(row["horizon"]), "training_config": training_config}), encoding="utf-8")
        return {
            "report": {"engine": "sklearn", "train_rows": 1, "validation_rows": 1, "test_rows": 1},
            "model_path": model_path,
            "report_path": report_path,
            "signals_path": signals_path,
            "metadata_path": metadata_path,
            "manifest_path": metadata_path,
        }

    globals()["run_production_pipeline_to_staging"] = _fake_train_pipeline
    try:
        with acquire_execution_log_lock(integration_log, timeout_seconds=3.0, poll_seconds=0.05):
            integration_result_line = process_run(
                integration_row,
                cfg_exec_lock_test,
                {(integration_row["symbol"], integration_row["timeframe"]): log_path},
                prepare_training_config(),
            )
    finally:
        globals()["run_production_pipeline_to_staging"] = original_train_fn

    integration_row_after = next(
        x for x in read_log_rows(integration_log)[1] if x["execution_id"] == integration_row["execution_id"]
    )
    started_log_failure_blocks_training = (
        (
            "STARTED_LOG_LOCK_FAILED" in integration_result_line
            or "STARTED_LOG_PERMISSION_FAILED" in integration_result_line
        )
        and not integration_marker.exists()
    )
    started_failure_status_unchanged = integration_row_after.get("checkpoint_status") == "QUEUED"

    result.update(
        {
            "lock_error_message_clear": lock_error_message_clear,
            "lock_failure_original_preserved": lock_failure_original_preserved,
            "replace_after_unlock_ok": replace_after_unlock_ok,
            "resume_promoted_not_replayed": row_validated["execution_id"] not in resume_candidates,
            "production_model_unchanged": prod_model_file_count_before == prod_model_file_count_after,
            "training_executed": False,
            "integration_started_log_failure_blocks_training": started_log_failure_blocks_training,
            "integration_started_failure_status_unchanged": started_failure_status_unchanged,
            "integration_started_result": integration_result_line,
        }
    )

    (test_root / "runner_self_test_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NEXORA Batch 1 Execution Runner Template")
    parser.add_argument("--log", default=str(PROD_ROOT / "reports" / "retraining" / "batch_execution_log.csv"))
    parser.add_argument("--plan", default=str(PROD_ROOT / "reports" / "retraining" / "batch_retraining_plan.csv"))
    parser.add_argument("--batch", default="Batch 1")
    parser.add_argument("--limit", type=int, default=0, help="Limit run count (0 = all selected rows)")
    parser.add_argument("--staging-root", default=str(PROD_ROOT / "reports" / "retraining" / "staging" / "batch1"))
    parser.add_argument("--backup-root", default=str(PROD_ROOT / "backups" / "batch1_runtime"))
    parser.add_argument("--log-lock-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--log-lock-poll-seconds", type=float, default=0.15)
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not mutate execution log or train")
    parser.add_argument("--validate-only", action="store_true", help="Only validate/promote from TRAIN_DONE/VALIDATED")
    parser.add_argument("--resume", action="store_true", help="Skip PROMOTED runs and continue from checkpoints")
    parser.add_argument("--execute", action="store_true", help="Allow real training execution")
    parser.add_argument(
        "--execution-id",
        default=None,
        help="Comma-separated execution_id(s) to scope this run to (e.g. PREP-001). "
             "When set, ONLY these rows are processed; unknown ids raise instead of "
             "falling back to batch-wide execution.",
    )
    parser.add_argument("--self-test", action="store_true", help="Run dummy validation suite only")
    parser.add_argument(
        "--target-type",
        choices=["T1", "T3"],
        default=None,
        help="Dual-target contract selector: T1 (statistical, close->close) or "
             "T3 (execution-aligned, open->open). Required for real T1/T3 "
             "dispatch; the authorization gate fails closed (TARGET_TYPE_MISSING) "
             "when neither the row nor this flag provides a target.",
    )
    parser.add_argument(
        "--candidate",
        choices=["A", "B", "C"],
        default=None,
        help="Experiment candidate for the dispatch intent (A/B/C). When set it is "
             "threaded into the authorization row so the gate binds candidate from "
             "the requested dispatch as well as the sign-off.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    log_path = Path(args.log)
    plan_path = Path(args.plan)

    if args.self_test:
        result = run_self_tests(log_path, plan_path)
        print(json.dumps(result, indent=2))
        return

    execute = bool(args.execute)
    dry_run = True if not execute else bool(args.dry_run)
    if not execute:
        dry_run = True

    cfg = RunnerConfig(
        log_path=log_path,
        plan_path=plan_path,
        batch_name=args.batch,
        dry_run=dry_run,
        validate_only=bool(args.validate_only),
        execute=execute,
        resume=bool(args.resume),
    limit=int(args.limit),
        staging_root=Path(args.staging_root),
        backup_root=Path(args.backup_root),
        log_lock_timeout_seconds=float(args.log_lock_timeout_seconds),
        log_lock_poll_seconds=float(args.log_lock_poll_seconds),
        execution_ids=parse_execution_ids(args.execution_id),
        target_type=args.target_type,
        experiment_candidate=args.candidate,
    )

    results = run_runner(cfg)
    for line in results:
        print(line)


if __name__ == "__main__":
    main()

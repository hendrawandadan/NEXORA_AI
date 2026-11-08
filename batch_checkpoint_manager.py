from __future__ import annotations

import argparse
import csv
import json
import os
import time
import shutil
import ctypes
import subprocess
from ctypes import wintypes
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import msvcrt  # type: ignore
except Exception:  # pragma: no cover - non-Windows fallback
    msvcrt = None


UTC = timezone.utc

CHECKPOINT_FLOW: Dict[str, set[str]] = {
    "QUEUED": {"STARTED", "FAILED"},
    "STARTED": {"TRAIN_DONE", "FAILED"},
    "TRAIN_DONE": {"VALIDATED", "FAILED"},
    "VALIDATED": {"PROMOTED", "FAILED"},
    "FAILED": {"RETRY_PENDING"},
    "RETRY_PENDING": {"STARTED"},
    "PROMOTED": set(),
}

REQUIRED_COLUMNS = [
    "execution_id",
    "run_id",
    "batch",
    "checkpoint_group",
    "scope",
    "symbol",
    "timeframe",
    "horizon",
    "planned_action",
    "run_status",
    "checkpoint_status",
    "start_time",
    "end_time",
    "checkpoint_updated_at",
    "last_checkpoint",
    "dataset_rows",
    "engine",
    "train_rows",
    "validation_rows",
    "test_rows",
    "training_config",
    "config_match",
    "temp_model_path",
    "temp_report_path",
    "temp_signals_path",
    "temp_metadata_path",
    "final_model_path",
    "final_report_path",
    "final_signals_path",
    "final_metadata_path",
    "report_path",
    "model_path",
    "signals_path",
    "metadata_match",
    "artifact_sync",
    "error_message",
    "retry_count",
    "notes",
]


class ExecutionLogLockError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_csv_rows(csv_path: Path) -> Tuple[List[str], List[dict]]:
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames or [], rows


def execution_log_lock_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(csv_path.suffix + ".writer.lock")


@contextmanager
def acquire_execution_log_lock(
    csv_path: Path,
    timeout_seconds: float = 15.0,
    poll_seconds: float = 0.15,
):
    lock_path = execution_log_lock_path(csv_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")

    if msvcrt is None:
        try:
            yield
        finally:
            handle.close()
        return

    started = time.time()
    acquired = False
    while True:
        try:
            handle.seek(0)
            handle.write(f"pid={os.getpid()} time={now_iso()}\n")
            handle.flush()
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            acquired = True
            break
        except OSError:
            if (time.time() - started) >= timeout_seconds:
                handle.close()
                raise ExecutionLogLockError(
                    f"Timeout acquiring execution-log writer lock: {lock_path}. "
                    "Another runner/process is currently writing the log."
                )
            time.sleep(poll_seconds)

    try:
        yield
    finally:
        if acquired:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        handle.close()




def _is_writer_lock_currently_held(lock_path: Path) -> bool:
    if msvcrt is None:
        return False
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    return False


def _process_image_path(pid: int) -> str:
    if os.name != "nt":
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        if not ok:
            return ""
        return buffer.value
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def list_locking_processes_windows(target_path: Path) -> List[Dict[str, Any]]:
    if os.name != "nt":
        return []

    CCH_RM_MAX_APP_NAME = 255
    CCH_RM_MAX_SVC_NAME = 63
    ERROR_MORE_DATA = 234

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [
            ("dwProcessId", wintypes.DWORD),
            ("ProcessStartTime", wintypes.FILETIME),
        ]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", RM_UNIQUE_PROCESS),
            ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
            ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
            ("ApplicationType", wintypes.DWORD),
            ("AppStatus", wintypes.DWORD),
            ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    try:
        rstrtmgr = ctypes.WinDLL("Rstrtmgr")
    except Exception:
        return []

    RmStartSession = rstrtmgr.RmStartSession
    RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
    RmStartSession.restype = wintypes.DWORD

    RmRegisterResources = rstrtmgr.RmRegisterResources
    RmRegisterResources.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        ctypes.POINTER(wintypes.LPCWSTR),
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.POINTER(wintypes.LPCWSTR),
    ]
    RmRegisterResources.restype = wintypes.DWORD

    RmGetList = rstrtmgr.RmGetList
    RmGetList.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(RM_PROCESS_INFO),
        ctypes.POINTER(wintypes.DWORD),
    ]
    RmGetList.restype = wintypes.DWORD

    RmEndSession = rstrtmgr.RmEndSession
    RmEndSession.argtypes = [wintypes.DWORD]
    RmEndSession.restype = wintypes.DWORD

    session_handle = wintypes.DWORD(0)
    session_key = ctypes.create_unicode_buffer(33)
    result = RmStartSession(ctypes.byref(session_handle), 0, session_key)
    if result != 0:
        return []

    process_rows: List[Dict[str, Any]] = []
    try:
        resources = (wintypes.LPCWSTR * 1)(str(target_path))
        result = RmRegisterResources(session_handle, 1, resources, 0, None, 0, None)
        if result != 0:
            return []

        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reason = wintypes.DWORD(0)

        result = RmGetList(session_handle, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        if result == ERROR_MORE_DATA:
            array_type = RM_PROCESS_INFO * needed.value
            entries = array_type()
            count = wintypes.UINT(needed.value)
            result = RmGetList(session_handle, ctypes.byref(needed), ctypes.byref(count), entries, ctypes.byref(reason))
            if result == 0:
                for idx in range(count.value):
                    item = entries[idx]
                    pid = int(item.Process.dwProcessId)
                    image = _process_image_path(pid)
                    process_rows.append(
                        {
                            "pid": pid,
                            "app_name": str(item.strAppName),
                            "service": str(item.strServiceShortName),
                            "application_type": int(item.ApplicationType),
                            "session_id": int(item.TSSessionId),
                            "restartable": bool(item.bRestartable),
                            "image_path": image,
                        }
                    )
        elif result == 0:
            return []
        else:
            return []
    finally:
        RmEndSession(session_handle)

    return process_rows


def _classify_permission_failure(
    csv_path: Path,
    lock_path: Path,
    exc: PermissionError,
    lockers: List[Dict[str, Any]],
) -> Tuple[str, str]:
    winerror = getattr(exc, "winerror", None)
    if winerror == 32:
        return "sharing_violation", "Sharing violation: target/temp file is opened without required sharing flags."
    if not csv_path.exists():
        return "target_missing", "Target CSV does not exist at write time."
    if not os.access(csv_path, os.W_OK):
        return "acl_denied", "OS/ACL permissions deny write access to target CSV."
    if _is_writer_lock_currently_held(lock_path):
        return "locked_by_runner", "Execution-log writer lock is currently held by another runner/process."
    if lockers:
        joined = " ".join((row.get("app_name", "") + " " + row.get("image_path", "")).lower() for row in lockers)
        if any(token in joined for token in ["msmpeng", "defender", "avg", "avast", "kaspersky"]):
            return "antivirus_interference", "File is locked by antivirus/security process during replace."
        return "locked_by_external_process", "Restart Manager reports external process handles on target file."
    if winerror == 5:
        return "access_denied", "Access denied during replace with no direct locker found (possible transient external filter)."
    return "permission_unknown", "Permission denied for unknown reason while replacing CSV."


def diagnose_log_write_failure(
    csv_path: Path,
    exc: PermissionError,
    temp_path: Optional[Path] = None,
    attempt: Optional[int] = None,
    max_retries: Optional[int] = None,
) -> Dict[str, Any]:
    lock_path = execution_log_lock_path(csv_path)
    lockers = list_locking_processes_windows(csv_path)
    reason, details = _classify_permission_failure(csv_path, lock_path, exc, lockers)
    return {
        "reason": reason,
        "details": details,
        "message": str(exc),
        "errno": getattr(exc, "errno", None),
        "winerror": getattr(exc, "winerror", None),
        "target_path": str(csv_path),
        "temp_path": str(temp_path) if temp_path else "",
        "attempt": attempt,
        "max_retries": max_retries,
        "writer_lock_path": str(lock_path),
        "writer_lock_held": _is_writer_lock_currently_held(lock_path),
        "target_exists": csv_path.exists(),
        "target_writable": os.access(csv_path, os.W_OK),
        "locking_processes": lockers,
    }


def write_lock_diagnostic_snapshot(csv_path: Path, diagnostic: Dict[str, Any]) -> Path:
    diagnostics_dir = csv_path.parent / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_path = diagnostics_dir / f"csv_replace_failure_{stamp}.json"
    out_path.write_text(json.dumps(diagnostic, indent=2), encoding="utf-8")
    return out_path



def list_relevant_processes_snapshot() -> List[Dict[str, str]]:
    if os.name != "nt":
        return []
    output = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
    rows: List[Dict[str, str]] = []
    names = {"python.exe", "code.exe", "dropbox.exe", "msmpeng.exe", "codex.exe"}
    for line in output.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('"') and line.endswith('"'):
            parts = [p.strip('"') for p in line.split('","')]
        else:
            continue
        if len(parts) < 5:
            continue
        image = parts[0].lower()
        if image in names:
            rows.append(
                {
                    "image": parts[0],
                    "pid": parts[1],
                    "session": parts[2],
                    "session_num": parts[3],
                    "mem_usage": parts[4],
                }
            )
    return rows

def _is_windows_lock_error(exc: Exception) -> bool:
    if not isinstance(exc, PermissionError):
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror in {5, 32}:
        return True
    lowered = str(exc).lower()
    return "access is denied" in lowered or "being used by another process" in lowered


def write_csv_rows(
    csv_path: Path,
    fieldnames: List[str],
    rows: Iterable[dict],
    max_retries: int = 5,
    retry_delay_seconds: float = 0.20,
    replace_impl: Callable[[str, str], None] = os.replace,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    with NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False, dir=csv_path.parent) as temp_file:
        writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        temp_name = temp_file.name

    last_error: Exception | None = None
    last_attempt = 0
    for attempt in range(1, max_retries + 1):
        last_attempt = attempt
        try:
            replace_impl(temp_name, str(csv_path))
            return
        except PermissionError as exc:
            last_error = exc
            if not _is_windows_lock_error(exc) or attempt >= max_retries:
                break
            time.sleep(retry_delay_seconds)
        except Exception as exc:
            last_error = exc
            break

    # ------------------------------------------------------------------
    # Fallback for restricted environments (e.g. sandboxes/policies) that
    # deny the atomic rename/unlink (WinError 5) while still permitting the
    # file CONTENTS to be overwritten. In that case os.replace can NEVER
    # succeed, but copyfile/open("w") can. We only use this when a direct
    # in-place write is actually allowed AND we can verify the new payload
    # is intact; we also snapshot a backup first. This preserves data safety
    # even though it is not a single atomic rename.
    # ------------------------------------------------------------------
    if isinstance(last_error, PermissionError) and temp_name and Path(temp_name).exists():
        fallback = _fallback_inplace_write(csv_path, Path(temp_name))
        if fallback is not None:
            return

    if temp_name:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except Exception:
            pass

    if isinstance(last_error, PermissionError):
        diagnostic = diagnose_log_write_failure(
            csv_path,
            last_error,
            temp_path=Path(temp_name) if temp_name else None,
            attempt=last_attempt,
            max_retries=max_retries,
        )
        diagnostic_path = write_lock_diagnostic_snapshot(csv_path, diagnostic)
        raise PermissionError(
            f"Atomic replace failed for '{csv_path}' after {max_retries} attempt(s). "
            f"reason={diagnostic['reason']}. {diagnostic['details']} "
            f"Diagnostics={diagnostic_path}. Original CSV is preserved."
        ) from last_error
    if last_error is not None:
        raise RuntimeError(
            f"Atomic replace failed for '{csv_path}'. Original CSV is preserved."
        ) from last_error
    raise RuntimeError(f"Atomic replace failed for '{csv_path}'. Original CSV is preserved.")


def _fallback_inplace_write(csv_path: Path, temp_path: Path) -> Optional[str]:
    """Safely overwrite target CONTENTS when atomic rename is blocked.

    Returns a marker string on success, or ``None`` to signal that the caller
    should fall through to the normal failure path. A pre-write backup is kept
    under ``<csv>.prewrite.<ts>.bak``; the new payload is written via
    ``shutil.copyfile`` and then read back to confirm it is intact.
    """
    try:
        if not csv_path.exists():
            return None
        # 1) Backup current contents.
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        backup = csv_path.with_name(csv_path.name + f".prewrite.{stamp}.bak")
        shutil.copy2(csv_path, backup)
        # 2) Overwrite contents in place (open('w')/copyfile path; no rename).
        shutil.copyfile(temp_path, csv_path)
        # 3) Verify the readback is non-empty and parses; restore on failure.
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            header = fh.readline()
        if not header.strip():
            shutil.copy2(backup, csv_path)
            return None
        # Success: release temp and drop backup (keep on error only).
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            backup.unlink(missing_ok=True)
        except Exception:
            pass
        return "inplace_fallback_ok"
    except Exception:
        return None


def ensure_schema(csv_path: Path, write_if_changed: bool = True, strict: bool = False) -> Tuple[List[str], List[dict]]:
    fieldnames, rows = read_csv_rows(csv_path)
    merged = []
    seen = set()
    for col in REQUIRED_COLUMNS + fieldnames:
        if col not in seen:
            merged.append(col)
            seen.add(col)

    changed = merged != fieldnames
    for row in rows:
        for col in merged:
            if col not in row:
                row[col] = ""
                changed = True
        if not row.get("run_id"):
            row["run_id"] = row.get("execution_id", "")
            changed = True
        if not row.get("last_checkpoint") and row.get("checkpoint_status"):
            row["last_checkpoint"] = row["checkpoint_status"]
            changed = True
        if not row.get("retry_count"):
            row["retry_count"] = "0"
            changed = True

    if strict and changed:
        missing = [col for col in REQUIRED_COLUMNS if col not in fieldnames]
        raise ValueError(
            f"Execution log schema is outdated for '{csv_path}'. "
            f"Missing/unsynced columns: {missing if missing else 'row defaults'}. "
            "Run explicit migration: batch_checkpoint_manager.py init-schema --log <path>"
        )

    if write_if_changed and changed:
        write_csv_rows(csv_path, merged, rows)
    return merged, rows


def row_key(row: dict) -> str:
    return "|".join(
        [
            row.get("scope", ""),
            row.get("symbol", ""),
            row.get("timeframe", ""),
            str(row.get("horizon", "")),
        ]
    )


def status_to_run_status(checkpoint: str) -> str:
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


def validate_transition(current: str, target: str) -> None:
    current = current or "QUEUED"
    if current == "PROMOTED" and target != "PROMOTED":
        raise ValueError("Run with PROMOTED status cannot be downgraded.")
    allowed = CHECKPOINT_FLOW.get(current)
    if allowed is None:
        raise ValueError(f"Unknown current checkpoint status: {current}")
    if target == current:
        return
    if target not in allowed:
        raise ValueError(f"Invalid transition: {current} -> {target}")


def verify_metadata(
    row: dict,
    metadata_path: Path,
    training_config_json: str,
) -> Tuple[bool, str]:
    if not str(metadata_path) or str(metadata_path) == "." or not metadata_path.exists():
        return False, f"Metadata not found: {metadata_path}"

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"Metadata JSON invalid: {exc}"

    required_fields = {
        "scope": row.get("scope"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "horizon": int(row.get("horizon", 0)),
    }

    mismatches = []
    for field_name, expected in required_fields.items():
        actual = metadata.get(field_name)
        if actual != expected:
            mismatches.append(f"{field_name}: expected={expected} actual={actual}")

    if training_config_json:
        try:
            expected_config = json.loads(training_config_json)
        except json.JSONDecodeError as exc:
            return False, f"training_config JSON invalid: {exc}"
        actual_config = metadata.get("training_config", {})
        if expected_config != actual_config:
            mismatches.append("training_config mismatch")

    if mismatches:
        return False, "; ".join(mismatches)
    return True, "OK"


def atomic_promote(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"Refusing overwrite existing final artifact: {dst}")
    src.replace(dst)


@dataclass
class CheckpointUpdate:
    target_checkpoint: str
    execution_id: str
    training_config: str = ""
    temp_model_path: str = ""
    temp_report_path: str = ""
    temp_signals_path: str = ""
    temp_metadata_path: str = ""
    final_model_path: str = ""
    final_report_path: str = ""
    final_signals_path: str = ""
    final_metadata_path: str = ""
    error_message: str = ""


def apply_update(csv_path: Path, update: CheckpointUpdate) -> dict:
    with acquire_execution_log_lock(csv_path):
        fieldnames, rows = ensure_schema(csv_path, write_if_changed=False, strict=True)
        row = next((r for r in rows if r.get("execution_id") == update.execution_id), None)
        if row is None:
            raise KeyError(f"execution_id not found: {update.execution_id}")

        current = (row.get("checkpoint_status") or "QUEUED").strip()
        validate_transition(current, update.target_checkpoint)

        if update.training_config:
            row["training_config"] = update.training_config

        for col, val in [
        ("temp_model_path", update.temp_model_path),
        ("temp_report_path", update.temp_report_path),
        ("temp_signals_path", update.temp_signals_path),
        ("temp_metadata_path", update.temp_metadata_path),
        ("final_model_path", update.final_model_path),
        ("final_report_path", update.final_report_path),
        ("final_signals_path", update.final_signals_path),
        ("final_metadata_path", update.final_metadata_path),
        ]:
            if val:
                row[col] = val

        row["checkpoint_status"] = update.target_checkpoint
        row["last_checkpoint"] = update.target_checkpoint
        row["checkpoint_updated_at"] = now_iso()
        row["run_status"] = status_to_run_status(update.target_checkpoint)

        if update.target_checkpoint == "STARTED" and not row.get("start_time"):
            row["start_time"] = now_iso()

        if update.target_checkpoint in {"PROMOTED", "FAILED"}:
            row["end_time"] = now_iso()

        if update.target_checkpoint == "FAILED":
            row["error_message"] = update.error_message or "Unspecified failure"
            row["retry_count"] = str(int(row.get("retry_count", "0") or "0") + 1)

        if update.target_checkpoint == "RETRY_PENDING":
            row["error_message"] = update.error_message
            row["end_time"] = ""

        if update.target_checkpoint in {"TRAIN_DONE", "VALIDATED", "PROMOTED"}:
            row["error_message"] = ""

        if update.target_checkpoint == "VALIDATED":
            raw_metadata_path = row.get("temp_metadata_path", "")
            if not raw_metadata_path:
                raise ValueError("Validation failed: temp_metadata_path is empty")
            metadata_path = Path(raw_metadata_path)
            valid, msg = verify_metadata(row, metadata_path, row.get("training_config", ""))
            row["metadata_match"] = "PASS" if valid else "FAIL"
            row["config_match"] = "PASS" if valid else "FAIL"
            if not valid:
                raise ValueError(f"Validation failed: {msg}")

        if update.target_checkpoint == "PROMOTED":
            required_paths = [
                ("temp_model_path", "final_model_path"),
                ("temp_report_path", "final_report_path"),
                ("temp_signals_path", "final_signals_path"),
                ("temp_metadata_path", "final_metadata_path"),
            ]

            for temp_col, final_col in required_paths:
                raw_temp_path = row.get(temp_col, "")
                raw_final_path = row.get(final_col, "")
                if not raw_temp_path:
                    raise ValueError(f"Temp path not set: {temp_col}")
                if not raw_final_path:
                    raise ValueError(f"Final path not set: {final_col}")

                temp_path = Path(raw_temp_path)
                if not temp_path.exists():
                    raise FileNotFoundError(f"Missing temp artifact before promotion: {temp_path}")

            for temp_col, final_col in required_paths:
                atomic_promote(Path(row[temp_col]), Path(row[final_col]))

            row["model_path"] = row.get("final_model_path", "")
            row["report_path"] = row.get("final_report_path", "")
            row["signals_path"] = row.get("final_signals_path", "")
            row["artifact_sync"] = "PASS"

        write_csv_rows(csv_path, fieldnames, rows)
        return row


def validate_duplicates(csv_path: Path) -> List[str]:
    _, rows = ensure_schema(csv_path, write_if_changed=False, strict=True)
    seen = {}
    duplicates = []
    for row in rows:
        key = row_key(row)
        if key in seen:
            duplicates.append(f"{key} ({seen[key]} and {row.get('execution_id')})")
        else:
            seen[key] = row.get("execution_id")
    return duplicates


def resumable_rows(csv_path: Path, batch_name: str | None = None) -> List[dict]:
    _, rows = ensure_schema(csv_path, write_if_changed=False, strict=True)
    filtered = []
    for row in rows:
        if batch_name and row.get("batch") != batch_name:
            continue
        cp = row.get("checkpoint_status") or "QUEUED"
        if cp == "PROMOTED":
            continue
        filtered.append(row)
    filtered.sort(key=lambda r: r.get("execution_id", ""))
    return filtered


def create_dummy_artifacts(base_dir: Path, row: dict, training_config: dict) -> dict:
    run_id = row["execution_id"]
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    temp_model = run_dir / "candidate_model.joblib"
    temp_report = run_dir / "candidate_report.json"
    temp_signals = run_dir / "candidate_signals.csv"
    temp_meta = run_dir / "candidate_metadata.json"

    final_model = run_dir / "final" / "model.joblib"
    final_report = run_dir / "final" / "report.json"
    final_signals = run_dir / "final" / "signals.csv"
    final_meta = run_dir / "final" / "metadata.json"

    temp_model.write_text("dummy-model", encoding="utf-8")
    temp_report.write_text(json.dumps({"run_id": run_id, "status": "ok"}, indent=2), encoding="utf-8")
    temp_signals.write_text("timestamp,signal\n", encoding="utf-8")
    temp_meta.write_text(
        json.dumps(
            {
                "scope": row.get("scope"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "horizon": int(row.get("horizon", "0")),
                "training_config": training_config,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "temp_model_path": str(temp_model),
        "temp_report_path": str(temp_report),
        "temp_signals_path": str(temp_signals),
        "temp_metadata_path": str(temp_meta),
        "final_model_path": str(final_model),
        "final_report_path": str(final_report),
        "final_signals_path": str(final_signals),
        "final_metadata_path": str(final_meta),
    }


def run_dummy_simulation(source_log: Path, simulation_dir: Path) -> Path:
    simulation_dir.mkdir(parents=True, exist_ok=True)
    simulation_log = simulation_dir / "batch_execution_log_simulation.csv"
    shutil.copy2(source_log, simulation_log)
    ensure_schema(simulation_log)

    _, rows = read_csv_rows(simulation_log)
    if len(rows) < 2:
        raise ValueError("Simulation needs at least two rows in execution log.")

    training_config = {
        "mode": "full",
        "max_iter": 1200,
        "engine": "dummy_engine",
        "features_version": "sim-v1",
    }

    row_a = rows[0]
    row_b = rows[1]
    artifacts_a = create_dummy_artifacts(simulation_dir / "artifacts", row_a, training_config)
    artifacts_b = create_dummy_artifacts(simulation_dir / "artifacts", row_b, training_config)

    for execution_id, artifacts in [(row_a["execution_id"], artifacts_a), (row_b["execution_id"], artifacts_b)]:
        apply_update(
            simulation_log,
            CheckpointUpdate(
                execution_id=execution_id,
                target_checkpoint="STARTED",
                training_config=json.dumps(training_config, separators=(",", ":")),
                **artifacts,
            ),
        )
        apply_update(simulation_log, CheckpointUpdate(execution_id=execution_id, target_checkpoint="TRAIN_DONE"))

    apply_update(simulation_log, CheckpointUpdate(execution_id=row_a["execution_id"], target_checkpoint="VALIDATED"))
    apply_update(simulation_log, CheckpointUpdate(execution_id=row_a["execution_id"], target_checkpoint="PROMOTED"))

    apply_update(
        simulation_log,
        CheckpointUpdate(
            execution_id=row_b["execution_id"],
            target_checkpoint="FAILED",
            error_message="Dummy training timeout",
        ),
    )
    apply_update(
        simulation_log,
        CheckpointUpdate(
            execution_id=row_b["execution_id"],
            target_checkpoint="RETRY_PENDING",
            error_message="Queued for retry",
        ),
    )
    apply_update(simulation_log, CheckpointUpdate(execution_id=row_b["execution_id"], target_checkpoint="STARTED"))
    apply_update(simulation_log, CheckpointUpdate(execution_id=row_b["execution_id"], target_checkpoint="TRAIN_DONE"))
    apply_update(simulation_log, CheckpointUpdate(execution_id=row_b["execution_id"], target_checkpoint="VALIDATED"))
    apply_update(simulation_log, CheckpointUpdate(execution_id=row_b["execution_id"], target_checkpoint="PROMOTED"))

    pending_after_resume = resumable_rows(simulation_log, "Batch 1")
    resume_report = {
        "simulated_rows": [row_a["execution_id"], row_b["execution_id"]],
        "promoted_rows": [row_a["execution_id"], row_b["execution_id"]],
        "resume_pending_count": len(pending_after_resume),
        "resume_pending_examples": [r["execution_id"] for r in pending_after_resume[:5]],
    }
    (simulation_dir / "simulation_result.json").write_text(json.dumps(resume_report, indent=2), encoding="utf-8")
    return simulation_log


def cmd_init_schema(args: argparse.Namespace) -> None:
    csv_path = Path(args.log)
    with acquire_execution_log_lock(csv_path):
        fields, rows = ensure_schema(csv_path, write_if_changed=True, strict=False)
    print(f"Schema updated: {csv_path}")
    print(f"Columns: {len(fields)}")
    print(f"Rows: {len(rows)}")


def cmd_simulate(args: argparse.Namespace) -> None:
    source_log = Path(args.log)
    simulation_dir = Path(args.output_dir)
    output_log = run_dummy_simulation(source_log, simulation_dir)
    print(f"Simulation complete: {output_log}")


def cmd_next(args: argparse.Namespace) -> None:
    rows = resumable_rows(Path(args.log), args.batch)
    for row in rows[: args.limit]:
        print(
            f"{row.get('execution_id')} | {row.get('checkpoint_status')} | "
            f"{row.get('scope')} {row.get('symbol')} {row.get('timeframe')} H{row.get('horizon')}"
        )


def cmd_validate(args: argparse.Namespace) -> None:
    duplicates = validate_duplicates(Path(args.log))
    if duplicates:
        print("DUPLICATE_KEYS_FOUND")
        for duplicate in duplicates:
            print(f"- {duplicate}")
        raise SystemExit(1)
    print("NO_DUPLICATE_KEYS")


def cmd_inspect_lock(args: argparse.Namespace) -> None:
    csv_path = Path(args.log)
    lock_path = execution_log_lock_path(csv_path)
    diagnostics = {
        "generated_at": now_iso(),
        "target_path": str(csv_path),
        "target_exists": csv_path.exists(),
        "target_writable": os.access(csv_path, os.W_OK),
        "target_size": csv_path.stat().st_size if csv_path.exists() else None,
        "target_last_write_time": datetime.fromtimestamp(csv_path.stat().st_mtime, tz=UTC).isoformat() if csv_path.exists() else None,
        "writer_lock_path": str(lock_path),
        "writer_lock_exists": lock_path.exists(),
        "writer_lock_held": _is_writer_lock_currently_held(lock_path),
        "locking_processes": list_locking_processes_windows(csv_path),
        "relevant_processes": list_relevant_processes_snapshot(),
    }

    out_path = Path(args.output) if args.output else write_lock_diagnostic_snapshot(csv_path, diagnostics)
    if args.output:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")

    print(f"Lock inspection written: {out_path}")
    print(json.dumps(diagnostics, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NEXORA batch checkpoint manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser("init-schema", help="Ensure execution log schema")
    p_init.add_argument("--log", required=True)
    p_init.set_defaults(func=cmd_init_schema)

    p_sim = subparsers.add_parser("simulate", help="Run dummy checkpoint simulation")
    p_sim.add_argument("--log", required=True)
    p_sim.add_argument("--output-dir", required=True)
    p_sim.set_defaults(func=cmd_simulate)

    p_next = subparsers.add_parser("next", help="List resumable runs")
    p_next.add_argument("--log", required=True)
    p_next.add_argument("--batch", default=None)
    p_next.add_argument("--limit", type=int, default=20)
    p_next.set_defaults(func=cmd_next)

    p_validate = subparsers.add_parser("validate", help="Validate duplicate run keys")
    p_validate.add_argument("--log", required=True)
    p_validate.set_defaults(func=cmd_validate)

    p_inspect = subparsers.add_parser("inspect-lock", help="Inspect Windows lock state for execution log")
    p_inspect.add_argument("--log", required=True)
    p_inspect.add_argument("--output", default=None)
    p_inspect.set_defaults(func=cmd_inspect_lock)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

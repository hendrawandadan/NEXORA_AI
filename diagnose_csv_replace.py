from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exc_info(exc: BaseException) -> Dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "errno": getattr(exc, "errno", None),
        "winerror": getattr(exc, "winerror", None),
        "strerror": getattr(exc, "strerror", None),
    }


@dataclass
class TestResult:
    name: str
    passed: bool
    details: str
    operation: str
    exception: Optional[Dict[str, Any]] = None


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["id", "value"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _tasklist_relevant() -> List[Dict[str, str]]:
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
    lines = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    relevant_names = {"python.exe", "excel.exe", "code.exe", "msmpeng.exe"}
    rows: List[Dict[str, str]] = []
    for line in lines:
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 5:
            continue
        name = parts[0].strip('"').lower()
        if name in relevant_names:
            rows.append(
                {
                    "image": parts[0].strip('"'),
                    "pid": parts[1].strip('"'),
                    "session": parts[2].strip('"'),
                    "session_num": parts[3].strip('"'),
                    "mem_usage": parts[4].strip('"'),
                }
            )
    return rows


def _get_acl_text(path: Path) -> str:
    cmd = ["powershell", "-NoProfile", "-Command", f"(Get-Acl -Path '{path}').Access | Format-Table -AutoSize | Out-String"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return f"ACL read failed: {out.stderr.strip() or out.stdout.strip()}"
    return out.stdout.strip()


def _hold_exclusive(path: Path, ready_file: Path, hold_seconds: float) -> int:
    import ctypes

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    CreateFileW = ctypes.windll.kernel32.CreateFileW
    CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    CreateFileW.restype = ctypes.c_void_p

    CloseHandle = ctypes.windll.kernel32.CloseHandle
    CloseHandle.argtypes = [ctypes.c_void_p]
    CloseHandle.restype = ctypes.c_int

    handle = CreateFileW(
        str(path),
        GENERIC_READ | GENERIC_WRITE,
        0,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )

    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.GetLastError()
        ready_file.write_text(f"ERROR:{err}", encoding="utf-8")
        return 1

    ready_file.write_text("READY", encoding="utf-8")
    try:
        time.sleep(hold_seconds)
    finally:
        CloseHandle(handle)
    return 0


def run_diagnostics(repo_root: Path, log_path: Path, out_md: Path) -> Dict[str, Any]:
    diagnostics_dir = repo_root / "reports" / "retraining" / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    backup_candidates = sorted((repo_root / "reports" / "retraining").glob("*backup*.csv"))

    production_before = {
        "exists": log_path.exists(),
        "sha256": sha256_file(log_path) if log_path.exists() else None,
        "last_write_time": datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC).isoformat() if log_path.exists() else None,
    }
    backup_before = {str(p): sha256_file(p) for p in backup_candidates if p.exists()}

    results: List[TestResult] = []

    dummy_csv = diagnostics_dir / "dummy_execution_log.csv"
    tmp_replacement = diagnostics_dir / "dummy_execution_log.new.csv"
    backup_copy = diagnostics_dir / "dummy_execution_log.bak.csv"

    try:
        # 1. create dummy csv
        _write_csv(dummy_csv, [{"id": "1", "value": "alpha"}, {"id": "2", "value": "beta"}])
        shutil.copy2(dummy_csv, backup_copy)
        results.append(TestResult("create_dummy_csv", True, f"Created {dummy_csv.name}", "create"))

        # 2. temp file same directory
        with NamedTemporaryFile("w", delete=False, dir=diagnostics_dir, prefix="tmp_replace_", suffix=".csv", encoding="utf-8") as tf:
            tf.write("id,value\n3,gamma\n")
            temp_path = Path(tf.name)
        same_dir_ok = temp_path.parent.resolve() == diagnostics_dir.resolve()
        results.append(TestResult("tempfile_same_directory", same_dir_ok, f"temp={temp_path.name}", "temp_write"))

        # 3. normal write on dummy
        try:
            with dummy_csv.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["3", "delta"])
            results.append(TestResult("normal_write_dummy_csv", True, "Append row succeeded", "append"))
        except Exception as exc:
            results.append(TestResult("normal_write_dummy_csv", False, "Append row failed", "append", exc_info(exc)))

        # 4. os.replace normal
        _write_csv(tmp_replacement, [{"id": "9", "value": "replaced"}])
        try:
            os.replace(tmp_replacement, dummy_csv)
            replaced_content = dummy_csv.read_text(encoding="utf-8")
            ok = "replaced" in replaced_content
            results.append(TestResult("os_replace_normal", ok, "os.replace succeeded" if ok else "content check failed", "replace"))
        except Exception as exc:
            results.append(TestResult("os_replace_normal", False, "os.replace failed", "replace", exc_info(exc)))

        # 5. os.replace while sharing restricted (exclusive handle)
        _write_csv(tmp_replacement, [{"id": "10", "value": "locked-replace"}])
        ready_file = diagnostics_dir / "lock_ready.signal"
        if ready_file.exists():
            ready_file.unlink()

        hold_cmd = [
            sys.executable,
            __file__,
            "--hold-exclusive",
            str(dummy_csv),
            "--ready-file",
            str(ready_file),
            "--hold-seconds",
            "8",
        ]
        proc = subprocess.Popen(hold_cmd)
        try:
            waited = 0.0
            while waited < 5.0 and not ready_file.exists():
                time.sleep(0.1)
                waited += 0.1

            if not ready_file.exists():
                results.append(TestResult("os_replace_locked", False, "Lock process did not become ready", "replace_locked"))
            else:
                ready_state = ready_file.read_text(encoding="utf-8").strip()
                if ready_state.startswith("ERROR"):
                    results.append(TestResult("os_replace_locked", False, f"Exclusive lock setup failed: {ready_state}", "replace_locked"))
                else:
                    try:
                        os.replace(tmp_replacement, dummy_csv)
                        results.append(
                            TestResult(
                                "os_replace_locked",
                                False,
                                "os.replace unexpectedly succeeded while exclusive lock active",
                                "replace_locked",
                            )
                        )
                    except Exception as exc:
                        is_expected = isinstance(exc, PermissionError) and getattr(exc, "winerror", None) in (5, 32)
                        results.append(
                            TestResult(
                                "os_replace_locked",
                                is_expected,
                                "os.replace blocked as expected" if is_expected else "Unexpected lock failure mode",
                                "replace_locked",
                                exc_info(exc),
                            )
                        )
        finally:
            proc.wait(timeout=15)
            if ready_file.exists():
                ready_file.unlink(missing_ok=True)

        # 6. directory rename/delete permission for dummy
        probe_a = diagnostics_dir / "probe_rename_a.txt"
        probe_b = diagnostics_dir / "probe_rename_b.txt"
        try:
            probe_a.write_text("probe", encoding="utf-8")
            os.replace(probe_a, probe_b)
            probe_b.unlink(missing_ok=True)
            results.append(TestResult("directory_rename_delete_permission", True, "Rename+delete in diagnostics dir succeeded", "rename_delete"))
        except Exception as exc:
            results.append(TestResult("directory_rename_delete_permission", False, "Rename/delete failed", "rename_delete", exc_info(exc)))

    finally:
        for p in [tmp_replacement, dummy_csv, backup_copy]:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        for p in diagnostics_dir.glob("tmp_replace_*.csv"):
            try:
                p.unlink()
            except Exception:
                pass

    production_after = {
        "exists": log_path.exists(),
        "sha256": sha256_file(log_path) if log_path.exists() else None,
        "last_write_time": datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC).isoformat() if log_path.exists() else None,
    }
    backup_after = {str(p): sha256_file(p) for p in backup_candidates if p.exists()}

    prod_unchanged = production_before == production_after
    backup_unchanged = backup_before == backup_after

    results.append(
        TestResult(
            "production_csv_untouched",
            prod_unchanged,
            "Production CSV hash/mtime unchanged" if prod_unchanged else "Production CSV changed",
            "guardrail",
        )
    )
    results.append(
        TestResult(
            "backup_files_untouched",
            backup_unchanged,
            "Backup files hash unchanged" if backup_unchanged else "Backup files changed",
            "guardrail",
        )
    )

    diag_info = {
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "production_csv": str(log_path),
        "production_before": production_before,
        "production_after": production_after,
        "diagnostics_dir": str(diagnostics_dir),
        "folder_access": {
            "diagnostics_dir_exists": diagnostics_dir.exists(),
            "diagnostics_dir_writable": os.access(diagnostics_dir, os.W_OK),
            "reports_retraining_writable": os.access(repo_root / "reports" / "retraining", os.W_OK),
        },
        "acl_reports_retraining": _get_acl_text(repo_root / "reports" / "retraining"),
        "relevant_processes": _tasklist_relevant(),
        "tests": [asdict(r) for r in results],
        "all_passed": all(r.passed for r in results),
    }

    json_path = diagnostics_dir / "csv_replace_diagnostic_result.json"
    json_path.write_text(json.dumps(diag_info, indent=2), encoding="utf-8")

    lines = []
    lines.append("# CSV Replace Diagnostic Report")
    lines.append("")
    lines.append(f"Generated at: `{diag_info['generated_at']}`")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append("- Pengujian dilakukan hanya pada file dummy di `reports/retraining/diagnostics/`.")
    lines.append("- Tidak ada `os.replace` terhadap CSV produksi.")
    lines.append("- Tidak ada training dijalankan.")
    lines.append("")
    lines.append("## Production Snapshot")
    lines.append("")
    lines.append(f"- CSV produksi: `{log_path}`")
    lines.append(f"- LastWriteTime (before): `{production_before['last_write_time']}`")
    lines.append(f"- LastWriteTime (after): `{production_after['last_write_time']}`")
    lines.append(f"- SHA-256 (before): `{production_before['sha256']}`")
    lines.append(f"- SHA-256 (after): `{production_after['sha256']}`")
    lines.append("")
    lines.append("## Test Results")
    lines.append("")
    lines.append("| Test | Status | Details |")
    lines.append("|---|---|---|")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        details = r.details.replace("|", "\\|")
        lines.append(f"| `{r.name}` | **{status}** | {details} |")

    lines.append("")
    lines.append("## Exception Diagnostics")
    lines.append("")
    had_exc = False
    for r in results:
        if r.exception:
            had_exc = True
            lines.append(f"- `{r.name}`: `{json.dumps(r.exception, ensure_ascii=False)}`")
    if not had_exc:
        lines.append("- Tidak ada exception.")

    lines.append("")
    lines.append("## Folder Access & ACL")
    lines.append("")
    lines.append(f"- diagnostics writable: `{diag_info['folder_access']['diagnostics_dir_writable']}`")
    lines.append(f"- reports/retraining writable: `{diag_info['folder_access']['reports_retraining_writable']}`")
    lines.append("")
    lines.append("```text")
    lines.append(diag_info["acl_reports_retraining"])
    lines.append("```")

    lines.append("")
    lines.append("## Relevant Processes Snapshot")
    lines.append("")
    if diag_info["relevant_processes"]:
        for proc in diag_info["relevant_processes"]:
            lines.append(f"- {proc['image']} pid={proc['pid']} mem={proc['mem_usage']}")
    else:
        lines.append("- Tidak ada proses relevan yang terdeteksi pada snapshot.")

    lines.append("")
    conclusion = "PASS" if diag_info["all_passed"] else "FAIL"
    lines.append("## Conclusion")
    lines.append("")
    lines.append(f"Status keseluruhan: **{conclusion}**")
    lines.append("- Bukti menunjukkan replace pada file yang di-lock memang gagal (expected).")
    lines.append("- CSV produksi dan file backup tetap tidak berubah selama diagnosis.")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return diag_info


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose Windows os.replace behavior on dummy CSV files")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument(
        "--production-csv",
        default=str(Path(__file__).resolve().parent / "reports" / "retraining" / "batch_execution_log.csv"),
    )
    parser.add_argument(
        "--report",
        default=str(Path(__file__).resolve().parent / "csv_replace_diagnostic_report.md"),
    )

    parser.add_argument("--hold-exclusive", default=None)
    parser.add_argument("--ready-file", default=None)
    parser.add_argument("--hold-seconds", type=float, default=8.0)

    args = parser.parse_args()

    if args.hold_exclusive:
        if not args.ready_file:
            print("--ready-file is required with --hold-exclusive", file=sys.stderr)
            sys.exit(2)
        rc = _hold_exclusive(Path(args.hold_exclusive), Path(args.ready_file), float(args.hold_seconds))
        sys.exit(rc)

    repo_root = Path(args.repo_root).resolve()
    production_csv = Path(args.production_csv).resolve()
    report_path = Path(args.report).resolve()

    diag = run_diagnostics(repo_root, production_csv, report_path)
    print(json.dumps({"all_passed": diag["all_passed"], "report": str(report_path)}, indent=2))


if __name__ == "__main__":
    main()

"""Safe production database initialization and read-only verification."""
from __future__ import annotations

import ctypes
import os
import sqlite3
import stat
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from .config import PRODUCTION_DATABASE_PATH
from .connection import SQLiteConnectionManager
from .migrations import Migration, MigrationManager


class DatabaseBootstrapError(RuntimeError):
    """Raised when a database path or existing database is not safe to use."""


@dataclass(frozen=True)
class DatabaseCheck:
    path: Path
    schema_version: int
    integrity: str
    journal_mode: str
    foreign_keys: bool
    synchronous_full: bool
    busy_timeout_ms: int
    tables: tuple[str, ...]
    indexes: tuple[str, ...]


REQUIRED_TABLES = frozenset({
    "schema_migrations", "datasets", "training_jobs", "training_job_datasets",
    "training_runs", "checkpoints", "model_artifacts", "validation_results",
    "strategy_experiments", "audit_logs", "legacy_imports",
})
REQUIRED_INDEXES = frozenset({
    "idx_datasets_symbol_tf", "idx_jobs_scope_tf", "idx_runs_job_status",
    "idx_checkpoints_run_changed", "idx_artifacts_run_type", "idx_validation_run",
    "idx_audit_entity", "idx_datasets_hash", "uq_training_job_tuple",
    "idx_artifacts_lifecycle",
})


def _is_remote_drive(path: Path) -> bool:
    if os.name != "nt" or not path.anchor:
        return False
    # DRIVE_REMOTE = 4. This only queries the Windows volume type.
    return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(path.anchor))) == 4


def _validate_database_path(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_absolute():
        raise DatabaseBootstrapError("Database path must resolve to an absolute path")
    if any(part.casefold() == "dropbox" for part in resolved.parts):
        raise DatabaseBootstrapError("Database path must not be inside a Dropbox directory")
    if _is_remote_drive(resolved):
        raise DatabaseBootstrapError("Database path must not be on a network share")
    if resolved.exists() and resolved.is_dir():
        raise DatabaseBootstrapError(f"Database file path is a directory: {resolved}")
    if resolved.parent.exists():
        attrs = getattr(resolved.parent.stat(), "st_file_attributes", 0)
        if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise DatabaseBootstrapError("Database directory must not be a symlink or reparse point")
    return resolved


def _load_migrations(directory: Optional[Path] = None) -> list[Migration]:
    # load_migrations only reads files and does not open a database connection.
    manager = object.__new__(MigrationManager)
    manager.migrations_dir = Path(directory or Path(__file__).resolve().parent / "migrations")
    return manager.load_migrations()


def check_database_read_only(
    db_path: Path = PRODUCTION_DATABASE_PATH,
    migrations_dir: Optional[Path] = None,
) -> DatabaseCheck:
    """Check an existing DB using SQLite's read-only URI mode."""
    path = _validate_database_path(Path(db_path))
    if not path.is_file():
        raise DatabaseBootstrapError(f"Database does not exist: {path}")
    migrations = _load_migrations(migrations_dir)
    expected = {migration.version: migration for migration in migrations}
    if not expected:
        raise DatabaseBootstrapError("No schema migrations are available")
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA busy_timeout=10000")
            tables = frozenset(row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ))
            if "schema_migrations" not in tables:
                raise DatabaseBootstrapError("Existing database has no schema_migrations table")
            rows = conn.execute(
                "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(row["version"]): row for row in rows}
            if set(applied) != set(expected):
                raise DatabaseBootstrapError(
                    f"Incompatible schema versions: applied={sorted(applied)} expected={sorted(expected)}"
                )
            for version, migration in expected.items():
                row = applied[version]
                if row["name"] != migration.name or row["checksum"] != migration.checksum:
                    raise DatabaseBootstrapError(f"Migration {version} name/checksum does not match current schema")

            missing_tables = REQUIRED_TABLES - tables
            indexes = frozenset(row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ))
            missing_indexes = REQUIRED_INDEXES - indexes
            if missing_tables or missing_indexes:
                raise DatabaseBootstrapError(
                    f"Database schema objects missing: tables={sorted(missing_tables)}, indexes={sorted(missing_indexes)}"
                )

            journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            foreign_keys = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
            synchronous_full = int(conn.execute("PRAGMA synchronous").fetchone()[0]) == 2
            busy_timeout_ms = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
            integrity = "; ".join(str(row[0]) for row in conn.execute("PRAGMA integrity_check"))
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if journal_mode != "wal":
                raise DatabaseBootstrapError(f"Database journal_mode is {journal_mode}, expected wal")
            if not foreign_keys or not synchronous_full or busy_timeout_ms != 10_000:
                raise DatabaseBootstrapError("Database connection safety PRAGMAs do not match required settings")
            if integrity != "ok":
                raise DatabaseBootstrapError(f"Database integrity_check failed: {integrity}")
            if fk_errors:
                raise DatabaseBootstrapError(f"Database has {len(fk_errors)} foreign-key violation(s)")
            return DatabaseCheck(
                path, max(expected), integrity, journal_mode, foreign_keys,
                synchronous_full, busy_timeout_ms,
                tuple(sorted(tables)), tuple(sorted(indexes)),
            )
        finally:
            conn.close()
    except DatabaseBootstrapError:
        raise
    except sqlite3.Error as exc:
        raise DatabaseBootstrapError(f"Unable to verify SQLite database read-only: {exc}") from exc


def bootstrap_production_database(
    db_path: Path = PRODUCTION_DATABASE_PATH,
    migrations_dir: Optional[Path] = None,
) -> DatabaseCheck:
    """Create a new database atomically, or validate an existing DB read-only."""
    path = _validate_database_path(Path(db_path))
    if path.exists():
        return check_database_read_only(path, migrations_dir)

    path.parent.mkdir(parents=True, exist_ok=True)
    path = _validate_database_path(path)
    if path.exists():
        return check_database_read_only(path, migrations_dir)

    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".bootstrap.tmp", dir=path.parent
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        manager = SQLiteConnectionManager(temp_path)
        migration_path = migrations_dir or Path(__file__).resolve().parent / "migrations"
        MigrationManager(manager, Path(migration_path)).migrate()
        temp_check = check_database_read_only(temp_path, migrations_dir)
        try:
            # Same-directory hard-link publication is atomic and fails if target exists.
            os.link(temp_path, path)
        except FileExistsError:
            return check_database_read_only(path, migrations_dir)
        return replace(temp_check, path=path)
    except DatabaseBootstrapError:
        raise
    except Exception as exc:
        raise DatabaseBootstrapError(f"Production database bootstrap failed: {exc}") from exc
    finally:
        for candidate in (temp_path, Path(str(temp_path) + "-wal"), Path(str(temp_path) + "-shm")):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from .connection import SQLiteConnectionManager, transaction_immediate


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


class MigrationManager:
    def __init__(self, manager: SQLiteConnectionManager, migrations_dir: Path) -> None:
        self.manager = manager
        self.migrations_dir = Path(migrations_dir)

    def load_migrations(self) -> List[Migration]:
        migrations: List[Migration] = []
        for path in sorted(self.migrations_dir.glob("*.sql")):
            stem = path.stem
            parts = stem.split("__", 1)
            if len(parts) != 2:
                continue
            version = int(parts[0])
            name = parts[1]
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            migrations.append(Migration(version=version, name=name, sql=sql, checksum=checksum))
        return migrations

    def _ensure_migration_table(self) -> None:
        with self.manager.open() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                """
            )
            conn.commit()

    def get_applied_versions(self) -> dict[int, str]:
        self._ensure_migration_table()
        with self.manager.open() as conn:
            rows = conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY version").fetchall()
        return {int(row["version"]): str(row["checksum"]) for row in rows}

    def migrate(self) -> List[int]:
        self._ensure_migration_table()
        migrations = self.load_migrations()
        applied = self.get_applied_versions()
        executed: List[int] = []

        for migration in migrations:
            if migration.version in applied:
                if applied[migration.version] != migration.checksum:
                    raise ValueError(
                        f"Migration checksum mismatch for version {migration.version}: "
                        f"expected {applied[migration.version]} got {migration.checksum}"
                    )
                continue
            with self.manager.open() as conn:
                foreign_keys_were_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
                rebuilds_referenced_table = "-- nexora:foreign_keys_off" in migration.sql
                if rebuilds_referenced_table:
                    # SQLite cannot toggle FK enforcement inside a transaction.
                    # This opt-in is for atomic table rebuilds only; check all
                    # foreign keys before commit and restore enforcement below.
                    conn.execute("PRAGMA foreign_keys=OFF")
                try:
                    with transaction_immediate(conn):
                        # executescript() issues an implicit COMMIT before running,
                        # which breaks schema + version row atomicity.
                        self._execute_statements(conn, migration.sql)
                        conn.execute(
                            "INSERT INTO schema_migrations(version,name,checksum) VALUES(?,?,?)",
                            (migration.version, migration.name, migration.checksum),
                        )
                        if rebuilds_referenced_table:
                            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                            if violations:
                                raise sqlite3.IntegrityError(
                                    f"Foreign key violations after migration {migration.version}: {len(violations)}"
                                )
                finally:
                    if rebuilds_referenced_table and foreign_keys_were_enabled:
                        conn.execute("PRAGMA foreign_keys=ON")
            executed.append(migration.version)
        return executed

    @staticmethod
    def _execute_statements(conn: sqlite3.Connection, sql: str) -> None:
        """Execute a migration without leaving the caller's transaction."""
        statement = ""
        for line in sql.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                if statement.strip():
                    conn.execute(statement)
                statement = ""
        if statement.strip():
            raise ValueError("Incomplete SQL statement in migration")

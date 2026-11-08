from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from nexora_state_db.config import PROJECT_ROOT, PRODUCTION_DATABASE_PATH
from nexora_state_db.production_bootstrap import (
    DatabaseBootstrapError,
    REQUIRED_INDEXES,
    REQUIRED_TABLES,
    bootstrap_production_database,
    check_database_read_only,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_production_path_is_absolute_and_project_root_based() -> None:
    assert PRODUCTION_DATABASE_PATH.is_absolute()
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert PRODUCTION_DATABASE_PATH == PROJECT_ROOT / "database" / "nexora_state.db"


def test_bootstrap_empty_database_has_full_schema_and_pragmas(tmp_path: Path) -> None:
    db_path = tmp_path / "database" / "nexora_state.db"
    result = bootstrap_production_database(db_path)
    assert result.path == db_path.resolve()
    assert db_path.is_file()
    # schema now ships migration 005 (dual-target training jobs) -> version 5
    assert result.schema_version == 5
    assert result.integrity == "ok"
    assert result.journal_mode == "wal"
    assert result.foreign_keys
    assert result.synchronous_full
    assert result.busy_timeout_ms == 10_000
    assert REQUIRED_TABLES.issubset(result.tables)
    assert REQUIRED_INDEXES.issubset(result.indexes)


def test_second_bootstrap_is_idempotent_and_does_not_change_file(tmp_path: Path) -> None:
    db_path = tmp_path / "database" / "nexora_state.db"
    first = bootstrap_production_database(db_path)
    digest_before = _sha256(db_path)
    second = bootstrap_production_database(db_path)
    assert second.schema_version == first.schema_version
    assert _sha256(db_path) == digest_before


def test_read_only_check_and_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    bootstrap_production_database(db_path)
    checked = check_database_read_only(db_path)
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == checked.schema_version
    finally:
        conn.close()
    assert check_database_read_only(db_path).integrity == "ok"


def test_incompatible_existing_database_rejected_without_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "incompatible.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE unrelated(value TEXT)")
    conn.commit()
    conn.close()
    digest_before = _sha256(db_path)
    with pytest.raises(DatabaseBootstrapError, match="schema_migrations"):
        bootstrap_production_database(db_path)
    assert _sha256(db_path) == digest_before


def test_failed_bootstrap_leaves_no_partial_database(tmp_path: Path) -> None:
    db_path = tmp_path / "database" / "state.db"
    migration_dir = tmp_path / "broken_migrations"
    migration_dir.mkdir()
    (migration_dir / "001__broken.sql").write_text(
        "CREATE TABLE partial_schema(value TEXT);\nSELECT * FROM missing_table;\n", encoding="utf-8"
    )
    with pytest.raises(DatabaseBootstrapError, match="bootstrap failed"):
        bootstrap_production_database(db_path, migration_dir)
    assert not db_path.exists()
    assert list(db_path.parent.glob(".*.bootstrap.tmp")) == []
    assert list(db_path.parent.glob("*.bootstrap.tmp-wal")) == []


def test_database_in_dropbox_path_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Dropbox" / "nexora_state.db"
    with pytest.raises(DatabaseBootstrapError, match="Dropbox"):
        bootstrap_production_database(path)
    assert not path.exists()

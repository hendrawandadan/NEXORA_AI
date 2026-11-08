import hashlib
import sqlite3
from contextlib import closing

import pytest

from nexora_dashboard import config
from nexora_dashboard.database import (
    QueryRejected,
    connect_readonly,
    execute_readonly,
    schema_snapshot,
    validate_query,
)


@pytest.fixture
def dashboard_db(tmp_path, monkeypatch):
    path = tmp_path / "nexora_test.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT);
        INSERT INTO schema_migrations VALUES(2, 'test-fixture', 'fixture', '2026-01-01');
        CREATE TABLE datasets(id INTEGER PRIMARY KEY, symbol TEXT, timeframe TEXT, source_path TEXT,
            content_sha256 TEXT, time_start TEXT, time_end TEXT, created_at TEXT);
        CREATE TABLE training_jobs(id INTEGER PRIMARY KEY, job_key TEXT, scope TEXT, symbol TEXT,
            timeframe TEXT, horizon INTEGER, status TEXT, config_json TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE training_job_datasets(job_id INTEGER, dataset_id INTEGER, role TEXT);
        CREATE TABLE training_runs(id INTEGER PRIMARY KEY, job_id INTEGER, run_uid TEXT, status TEXT,
            started_at TEXT, ended_at TEXT, error_message TEXT, created_at TEXT);
        CREATE TABLE checkpoints(id INTEGER PRIMARY KEY, run_id INTEGER, checkpoint_status TEXT,
            changed_at TEXT, metadata_json TEXT);
        CREATE TABLE model_artifacts(id INTEGER PRIMARY KEY, run_id INTEGER, artifact_path TEXT,
            sha256 TEXT, lifecycle_status TEXT, created_at TEXT);
        CREATE TABLE validation_results(id INTEGER PRIMARY KEY, run_id INTEGER, validation_type TEXT,
            passed INTEGER, details_json TEXT, created_at TEXT);
        CREATE TABLE strategy_experiments(id INTEGER PRIMARY KEY, experiment_key TEXT, result_json TEXT);
        CREATE TABLE audit_logs(id INTEGER PRIMARY KEY, entity_type TEXT, entity_id TEXT, action TEXT,
            payload_json TEXT, created_at TEXT);
        CREATE TABLE legacy_imports(id INTEGER PRIMARY KEY, source_name TEXT, source_path TEXT, status TEXT);
        CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT);
    """)
    conn.executemany("INSERT INTO sample(value) VALUES(?)", [(str(i),) for i in range(1201)])
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DATABASE_PATH", path)
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_connection_is_readonly_and_does_not_change_fixture(dashboard_db):
    before = digest(dashboard_db)
    with closing(connect_readonly()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1201
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO sample(value) VALUES('blocked')")
    assert digest(dashboard_db) == before


def test_missing_database_is_not_created(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(config, "DATABASE_PATH", missing)
    with pytest.raises(FileNotFoundError):
        connect_readonly()
    assert not missing.exists()


@pytest.mark.parametrize("sql", [
    "INSERT INTO sample VALUES(1,'x')", "UPDATE sample SET value='x'", "DELETE FROM sample",
    "DROP TABLE sample", "ALTER TABLE sample ADD COLUMN x", "CREATE TABLE x(a)",
    "REPLACE INTO sample VALUES(1,'x')", "ATTACH DATABASE 'x' AS x", "DETACH DATABASE x",
    "VACUUM", "REINDEX", "PRAGMA journal_mode=WAL", "PRAGMA foreign_keys=OFF",
    "PRAGMA writable_schema=ON", "PRAGMA user_version=3",
])
def test_mutations_are_rejected(dashboard_db, sql):
    with pytest.raises(QueryRejected):
        execute_readonly(sql)


def test_multiple_statements_rejected_by_sqlite(dashboard_db):
    with pytest.raises(sqlite3.ProgrammingError):
        execute_readonly("SELECT 1; SELECT 2")


def test_select_explain_and_readonly_pragma_work(dashboard_db):
    columns, rows, truncated = execute_readonly("SELECT value FROM sample WHERE id = 1")
    assert columns == ["value"] and rows == [("0",)] and not truncated
    columns, rows, _ = execute_readonly("EXPLAIN QUERY PLAN SELECT * FROM sample")
    assert columns and rows
    columns, rows, _ = execute_readonly("PRAGMA table_info(sample)")
    assert rows and "name" in columns
    columns, rows, _ = execute_readonly("PRAGMA user_version")
    assert columns and rows


def test_result_limit_and_schema_discovery(dashboard_db):
    columns, rows, truncated = execute_readonly(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<1201) SELECT x FROM n")
    assert len(rows) == 1000 and truncated
    schema = schema_snapshot()
    assert schema["schema_version"] == 2
    assert set(schema["tables"]) == {"schema_migrations", "datasets", "training_jobs",
        "training_job_datasets", "training_runs", "checkpoints", "model_artifacts",
        "validation_results", "strategy_experiments", "audit_logs", "legacy_imports", "sample"}
    assert "content_sha256" in {field["name"] for field in schema["columns"]["datasets"]}


def test_database_path_is_not_user_selectable(tmp_path, dashboard_db):
    other = tmp_path / "elsewhere.db"
    sqlite3.connect(other).close()
    with pytest.raises(ValueError):
        connect_readonly(other)


def test_query_timeout_is_enforced(dashboard_db):
    query = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT x FROM n"
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        execute_readonly(query, timeout_seconds=0)


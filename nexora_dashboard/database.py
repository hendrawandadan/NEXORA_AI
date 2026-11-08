"""Read-only access and a defensive SQL Explorer for the production database."""
from __future__ import annotations

import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import MAX_ROWS, QUERY_TIMEOUT_SECONDS, validated_database_path

READONLY_PRAGMAS = {
    "application_id", "compile_options", "foreign_key_check", "foreign_key_list",
    "index_info", "index_list", "index_xinfo", "integrity_check", "quick_check",
    "schema_version", "table_info", "table_list", "table_xinfo", "user_version",
}
_FIRST_TOKEN = re.compile(r"^\s*(?:--[^\n]*(?:\n|$)|/\*.*?\*/\s*)*(\w+)", re.S)
_PRAGMA = re.compile(
    r"^\s*PRAGMA\s+(?:main\s*\.\s*)?([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*\(\s*([A-Za-z_][A-Za-z0-9_$]*|\"(?:\"\"|[^\"])+\"|'(?:''|[^'])*'|`[^`]+`|\[[^]]+\])\s*\))?\s*$",
    re.I | re.S,
)
_PRAGMA_WITH_ARGUMENT = {"foreign_key_check", "foreign_key_list", "index_info", "index_list",
                        "index_xinfo", "table_info", "table_xinfo"}


class QueryRejected(ValueError):
    """A statement falls outside the read-only SQL Explorer subset."""


def connect_readonly(path: Path | None = None) -> sqlite3.Connection:
    """Open only the fixed production path using SQLite URI mode=ro."""
    configured = validated_database_path()
    if path is not None and Path(path).resolve(strict=True) != configured:
        raise ValueError("Database path is fixed by application configuration")
    conn = sqlite3.connect(configured.as_uri() + "?mode=ro", uri=True,
                           timeout=1.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(False)
    conn.set_authorizer(_readonly_authorizer)
    return conn


def _readonly_authorizer(action: int, arg1: str | None, arg2: str | None,
                         database: str | None, source: str | None) -> int:
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    if hasattr(sqlite3, "SQLITE_RECURSIVE"):
        allowed.add(sqlite3.SQLITE_RECURSIVE)
    if action == sqlite3.SQLITE_PRAGMA:
        name = (arg1 or "").lower()
        safe_arg = arg2 is None or (name in _PRAGMA_WITH_ARGUMENT and bool(arg2))
        return sqlite3.SQLITE_OK if name in READONLY_PRAGMAS and safe_arg else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def validate_query(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip() or "\x00" in sql:
        raise QueryRejected("Enter a read-only SQL query")
    match = _FIRST_TOKEN.match(sql)
    first = match.group(1).upper() if match else ""
    if first == "PRAGMA":
        pragma = _PRAGMA.fullmatch(sql)
        if not pragma or pragma.group(1).lower() not in READONLY_PRAGMAS:
            raise QueryRejected("This PRAGMA is not on the read-only allowlist")
        return sql
    if first == "EXPLAIN":
        explain = re.match(r"^\s*EXPLAIN\s+QUERY\s+PLAN\b", sql, re.I)
        inner = _FIRST_TOKEN.match(sql[explain.end():]) if explain else None
        if not inner or inner.group(1).upper() not in {"SELECT", "WITH"}:
            raise QueryRejected("Only EXPLAIN QUERY PLAN for a SELECT is allowed")
        return sql
    if first not in {"SELECT", "WITH"}:
        raise QueryRejected("Only SELECT, EXPLAIN QUERY PLAN, and allowlisted read-only PRAGMA are allowed")
    return sql


def execute_readonly(sql: str, *, max_rows: int = MAX_ROWS,
                     timeout_seconds: float = QUERY_TIMEOUT_SECONDS) -> tuple[list[str], list[tuple[Any, ...]], bool]:
    """Execute one allowed statement with an authorizer, deadline, and hard row cap."""
    statement = validate_query(sql)
    cap = min(max(int(max_rows), 1), MAX_ROWS)
    started = time.monotonic()
    with closing(connect_readonly()) as conn:
        def progress() -> int:
            return int(time.monotonic() - started > timeout_seconds)
        conn.set_progress_handler(progress, 1000)
        cursor = conn.execute(statement)  # sqlite3 rejects multiple statements here
        columns = [column[0] for column in (cursor.description or [])]
        rows = cursor.fetchmany(cap + 1)
        return columns, [tuple(row) for row in rows[:cap]], len(rows) > cap


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def schema_snapshot(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    own = conn is None
    db = conn or connect_readonly()
    try:
        objects = db.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables = [row["name"] for row in objects if row["type"] == "table"]
        columns = {
            table: [dict(row) for row in db.execute(f"PRAGMA table_info({quote_identifier(table)})")]
            for table in tables
        }
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0]
                  for table in tables}
        index_count = sum(len(db.execute(f"PRAGMA index_list({quote_identifier(table)})").fetchall())
                          for table in tables)
        version = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] \
            if "schema_migrations" in tables else None
        return {"objects": [dict(row) for row in objects], "tables": tables,
                "columns": columns, "counts": counts, "schema_version": version,
                "index_count": index_count}
    finally:
        if own:
            db.close()


def table_rows(table: str, *, search: str = "", limit: int = MAX_ROWS,
               offset: int = 0, filters: dict[str, list[str]] | None = None) -> tuple[list[str], list[tuple[Any, ...]], int]:
    schema = schema_snapshot()
    if table not in schema["tables"]:
        raise ValueError("Unknown table")
    names = [field["name"] for field in schema["columns"][table]]
    where, params = "", []
    if search.strip() and names:
        where = " WHERE (" + " OR ".join(
            f"CAST({quote_identifier(name)} AS TEXT) LIKE ?" for name in names) + ")"
        params = [f"%{search.strip()}%"] * len(names)
    for column, values in (filters or {}).items():
        if column not in names or not values:
            continue
        where += (" AND " if where else " WHERE ") + f"{quote_identifier(column)} IN ({','.join('?' for _ in values)})"
        params.extend(values)
    take = min(max(int(limit), 1), MAX_ROWS)
    with closing(connect_readonly()) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}{where}", params).fetchone()[0]
        if table == "audit_logs" and "created_at" in names:
            order = " ORDER BY \"created_at\" DESC"
        elif table == "checkpoints" and "changed_at" in names:
            order = " ORDER BY \"changed_at\" ASC"
        else:
            order = ""
        rows = conn.execute(f"SELECT * FROM {quote_identifier(table)}{where}{order} LIMIT ? OFFSET ?",
                            (*params, take, max(0, int(offset)))).fetchall()
    return names, [tuple(row) for row in rows], total

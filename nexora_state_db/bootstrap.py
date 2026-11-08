from __future__ import annotations

from pathlib import Path

from .connection import SQLiteConnectionManager
from .migrations import MigrationManager


def create_dev_database(db_path: Path) -> SQLiteConnectionManager:
    manager = SQLiteConnectionManager(db_path=db_path)
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    MigrationManager(manager=manager, migrations_dir=migrations_dir).migrate()
    return manager

"""Explicit command-line entry points for production database bootstrap/check."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PRODUCTION_DATABASE_PATH
from .production_bootstrap import (
    DatabaseBootstrapError,
    bootstrap_production_database,
    check_database_read_only,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nexora_state_db")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("bootstrap", "check"):
        command = commands.add_parser(name)
        command.add_argument("--database-path", type=Path, default=PRODUCTION_DATABASE_PATH)
    args = parser.parse_args(argv)
    try:
        result = (
            bootstrap_production_database(args.database_path)
            if args.command == "bootstrap"
            else check_database_read_only(args.database_path)
        )
    except DatabaseBootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"database_path={result.path}")
    print(f"schema_version={result.schema_version}")
    print(f"integrity_check={result.integrity}")
    print(f"journal_mode={result.journal_mode}")
    print(f"foreign_keys={int(result.foreign_keys)}")
    print(f"synchronous_full={int(result.synchronous_full)}")
    print(f"busy_timeout_ms={result.busy_timeout_ms}")
    print(f"tables={len(result.tables)}")
    print(f"indexes={len(result.indexes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Central paths for the NEXORA AI state database."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIRECTORY = PROJECT_ROOT / "database"
PRODUCTION_DATABASE_PATH = DATABASE_DIRECTORY / "nexora_state.db"

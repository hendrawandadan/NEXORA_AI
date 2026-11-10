"""Central paths for the NEXORA research database (SEPARATE from production)."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIRECTORY = PROJECT_ROOT / "database"

# Deliberately distinct from the production DB (database/nexora_state.db) so the
# autonomous research loop can never write into production state.
RESEARCH_DATABASE_PATH = DATABASE_DIRECTORY / "nexora_research.db"
RESEARCH_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

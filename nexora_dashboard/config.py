"""Fixed, validated locations for the local NEXORA database dashboard."""
import os
from pathlib import Path

from nexora_state_db.config import PRODUCTION_DATABASE_PATH

# The dashboard must point at exactly one database. It defaults to the
# project-relative production path (portable across machines) and may be
# overridden explicitly with NEXORA_DATABASE_PATH. There is no UI control that
# can redirect it at runtime.
_ENV_OVERRIDE = os.environ.get("NEXORA_DATABASE_PATH")
DATABASE_PATH = Path(_ENV_OVERRIDE) if _ENV_OVERRIDE else PRODUCTION_DATABASE_PATH
BIND_ADDRESS = "127.0.0.1"
PORT = 8501
MAX_ROWS = 1000
QUERY_TIMEOUT_SECONDS = 5.0


def validated_database_path() -> Path:
    """Return the sole configured DB path; fail closed if it is missing or redirected."""
    expected = DATABASE_PATH.resolve(strict=True)
    if not expected.is_file() or expected != DATABASE_PATH.absolute():
        raise FileNotFoundError("Configured NEXORA database is unavailable")
    return expected

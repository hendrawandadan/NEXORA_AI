"""Configuration for NEXORA External Information Intelligence V1.

Centralises the ISOLATED database path, operating-mode flags and network/timeout
defaults. All operating-mode flags default to the safe (dry) values, per the
project's operating mode. These flags are read-only *intent* markers: the system
never trains / promotes / trades automatically regardless of what is set here --
those actions are gated elsewhere and are out of scope for this module.

IMPORTANT path rule: the external-intelligence DB is a freshly created file
``database/nexora_external_intel.db``. It is deliberately a different path from
both the production DB (``nexora_state.db``) and the research DB
(``nexora_research.db``) so accidental cross-contamination is impossible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_DIRECTORY = PROJECT_ROOT / "database"

SYSTEM_NAME = "NEXORA_EXTERNAL_INFORMATION_INTELLIGENCE"
SYSTEM_VERSION = "V1"

# A SEPARATE, isolated database. Never nexora_state.db, never nexora_research.db.
EXTERNAL_INTEL_DB_PATH = DATABASE_DIRECTORY / "nexora_external_intel.db"
EXTERNAL_INTEL_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Forbidden production path (defence-in-depth: assert we never touch it).
PRODUCTION_DB_PATH = DATABASE_DIRECTORY / "nexora_state.db"
RESEARCH_DB_PATH = DATABASE_DIRECTORY / "nexora_research.db"


@dataclass(frozen=True)
class ExternalIntelConfig:
    """Immutable operating configuration (safe defaults = DRY / no side-effects)."""

    # ---- Operating mode (all SAFE by default) --------------------------------
    dry_run: bool = True
    production_access: bool = False
    model_training: bool = False
    model_promotion: bool = False
    live_trading: bool = False
    auto_reopen: bool = False

    # ---- Network / robustness ------------------------------------------------
    request_timeout_s: float = 10.0
    max_retries: int = 2
    retry_backoff_s: float = 0.5
    rate_limit_per_min: int = 30             # conservative default per provider
    user_agent: str = "NEXORA-ExternalIntel/1.0 (+research; non-trading)"

    # ---- Data-quality thresholds --------------------------------------------
    max_event_staleness_hours: float = 24.0  # freshness bound for "current" events
    timestamp_past_tolerance_days: float = 3650.0   # reject absurdly old/future
    timestamp_future_tolerance_days: float = 365.0

    # ---- Cross-market analysis defaults -------------------------------------
    rolling_correlation_window: int = 60
    lead_lag_max_lag: int = 10
    min_observations: int = 30               # refuse correlation below this

    # ---- Event-response horizons (post-release windows) ---------------------
    response_horizons: tuple = (
        ("1m", 1), ("5m", 5), ("15m", 15), ("30m", 30),
        ("1h", 60), ("4h", 240), ("1d", 1440),
    )

    # ---- Allowed proxy environment keys (secrets stay in env, never stored) --
    secrets_env_allowlist: tuple = field(default_factory=lambda: (
        "NEXORA_FRED_API_KEY",
        "NEXORA_TRADINGECONOMICS_KEY",
        "NEXORA_NEWSAPI_KEY",
    ))

    def as_public_dict(self) -> dict:
        """Serialize WITHOUT any secret material (there is none stored here)."""
        return {
            "system_name": SYSTEM_NAME,
            "system_version": SYSTEM_VERSION,
            "dry_run": self.dry_run,
            "production_access": self.production_access,
            "model_training": self.model_training,
            "model_promotion": self.model_promotion,
            "live_trading": self.live_trading,
            "auto_reopen": self.auto_reopen,
            "request_timeout_s": self.request_timeout_s,
            "max_retries": self.max_retries,
            "rate_limit_per_min": self.rate_limit_per_min,
        }


DEFAULT_CONFIG = ExternalIntelConfig()


def read_secret(env_key: str, config: ExternalIntelConfig = DEFAULT_CONFIG) -> str | None:
    """Read a secret strictly from the environment.

    Returns ``None`` if the key is not allowlisted or not set. Never reads from a
    file, never logs the value. This is the ONLY sanctioned secret channel.
    """
    if env_key not in config.secrets_env_allowlist:
        raise ValueError(f"secret env key not allowlisted: {env_key}")
    val = os.environ.get(env_key)
    return val if val else None


def has_secret(env_key: str, config: ExternalIntelConfig = DEFAULT_CONFIG) -> bool:
    try:
        return read_secret(env_key, config) is not None
    except ValueError:
        return False

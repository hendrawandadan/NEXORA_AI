"""NEXORA EXTERNAL INFORMATION INTELLIGENCE V1.

Autonomous fundamental & global-market knowledge discovery, kept STRICTLY isolated
from production. This package:

  * discovers and categorises external information SOURCES (official / financial
    data / news) that can inform the market (macro, central-bank policy, news,
    cross-market relationships),
  * normalises economic events, central-bank documents and news into an
    append-only, provenance-tagged, content-hashed EXTERNAL KNOWLEDGE REPOSITORY
    (a SEPARATE SQLite DB -- never ``nexora_state.db``),
  * produces evidence-grounded FUNDAMENTAL interpretations (never invented values),
  * studies CROSS-MARKET relationships (correlation != causation),
  * links external events to measurable MARKET RESPONSE (leakage-aware),
  * and proposes NEW-INFORMATION research hypotheses routed through the existing
    Tahap-C registry + governance gates (``INFO_ACQUISITION`` lane only).

HARD INVARIANTS (enforced and tested):
  * DRY_RUN default; no training, no promotion, no live trading, no auto-reopen.
  * Never reads or writes the production DB (``nexora_state.db``).
  * The Price-Derived Research Lane remains SUSPENDED (NEXORA-GOV-PRD-001); this
    system cannot reopen, bypass, or launder experiments through it.
  * External content is treated as UNTRUSTED DATA -- never executed as commands.
  * Secrets come from environment variables only; never logged or persisted.

Nothing here claims predictive edge. Building a connector or an interpretation
engine is NOT evidence of an edge; the honest status is reported separately.
"""

from .config import (  # noqa: F401
    ExternalIntelConfig,
    DEFAULT_CONFIG,
    EXTERNAL_INTEL_DB_PATH,
    EXTERNAL_INTEL_MIGRATIONS_DIR,
    SYSTEM_NAME,
    SYSTEM_VERSION,
)
from . import (  # noqa: F401
    source_registry,
    connectors,
    repository,
    fundamental_intelligence,
    central_bank_intelligence,
    news_intelligence,
    cross_market_intelligence,
    event_response,
    new_information,
    research_bridge,
    asof,
)

__all__ = [
    "ExternalIntelConfig",
    "DEFAULT_CONFIG",
    "EXTERNAL_INTEL_DB_PATH",
    "EXTERNAL_INTEL_MIGRATIONS_DIR",
    "SYSTEM_NAME",
    "SYSTEM_VERSION",
    "source_registry",
    "connectors",
    "repository",
    "fundamental_intelligence",
    "central_bank_intelligence",
    "news_intelligence",
    "cross_market_intelligence",
    "event_response",
    "new_information",
    "research_bridge",
    "orchestrator",
    "repository",
    "ExternalKnowledgeRepository",
]
from .repository import ExternalKnowledgeRepository  # noqa: E402,F401

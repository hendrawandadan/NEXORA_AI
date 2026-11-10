"""NEXORA — Autonomous Research Architecture (research state, isolated).

Read-only with respect to PRODUCTION data/DB/model/reports. This package owns a
SEPARATE research database (``database/nexora_research.db``) that records the
knowledge-memory artefacts of the autonomous research loop:

    hypotheses      -> pre-registered, hashed, immutable in content
    experiments     -> deterministic specs bound to a hypothesis (hashed)
    evaluations     -> net-of-cost results + verdict + bootstrap CI
    failures        -> structured failure classification + evidence
    knowledge       -> immutable, versioned knowledge entries (no overwrite)

Nothing here trains a model, touches production state, or enforces a profit claim.
It is the durable MEMORY the loop reads/writes; decisions live elsewhere.
"""

from .config import RESEARCH_DATABASE_PATH, RESEARCH_MIGRATIONS_DIR  # noqa: F401
from . import store, failure_learning, knowledge_query, hypothesis_generator, registry  # noqa: F401
from . import control_loop, strategy_evolution  # noqa: F401
from . import external_intelligence  # noqa: F401  (INFO_ACQUISITION lane; wired into control_loop)

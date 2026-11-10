"""Hard isolation guarantee: a full run must never modify production or research DBs."""

import hashlib
from pathlib import Path

from nexora_research.external_intelligence import orchestrator
from nexora_research.external_intelligence.config import PRODUCTION_DB_PATH, RESEARCH_DB_PATH


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def test_production_and_research_db_untouched_by_run(repo):
    """Capture engine hashes; run the pipeline; assert DB files are byte-identical."""
    # We only compare the main .db files (WAL sidecars are produced by live connections
    # of OTHER processes and are irrelevant to our isolation because we never open them).
    prod_before = _sha(PRODUCTION_DB_PATH)
    res_before = _sha(RESEARCH_DB_PATH)

    events = [{
        "event_type": "CPI", "country": "US", "currency": "USD",
        "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": 3.1,
        "previous": 3.2, "source_provider": "mock", "source_ref": "mock://cpi",
        "retrieved_at_utc": "2026-01-15T13:35:00Z",
    }]
    orchestrator.run_intelligence(instrument="EURUSD", repo=repo, events=events,
                                  record_raw_snapshot=False)

    assert _sha(PRODUCTION_DB_PATH) == prod_before, "production DB was modified!"
    assert _sha(RESEARCH_DB_PATH) == res_before, "research DB was modified!"


def test_external_repo_path_is_isolated(repo):
    assert repo.db_path != PRODUCTION_DB_PATH
    assert repo.db_path != RESEARCH_DB_PATH
    assert repo.db_path.name == "ext.db"  # tmp fixture name

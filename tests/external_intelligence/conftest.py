"""Shared fixtures for external-intelligence tests (isolated temp DBs, mock)."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
from nexora_research.external_intelligence.config import ExternalIntelConfig


@pytest.fixture
def repo(tmp_path):
    return ExternalKnowledgeRepository(tmp_path / "ext.db", bootstrap=True)


@pytest.fixture
def config():
    return ExternalIntelConfig()


@pytest.fixture
def sample_event():
    return {
        "event_type": "CPI", "country": "US", "currency": "USD", "economic_domain": "INFLATION",
        "importance": "HIGH", "period": "2026-01",
        "scheduled_ts": "2026-01-15T13:30:00Z",
        "actual": 3.4, "forecast": 3.1, "previous": 3.2, "revised_previous": None,
        "source_provider": "mock", "source_ref": "mock://cpi", "retrieved_at_utc": "2026-01-15T13:35:00Z",
    }

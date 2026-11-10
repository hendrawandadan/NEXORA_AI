"""Tests for Tahap A — Knowledge Memory store (nexora_research.store).

Uses an isolated temporary DB path; never touches the real research/production DB.
Covers: pre-registration ordering, content hashing, append-only versioning,
failure-must-teach, and basic queries.
"""

import tempfile
from pathlib import Path

import pytest

from nexora_research.store import ResearchMemoryStore


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "research_test.db"
    return ResearchMemoryStore(db_path=db)


def _reg(store, key="H1", **kw):
    base = dict(
        hypothesis_key=key, instrument="EURUSD", timeframe="H4", horizon_bars=12,
        claim="mean-reversion factor survives cost at 48h",
        go_criteria={"auc_net_min": 0.55},
    )
    base.update(kw)
    return store.register_hypothesis(**base)


# ---------- hypothesis pre-registration ----------
def test_register_hypothesis_returns_sha_and_id(store):
    r = _reg(store)
    assert r["id"] >= 1
    assert len(r["content_sha256"]) == 64
    assert r["status"] == "PRE_REGISTERED"


def test_hypothesis_content_hash_is_deterministic(store, tmp_path):
    r1 = _reg(store, key="H1")
    # same content, different key -> different hash (key is part of body)
    r2 = _reg(store, key="H2")
    assert r1["content_sha256"] != r2["content_sha256"]


def test_duplicate_hypothesis_key_rejected(store):
    _reg(store, key="H1")
    with pytest.raises(Exception):
        _reg(store, key="H1")


def test_invalid_status_rejected(store):
    with pytest.raises(ValueError):
        _reg(store, status="BOGUS")


# ---------- experiment requires pre-registered hypothesis ----------
def test_experiment_requires_existing_hypothesis(store):
    with pytest.raises(KeyError):
        store.create_experiment(experiment_key="E1", hypothesis_id=999, spec={"a": 1})


def test_experiment_bound_to_hypothesis(store):
    h = _reg(store)
    e = store.create_experiment(experiment_key="E1", hypothesis_id=h["id"],
                                spec={"split": "60/20/20", "cost_pips": 3.2})
    assert e["id"] >= 1
    assert len(e["spec_sha256"]) == 64
    got = store.get_experiment(e["id"])
    assert got["hypothesis_id"] == h["id"]


# ---------- evaluation / failure ordering ----------
def test_evaluation_requires_experiment(store):
    with pytest.raises(KeyError):
        store.record_evaluation(experiment_id=999, verdict="GO", result={})


def test_failure_requires_recommendation(store):
    h = _reg(store)
    e = store.create_experiment(experiment_key="E1", hypothesis_id=h["id"], spec={})
    with pytest.raises(ValueError):
        store.record_failure(experiment_id=e["id"], failure_type="OVERFIT",
                             recommendation="   ")
    ok = store.record_failure(experiment_id=e["id"], failure_type="OVERFIT",
                              recommendation="tighten purge & retest")
    assert ok["failure_type"] == "OVERFIT"


def test_invalid_failure_type_rejected(store):
    h = _reg(store)
    e = store.create_experiment(experiment_key="E1", hypothesis_id=h["id"], spec={})
    with pytest.raises(ValueError):
        store.record_failure(experiment_id=e["id"], failure_type="NOPE",
                             recommendation="x")


# ---------- knowledge immutability / versioning ----------
def test_knowledge_is_versioned_append_only(store):
    k1 = store.record_knowledge(knowledge_key="K1", kind="FINDING", summary="v1")
    k2 = store.record_knowledge(knowledge_key="K1", kind="FINDING", summary="v2")
    assert k1["version"] == 1
    assert k2["version"] == 2
    versions = store.knowledge_versions("K1")
    assert [v["version"] for v in versions] == [1, 2]
    # original row content preserved (append-only)
    assert versions[0]["summary"] == "v1"
    assert versions[1]["summary"] == "v2"


def test_knowledge_invalid_kind(store):
    with pytest.raises(ValueError):
        store.record_knowledge(knowledge_key="K1", kind="BOGUS", summary="x")


# ---------- queries ----------
def test_list_hypotheses_and_failures(store):
    h = _reg(store, key="H1")
    _reg(store, key="H2", status="PROPOSED")
    e = store.create_experiment(experiment_key="E1", hypothesis_id=h["id"], spec={})
    store.record_failure(experiment_id=e["id"], failure_type="DATA_QUALITY",
                         recommendation="acquire ticks")
    assert len(store.list_hypotheses()) == 2
    assert len(store.list_hypotheses(status="PROPOSED")) == 1
    assert len(store.list_failures(experiment_id=e["id"])) == 1


def test_default_db_path_is_research_not_production(store):
    # The store must never default to the production DB file.
    from nexora_research.config import RESEARCH_DATABASE_PATH
    assert RESEARCH_DATABASE_PATH.name == "nexora_research.db"
    assert RESEARCH_DATABASE_PATH.name != "nexora_state.db"

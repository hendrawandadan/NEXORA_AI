"""PREP-001 dual-target contract and isolation tests.

SAFETY: all tests use synthetic in-memory fixtures or temporary SQLite DBs.
No training (no model.fit), no writes to production DB/CSV/model/backup.
"""
from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nexora_learning import targets as T
from nexora_learning import pipeline as P


# ---------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------
def _bars(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1.1 + np.cumsum(rng.normal(0, 1e-4, n))
    # open differs from close so T1/T3 must not coincide
    open_ = close - 1e-5
    ts = pd.date_range("2021-01-01", periods=n, freq="30min")
    return pd.DataFrame({
        "ts": ts, "open": open_, "high": close + 2e-4,
        "low": close - 2e-4, "close": close, "volume": rng.integers(1, 100, n),
    })


# ---------------------------------------------------------------------------------
# 1. T1 formula, exact
# ---------------------------------------------------------------------------------
def test_t1_formula_close_to_close():
    df = _bars(50, seed=1)
    h = 2
    fwd = T.compute_return_t1(df, h)
    close = df["close"].to_numpy()
    assert np.isclose(fwd[0], close[h] / close[0] - 1)
    assert np.isclose(fwd[10], close[10 + h] / close[10] - 1)
    # trailing h labels are unavailable
    assert np.isnan(fwd[-h:]).all()
    assert np.isfinite(fwd[:-h]).all()


def test_t1_binary_label():
    df = _bars(50, seed=2)
    fwd, y = T.compute_target(df, 2, "T1")
    finite = np.isfinite(fwd)
    assert (y[finite] == (fwd[finite] > 0).astype(int)).all()
    assert (y[~finite] == -1).all()  # sentinel, masked out by caller


# ---------------------------------------------------------------------------------
# 2. T3 formula, exact; differs from T1
# ---------------------------------------------------------------------------------
def test_t3_formula_open_to_open_withhplusone():
    df = _bars(50, seed=3)
    h = 2
    fwd = T.compute_return_t3(df, h)
    op = df["open"].to_numpy()
    for t in [0, 5, 20]:
        expected = op[t + 1 + h] / op[t + 1] - 1
        assert np.isclose(fwd[t], expected)
    # last h+1 rows cannot be labelled
    assert np.isnan(fwd[-(h + 1):]).all()
    assert np.isfinite(fwd[: len(df) - (h + 1)]).all()


def test_t3_uses_open_not_close():
    df = _bars(60, seed=4)
    h = 3
    t1 = T.compute_return_t1(df, h)
    t3 = T.compute_return_t3(df, h)
    # They must differ (open != close and different anchor rows)
    assert not np.allclose(t1[: len(df) - (h + 1)], t3[: len(df) - (h + 1)])


def test_t3_effective_horizon_is_h_plus_one():
    h = 2
    assert T.get_target_spec("T1", h).effective_horizon == h
    assert T.get_target_spec("T3", h).effective_horizon == h + 1


# ---------------------------------------------------------------------------------
# 3. Independent masks per target
# ---------------------------------------------------------------------------------
def test_t3_mask_excludes_more_trailing_rows_than_t1():
    from nexora_vision.features import build_features

    df = _bars(3000, seed=5)
    X = build_features(df)
    t1_fwd, _ = T.compute_target(df, 2, "T1")
    t3_fwd, _ = T.compute_target(df, 2, "T3")
    m1 = T.build_target_mask(X, t1_fwd, "T1", 2)
    m3 = T.build_target_mask(X, t3_fwd, "T3", 2)
    # T3 needs one more trailing row than T1 after the feature warmup.
    assert m3.sum() < m1.sum()
    # The masked-region difference is exactly the extra T3 trailing row.
    assert m1.sum() - m3.sum() >= 1


# ---------------------------------------------------------------------------------
# 4. Target version & hashing (≠, deterministic)
# ---------------------------------------------------------------------------------
def test_target_hashes_differ_and_are_deterministic():
    s1 = T.get_target_spec("T1", 2)
    s3 = T.get_target_spec("T3", 2)
    assert s1.target_hash(2) != s3.target_hash(2)
    assert s1.target_hash(2) == T.get_target_spec("T1", 2).target_hash(2)
    assert len(s1.target_hash(2)) == 64


def test_target_hash_changes_with_horizon():
    s = T.get_target_spec("T1", 2)
    assert s.target_hash(2) != s.target_hash(3)


def test_target_definition_version_ids_differ():
    v1 = T.get_target_spec("T1", 2).target_definition_version(2)
    v3 = T.get_target_spec("T3", 2).target_definition_version(2)
    assert v1["id"] != v3["id"]
    assert v1["hash"] != v3["id"]  # sanity


def test_unknown_target_rejected():
    with pytest.raises(ValueError):
        T.get_target_spec("T2", 2)


# ---------------------------------------------------------------------------------
# 5. Purge / embargo, target-aware
# ---------------------------------------------------------------------------------
def test_purge_t3_never_below_h_plus_one():
    assert P.purge_bars(24, "T3") == 25   # > embargo(24), h+1=25
    assert P.purge_bars(48, "T3") == 49   # h+1=49 > 24
    assert P.purge_bars(2, "T3") == 24    # embargo floor
    assert P.purge_bars(2, "T1") == 24


def test_split_embargo_clamped_to_effective_horizon():
    n = 5000
    mask = np.ones(n, dtype=bool)
    tr1, va1, te1 = P.split_indices(mask, 2, 0.6, 0.2, embargo=0, target_type="T1")
    tr3, va3, te3 = P.split_indices(mask, 2, 0.6, 0.2, embargo=0, target_type="T3")
    eligible = np.flatnonzero(mask)
    a = len(tr1)
    # T1 floor = h = 2; T3 floor = h+1 = 3
    assert va1[0] == eligible[a + 2]
    assert va3[0] == eligible[a + 3]


def test_t3_split_labels_never_cross_boundary():
    mask = np.ones(6000, dtype=bool)
    h = 2
    tr, va, te = P.split_indices(mask, h, 0.6, 0.2, embargo=P.purge_bars(24, "T3"), target_type="T3")
    # last train anchor + (h+1) must be strictly before validation start
    assert int(tr[-1]) + (h + 1) < int(va[0])
    assert int(va[-1]) + (h + 1) < int(te[0])


# ---------------------------------------------------------------------------------
# 6. Artifact namespaces isolated (no overwrite)
# ---------------------------------------------------------------------------------
def test_artifact_namespaces_isolated():
    assert P.target_artifact_root("T1") == "t1"
    assert P.target_artifact_root("T3") == "t3"
    assert P.target_artifact_root("T1") != P.target_artifact_root("T3")


def test_experiment_ids_isolated_per_target():
    from nexora_audit import experiment_config as ec

    for cand in "ABC":
        assert ec.experiment_id("T1", cand) != ec.experiment_id("T3", cand)
        assert ec.experiment_id("T1", cand) == f"PREP-001-T1-{cand}"
    idt1 = ec.build_experiment_identity("T1", "B", 2)
    idt3 = ec.build_experiment_identity("T3", "B", 2)
    assert idt1["target_hash"] != idt3["target_hash"]
    assert idt1["experiment_id"] != idt3["experiment_id"]
    assert idt1["artifact_namespace"] == "t1"
    assert idt3["artifact_namespace"] == "t3"


# ---------------------------------------------------------------------------------
# 7. Migration v5: column, backfill, coexistence, dup, invalid, integrity
# ---------------------------------------------------------------------------------
MIGRATIONS = Path(__file__).resolve().parents[1] / "nexora_state_db" / "migrations"


def _migrated_db(tmp_path: Path):
    from nexora_state_db.connection import SQLiteConnectionManager
    from nexora_state_db.migrations import MigrationManager

    manager = SQLiteConnectionManager(tmp_path / "v5.db")
    MigrationManager(manager, MIGRATIONS).migrate()
    return manager


def test_migration_v5_adds_target_type_default_t1(tmp_path):
    manager = _migrated_db(tmp_path)
    with manager.open() as conn:
        assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 5
        cols = {r[1] for r in conn.execute("PRAGMA table_info(training_jobs)")}
        assert "target_type" in cols


def test_migration_v5_legacy_rows_backfill_to_t1(tmp_path):
    # Build a v4 DB with a row, then migrate to v5.
    import shutil
    from nexora_state_db.connection import SQLiteConnectionManager
    from nexora_state_db.migrations import MigrationManager

    v4 = tmp_path / "mig_v4"
    v4.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if int(f.stem.split("__")[0]) <= 4:
            shutil.copy2(f, v4)
    manager = SQLiteConnectionManager(tmp_path / "up.db")
    MigrationManager(manager, v4).migrate()
    with manager.open() as conn:
        jid = conn.execute(
            "INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status) "
            "VALUES('legacy','individual','EURUSD','M30',2,'QUEUED')"
        ).lastrowid
        conn.commit()
    MigrationManager(manager, MIGRATIONS).migrate()
    with manager.open() as conn:
        assert conn.execute("SELECT target_type FROM training_jobs WHERE id=?", (jid,)).fetchone()[0] == "T1"


def test_migration_v5_t1_and_t3_coexist(tmp_path):
    manager = _migrated_db(tmp_path)
    with manager.open() as conn:
        conn.execute(
            "INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status,target_type) "
            "VALUES('t1','individual','EURUSD','M30',2,'PLANNED','T1')"
        )
        conn.execute(
            "INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status,target_type) "
            "VALUES('t3','individual','EURUSD','M30',2,'PLANNED','T3')"
        )
        conn.commit()
        assert conn.execute("SELECT count(*) FROM training_jobs").fetchone()[0] == 2


def test_migration_v5_rejects_duplicate_within_target(tmp_path):
    manager = _migrated_db(tmp_path)
    with manager.open() as conn:
        conn.execute(
            "INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status,target_type) "
            "VALUES('a','individual','EURUSD','M30',2,'PLANNED','T1')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status,target_type) "
                "VALUES('b','individual','EURUSD','M30',2,'PLANNED','T1')"
            )


def test_migration_v5_rejects_invalid_target_type(tmp_path):
    manager = _migrated_db(tmp_path)
    with manager.open() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO training_jobs(job_key,scope,symbol,timeframe,horizon,status,target_type) "
            "VALUES('x','individual','EURUSD','M30',2,'PLANNED','T2')"
        )


def test_migration_v5_preserves_triggers_and_integrity(tmp_path):
    manager = _migrated_db(tmp_path)
    with manager.open() as conn:
        triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert "training_runs_insert_guard" in triggers
        assert "training_jobs_status_transition" in triggers
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# ---------------------------------------------------------------------------------
# 8. Authorization: T1/T3 binding (fail closed)
# ---------------------------------------------------------------------------------
def _auth_row(target_type=None, **extra):
    base = {
        "execution_id": "PREP-001", "batch": "Batch 1",
        "scope": "individual", "symbol": "EURUSD", "timeframe": "M30", "horizon": "2",
    }
    if target_type is not None:
        base["target_type"] = target_type
    base.update(extra)
    return base


def test_authorization_rejects_missing_target_type(tmp_path, monkeypatch):
    # Reuse the full-binding harness from the authorization test module.
    import test_execution_authorization as H
    from nexora_audit.authorization import authorize_execution
    from nexora_audit.safety_probe import probe_crash_recovery, run_claim_and_lifecycle_probes

    monkeypatch.setenv("NEXORA_GOVERNANCE_KEY", "test-key")
    root = H._build_base_root(tmp_path)
    H._write_signoff(root, H._signed_payload(root, candidate="B", sign=True))
    claim, recovery = run_claim_and_lifecycle_probes(), probe_crash_recovery()
    decision = authorize_execution(
        execution_row=_auth_row(target_type=None),  # no target_type
        project_root=root, batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim, recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "TARGET_TYPE_MISSING" in decision.codes()


def test_authorization_rejects_t3_when_signoff_is_t1(tmp_path, monkeypatch):
    import test_execution_authorization as H
    from nexora_audit.authorization import authorize_execution
    from nexora_audit.safety_probe import probe_crash_recovery, run_claim_and_lifecycle_probes

    monkeypatch.setenv("NEXORA_GOVERNANCE_KEY", "test-key")
    root = H._build_base_root(tmp_path)
    # Sign-off is for T1 (default in harness).
    H._write_signoff(root, H._signed_payload(root, candidate="B", sign=True))
    claim, recovery = run_claim_and_lifecycle_probes(), probe_crash_recovery()
    decision = authorize_execution(
        execution_row=_auth_row(target_type="T3"),
        project_root=root, batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim, recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "TARGET_TYPE_MISMATCH" in decision.codes()


def test_authorization_t1_full_binding_and_t3_signoff(tmp_path, monkeypatch):
    """A T3-specific sign-off authorizes a T3 row, and not a T1 row."""
    import test_execution_authorization as H
    from nexora_audit.authorization import authorize_execution
    from nexora_audit.configuration_freeze import target_definition_version_for
    from nexora_audit.safety_probe import probe_crash_recovery, run_claim_and_lifecycle_probes

    monkeypatch.setenv("NEXORA_GOVERNANCE_KEY", "test-key")
    root = H._build_base_root(tmp_path)
    payload = H._signed_payload(root, candidate="B", sign=True)
    # Re-point the sign-off at T3 and re-sign.
    payload["target"] = {
        "target_type": "T3",
        "target_hash": target_definition_version_for("T3", 2)["hash"],
    }
    body = {k: v for k, v in payload.items() if k != "integrity"}
    import hmac
    from nexora_audit.canonical_config import canonical_json
    sig = hmac.new(b"test-key", canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
    payload["integrity"] = {"mechanism": "hmac-sha256", "signature": sig}
    H._write_signoff(root, payload)

    claim, recovery = run_claim_and_lifecycle_probes(), probe_crash_recovery()
    t3 = authorize_execution(
        execution_row=_auth_row(target_type="T3"),
        project_root=root, batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim, recovery_probe_result=recovery,
    )
    # T3 row matches the T3 sign-off target binding (even if readiness/timing
    # still gate the full authorization, it must NOT be a target mismatch).
    assert "TARGET_TYPE_MISMATCH" not in t3.codes()
    assert "TARGET_HASH_MISMATCH" not in t3.codes()

    t1 = authorize_execution(
        execution_row=_auth_row(target_type="T1"),
        project_root=root, batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim, recovery_probe_result=recovery,
    )
    assert t1.authorized is False
    assert "TARGET_TYPE_MISMATCH" in t1.codes()


# ---------------------------------------------------------------------------------
# 9. Evaluator: T3 gross execution metrics
# ---------------------------------------------------------------------------------
def test_t3_evaluator_gross_metrics():
    from nexora_evaluator.t3_evaluation import evaluate_t3_execution_gross

    df = pd.DataFrame({
        "direction": [1, -1, 0, 1, -1],
        "realized_forward_return": [0.01, -0.02, 0.0, 0.03, -0.01],
    })
    out = evaluate_t3_execution_gross(df)
    assert out["target_type"] == "T3"
    assert out["is_gross"] is True
    assert out["transaction_cost_status"] == "DEFERRED"
    assert out["long_count"] == 2 and out["short_count"] == 2 and out["neutral_count"] == 1
    # gross pnl over the 4 ACTIVE trades = [0.01, 0.02, 0.03, 0.01] -> mean 0.07/4
    assert np.isclose(out["gross_expectancy"], 0.07 / 4, atol=1e-9)


def test_t3_evaluator_requires_columns():
    from nexora_evaluator.t3_evaluation import evaluate_t3_execution_gross

    with pytest.raises(ValueError):
        evaluate_t3_execution_gross(pd.DataFrame({"direction": [1]}))


def test_t3_evaluator_no_costs_applied():
    """Evaluator must not subtract any cost (gross only)."""
    from nexora_evaluator.t3_evaluation import evaluate_t3_execution_gross

    df = pd.DataFrame({"direction": [1, 1], "realized_forward_return": [0.10, -0.05]})
    out = evaluate_t3_execution_gross(df)
    # gross expectancy = mean(0.10, -0.05) = 0.025 exactly (no cost deducted)
    assert np.isclose(out["gross_expectancy"], 0.025, atol=1e-12)

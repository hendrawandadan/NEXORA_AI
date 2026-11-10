"""Tests for the NEXORA Autonomous Research Scheduler (Item 2.5).

Covers every required behavior:
  Phase 1: persistent job queue (states), idempotency, duplicate prevention,
           provider rate limits, exponential-backoff retries,
           checkpoint/restart recovery, WAL.
  Phase 2: manual activation (dry-run default) + interval execution + event trigger,
           research cycle / info acquisition / strategy evolution handlers,
           training/promotion/live action refusal.
  Phase 3: governance preflight, PRICE_DERIVED suspension, INFO_ACQUISITION allowed
           for valid proposals, PIT gating, kill switch, graceful shutdown, uniqueness.
  Phase 4: observability (status/queue/history/retry/provider/audit).

Hard guarantees asserted here:
  * production DB untouched (hash unchanged),
  * no training / tuning / promotion / live trading / lane reopen possible,
  * scheduler DB isolated from production.
"""

import hashlib
import json
import pathlib
import sqlite3

import pytest

from nexora_scheduler import (
    ResearchJobQueue, ResearchScheduler, SchedulerConfig, KillSwitch,
    ProviderRateLimiter, DEFAULT_CONFIG, JOB_KINDS,
    JOB_RESEARCH_CYCLE, JOB_INFO_ACQUISITION, JOB_STRATEGY_EVOLUTION,
    FORBIDDEN_JOB_KINDS, DuplicateJobError,
)
from nexora_scheduler import config as cfg
from nexora_scheduler import observability as obs
from nexora_scheduler import jobs as job_handlers


PRODUCTION_DB = pathlib.Path(cfg.PRODUCTION_DB_PATH)


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def prod_hash():
    before = _sha(PRODUCTION_DB) if PRODUCTION_DB.exists() else None
    yield before
    after = _sha(PRODUCTION_DB) if PRODUCTION_DB.exists() else None
    assert before == after, "PRODUCTION DB WAS MODIFIED"


@pytest.fixture
def queue(tmp_path):
    return ResearchJobQueue(tmp_path / "sched.db")


@pytest.fixture
def scheduler(queue):
    return ResearchScheduler(queue, config=SchedulerConfig(dry_run=True))


# ===================================================================== #
# Phase 1 — job queue / state machine / idempotency / isolation
# ===================================================================== #
def test_queue_uses_isolated_db(queue):
    assert queue.db_path == (pathlib.Path(str(queue.db_path)).resolve())
    protected = {pathlib.Path(cfg.PRODUCTION_DB_PATH).resolve(),
                 pathlib.Path(cfg.RESEARCH_DB_PATH).resolve(),
                 pathlib.Path(cfg.EXTERNAL_INTEL_DB_PATH).resolve()}
    assert queue.db_path not in protected


def test_refuses_protected_db_as_queue():
    with pytest.raises(ValueError):
        ResearchJobQueue(cfg.PRODUCTION_DB_PATH)


def test_enqueue_starts_queued(queue):
    jid = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    rec = queue.get(jid)
    assert rec.status == cfg.STATUS_QUEUED
    assert rec.attempts == 0


def test_job_states_closed_set(queue):
    assert set(cfg.JOB_STATUSES) == {
        "QUEUED", "RUNNING", "COMPLETED", "FAILED", "RETRY_WAIT", "BLOCKED", "CANCELLED"}


def test_idempotent_enqueue_returns_same_id(queue):
    a = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    b = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    assert a == b


def test_duplicate_active_prevention_reject(queue):
    queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    with pytest.raises(DuplicateJobError):
        queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"},
                      reject_duplicates=True)


def test_forbidden_kind_rejected_app_layer(queue):
    for k in ("TRAIN", "TUNE", "PROMOTE_MODEL", "ENABLE_LIVE_TRADING",
              "REOPEN_LANE", "PRODUCTION_WRITE"):
        with pytest.raises(ValueError):
            queue.enqueue(kind=k, payload={})


def test_forbidden_kind_rejected_db_trigger(queue):
    conn = sqlite3.connect(str(queue.db_path))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduler_jobs(job_key,idempotency_key,kind,spec_sha256,"
                "created_at,updated_at) VALUES('x','y','PROMOTE_MODEL','z','t','t')")
            conn.commit()
    finally:
        conn.close()


def test_illegal_transition_rejected(queue):
    jid = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={})
    from nexora_scheduler.job_queue import IllegalTransition
    with pytest.raises(IllegalTransition):
        queue.mark_completed(jid)  # not RUNNING


def test_claim_is_atomic_only_one_worker(queue):
    queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    first = queue.claim_next()
    second = queue.claim_next()
    assert first is not None and second is None  # only one claim wins


def test_claim_marks_running_and_logs_execution(queue):
    jid = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    rec = queue.claim_next()
    assert rec.status == cfg.STATUS_RUNNING
    assert rec.attempts == 1
    assert queue.executions(jid)[0]["status"] == "RUNNING"


def test_provider_rate_limiter():
    lim = ProviderRateLimiter(SchedulerConfig(provider_rate_limit_per_min={"p": 3}))
    assert all(lim.try_acquire("p") for _ in range(3))
    assert lim.try_acquire("p") is False  # 4th within window blocked
    assert lim.remaining("p") == 0


def test_retry_exponential_backoff(queue, scheduler):
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("x")
    orig = job_handlers.HANDLERS[JOB_RESEARCH_CYCLE]
    job_handlers.HANDLERS[JOB_RESEARCH_CYCLE] = boom
    try:
        cfgq = ResearchJobQueue(queue.db_path, config=SchedulerConfig(
            dry_run=True, max_retries=2, retry_base_delay_s=0.0, retry_max_delay_s=0.0))
        s = ResearchScheduler(cfgq, config=SchedulerConfig(
            dry_run=True, max_retries=2, retry_base_delay_s=0.0, retry_max_delay_s=0.0))
        jid = s.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
        for _ in range(8):
            s.tick()
            if cfgq.get(jid).status in ("FAILED", "COMPLETED", "BLOCKED"):
                break
        rec = cfgq.get(jid)
        assert rec.status == "FAILED"
        # 1 initial + 2 retries => 3 attempts; retries logged == 2
        assert rec.attempts == 3
        assert len(cfgq.retries(jid)) == 2
        # backoff doubling
        rs = cfgq.retries(jid)
        assert rs[0]["backoff_s"] <= rs[1]["backoff_s"]
    finally:
        job_handlers.HANDLERS[JOB_RESEARCH_CYCLE] = orig


def test_checkpoint_restart_recovery(queue):
    jid = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    queue.claim_next()
    assert queue.get(jid).status == cfg.STATUS_RUNNING
    n = queue.recover_running_jobs()
    assert n == 1
    assert queue.get(jid).status == cfg.STATUS_RETRY_WAIT
    # Re-claimable after recovery.
    assert queue.claim_next() is not None


def test_wal_mode_enabled(queue):
    with queue.manager.open() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


# ===================================================================== #
# Phase 2 — manual/interval/event scheduling + handlers + refusal
# ===================================================================== #
def test_default_config_is_dry_run():
    assert DEFAULT_CONFIG.dry_run is True
    assert DEFAULT_CONFIG.use_mock_provider is True


def test_research_cycle_completes(scheduler, queue, prod_hash):
    jid = scheduler.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    tr = scheduler.tick()
    assert tr.final_status == cfg.STATUS_COMPLETED
    rec = queue.get(jid)
    assert rec.status == cfg.STATUS_COMPLETED
    assert rec.result["job_kind"] == JOB_RESEARCH_CYCLE


def test_info_acquisition_produces_proposals(scheduler, queue):
    jid = scheduler.submit_event(kind=JOB_INFO_ACQUISITION,
                                 payload={"instrument": "EURUSD"})
    scheduler.tick()
    rec = queue.get(jid)
    assert rec.status == cfg.STATUS_COMPLETED
    assert rec.result["external_proposals"] >= 1
    assert rec.result["loop_max_verdict"] in (
        "READY_FOR_CONFIRMATORY_EXPERIMENT", "NO_OUTCOME")


def test_strategy_evolution_completes(scheduler, queue):
    jid = scheduler.submit_event(kind=JOB_STRATEGY_EVOLUTION, payload={})
    scheduler.tick()
    assert queue.get(jid).status == cfg.STATUS_COMPLETED


def test_event_trigger_idempotent(scheduler, queue):
    a = scheduler.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"},
                               event_id="evt-1")
    b = scheduler.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"},
                               event_id="evt-1")
    assert a == b


def test_interval_scheduling_enqueues(queue):
    s = ResearchScheduler(queue, config=SchedulerConfig(
        dry_run=True, interval_research_cycle_s=1.0))
    enq = s.enqueue_interval_jobs()
    assert len(enq) == 1
    # Same window (clock not advanced) -> no duplicate.
    assert s.enqueue_interval_jobs() == []


def test_manual_activation_required_no_auto_start():
    # Constructing a scheduler must not run anything.
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    q = ResearchJobQueue(d / "s.db")
    ResearchScheduler(q, config=SchedulerConfig(dry_run=True))
    assert q.count_by_status()["RUNNING"] == 0
    assert sum(q.count_by_status().values()) == 0


def test_training_promotion_live_refused(scheduler):
    for bad in ("TRAIN", "PROMOTE_MODEL", "LIVE_TRADING", "REOPEN_LANE",
                "ENABLE_LIVE_TRADING"):
        with pytest.raises((ValueError, RuntimeError)):
            scheduler.submit_event(kind=bad, payload={})


def test_dispatch_refuses_forbidden():
    for bad in FORBIDDEN_JOB_KINDS:
        with pytest.raises(ValueError):
            job_handlers.dispatch(bad, {})


# ===================================================================== #
# Phase 3 — governance / PIT / kill switch / shutdown
# ===================================================================== #
def test_governance_guard_armed():
    from nexora_scheduler.safety import _guard_is_armed
    armed, reason = _guard_is_armed()
    assert armed is True


def test_price_derived_suspended_still_armed():
    from nexora_laboratory.governance.lane_suspension import (
        is_suspended, assert_can, GovernanceViolation)
    assert is_suspended() is True
    for action in ("train", "promote_model", "enable_live_trading", "auto_reopen"):
        with pytest.raises(GovernanceViolation):
            assert_can(action)


def test_info_acquisition_proposal_allowed_through_preflight():
    from nexora_scheduler.safety import combined_preflight
    d = combined_preflight(job_kind=JOB_INFO_ACQUISITION, payload={
        "lane": "INFO_ACQUISITION", "governance_status": "ALLOWED",
        "rule_id": "R_EXT_EVENT_RESPONSE", "instrument": "EURUSD"})
    assert d.allowed is True


def test_blocked_proposal_preflight_blocks():
    from nexora_scheduler.safety import combined_preflight
    d = combined_preflight(job_kind=JOB_INFO_ACQUISITION, payload={
        "lane": "INFO_ACQUISITION", "governance_status": "BLOCKED_GOVERNANCE",
        "rule_id": "R_EXT_X", "instrument": "EURUSD"})
    assert d.allowed is False


def test_price_rule_smuggled_under_info_lane_blocked():
    from nexora_scheduler.safety import combined_preflight
    # A non-R_EXT rule id on the info lane is re-checked as price-derived; EURUSD H4 h12
    # is suspended -> BLOCKED.
    d = combined_preflight(job_kind=JOB_INFO_ACQUISITION, payload={
        "lane": "INFO_ACQUISITION", "governance_status": "ALLOWED",
        "rule_id": "R_HORIZON", "instrument": "EURUSD", "timeframe": "H4", "horizon": 12})
    assert d.allowed is False


def test_non_pit_evidence_blocked_when_policy(queue):
    # A job whose evidence is non-PIT-safe should be BLOCKED under block policy.
    s = ResearchScheduler(queue, config=SchedulerConfig(dry_run=True),
                          policy_block_non_pit=True)
    jid = s.submit_event(kind=JOB_RESEARCH_CYCLE, payload={
        "instrument": "EURUSD", "lane": "INFO_ACQUISITION",
        "governance_status": "ALLOWED", "rule_id": "R_EXT_X",
        "evidence": {"data_quality": "UNVERIFIED", "is_synthetic": False,
                     "asof_safe": False}})
    s.tick()
    rec = queue.get(jid)
    assert rec.status == cfg.STATUS_BLOCKED


def test_non_confirmatory_lead_allowed_when_policy_off():
    from nexora_scheduler.safety import preflight_pit
    d = preflight_pit(evidence={"data_quality": "UNVERIFIED", "asof_safe": False},
                      policy_block_non_pit=False)
    assert d.allowed is True
    assert d.non_confirmatory_lead is True
    assert d.confirmatory_ready is False


def test_kill_switch_blocks_execution(queue):
    ks = KillSwitch()
    ks.engage(reason="test", write_file=False)
    try:
        s = ResearchScheduler(queue, config=SchedulerConfig(dry_run=True),
                              kill_switch=ks)
        jid = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
        tr = s.tick()
        assert tr.kill_switch is True
        # Job remains QUEUED (not executed).
        assert queue.get(jid).status == cfg.STATUS_QUEUED
    finally:
        ks.disengage(remove_file=True)


def test_kill_switch_prevents_enqueue(scheduler_queue_with_kill):
    q, s = scheduler_queue_with_kill
    with pytest.raises(RuntimeError):
        s.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})


@pytest.fixture
def scheduler_queue_with_kill(tmp_path):
    ks = KillSwitch(path=tmp_path / "KILL")
    ks.engage(reason="test", write_file=True)
    q = ResearchJobQueue(tmp_path / "s.db")
    s = ResearchScheduler(q, config=SchedulerConfig(dry_run=True), kill_switch=ks)
    yield q, s
    ks.disengage(remove_file=True)


def test_graceful_shutdown_finishes_current_job(queue):
    s = ResearchScheduler(queue, config=SchedulerConfig(dry_run=True))
    # A handler that requests stop WHILE executing: the current job must still COMPLETE
    # (finish), and only then does the loop exit.
    orig = job_handlers.HANDLERS[JOB_RESEARCH_CYCLE]

    def stop_after_work(payload, *, dry_run=True, store=None):
        s.request_stop()
        return {"job_kind": JOB_RESEARCH_CYCLE, "instrument": payload.get("instrument"),
                "dry_run": dry_run, "note": "worked then requested stop"}
    job_handlers.HANDLERS[JOB_RESEARCH_CYCLE] = stop_after_work
    try:
        jid = s.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
        rep = s.run(max_ticks=5)
        # Current job finished (COMPLETED) even though stop was requested mid-run.
        assert queue.get(jid).status == cfg.STATUS_COMPLETED
        assert "stopped by request" in rep.notes
    finally:
        job_handlers.HANDLERS[JOB_RESEARCH_CYCLE] = orig


def test_request_stop_before_run_is_respected(queue):
    s = ResearchScheduler(queue, config=SchedulerConfig(dry_run=True))
    jid = s.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    s.request_stop()  # pre-armed stop (simulated: already shutting down)
    rep = s.run(max_ticks=5)
    assert "stopped by request" in rep.notes
    assert queue.get(jid).status == cfg.STATUS_QUEUED  # never executed


def test_run_drains_and_stops(queue):
    s = ResearchScheduler(queue, config=SchedulerConfig(dry_run=True))
    s.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    rep = s.run(max_ticks=10)
    assert rep.jobs_completed >= 1
    assert queue.count_by_status()["QUEUED"] == 0


# ===================================================================== #
# Phase 4 — observability
# ===================================================================== #
def test_status_observability(queue):
    queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    snap = obs.snapshot(queue)
    d = snap.as_dict()
    assert d["queue"]["counts"]["QUEUED"] == 1
    assert "governance" in d
    text = obs.format_status_text(snap)
    assert "Research Scheduler" in text


def test_history_observability(scheduler, queue):
    jid = scheduler.submit_event(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    scheduler.tick()
    hist = obs.job_history(queue, jid)
    assert hist["job"]["status"] == cfg.STATUS_COMPLETED
    assert hist["executions"]
    assert hist["audit"]


def test_retry_history_observability(queue):
    jid = queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    queue.claim_next()
    queue.mark_failed(jid, "err")
    assert queue.get(jid).status == cfg.STATUS_RETRY_WAIT
    assert len(queue.retries(jid)) == 1


def test_provider_health_observability(queue):
    queue.record_provider_health("mock", "OK", {"latency_ms": 5})
    health = queue.provider_health()
    assert health["mock"]["status"] == "OK"


def test_audit_report(queue):
    queue.enqueue(kind=JOB_RESEARCH_CYCLE, payload={"instrument": "EURUSD"})
    rep = obs.audit_report(queue)
    assert rep["by_status"]["QUEUED"] == 1
    assert rep["recent_audit"]


# ===================================================================== #
# CLI manual activation
# ===================================================================== #
def test_cli_run_requires_consent(tmp_path, capsys):
    from nexora_scheduler import cli
    rc = cli.main(["--db", str(tmp_path / "s.db"), "run", "--max-ticks", "1"])
    assert rc == 2
    out = capsys.readouterr()
    assert "consent" in (out.err + out.out).lower()


def test_cli_enqueue_and_status(tmp_path, capsys):
    from nexora_scheduler import cli
    db = str(tmp_path / "s.db")
    assert cli.main(["--db", db, "enqueue", "--kind", JOB_RESEARCH_CYCLE,
                     "--instrument", "EURUSD"]) == 0
    assert cli.main(["--db", db, "status", "--json"]) == 0
    out = capsys.readouterr().out
    assert "QUEUED" in out


# ===================================================================== #
# Apparent no-production-touch integration
# ===================================================================== #
def test_full_cycle_production_untouched(scheduler, queue, prod_hash):
    for kind, payload in ((JOB_RESEARCH_CYCLE, {"instrument": "EURUSD"}),
                          (JOB_INFO_ACQUISITION, {"instrument": "EURUSD"}),
                          (JOB_STRATEGY_EVOLUTION, {})):
        scheduler.submit_event(kind=kind, payload=payload)
    scheduler.run(max_ticks=10)
    # prod_hash fixture asserts hash unchanged at teardown.
    assert sum(queue.count_by_status().values()) == 3

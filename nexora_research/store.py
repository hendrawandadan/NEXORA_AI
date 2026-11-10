"""Knowledge Memory store for the autonomous research loop (Tahap A).

Durable, append-only, hashed memory of hypotheses / experiments / evaluations /
failures / knowledge. Built on the shared ``nexora_state_db`` connection +
migration machinery, but against a SEPARATE research DB path.

Design invariants (enforced here, tested in tests/test_research_memory.py):
  * Append-only. There is NO update-in-place API for recorded content. A change
    is recorded as a NEW version/row, preserving history.
  * Content-hashed. Every payload gets a canonical SHA256 so tampering is
    detectable (same canonical scheme as ``experiment_freeze``).
  * Pre-registration ordering. An experiment REQUIRES its hypothesis to already be
    PRE_REGISTERED; an evaluation REQUIRES an experiment; a failure REQUIRES an
    experiment (and must carry a recommendation -- "failure must teach").
  * No production writes. This module only ever opens the research DB path.

This module does NOT train, does NOT touch production state, and does NOT make
profitability claims. It stores facts/verdicts produced elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from nexora_laboratory.experiment_freeze import _hash_payload
from nexora_state_db.bootstrap import create_dev_database
from nexora_state_db.connection import SQLiteConnectionManager

from .config import RESEARCH_DATABASE_PATH, RESEARCH_MIGRATIONS_DIR
from nexora_state_db.migrations import MigrationManager

HYPOTHESIS_STATUSES = ("PROPOSED", "PRE_REGISTERED", "UNDER_TEST", "EVALUATED", "RETIRED")
EXPERIMENT_STATUSES = ("CREATED", "SKIPPED_INFEASIBLE", "TRAINED", "EVALUATED", "FAILED")
EVAL_VERDICTS = ("GO", "NO_GO", "INCONCLUSIVE")
FAILURE_TYPES = (
    "DATA_QUALITY", "STRUCTURAL_INFEASIBILITY", "NO_PREDICTIVE_POWER",
    "EDGE_BELOW_COST", "OVERFIT", "REGIME_FRAGILE", "UNKNOWN",
)
KNOWLEDGE_KINDS = ("FINDING", "CONSTRAINT", "DEAD_END", "STRATEGY_LEAD")

# R1 — closed set of research lanes. Every artefact records which lane produced it so
# INFO_ACQUISITION and PRICE_DERIVED can never be silently mixed.
LANES = ("PRICE_DERIVED", "INFO_ACQUISITION")
DEFAULT_LANE = "PRICE_DERIVED"   # backward-compatible: pre-R1 rows were price-derived


def _normalise_lane(lane: Optional[str]) -> str:
    """Validate/normalise a lane value (fail-closed on unknown input)."""
    val = (lane or "").strip().upper()
    if val not in LANES:
        raise ValueError(f"invalid lane: {lane!r} (must be one of {LANES})")
    return val


def _canonical_sha(payload) -> str:
    """Canonical content hash (stable across key order)."""
    return _hash_payload(payload)


class ResearchMemoryStore:
    """Append-only knowledge memory over the isolated research DB."""

    def __init__(self, db_path: Optional[Path] = None, *, bootstrap: bool = True) -> None:
        self.db_path = Path(db_path) if db_path else RESEARCH_DATABASE_PATH
        self.manager = SQLiteConnectionManager(db_path=self.db_path)
        if bootstrap:
            MigrationManager(self.manager, RESEARCH_MIGRATIONS_DIR).migrate()

    # ------------------------------------------------------------------ #
    # (2) Hypotheses — pre-registration with content hash
    # ------------------------------------------------------------------ #
    def register_hypothesis(
        self,
        *,
        hypothesis_key: str,
        instrument: str,
        timeframe: str,
        horizon_bars: int,
        claim: str,
        market_condition: str = "",
        signal_source: str = "",
        go_criteria: Optional[dict] = None,
        status: str = "PRE_REGISTERED",
        lane: Optional[str] = DEFAULT_LANE,
    ) -> Dict[str, object]:
        if not hypothesis_key.strip():
            raise ValueError("hypothesis_key must be non-empty")
        if horizon_bars <= 0:
            raise ValueError("horizon_bars must be positive")
        if status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"invalid hypothesis status: {status}")
        lane = _normalise_lane(lane)
        body = {
            "hypothesis_key": hypothesis_key.strip(),
            "instrument": instrument, "timeframe": timeframe,
            "horizon_bars": int(horizon_bars),
            "market_condition": market_condition,
            "signal_source": signal_source,
            "claim": claim,
            "go_criteria": go_criteria or {},
            "lane": lane,
        }
        csha = _canonical_sha(body)
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT INTO research_hypotheses
                   (hypothesis_key,instrument,timeframe,horizon_bars,market_condition,
                    signal_source,claim,go_criteria_json,content_sha256,status,lane)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (body["hypothesis_key"], instrument, timeframe, int(horizon_bars),
                 market_condition, signal_source, claim,
                 json.dumps(go_criteria or {}, sort_keys=True), csha, status, lane),
            )
            conn.commit()
            return {"id": int(cur.lastrowid), "content_sha256": csha, "status": status,
                    "lane": lane}

    def get_hypothesis(self, hypothesis_id: int) -> Optional[Dict[str, object]]:
        with self.manager.open() as conn:
            row = conn.execute(
                "SELECT * FROM research_hypotheses WHERE id=?", (hypothesis_id,)
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    # (3) Experiments — must bind an existing PRE_REGISTERED hypothesis
    # ------------------------------------------------------------------ #
    def create_experiment(
        self,
        *,
        experiment_key: str,
        hypothesis_id: int,
        spec: dict,
        status: str = "CREATED",
    ) -> Dict[str, object]:
        if status not in EXPERIMENT_STATUSES:
            raise ValueError(f"invalid experiment status: {status}")
        hyp = self.get_hypothesis(hypothesis_id)
        if hyp is None:
            raise KeyError(f"hypothesis not found: {hypothesis_id}")
        if hyp["status"] not in ("PRE_REGISTERED", "UNDER_TEST", "EVALUATED"):
            raise ValueError(
                "experiment requires a pre-registered hypothesis "
                f"(current status: {hyp['status']})"
            )
        # R1: denormalise lane from the bound hypothesis so experiments are queryable.
        lane = _normalise_lane(hyp.get("lane") or DEFAULT_LANE)
        ssha = _canonical_sha(spec)
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT INTO research_experiments
                   (experiment_key,hypothesis_id,spec_json,spec_sha256,status,lane)
                   VALUES(?,?,?,?,?,?)""",
                (experiment_key.strip(), hypothesis_id,
                 json.dumps(spec, sort_keys=True), ssha, status, lane),
            )
            conn.commit()
            return {"id": int(cur.lastrowid), "spec_sha256": ssha, "status": status,
                    "lane": lane}

    def get_experiment(self, experiment_id: int) -> Optional[Dict[str, object]]:
        with self.manager.open() as conn:
            row = conn.execute(
                "SELECT * FROM research_experiments WHERE id=?", (experiment_id,)
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    # (5) Evaluations — net-of-cost verdict
    # ------------------------------------------------------------------ #
    def record_evaluation(
        self,
        *,
        experiment_id: int,
        verdict: str,
        result: dict,
        net_expectancy_pips: Optional[float] = None,
        auc_net: Optional[float] = None,
        lower_ci: Optional[float] = None,
        upper_ci: Optional[float] = None,
    ) -> Dict[str, object]:
        if verdict not in EVAL_VERDICTS:
            raise ValueError(f"invalid verdict: {verdict}")
        exp = self.get_experiment(experiment_id)
        if exp is None:
            raise KeyError(f"experiment not found: {experiment_id}")
        lane = _normalise_lane(exp.get("lane") or DEFAULT_LANE)
        rsha = _canonical_sha(result)
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT INTO research_evaluations
                   (experiment_id,verdict,net_expectancy_pips,auc_net,lower_ci,upper_ci,
                    details_json,result_sha256,lane)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (experiment_id, verdict, net_expectancy_pips, auc_net, lower_ci,
                 upper_ci, json.dumps(result, sort_keys=True), rsha, lane),
            )
            conn.commit()
            return {"id": int(cur.lastrowid), "result_sha256": rsha, "verdict": verdict,
                    "lane": lane}

    # ------------------------------------------------------------------ #
    # (6) Failures — must teach (recommendation required)
    # ------------------------------------------------------------------ #
    def record_failure(
        self,
        *,
        experiment_id: int,
        failure_type: str,
        recommendation: str,
        evidence: Optional[dict] = None,
    ) -> Dict[str, object]:
        if failure_type not in FAILURE_TYPES:
            raise ValueError(f"invalid failure_type: {failure_type}")
        if not recommendation or not recommendation.strip():
            raise ValueError("failure must teach: a non-empty recommendation is required")
        exp = self.get_experiment(experiment_id)
        if exp is None:
            raise KeyError(f"experiment not found: {experiment_id}")
        lane = _normalise_lane(exp.get("lane") or DEFAULT_LANE)
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT INTO research_failures
                   (experiment_id,failure_type,evidence_json,recommendation,lane)
                   VALUES(?,?,?,?,?)""",
                (experiment_id, failure_type,
                 json.dumps(evidence or {}, sort_keys=True), recommendation.strip(), lane),
            )
            conn.commit()
            return {"id": int(cur.lastrowid), "failure_type": failure_type, "lane": lane}

    # ------------------------------------------------------------------ #
    # (7) Knowledge — immutable, versioned (append new version, never overwrite)
    # ------------------------------------------------------------------ #
    def record_knowledge(
        self,
        *,
        knowledge_key: str,
        kind: str,
        summary: str,
        detail: Optional[dict] = None,
        source_experiment_id: Optional[int] = None,
        lane: Optional[str] = None,
    ) -> Dict[str, object]:
        if kind not in KNOWLEDGE_KINDS:
            raise ValueError(f"invalid knowledge kind: {kind}")
        if not knowledge_key.strip():
            raise ValueError("knowledge_key must be non-empty")
        if source_experiment_id is not None and self.get_experiment(source_experiment_id) is None:
            raise KeyError(f"source experiment not found: {source_experiment_id}")

        # R1: lane is nullable for knowledge. Explicit value is validated; otherwise it is
        # inherited from the source experiment when available, else stays NULL.
        if lane is not None:
            lane = _normalise_lane(lane)
        elif source_experiment_id is not None:
            exp = self.get_experiment(source_experiment_id)
            if exp and exp.get("lane"):
                lane = _normalise_lane(exp.get("lane"))

        with self.manager.open() as conn:
            prev = conn.execute(
                "SELECT MAX(version) AS v FROM research_knowledge WHERE knowledge_key=?",
                (knowledge_key.strip(),),
            ).fetchone()
            next_version = int(prev["v"]) + 1 if prev and prev["v"] is not None else 1
            body = {
                "knowledge_key": knowledge_key.strip(),
                "version": next_version,
                "kind": kind,
                "summary": summary,
                "detail": detail or {},
                "source_experiment_id": source_experiment_id,
                "lane": lane,
            }
            csha = _canonical_sha(body)
            cur = conn.execute(
                """INSERT INTO research_knowledge
                   (knowledge_key,version,kind,summary,detail_json,source_experiment_id,
                    content_sha256,lane)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (knowledge_key.strip(), next_version, kind, summary,
                 json.dumps(detail or {}, sort_keys=True), source_experiment_id, csha, lane),
            )
            conn.commit()
            return {"id": int(cur.lastrowid), "version": next_version,
                    "content_sha256": csha, "lane": lane}

    def knowledge_versions(self, knowledge_key: str) -> List[Dict[str, object]]:
        with self.manager.open() as conn:
            rows = conn.execute(
                "SELECT * FROM research_knowledge WHERE knowledge_key=? ORDER BY version",
                (knowledge_key.strip(),),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Convenience queries (read-only) for later stages / Strategy Evolution
    # ------------------------------------------------------------------ #
    def list_hypotheses(self, status: Optional[str] = None,
                        lane: Optional[str] = None) -> List[Dict[str, object]]:
        q = "SELECT * FROM research_hypotheses"
        where, args = [], []
        if status:
            where.append("status=?"); args.append(status)
        if lane:
            where.append("lane=?"); args.append(_normalise_lane(lane))
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id"
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(q, tuple(args)).fetchall()]

    def list_failures(self, experiment_id: Optional[int] = None,
                      lane: Optional[str] = None) -> List[Dict[str, object]]:
        q = "SELECT * FROM research_failures"
        where, args = [], []
        if experiment_id is not None:
            where.append("experiment_id=?"); args.append(experiment_id)
        if lane:
            where.append("lane=?"); args.append(_normalise_lane(lane))
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id"
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(q, tuple(args)).fetchall()]

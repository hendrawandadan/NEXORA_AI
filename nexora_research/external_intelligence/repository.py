"""External Information Intelligence — External Knowledge Repository (isolated, append-only, audited).

[Component of the INFO_ACQUISITION lane; enabler for Fase 2, see MASTER_ROADMAP §3a.]

A dedicated SQLite database at ``database/nexora_external_intel.db`` -- deliberately
different from both ``nexora_state.db`` (production) and ``nexora_research.db``
(research memory). Built on the shared connection + migration machinery, but with a
path guard that REFUSES to open the production or research DB.

Invariants enforced here (and tested in tests/external_intelligence/test_repository.py):
  * Append-only: no update-in-place API. Corrections are new rows (supersedes_id).
  * Content-hashed: every row carries content_sha256 (canonical SHA256).
  * Provenance: every row stores source_provider + retrieved_at + data_quality.
  * Validation: schema-level validation on insert (timestamps, currencies, ranges).
  * Audit trail: every write appends to ext_audit_log.
  * Idempotent de-duplication via UNIQUE constraints (returns existing id).

It does NOT read/write any other database. It does NOT train or trade.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from nexora_laboratory.experiment_freeze import _hash_payload
from nexora_state_db.connection import SQLiteConnectionManager
from nexora_state_db.migrations import MigrationManager

from .config import (
    EXTERNAL_INTEL_DB_PATH,
    EXTERNAL_INTEL_MIGRATIONS_DIR,
    PRODUCTION_DB_PATH,
    RESEARCH_DB_PATH,
)

VALID_CURRENCIES = {
    "USD", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD", "CNY", "NZD", "",
}
VALID_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}
VALID_TONE = {"HAWKISH", "DOVISH", "NEUTRAL", "UNKNOWN"}
VALID_QUALITY = {"VERIFIED", "UNVERIFIED", "SYNTHETIC", "STALE", "CONFLICTING"}
VALID_IMPORTANCE = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
VALID_NEWS_CATEGORY = {
    "ECONOMIC", "GEOPOLITICAL", "TRADE", "SANCTIONS", "SUPPLY_CHAIN",
    "FINANCIAL_CRISIS", "GOVERNMENT_POLICY", "OTHER",
}


class IsolationViolation(RuntimeError):
    """Raised if a caller tries to point the repository at a protected DB."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_sha(payload) -> str:
    return _hash_payload(payload)


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _validate_timestamp(ts: str, *, max_past_days: float = 3650.0,
                        max_future_days: float = 365.0) -> bool:
    dt = _parse_iso(ts)
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    delta_days = (now - dt).total_seconds() / 86400.0
    return -max_future_days <= delta_days <= max_past_days


class ExternalKnowledgeRepository:
    """Append-only, isolated external-knowledge store."""

    def __init__(self, db_path: Optional[Path] = None, *, bootstrap: bool = True) -> None:
        resolved = Path(db_path) if db_path else EXTERNAL_INTEL_DB_PATH
        # HARD isolation guard: never touch production or the research DB.
        if resolved in (Path(PRODUCTION_DB_PATH), Path(RESEARCH_DB_PATH)):
            raise IsolationViolation(
                f"refusing to open protected database: {resolved}")
        self.db_path = resolved
        self.manager = SQLiteConnectionManager(db_path=self.db_path)
        if bootstrap:
            MigrationManager(self.manager, EXTERNAL_INTEL_MIGRATIONS_DIR).migrate()

    # ---- audit helper -------------------------------------------------------
    def _audit(self, conn, action: str, table: str, sha: str) -> None:
        conn.execute(
            "INSERT INTO ext_audit_log(action, table_name, row_content_sha256, created_at_utc) "
            "VALUES(?,?,?,?)",
            (action, table, sha, _utcnow()),
        )

    # ---------------------------------------------------------------------- #
    # Raw records
    # ---------------------------------------------------------------------- #
    def record_raw(self, *, provider_id: str, resource: str, status: str,
                   content_sha256: str, retrieved_at_utc: str,
                   http_status: Optional[int] = None, byte_size: Optional[int] = None,
                   is_synthetic: bool = False, message: str = "") -> Dict[str, object]:
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_raw_records
                   (provider_id,resource,fetched_status,http_status,content_sha256,
                    byte_size,retrieved_at_utc,is_synthetic,message)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (provider_id, resource, status, http_status, content_sha256,
                 byte_size, retrieved_at_utc, 1 if is_synthetic else 0, message))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_raw_records", "ext_raw_records", content_sha256)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True}
            row = conn.execute(
                "SELECT id FROM ext_raw_records WHERE content_sha256=? AND provider_id=? "
                "AND resource=? AND retrieved_at_utc=?",
                (content_sha256, provider_id, resource, retrieved_at_utc)).fetchone()
            return {"id": int(row["id"]) if row else None, "inserted": False}

    # ---------------------------------------------------------------------- #
    # Economic events
    # ---------------------------------------------------------------------- #
    def insert_economic_event(self, *, event_type: str, country: str, currency: str,
                              scheduled_ts: str, source_provider: str,
                              retrieved_at_utc: str, economic_domain: str = "",
                              importance: str = "UNKNOWN", period: str = "",
                              actual: Optional[float] = None,
                              forecast: Optional[float] = None,
                              previous: Optional[float] = None,
                              revised_previous: Optional[float] = None,
                              unit: str = "", source_ref: str = "",
                              data_quality: str = "UNVERIFIED",
                              supersedes_id: Optional[int] = None,
                              is_synthetic: bool = False,
                              published_at_utc: Optional[str] = None,
                              available_at_utc: Optional[str] = None,
                              vintage: Optional[str] = None,
                              revision_as_of_utc: Optional[str] = None) -> Dict[str, object]:
        # ---- validation (fail-closed) ----
        if not event_type:
            raise ValueError("event_type required")
        if currency not in VALID_CURRENCIES:
            raise ValueError(f"invalid currency: {currency!r}")
        if importance not in VALID_IMPORTANCE:
            raise ValueError(f"invalid importance: {importance!r}")
        if data_quality not in VALID_QUALITY:
            raise ValueError(f"invalid data_quality: {data_quality!r}")
        if not _validate_timestamp(scheduled_ts):
            raise ValueError(f"invalid/absurd scheduled_ts: {scheduled_ts!r}")
        if not retrieved_at_utc:
            raise ValueError("retrieved_at_utc required")
        # R2 (PIT): availability must be a real source timestamp if provided; never invented.
        for label, ts in (("published_at_utc", published_at_utc),
                          ("available_at_utc", available_at_utc),
                          ("revision_as_of_utc", revision_as_of_utc)):
            if ts is not None and not _validate_timestamp(ts):
                raise ValueError(f"invalid {label}: {ts!r}")
        # pit_verified ONLY when the source gives an explicit availability timestamp.
        pit_verified = 1 if available_at_utc else 0
        ingested_at_utc = retrieved_at_utc

        has_actual = 1 if actual is not None else 0
        has_forecast = 1 if forecast is not None else 0
        event_key = f"{country}|{event_type}|{period}|{scheduled_ts}"
        body = {
            "event_key": event_key, "event_type": event_type, "country": country,
            "currency": currency, "scheduled_ts": scheduled_ts,
            "actual": actual, "forecast": forecast, "previous": previous,
            "revised_previous": revised_previous, "source_provider": source_provider,
            "source_ref": source_ref, "period": period,
            # PIT fields participate in the content hash so a changed availability/vintage
            # is a NEW row (append-only history preserved).
            "available_at_utc": available_at_utc, "published_at_utc": published_at_utc,
            "vintage": vintage, "revision_as_of_utc": revision_as_of_utc,
            "pit_verified": pit_verified,
        }
        csha = _canonical_sha(body)
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_economic_events
                   (event_key,event_type,country,currency,economic_domain,importance,period,
                    scheduled_ts,actual,forecast,previous,revised_previous,has_actual,
                    has_forecast,unit,source_provider,source_ref,retrieved_at_utc,
                    data_quality,content_sha256,supersedes_id,is_synthetic,
                    published_at_utc,available_at_utc,ingested_at_utc,vintage,
                    revision_as_of_utc,pit_verified)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_key, event_type, country, currency, economic_domain, importance,
                 period, scheduled_ts, actual, forecast, previous, revised_previous,
                 has_actual, has_forecast, unit, source_provider, source_ref,
                 retrieved_at_utc, data_quality, csha, supersedes_id,
                 1 if is_synthetic else 0, published_at_utc, available_at_utc,
                 ingested_at_utc, vintage, revision_as_of_utc, pit_verified))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_economic_events", "ext_economic_events", csha)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True,
                        "content_sha256": csha, "event_key": event_key,
                        "pit_verified": pit_verified}
            row = conn.execute(
                "SELECT id FROM ext_economic_events WHERE event_key=? AND content_sha256=?",
                (event_key, csha)).fetchone()
            return {"id": int(row["id"]) if row else None, "inserted": False,
                    "content_sha256": csha, "event_key": event_key,
                    "pit_verified": pit_verified}

    def get_event(self, event_id: int) -> Optional[Dict[str, object]]:
        with self.manager.open() as conn:
            row = conn.execute("SELECT * FROM ext_economic_events WHERE id=?",
                               (event_id,)).fetchone()
        return dict(row) if row else None

    def list_events(self, *, event_type: Optional[str] = None,
                    currency: Optional[str] = None) -> List[Dict[str, object]]:
        q = "SELECT * FROM ext_economic_events"
        where, args = [], []
        if event_type:
            where.append("event_type=?"); args.append(event_type)
        if currency:
            where.append("currency=?"); args.append(currency)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY scheduled_ts"
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(q, args).fetchall()]

    # ---------------------------------------------------------------------- #
    # Central-bank documents
    # ---------------------------------------------------------------------- #
    def insert_central_bank_doc(self, *, institution: str, doc_type: str, title: str,
                                published_ts: str, source_provider: str, source_ref: str,
                                body_text: str, retrieved_at_utc: str,
                                tone: str = "UNKNOWN", tone_confidence: float = 0.0,
                                summary: str = "", is_synthetic: bool = False,
                                available_at_utc: Optional[str] = None) -> Dict[str, object]:
        if not institution or not doc_type:
            raise ValueError("institution and doc_type required")
        if tone not in VALID_TONE:
            raise ValueError(f"invalid tone: {tone!r}")
        if not (0.0 <= float(tone_confidence) <= 1.0):
            raise ValueError("tone_confidence must be in [0,1]")
        if not _validate_timestamp(published_ts):
            raise ValueError(f"invalid published_ts: {published_ts!r}")
        if not source_ref:
            raise ValueError("source_ref required (provenance)")
        if available_at_utc is not None and not _validate_timestamp(available_at_utc):
            raise ValueError(f"invalid available_at_utc: {available_at_utc!r}")
        # R2 (PIT): availability from the source only; first-observed == our retrieval.
        pit_verified = 1 if available_at_utc else 0
        first_observed_at_utc = retrieved_at_utc
        body_sha = _canonical_sha({"body": body_text})
        doc_key = f"{institution}|{doc_type}|{published_ts}|{source_ref}"
        csha = _canonical_sha({"doc_key": doc_key, "body_sha256": body_sha,
                               "tone": tone, "summary": summary,
                               "available_at_utc": available_at_utc,
                               "pit_verified": pit_verified})
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_central_bank_docs
                   (doc_key,institution,doc_type,title,published_ts,source_provider,
                    source_ref,body_sha256,tone,tone_confidence,summary,retrieved_at_utc,
                    is_synthetic,content_sha256,available_at_utc,first_observed_at_utc,
                    pit_verified)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (doc_key, institution, doc_type, title, published_ts, source_provider,
                 source_ref, body_sha, tone, float(tone_confidence), summary,
                 retrieved_at_utc, 1 if is_synthetic else 0, csha, available_at_utc,
                 first_observed_at_utc, pit_verified))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_central_bank_docs",
                            "ext_central_bank_docs", csha)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True, "content_sha256": csha,
                        "pit_verified": pit_verified}
            row = conn.execute(
                "SELECT id FROM ext_central_bank_docs WHERE doc_key=? AND content_sha256=?",
                (doc_key, csha)).fetchone()
            return {"id": int(row["id"]) if row else None, "inserted": False,
                    "content_sha256": csha, "pit_verified": pit_verified}

    def list_central_bank_docs(self, *, institution: Optional[str] = None
                               ) -> List[Dict[str, object]]:
        q = "SELECT * FROM ext_central_bank_docs"
        args: tuple = ()
        if institution:
            q += " WHERE institution=?"; args = (institution,)
        q += " ORDER BY published_ts"
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(q, args).fetchall()]

    # ---------------------------------------------------------------------- #
    # News
    # ---------------------------------------------------------------------- #
    def insert_news(self, *, headline: str, category: str, published_ts: str,
                    source_provider: str, retrieved_at_utc: str,
                    currencies: Optional[List[str]] = None,
                    countries: Optional[List[str]] = None,
                    entities: Optional[List[str]] = None, impact: str = "UNKNOWN",
                    source_ref: str = "", country: str = "", currency: str = "",
                    reliability: str = "UNKNOWN", duplicate_of_id: Optional[int] = None,
                    event_ts: str = "", body_sha256: str = "",
                    is_synthetic: bool = False,
                    available_at_utc: Optional[str] = None) -> Dict[str, object]:
        currencies = currencies or []
        countries = countries or []
        entities = entities or []
        if category not in VALID_NEWS_CATEGORY:
            raise ValueError(f"invalid news category: {category!r}")
        for c in currencies:
            if c not in VALID_CURRENCIES:
                raise ValueError(f"invalid currency in news: {c!r}")
        if not _validate_timestamp(published_ts):
            raise ValueError(f"invalid published_ts: {published_ts!r}")
        if not headline.strip():
            raise ValueError("headline required")
        if available_at_utc is not None and not _validate_timestamp(available_at_utc):
            raise ValueError(f"invalid available_at_utc: {available_at_utc!r}")
        # R2 (PIT): availability from the source only; first-observed == our retrieval.
        pit_verified = 1 if available_at_utc else 0
        first_observed_at_utc = retrieved_at_utc
        news_key = _canonical_sha({"headline": headline.strip(),
                                   "source_ref": source_ref,
                                   "published_ts": published_ts})[:32]
        csha = _canonical_sha({"news_key": news_key, "category": category,
                               "currencies": sorted(currencies),
                               "impact": impact,
                               "available_at_utc": available_at_utc,
                               "pit_verified": pit_verified})
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_news_records
                   (news_key,headline,category,countries_json,currencies_json,impact,
                    entities_json,source_provider,source_ref,published_ts,country,currency,
                    reliability,duplicate_of_id,event_ts,body_sha256,retrieved_at_utc,
                    is_synthetic,content_sha256,available_at_utc,first_observed_at_utc,
                    pit_verified)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (news_key, headline.strip(), category, json.dumps(countries),
                 json.dumps(currencies), impact, json.dumps(entities), source_provider,
                 source_ref, published_ts, country, currency, reliability,
                 duplicate_of_id, event_ts, body_sha256, retrieved_at_utc,
                 1 if is_synthetic else 0, csha, available_at_utc, first_observed_at_utc,
                 pit_verified))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_news_records", "ext_news_records", csha)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True, "content_sha256": csha,
                        "news_key": news_key, "pit_verified": pit_verified}
            row = conn.execute(
                "SELECT id FROM ext_news_records WHERE news_key=? AND content_sha256=?",
                (news_key, csha)).fetchone()
            return {"id": int(row["id"]) if row else None, "inserted": False,
                    "content_sha256": csha, "news_key": news_key,
                    "pit_verified": pit_verified}

    def list_news(self, *, category: Optional[str] = None) -> List[Dict[str, object]]:
        q = "SELECT * FROM ext_news_records"
        args: tuple = ()
        if category:
            q += " WHERE category=?"; args = (category,)
        q += " ORDER BY published_ts"
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(q, args).fetchall()]

    # ---------------------------------------------------------------------- #
    # Cross-market observations
    # ---------------------------------------------------------------------- #
    def insert_cross_market_observation(self, *, pair_a: str, pair_b: str, method: str,
                                        value: float, n_obs: int,
                                        computed_at_utc: str, window: Optional[int] = None,
                                        lag: Optional[int] = None, regime: str = "",
                                        caveat: str = "") -> Dict[str, object]:
        analysis_key = f"{pair_a}|{pair_b}|{method}|w{window}|lag{lag}|{regime}"
        csha = _canonical_sha({"analysis_key": analysis_key, "value": value,
                               "n_obs": n_obs})
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_cross_market_observations
                   (analysis_key,pair_a,pair_b,method,window,lag,value,n_obs,regime,
                    caveat,computed_at_utc,content_sha256)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (analysis_key, pair_a, pair_b, method, window, lag, value, int(n_obs),
                 regime, caveat, computed_at_utc, csha))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_cross_market_observations",
                            "ext_cross_market_observations", csha)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True, "content_sha256": csha}
            row = conn.execute(
                "SELECT id FROM ext_cross_market_observations WHERE analysis_key=? "
                "AND content_sha256=?", (analysis_key, csha)).fetchone()
            return {"id": int(row["id"]) if row else None, "inserted": False,
                    "content_sha256": csha}

    # ---------------------------------------------------------------------- #
    # Fundamental findings
    # ---------------------------------------------------------------------- #
    def insert_fundamental_finding(self, *, subject: str, interpretation: str,
                                   created_at_utc: str, direction: str = "UNCLEAR",
                                   confidence: str = "LOW",
                                   event_id: Optional[int] = None,
                                   surprise: Optional[float] = None,
                                   implications: Optional[dict] = None,
                                   evidence: Optional[List[dict]] = None,
                                   source_ids: Optional[List[str]] = None,
                                   is_synthetic: bool = False) -> Dict[str, object]:
        if confidence not in VALID_CONFIDENCE:
            raise ValueError(f"invalid confidence: {confidence!r}")
        if not interpretation.strip():
            raise ValueError("interpretation required")
        surprise_present = 1 if surprise is not None else 0
        finding_key = _canonical_sha({"subject": subject,
                                      "interpretation": interpretation.strip()})[:32]
        csha = _canonical_sha({"finding_key": finding_key,
                               "direction": direction, "confidence": confidence})
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_fundamental_findings
                   (finding_key,event_id,subject,interpretation,direction,surprise,
                    surprise_present,implications_json,confidence,evidence_json,
                    source_ids_json,created_at_utc,is_synthetic,content_sha256)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (finding_key, event_id, subject, interpretation.strip(), direction,
                 surprise, surprise_present, json.dumps(implications or {}, sort_keys=True),
                 confidence, json.dumps(evidence or []), json.dumps(source_ids or []),
                 created_at_utc, 1 if is_synthetic else 0, csha))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_fundamental_findings",
                            "ext_fundamental_findings", csha)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True, "content_sha256": csha}
            row = conn.execute(
                "SELECT id FROM ext_fundamental_findings WHERE finding_key=? AND "
                "content_sha256=?", (finding_key, csha)).fetchone()
            return {"id": int(row["id"]) if row else None, "inserted": False,
                    "content_sha256": csha}

    def list_fundamental_findings(self) -> List[Dict[str, object]]:
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM ext_fundamental_findings ORDER BY id").fetchall()]

    # ---------------------------------------------------------------------- #
    # Event responses
    # ---------------------------------------------------------------------- #
    def insert_event_response(self, *, event_id: int, instrument: str, horizon: str,
                              horizon_minutes: int, valid: bool, computed_at_utc: str,
                              pre_price: Optional[float] = None,
                              post_price: Optional[float] = None,
                              return_pct: Optional[float] = None,
                              direction: str = "FLAT", note: str = "",
                              as_of_utc: Optional[str] = None,
                              event_available_at_utc: Optional[str] = None
                              ) -> Dict[str, object]:
        response_key = f"{event_id}|{instrument}|{horizon}"
        csha = _canonical_sha({"response_key": response_key, "return_pct": return_pct,
                               "valid": valid, "as_of_utc": as_of_utc,
                               "event_available_at_utc": event_available_at_utc})
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_event_responses
                   (response_key,event_id,instrument,horizon,horizon_minutes,pre_price,
                    post_price,return_pct,direction,valid,note,computed_at_utc,
                    content_sha256,as_of_utc,event_available_at_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (response_key, event_id, instrument, horizon, int(horizon_minutes),
                 pre_price, post_price, return_pct, direction, 1 if valid else 0, note,
                 computed_at_utc, csha, as_of_utc, event_available_at_utc))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_event_responses", "ext_event_responses", csha)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True, "content_sha256": csha}
            row = conn.execute(
                "SELECT id FROM ext_event_responses WHERE response_key=? AND content_sha256=?",
                (response_key, csha)).fetchone()
            return {"id": int(row["id"]) if row else None, "inserted": False,
                    "content_sha256": csha}

    def list_event_responses(self, *, event_id: Optional[int] = None
                             ) -> List[Dict[str, object]]:
        q = "SELECT * FROM ext_event_responses"
        args: tuple = ()
        if event_id is not None:
            q += " WHERE event_id=?"; args = (event_id,)
        q += " ORDER BY id"
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(q, args).fetchall()]

    # ---------------------------------------------------------------------- #
    # Source snapshots
    # ---------------------------------------------------------------------- #
    def insert_source_snapshot(self, *, provider_id: str, tier: int,
                               connector_available: bool, access_status: str,
                               captured_at_utc: str) -> Dict[str, object]:
        csha = _canonical_sha({"provider_id": provider_id, "tier": tier,
                               "connector_available": connector_available,
                               "access_status": access_status})
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_source_snapshots
                   (provider_id,tier,connector_available,access_status,captured_at_utc,
                    content_sha256) VALUES(?,?,?,?,?,?)""",
                (provider_id, tier, 1 if connector_available else 0, access_status,
                 captured_at_utc, csha))
            conn.commit()
            return {"id": int(cur.lastrowid) if cur.rowcount else None,
                    "inserted": bool(cur.rowcount)}

    # ---------------------------------------------------------------------- #
    # Research proposals
    # ---------------------------------------------------------------------- #
    def insert_research_proposal(self, *, proposal_key: str, instrument: str, claim: str,
                                 created_at_utc: str, lane: str = "INFO_ACQUISITION",
                                 novelty_rationale: str = "",
                                 data_requirements: Optional[List] = None,
                                 falsification_criteria: str = "",
                                 evidence: Optional[dict] = None,
                                 source_ids: Optional[List] = None,
                                 governance_status: str = "UNKNOWN") -> Dict[str, object]:
        csha = _canonical_sha({"proposal_key": proposal_key, "claim": claim,
                               "lane": lane})
        with self.manager.open() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO ext_research_proposals
                   (proposal_key,instrument,lane,claim,novelty_rationale,
                    data_requirements_json,falsification_criteria,evidence_json,
                    source_ids_json,governance_status,created_at_utc,content_sha256)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (proposal_key, instrument, lane, claim, novelty_rationale,
                 json.dumps(data_requirements or []), falsification_criteria,
                 json.dumps(evidence or {}, sort_keys=True), json.dumps(source_ids or []),
                 governance_status, created_at_utc, csha))
            conn.commit()
            if cur.rowcount:
                self._audit(conn, "INSERT_ext_research_proposals",
                            "ext_research_proposals", csha)
                conn.commit()
                return {"id": int(cur.lastrowid), "inserted": True, "content_sha256": csha}
            return {"id": None, "inserted": False, "content_sha256": csha}

    def list_research_proposals(self) -> List[Dict[str, object]]:
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM ext_research_proposals ORDER BY id").fetchall()]

    # ---------------------------------------------------------------------- #
    # Audit / integrity
    # ---------------------------------------------------------------------- #
    def audit_log(self) -> List[Dict[str, object]]:
        with self.manager.open() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM ext_audit_log ORDER BY id").fetchall()]

    def count(self, table: str) -> int:
        allowed = {
            "ext_raw_records", "ext_economic_events", "ext_central_bank_docs",
            "ext_news_records", "ext_cross_market_observations",
            "ext_fundamental_findings", "ext_event_responses",
            "ext_source_snapshots", "ext_research_proposals", "ext_audit_log",
        }
        if table not in allowed:
            raise ValueError(f"unknown table: {table}")
        with self.manager.open() as conn:
            return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])

    def schema_version(self) -> Optional[int]:
        with self.manager.open() as conn:
            try:
                row = conn.execute(
                    "SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            except Exception:
                return None
        return int(row["v"]) if row and row["v"] is not None else None

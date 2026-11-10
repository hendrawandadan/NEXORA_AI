# FINAL REPORT — NEXORA External Information Intelligence V1

**System:** `NEXORA_EXTERNAL_INFORMATION_INTELLIGENCE` (V1)
**Package:** `nexora_research/external_intelligence/`
**Operating mode:** DRY-RUN, offline-capable, isolated database.
**Governance:** respects NEXORA-GOV-PRD-001 (Price-Derived lane stays SUSPENDED).
**Test status:** 92 new tests green (offline); full suite 626 passed (was 534 pre-change, +92).

---

## 0. HONEST BOTTOM LINE (read this first)

This build **does** operate as an autonomous external-information intelligence layer:
it discovers/document sources, normalises economic events, central-bank documents and
news into an append-only, provenance-tagged, content-hashed isolated repository, produces
evidence-grounded fundamental interpretations, studies cross-market relationships,
measures event→market response without look-ahead, and turns novel findings into
**testable, falsifiable research proposals** routed through the existing Tahap-C registry
and governance gates (INFO_ACQUISITION lane only).

**But building the pipeline is NOT evidence of a trading edge.** No claim of profit,
predictive edge, or profitability is made anywhere. Every event-response, fundamental
and cross-market association produced here is an **UNVALIDATED research lead**. Turning a
lead into knowledge requires pre-registered, leakage-controlled, walk-forward validation
with human authorization — which this system does **not** do automatically.

The honest status: **capability: implemented; edge: none demonstrated.**

---

## 1. What was actually built (verified, not just reported)

| Component | File | What it really does |
|---|---|---|
| Config (isolation + safe flags) | `config.py` | Separate DB path (`nexora_external_intel.db`); all dry/off flags; env-only secrets. |
| Source registry (§A2) | `source_registry.py` | 22 documented providers, 3 tiers, license/rate/reliability/ToS fields. |
| Connectors (§A3) | `connectors.py` | Interface + Mock (offline, SYNTHETIC-tagged) + FRED/RSS adapters; fail-closed status enum; timeout/retry/rate-limit. |
| Repository (§A4) | `repository.py` + `migrations/001__…sql` | Isolated SQLite, append-only, content-hashed, audited, schema-versioned, dedup, validation. |
| Fundamental intelligence | `fundamental_intelligence.py` | Event taxonomy + surprise interpretation; **never** invents actual/consensus. |
| Central-bank intelligence | `central_bank_intelligence.py` | Heuristic hawkish/dovish tone (confidence + evidence), policy-shift detection, rate-expectation signal. |
| News intelligence | `news_intelligence.py` | Category classification, country/currency mapping, entity extraction, dedup, reliability. |
| Cross-market intelligence (§A6) | `cross_market_intelligence.py` | Correlation / rolling / breakdown / lead-lag / regime-split — **association only**, with causation caveat on every result. |
| Event-response intelligence | `event_response.py` | Leakage-aware multi-horizon returns (pre=before, post=at/after horizon); invalid when data insufficient. |
| New-information discovery (§A7) | `new_information.py` | Detects novelty → emits falsifiable proposals (claim, why-different, data needs, hypothesis, falsification, leakage risks, governance). |
| Research bridge (§A7) | `research_bridge.py` | Persists proposals; converts to `GeneratedHypothesis`; registration is **opt-in** and gated by pre-registration + governance. |
| Orchestrator | `orchestrator.py` | One-call pipeline; returns concrete `IntelReport` with honest bottom line. |
| Registry dump tool | `tools/external_intel_registry.py` | Emits `reports/external_intelligence/external_source_registry.json`. |

---

## 2. Data-source inventory (tiers, free/paid, limitations)

Emitted machine-readable at `reports/external_intelligence/external_source_registry.json`.
Summary: **14 OFFICIAL**, **3 FINANCIAL_DATA**, **5 NEWS**; **6 connectors wired** in this
build (FRED, ECB data, ECB press, Fed press, FRED-yields, NewsAPI placeholder).

**Tier 1 (official):** FRED, ECB Data, ECB Press, Fed Press, BoJ/BoE (docs only), BLS,
BEA, Eurostat, US Treasury, IMF, World Bank, BIS, OECD.
**Tier 2 (financial data):** Trading Economics (paid consensus), FRED yields, Nasdaq Data Link.
**Tier 3 (news):** Reuters (RSS only), FT (headline RSS), CNBC, Bloomberg (**paid; not
reachable; do not scrape**), NewsAPI (aggregator).

**Honest data limitations (documented, enforced):**
- Several providers are documented but **not connected** in this build
  (`connector_available=False`); using them raises `NotImplementedError` (fail-closed).
- **Consensus/forecast values are third-party** and may be absent; when absent the system
  says so rather than inventing a surprise.
- **Revision history matters**: using revised values in backtests is look-ahead. The system
  stores `revised_previous` separately and flags contradictory revisions.
- **Bloomberg/FT/Reuters article bodies are licensed** — only RSS/headline use is allowed;
  scraping is explicitly disallowed in the registry (`tos_safe_to_scrape=False`).
- Real connectors require env credentials (`NEXORA_FRED_API_KEY`, etc.); without them they
  return `UNAVAILABLE`, never fabricated data.

---

## 3. Database design (isolated, append-only)

`database/nexora_external_intel.db` — **distinct** from `nexora_state.db` (production) and
`nexora_research.db` (research). A hard guard raises `IsolationViolation` if pointed at
either. Tables: raw records, economic events, central-bank docs, news, cross-market
observations, fundamental findings, event responses, source snapshots, research proposals,
and an audit log. Every row carries `content_sha256` + `retrieved_at_utc` + `source_provider`
+ `data_quality`; corrections are new rows (`supersedes_id`), never in-place updates.

---

## 4. Interpretations produced (honest, evidence-bounded)

- **Fundamentals:** surprise = actual − forecast *only when both present*; confidence scales
  with data completeness and drops on contradictory revisions. Implications are labelled
  "stylised conditional tendencies; correlation is not causation".
- **Central bank:** tone is a heuristic with confidence + matched lexicon as evidence, not a
  fact ("UNKNOWN rather than guessed" when no markers). Policy shift compares latest vs
  previous (explicit rate change is the strongest signal).
- **News:** keyword classification + country/currency mapping + coarse impact + reliability
  from the registry; duplicates collapsed by headline similarity, original id referenced.
- **Cross-market:** correlation ≠ causation caveat is attached to *every* result; refuses on
  too-few observations; can flag regime-dependent breakdowns.

---

## 5. New-information proposals (mission-critical)

Each proposal (`new_information.ResearchProposal`) states: new information, why it differs
from prior knowledge, market relevance, required data, a testable hypothesis, **falsification
criteria**, leakage risks, and governance status. Proposals target **INFO_ACQUISITION only**;
none re-open or launder the suspended price-derived lane. A proposal is **not** a signal and
cannot be auto-registered.

---

## 6. Research-memory integration

`research_bridge` persists proposals to the isolated DB always; **registration is opt-in**
(`register=True` + a `ResearchMemoryStore`). Even when registering, it uses the existing
`pre_register` + `register_experiment_for`, which **creates** a hypothesis/experiment but does
**not** train or evaluate. A `STRATEGY_LEAD` knowledge entry points back to the external
proposal. Default call writes **nothing** to research memory.

---

## 7. Governance compliance (fail-closed, tested)

- Price-Derived lane (NEXORA-GOV-PRD-001) stays **SUSPENDED**; `train`, `promote_model`,
  `enable_live_trading`, `auto_reopen` remain blocked (verified by tests).
- Only INFO_ACQUISITION proposals are emitted; blocked proposals are never registered.
- No training / promotion / live trading / production access / auto-reopen anywhere.
- External text treated as **untrusted data**; never executed.
- Secrets read from env only; never logged nor persisted; public config contains no secret.

---

## 8. Dry-run / isolation verification

- `test_isolation.py` hashes `nexora_state.db` and `nexora_research.db` before/after a full
  orchestrator run and asserts **byte-identical** — production/research DBs untouched.
- `ExternalKnowledgeRepository` refuses to open either protected DB.
- Default `ExternalIntelConfig` is dry-run with every dangerous flag False.

---

## 9. Tests & reproducibility

```
.\.venv\Scripts\python.exe -m pytest tests/external_intelligence -q      # 92 passed
.\.venv\Scripts\python.exe -m pytest tests -q                            # 626 passed
.\.venv\Scripts\python.exe tools/external_intel_registry.py             # registry dump
```

Coverage maps to the required areas (92 tests):
- Source discovery: `test_source_discovery.py` (15)
- Data validation + isolation: `test_repository.py` (18) + `test_isolation.py` (2)
- Intelligence (fundamental/CB/news/cross-market/event-response): `test_intelligence.py` (33)
- New-info + research-memory + governance + dry-run: `test_integration_governance.py` (20)
- End-to-end orchestration: `test_orchestrator.py` (4)
- Final report: this document

---

## 10. Recommended next steps (explicitly NOT edge)

1. Wire real, authenticated Tier-1 connectors (FRED, ECB, BLS/BEA) and ingest **point-in-time**
   history (ALFRED as-of) to avoid look-ahead.
2. Add a proper release-timestamp alignment layer (embargo/delay) before any event-response
   study over real data.
3. For each INFO_ACQUISITION proposal: pre-register → leakage-controlled, purged/embargoed
   walk-forward → net-of-cost evaluation → **user authorization** before any training.
4. Treat every surviving lead with the same honesty bar already applied to the price-derived
   lane: if it is not stable and net-of-cost positive OOS, close it and record a dead-end.

**No profitability, no guaranteed edge, no autonomous trading is claimed or enabled.**

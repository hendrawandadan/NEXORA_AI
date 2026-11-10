# Tahap D — Autonomous Research Control Loop : Implementation Report

**Status:** ✅ Selesai (implementasi + tes). Non-produksi. Isolated.
**Referensi desain:** `AUTONOMOUS_RESEARCH_ARCHITECTURE.md` (§2 state machine, §4 Tahap D, §5 guardrails).
**Tes:** `tests/test_control_loop.py` → **12 lulus**. Full suite: **520 passed** (tanpa regresi).

---

## 1. Apa yang dibangun

**Orkestrasi** (kemampuan "sistem saraf") yang menyatukan komponen Tahap A/B/C menjadi
satu **gated state machine** — tanpa side-effect produksi.

### File baru
- `nexora_research/control_loop.py`
  - `run_control_loop(...)` — menjalankan satu instrumen melewati seluruh fase.
  - `Phase` (enum) — status transisi.
  - `HypothesisOutcome`, `LoopReport` — hasil terstruktur (serializable).
  - `assert_loop_is_allowed()` — preflight: memastikan aksi terlarang tetap diblokir.
- `nexora_research/__init__.py` — expose `control_loop`.
- `tests/test_control_loop.py` — 12 tes.

### State machine (tiap transisi lewat gate; tidak ada yang bisa melompati gate)

```
OBSERVE ──gate: data-quality──► HYPOTHESIZE ──gate: pre-registration──►
   per hipotesis:
      EXPERIMENT_SPEC
        ├─ gate: feasibility-economics ──fail──► SKIPPED_INFEASIBLE
        ├─ gate: governance           ──fail──► BLOCKED_GOVERNANCE
        └─ ok ──► READY_FOR_CONFIRMATORY_EXPERIMENT   (keputusan riset, BUKAN profit)
      dead-end/duplicate ──► FAILURE_LEARNING
   …… ──► KNOWLEDGE_MEMORY (hanya saat non-dry-run)
```

---

## 2. Guardrail yang DIENFORCE (bukan sekadar dokumen)

| Guardrail (§5) | Implementasi |
|---|---|
| **Feasibility-before-training** | `_feasibility_ok()` — hipotesis tak-layak → `SKIPPED_INFEASIBLE`, tidak lanjut |
| **Governance (NEXORA-GOV-PRD-001)** | `_governance_gate()` memanggil `is_candidate_suspended()` → kandidat tersuspensi → **`BLOCKED_GOVERNANCE`** |
| **Max verdict = research decision** | Fase tertinggi `READY_FOR_CONFIRMATORY_EXPERIMENT`; **tidak pernah** `GO`/`LIVE`/`PROMOTED`/`PROFIT` |
| **Failure must teach** | dead-end/duplicate → `FAILURE_LEARNING` (bukan diam-diam diulang) |
| **Immutable memory** | memakai `ResearchMemoryStore` Tahap A (append-only, hashed) |
| **No production side-effects** | tidak menulis `models/`, tidak menyentuh `nexora_state.db`, hanya DB riset terpisah |
| **No training (Tahap D)** | loop berhenti di *keputusan*; training = Tahap F (out of scope) |

**Bukti governance bekerja end-to-end (dari smoke test):**

| Instrumen | Hipotesis | Fase |
|---|---|---|
| XAUUSD D1 h2 | R_HORIZON_FEASIBLE | **BLOCKED_GOVERNANCE** (suspended) |
| XAUUSD H4 h12 | R_HORIZON_FEASIBLE | **BLOCKED_GOVERNANCE** (suspended) |
| EURUSD H4 h12 | R_HORIZON_FEASIBLE | **BLOCKED_GOVERNANCE** (suspended) |
| EURUSD (M30/H1/h4/h8/h24/h48) | R_HORIZON_FEASIBLE / R_CROSS_TF | READY_FOR_CONFIRMATORY_EXPERIMENT |

→ Loop otonom **tidak dapat** menjadwalkan riset pada kandidat price-derived yang
tersuspensi. Guardrail berfungsi persis pada triple (instrument, timeframe, horizon).

---

## 3. Sifat non-produksi (diverifikasi tes)

- **`dry_run=True`** → **tidak menulis apa pun** ke `database/nexora_research.db`
  (tes `test_dry_run_does_not_touch_research_db`: ukuran file tak berubah).
- **`dry_run=False` + store** → menulis ke DB riset **terpisah** (tes `test_non_dry_run_persists_to_store`).
- **Tidak** menyentuh `models/`, `nexora_state.db`, `reports/fase2a/`, `reports/t3/`
  (git status protected dirs = kosong).

---

## 4. Hasil smoke test pada data NYATA

- **EURUSD** (via `horizon_discovery.json`): 10 hipotesis → `READY_FOR_CONFIRMATORY_EXPERIMENT`,
  1 → `BLOCKED_GOVERNANCE` (H4 h12). Max verdict = `READY_FOR_CONFIRMATORY_EXPERIMENT`.
- **XAUUSD** (via `instrument_discovery.json`): semua hipotesis (D1 h2, H4 h12) →
  `BLOCKED_GOVERNANCE`. Max verdict = `BLOCKED_GOVERNANCE`.

Tidak ada klaim profit. "READY_FOR_CONFIRMATORY_EXPERIMENT" = *keputusan* bahwa hipotesis
layak diuji secara confirmatory (walk-forward + net-of-cost), **bukan** hasil lolos.

---

## 5. Yang BELUM (di luar Tahap D)

- **Eksekusi training nyata** = **Tahap F** (butuh izin manusia terpisah). Tahap D sengaja
  tidak latih/evaluasi.
- **Scheduler cadence** (harian/mingguan) belum dijadwalkan otomatis — loop callable manual.
- **Strategy Evolution (Tahap E)** belum dibangun.

---

## 6. Kesimpulan

Tahap D menghadirkan **orkestrasi riset otonom yang aman & ter-gate**:
Observasi → Hipotesis (pre-registered) → Spesifikasi Eksperimen → **gate feasibility** →
**gate governance** → keputusan riset (`READY_FOR_CONFIRMATORY_EXPERIMENT` / `BLOCKED_GOVERNANCE`
/ `SKIPPED_INFEASIBLE` / `FAILURE_LEARNING`). Tidak ada training, tidak ada promosi, tidak ada
live, dan **kandidat tersuspensi diblokir otomatis**. Ini partner riset disiplin — bukan
generator klaim untung.

# NEXORA — Autonomous Research Architecture (Design)

**Status:** Proposal / design only. Tidak ada kode diimplementasikan. Dokumen untuk
direview sebelum dibangun. Konsisten dengan disiplin riset NEXORA yang sudah ada
(read-only discovery → pre-registration → experiment → freeze → verify; anti-lookahead;
tidak overclaim profitabilitas).

**Tujuan:** 8 kemampuan yang diminta sebagai satu loop riset otomatis yang **menjaga
integritas metodologi**, bukan "AI yang langsung trading". Inti prinsip:

> Menemukan peluang dulu → akuisisi informasi → latih hanya jika bukti membenarkan.
> Kegagalan harus MENGHASILKAN pengetahuan, bukan diam-diam diulang.

---

## 1. Pemetaan: yang diminta vs yang SUDAH ADA

| # | Kemampuan | Status saat ini | Modul yang ada | Gap utama |
|---|---|---|---|---|
| 1 | Market Observation | 🟡 Parsial | `nexora_datahub` (loader/audit), `nexora_laboratory/regime.py`, `data_validation.py` | Penjadwalan berkala + ringkasan kondisi pasar yang tersimpan |
| 2 | Hypothesis Generation | 🔴 Belum | (desain di `opportunity_discovery`) | Generator hipotesis terstruktur + registri hipotesis |
| 3 | Experiment Creation | 🟡 Parsial | `nexora_laboratory/adaptive_experiment.py`, `primary_model.py`, `triple_barrier.py` | "Compiler" hipotesis → spesifikasi eksperimen (pre-registered) |
| 4 | Automatic Training | 🟡 Parsial | `nexora_learning/pipeline.train_one`, `train_all`, `batch1_execution_runner.py` | Pemicu otomatis berbasis keputusan (bukan manual) |
| 5 | Performance Evaluation | 🟡 Kuat (gross) | `nexora_evaluator/*`, `directional_edge_audit.py`, `cost_engine.py`, `break_even.py` | Rantai end-to-end net-of-cost otomatis + verdict |
| 6 | Failure Learning | 🟡 Parsial | `directional_edge_audit`, `event_attribution.py` | Klasifikasi SEBAB kegagalan + knowledge capture otomatis |
| 7 | Knowledge Memory | 🟡 Fondasi ada | `experiment_freeze.py` (manifest+verify), `nexora_state_db` (repos) | Registri pengetahuan lintas-eksperimen yang query-able |
| 8 | Strategy Evolution | 🔴 Belum | — | Usulan turunan strategi dari memori + hipotesis baru |

**Kesimpulan:** fondasi evaluasi (5), freeze/verifikasi (7), dan pipeline training (4)
sudah cukup kuat. Yang perlu dibangun terutama: **orkestrasi** (`nexora_scheduler` yang
masih kosong), **registri hipotesis & pengetahuan**, dan **mesin keputusan** yang
mengikat semuanya dengan gate metodologis.

---

## 2. Arsitektur: "Research Control Loop"

Delapan kemampuan disusun sebagai **state machine** yang digerakkan scheduler, dengan
setiap transisi melewati **gate** (gerbang validasi). Tidak ada langkah yang bisa
melompati gate.

```
           ┌──────────────────────────────────────────────────────────────┐
           │                    NEXORA RESEARCH CONTROL LOOP               │
           └──────────────────────────────────────────────────────────────┘

 (1) MARKET OBSERVATION ──► datanya bersih? ──gate: data-quality──►
        │
        ▼
 (2) HYPOTHESIS GENERATION ─► spesifik & falsifiable? ─gate: pre-registration─►
        │
        ▼
 (3) EXPERIMENT CREATION ──► benar & bebas lookahead? ─gate: no-leakage/lint─►
        │
        ▼
 (4) AUTOMATIC TRAINING ──► perlu latih? & lulus split? ─gate: economics-feasibility─►
        │                       (jika move/cost tak layak → SKIP ke (6), hemat biaya)
        ▼
 (5) PERFORMANCE EVALUATION ─► net-of-cost + CI bootstrap ─► verdict GO/NO-GO
        │
        ├── NO-GO ──► (6) FAILURE LEARNING ──► (7) KNOWLEDGE MEMORY
        │                                            │
        └── GO ─────────────────────────────────────┤
                                                     ▼
                                    (8) STRATEGY EVOLUTION ──► usul strategi turunan
                                                     │
                                                     └──► hipotesis baru balik ke (2)
```

**Prinsip kunci:** loop ini **tidak pernah** langsung mempromosikan ke produksi. Output
tertinggi adalah **`READY_FOR_CONFIRMATORY_EXPERIMENT`**, sama seperti disiplin yang
sudah dipakai di `opportunity_discovery`. Promosi ke live trading adalah keputusan
manusia terpisah.

---

## 3. Detail tiap kemampuan (kontrak perilaku)

### (1) Market Observation
- **Perilaku:** secara berkala (mis. harian/mingguan) memuat data terbaru, menghitung
  kondisi pasar (volatilitas, sesi, spread bila ada tick, regime), dan menulis
  **MarketSnapshot** ke state DB.
- **Gate:** data-quality (missing %, duplikat, granuralitas — pakai
  `opportunity_discovery.granularity` + `datahub.audit`). Snapshot buruk → ditandai,
  tidak dipakai untuk hipotesis.
- **Reuse:** `datahab.loader`, `audit`, `regime.py`.
- **Output:** `MarketSnapshot` (SQLite `nexora_state_db`), JSON ringkasan.

### (2) Hypothesis Generation
- **Perilaku:** dari snapshot + memori pengetahuan, mengusulkan hipotesis
  **terstruktur & falsifiable**. Contoh format:
  `{instrument, timeframe, horizon, kondisi pasar, sinyal sumber, klaim terukur, kriteria GO/NO-GO}`.
- **Gate: PRE-REGISTRATION (wajib).** Hipotesis harus ditulis dulu (hash + timestamp)
  SEBELUM eksperimen dijalankan — persis disiplin `UPSTREAM_SIGNAL_QUALITY_AUDIT_SCOPE.md`.
  Ini mencegah p-hacking/overfitting.
- **Sumber kandidat hipotesis:** kombinasi dari STAGE 3–6 discovery (mis. "di H4/48h,
  faktor mean-reversion punya IC cukup setelah biaya?"), bukan mengarang bebas.
- **Output:** `HypothesisRecord` (registri), status awal `PROPOSED` → `PRE-REGISTERED`.

### (3) Experiment Creation
- **Perilaku:** menerjemahkan hipotesis menjadi **spesifikasi eksperimen deterministik**:
  dataset, split (train/valid/test + embargo/purge), target, fitur, skenario biaya,
  metrik, kriteria GO/NO-GO (identik dengan yang sudah dipakai).
- **Gate:** (a) **no-leakage / lint** otomatis — pakai tes anti-leakage yang sudah ada
  (`tests/test_purge_boundary.py`, `test_nexora_execution_safety_freeze.py`);
  (b) hipotesis harus sudah `PRE-REGISTERED`.
- **Reuse:** `adaptive_experiment.py`, `primary_model.py`, `pipeline.split_indices`.
- **Output:** `ExperimentSpec` (JSON, di-hash) → `ExperimentRecord` status `CREATED`.

### (4) Automatic Training
- **Perilaku:** menjalankan training HANYA jika eksperimen "memang memerlukannya".
  **Sebelum training, jalankan gate feasibility ekonomi** (dari `opportunity_discovery`):
  jika move-to-cost ratio & required-accuracy tak layak secara struktural → **SKIP**
  training (hemat biaya, langsung ke Failure Learning dengan sebab
  `STRUCTURAL_INFEASIBILITY`). Ini menghormati pelajaran dari audit EURUSD M30.
- **Gate:** (a) feasibility-economics pre-check; (b) cukup data & 2 kelas; (c) split valid.
- **Reuse:** `nexora_learning.train_one`, `create_model`, `batch_checkpoint_manager.py`
  (checkpointing sudah ada).
- **Output:** artefak di `models/...`, signals, report — status `TRAINED`.

### (5) Performance Evaluation
- **Perilaku:** evaluasi **net-of-cost** (bukan gross). Rantai: gross execution evaluator
  (`t3_evaluation`) → kurangi biaya (`cost_engine`, `event_attribution.add_net_and_meta`)
  → audit edge (`directional_edge_audit`: AUC-net, monotonicity, threshold grid) →
  **block bootstrap CI** (`feature_power._block_bootstrap_ic`).
- **Gate:** verdict hanya GO jika: AUC-net > ambang, bucket monoton, ada threshold
  total-net > 0, DAN lower-bound CI > 0. (Menolak "menang kebetulan".)
- **Output:** `EvaluationResult` + verdict `GO` / `NO-GO` + alasan terukur.

### (6) Failure Learning
- **Perilaku:** saat NO-GO, **mengklasifikasikan sebab** secara terstruktur. Tipe kegagalan:
  - `DATA_QUALITY` (granuralitas, gap, spread jarang)
  - `STRUCTURAL_INFEASIBILITY` (move ≪ cost; required-acc tak terjangkau)
  - `NO_PREDICTIVE_POWER` (fitur tak punya IC OOS — `feature_power`)
  - `EDGE_BELOW_COST` (ada IC tapi magnitudo < biaya — pelajaran EURUSD)
  - `OVERFIT` (train bagus, test buruk / tidak stabil walk-forward)
  - `REGIME_FRAGILE` (gagal di sebagian regime/tahun)
- **Gate:** tiap kegagalan **wajib** menghasilkan hipotesis-tindak-lanjut atau alasan
  "dead-end terdokumentasi". Tidak boleh NO-GO tanpa penjelasan.
- **Reuse:** `directional_edge_audit`, `feature_power`, hasil `opportunity_discovery`.
- **Output:** `FailureRecord` (sebab + bukti + rekomendasi).

### (7) Knowledge Memory
- **Perilaku:** menyimpan SEMUA hasil (GO & NO-GO) secara query-able + immutable
  (provenance via `experiment_freeze.build_freeze_manifest` + `verify_manifest`).
- **Gate:** entri tak bisa dihapus/ditimpa; perubahan = entri baru berversi.
- **Reuse:** `nexora_state_db` (repositori), `experiment_freeze` (hash+verify).
- **Output:** tabel `hypotheses`, `experiments`, `evaluations`, `failures`,
  `knowledge_entries` + **manifest SHA256** tiap entri.

### (8) Strategy Evolution
- **Perilaku:** dari memori pengetahuan, **mengusulkan strategi turunan** — mis.
  variasi horizon/instrument/regime-conditioning yang mengeksploitasi faktor yang
  TERBUKTI punya IC, atau menyusun ulang kriteria untuk menghindari kegagalan lampau.
  Output: hipotesis baru terstruktur (kembali ke (2)).
- **Gate:** usulan harus merujuk bukti (tidak boleh "mengarang"); dan tidak boleh
  mengulang kombinasi yang sudah tercatat gagal kecuali ada perubahan tercatat.
- **Reuse:** query ke Knowledge Memory.
- **Output:** `StrategyProposal` → Hypothesis baru.

---

## 4. Ruang lingkup implementasi bertahap (phased, minimal risk)

**Semua tahap tetap READ-ONLY terhadap produksi** kecuali tahap yang eksplisit menulis
state DB *baru* (bukan DB produksi). Tiap tahap punya deliverable + tes sendiri.

| Tahap | Isi | Menulis ke | Risiko |
|---|---|---|---|
| **A** | Knowledge Memory + registri (tabel SQLite baru `nexora_state_db`) + wrapper freeze/verify | DB state baru | Rendah |
| **B** | Failure Learning classifier (fungsi murni) + tes | JSON/DB state | Rendah |
| **C** | Hypothesis & Experiment repositories (pre-registration hashing) | DB state | Rendah |
| **D** | Research Control Loop skeleton di `nexora_scheduler` (state machine + gates), tanpa side-effect produksi | DB state | Sedang |
| **E** | Strategy Evolution (query-based proposal generator) | DB state | Sedang |
| **F** | (opsional, terpisah, butuh izin) pemicu training otomatis nyata | `models/` | Tinggi → butuh gerbang manusia |

**Gate keselamatan global (tetap berlaku):** tidak menyentuh DB produksi, tidak retrain
model yang di-freeze, tidak mengubah ATR/R1/PREP-001, tidak menghapus/menimpa report.

---

## 5. Yang menahan "AI liar" (guardrails wajib)

1. **Pre-registration dulu** — hipotesis di-hash sebelum eksperimen; tidak bisa diubah
   belakangan (curang).
2. **Feasibility-before-training** — loop menolak melatih model pada target yang secara
   struktural tak bisa mengalahkan biaya (mencegah pemborosan & overclaim).
3. **Net-of-cost + bootstrap-CI gate** — GO hanya jika lower-CI > 0.
4. **Immutable knowledge + provenance** — semua hasil di-hash & terverifikasi
   (`experiment_freeze`); auditability penuh.
5. **Verdict maksimum = `READY_FOR_CONFIRMATORY_EXPERIMENT`** — tidak pernah otomatis ke
   live. Promosi = keputusan manusia.
6. **Failure must teach** — NO-GO tanpa sebab & rekomendasi ditolak sistem.
7. **Multiple-comparison ledger** — setiap kombinasi yang diuji tercatat (sudah dipraxis).

---

## 6. Keputusan yang perlu persetujuan Anda sebelum implementasi

1. **Ruang lingkup Tahap A–E** (semua non-produksi) — setuju dimulai dari **Tahap A
   (Knowledge Memory)**? Ini fondasi yang dipakai semua tahap lain.
2. **Storage:** gunakan **SQLite state baru** (`database/nexora_research.db`) terpisah
   dari DB produksi — atau JSON-file registry dulu? (rekomendasi: SQLite baru, terpisah).
3. **Generator hipotesis (2) & evolusi (8):** murni **deterministik berbasis aturan+bukti**
   dulu (rekomendasi, agar teraudit), atau boleh memakai LLM untuk brainstorming hipotesis
   (perlu guardrail ketat + pre-registration tetap wajib)?
4. **Scheduler cadence:** harian untuk observasi, mingguan untuk batch eksperimen? Atau
   manual-trigger dulu sampai loop terbukti?
5. **Urutan:** setelah A (Knowledge Memory), mau lanjut B (Failure Learning) atau C
   (Hypothesis/Experiment registry)?

---

## 7. Ringkasan satu paragraf

NEXORA sudah punya "organ" yang tepat — evaluasi biaya, freeze/verify, pipeline training —
tetapi belum punya "sistem saraf" yang menyambungkannya menjadi loop riset otonom yang aman.
Yang dibangun bukan model baru, melainkan **orkestrasi + memori + gerbang metodologis**:
Observasi → Hipotesis (pre-registered) → Eksperimen → (latih hanya jika layak) → Evaluasi
net-of-cost → Belajar dari gagal → Simpan pengetahuan → Usul evolusi. Dengan enam
guardrail di §5, kemampuan ini menjadi partner riset yang disiplin, bukan generator klaim
untung palsu.

# P2 — LANE SCHEMA & POINT-IN-TIME DATA AUDIT (READ-ONLY)

**Status: AUDIT ONLY. Tidak ada migrasi, tidak ada training, tidak ada perubahan DB,
tidak ada live acquisition, PRICE_DERIVED tetap SUSPENDED, ATR baseline tidak berubah.**
**Keputusan implementasi MENUNGGU PERSETUJUAN.**

**Acuan:** `docs/MASTER_ROADMAP.md` §3a, `GOVERNANCE_DECISION_PRD_001.md`,
`reports/external_intelligence/ROADMAP_ALIGNMENT_AUDIT.md` (P0/P1), 
`nexora_research/migrations/001__research_memory_schema.sql`,
`nexora_research/external_intelligence/migrations/001__external_intel_schema.sql`.

**Metode:** verifikasi schema nyata (PRAGMA table_info), pembacaan kode jalur nyata
(store, repository, orchestrator, event_response, research_bridge, control_loop),
dan inspeksi data aktual (read-only) di DB terisolasi.

---

## 0. RINGKASAN EKSEKUTIF

| Area | Temuan inti | Severity |
|---|---|---|
| **P2-A Lane** | `research_hypotheses`/`research_experiments`/`research_knowledge`/`research_failures`/`research_evaluations` **TIDAK punya kolom `lane`**. Lane hanya hidup di `go_criteria_json` (JSON) atau di default Python. Tidak ter-query, tidak ter-enforce di skema. | **HIGH** |
| **P2-A Lane** | `ext_research_proposals.lane` ada, tetapi tidak ada `CHECK` constraint → lane bebas (laundering di level DB). | **MEDIUM** |
| **P2-A Lane** | Failure & evaluation tidak membawa lane sama sekali. Lane hilang di akhir pipeline (failure_learning / evaluation). | **HIGH** |
| **P2-B PIT** | `ext_economic_events` hanya punya `scheduled_ts` + `retrieved_at_utc`. **Tidak ada `available_at` (release embargo), tidak ada `vintage`/`revision_as_of`/`ingested_at` vs `published_at`.** Hanya 1 timestamp "fakta"; tidak bisa membedakan ketersediaan historis vs ingestion. | **CRITICAL** |
| **P2-B PIT** | `event_response` memakai `scheduled_ts` sebagai event_ts; response `computed_at_utc` bisa jauh setelah event (dibuktikan: event 2026-01-15, response dihitung 2026-11-10). | **HIGH** |
| **P2-B PIT** | News/CB hanya `published_ts` + `retrieved_at_utc`; tidak ada `available_at`/embargo/koreksi. | **HIGH** |
| **P2-B PIT** | `data_quality='UNVERIFIED'` dan `is_synthetic` ada tapi tidak dipakai sebagai gate anti-look-ahead di bridge/evaluator. | **HIGH** |

**Kesimpulan:** P1 menutup *bypass governance*. P2 menemukan bahwa **lane tidak
terstruktur di skema** (JSON-only) dan **data eksternal TIDAK point-in-time safe**
hanya dari keberadaan timestamp. Keduanya harus diperbaiki **sebelum** ada klaim
backtest dari data fundamental/berita.

---

## 1. SCHEMA INVENTORY

### 1.1 Research Memory DB (`database/nexora_research.db`)

| Tabel | Kolom lane? | Timestamp | Catatan |
|---|---|---|---|
| `research_hypotheses` | ❌ **TIDAK** (lane hanya di `go_criteria_json`) | `created_at` | Lokasi lane "implisit" = JSON |
| `research_experiments` | ❌ **TIDAK** | `created_at` | Lane harus diwarisi dari hypothesis; tidak disimpan |
| `research_evaluations` | ❌ **TIDAK** | `created_at` | Verdict GO/NO_GO tanpa lane |
| `research_failures` | ❌ **TIDAK** (`evidence_json`) | `created_at` | Failure learning tanpa lane |
| `research_knowledge` | ❌ **TIDAK** (`kind` ∈ FINDING/CONSTRAINT/DEAD_END/STRATEGY_LEAD) | `created_at` | `STRATEGY_LEAD` dipakai untuk external, tapi tak ada kolom lane |
| `schema_migrations` | n/a | `applied_at` | — |

> **Bukti `PRAGMA table_info(research_hypotheses)`:** `id, hypothesis_key, instrument,
> timeframe, horizon_bars, market_condition, signal_source, claim, go_criteria_json,
> content_sha256, status, created_at`. **Tidak ada `lane`.**

### 1.2 External Intel DB (`database/nexora_external_intel.db`)

| Tabel | Kolom lane? | Timestamp yang ada | Timestamp yang HILANG (PIT) |
|---|---|---|---|
| `ext_raw_records` | ❌ | `retrieved_at_utc` | `published_at` sumber |
| `ext_economic_events` | ❌ | `scheduled_ts`, `retrieved_at_utc` | **`available_at`**, `vintage`/`revision_as_of`, `published_at` asli vs `ingested_at` |
| `ext_central_bank_docs` | ❌ | `published_ts`, `retrieved_at_utc` | **`available_at`** (embargo), `revision` |
| `ext_news_records` | ❌ | `published_ts`, `retrieved_at_utc`, `event_ts` | **`available_at`**, `first_observed_at` |
| `ext_cross_market_observations` | ❌ | `computed_at_utc` | jendela observasi `as_of` |
| `ext_fundamental_findings` | ❌ | `created_at_utc` | — (derivatif, tergantung event) |
| `ext_event_responses` | ❌ | `computed_at_utc` (+ implisit `scheduled_ts` event) | `as_of` price bar, `event_available_at` |
| `ext_source_snapshots` | ❌ | `captured_at_utc` | — |
| `ext_research_proposals` | ✅ `lane` (default `INFO_ACQUISITION`, **tanpa CHECK**) | `created_at_utc` | — |
| `ext_audit_log` | n/a | `created_at_utc` | — |

### 1.3 Production DB (`database/nexora_state.db`) — referensi, TIDAK diaudit isinya
Tidak disentuh. Tidak ada lane/timestamp research di sini (di luar scope riset).

---

## 2. LANE CONSISTENCY MATRIX (P2-A)

Legenda: ✅ lane ada & terstruktur & ter-enforce · ⚠️ lane ada tapi lemah (JSON/no CHECK) ·
❌ lane tidak ada / hilang.

| Stage / Artefak | Disimpan di | Lane terstruktur? | Nilai lane aktual | Risiko |
|---|---|---|---|---|
| `ResearchProposal` (external_intelligence) | objek + `ext_research_proposals.lane` | ⚠️ (kolom ada, **tanpa CHECK**) | `INFO_ACQUISITION` | lane laundering di DB |
| `EvolutionProposal` (strategy_evolution) | objek (tak dipersist ke kolom lane) | ⚠️ (field `lane` objek) | `PRICE_DERIVED` / `INFO_ACQUISITION` | tidak durable |
| `GeneratedHypothesis` (hypothesis_generator) | objek | ❌ (tak punya field lane) | implisit price-derived | lane hilang saat dibuat |
| `research_hypotheses` (store) | DB | ❌ **kolom tidak ada** | **tidak tersimpan terstruktur** (hanya bila caller menaruh di `go_criteria_json`) | **HIGH: lane tak ter-query** |
| external hypothesis (control_loop `_proposal_to_hypothesis`) | DB via `research_hypotheses` | ⚠️ lane di `go_criteria_json["lane"]` | `INFO_ACQUISITION` | JSON-only, mudah hilang |
| `research_experiments` | DB | ❌ **kolom tidak ada** | diwarisi via `spec_json` | lane tak ter-query |
| `research_evaluations` | DB | ❌ **tidak ada sama sekali** | — | **verdict GO tanpa lane** |
| `research_failures` | DB | ❌ (hanya `evidence_json`) | — | **failure tanpa lane** |
| `research_knowledge` (STRATEGY_LEAD/FINDING/CONSTRAINT/DEAD_END) | DB | ❌ (`kind` bukan lane) | external↔price tak terpisah | **INFO & PRICE tercampur** |

### 2.1 Pencampuran INFO_ACQUISITION vs PRICE_DERIVED
- **Terbukti tercampur** di `research_knowledge`: external proposal disimpan sebagai
  `kind=STRATEGY_LEAD`, sedangkan failure/constraint price-derived juga `STRATEGY_LEAD`
  atau `CONSTRAINT`/`DEAD_END`. **Tidak ada kolom yang membedakan lane** → query
  "semua knowledge INFO_ACQUISITION" **tidak mungkin** tanpa parsing `detail_json`.
- Di `research_hypotheses`, external & price-derived sama-sama 1 tabel; pembeda hanya
  `go_criteria_json["lane"]` (string bebas). Satu record price-derived yang lupa mengisi
  `lane` akan **default dianggap PRICE_DERIVED** oleh control_loop
  (`(hyp.get("go_criteria", {}) or {}).get("lane", "PRICE_DERIVED")`) — *implicit default*.

### 2.2 Lane laundering di level DB
- `ext_research_proposals.lane` **tidak punya CHECK**. Secara skema, nilai apa pun
  diterima (`'PRICE_DERIVED'`, `'X'`, kosong). Saat ini dicegah oleh **kode P1**
  (bridge menolak non-INFO), tetapi **skema tidak menegakkannya**. Defense-in-depth
  hilang di level storage.
- `research_hypotheses` tidak menyimpan lane sama sekali → tidak bisa membuktikan
  dari DB bahwa sebuah hypothesis adalah INFO_ACQUISITION (kecuali buka JSON).

---

## 3. PIT INTEGRITY MATRIX (P2-B)

Legenda: ✅ PIT-safe · ⚠️ sebagian · ❌ tidak PIT-safe / tak dapat diverifikasi.

| Sumber / Artefak | `event_time` | `published_at` (sumber) | `available_at` (embargo) | `ingested_at` (retrieval) | timezone | provenance | PIT-safe? |
|---|---|---|---|---|---|---|---|
| `ext_raw_records` | — | ❌ | ❌ | ✅ `retrieved_at_utc` | UTC (asumsi) | ✅ provider_id/resource | ❌ (tak tahu kapan sumber terbit) |
| `ext_economic_events` | ✅ `scheduled_ts` | ❌ (disamakan dgn scheduled) | ❌ **tidak ada** | ✅ `retrieved_at_utc` | UTC (asumsi) | ✅ source_provider/ref | ❌ **CRITICAL** |
| `ext_central_bank_docs` | ✅ `published_ts` | ✅ (published_ts) | ❌ **tidak ada** | ✅ `retrieved_at_utc` | UTC (asumsi) | ✅ source_ref | ⚠️ (publish ada, embargo tidak) |
| `ext_news_records` | ⚠️ `event_ts` (bisa kosong) | ✅ `published_ts` | ❌ **tidak ada** | ✅ `retrieved_at_utc` | UTC (asumsi) | ✅ source_provider/ref | ⚠️ |
| `ext_event_responses` | ⚠️ via event `scheduled_ts` | n/a | ❌ | ✅ `computed_at_utc` | UTC | via event_id | ❌ (bar `as_of` tak dicatat) |
| `ext_fundamental_findings` | via event | n/a | ❌ | ✅ `created_at_utc` | UTC | ✅ source_ids | ⚠️ |
| `ext_research_proposals` | n/a | n/a | n/a | ✅ `created_at_utc` | UTC | ✅ evidence/source_ids | n/a |

### 3.1 "Historical timestamp dari sumber asli" vs "hasil ingestion"
**Temuan kunci:** schema hanya menyimpan **satu** `retrieved_at_utc` (ingestion) dan
**satu** `scheduled_ts`/`published_ts` (klaim waktu fakta). **Tidak ada** pemisahan:
- `published_at` (kapan sumber menerbitkan) **vs** `ingested_at` (kapan kita ambil)
  **vs** `available_at` (kapan nilai itu benar-benar dapat diketahui pasar — mis.
  embargo rilis CPI: data "Januari" tersedia pada tanggal rilis, bukan tanggal periode).
- **Vintage/revision**: FRED/ALFRED menyediakan revisi; schema menyimpan `revised_previous`
  sebagai angka tetapi **tidak menyimpan `vintage`/`revision_as_of`** → tidak bisa
  merekonstruksi "nilai yang diketahui pada waktu T".

**Bukti data aktual (read-only, DB terisolasi):**
```
EVENT: event_key='US|CPI||2026-01-15T13:30:00Z', scheduled_ts='2026-01-15T13:30:00Z',
       retrieved_at_utc='2026-01-15T13:35:00Z', data_quality='UNVERIFIED', is_synthetic=0
RESP:  horizon='1m', computed_at_utc='2026-11-10T01:40:34Z', valid=1
PROP:  lane='INFO_ACQUISITION', governance_status='ALLOWED'
```
→ event diklaim 2026-01-15, namun response dihitung 2026-11-10. Tidak ada field yang
menyatakan "pada 2026-01-15 13:30 nilai actual/forecast yang *tersedia saat itu* adalah X".
`scheduled_ts` disamakan dengan waktu fakta; **tidak ada jaminan bebas look-ahead.**

### 3.2 Look-ahead leakage pada research bridge & evaluator
- **Research bridge:** hanya memeriksa `governance_status`, lane, rule_id, suspension
  (P1). **Tidak** memeriksa apakah `evidence`/timestamp proposal PIT-safe, atau apakah
  `is_synthetic`/`data_quality` valid. Proposal dari data sintetis/UNVERIFIED bisa lolos
  ke pre-registration sebagai "research lead" (verdict tetap READY, bukan GO — jadi belum
  klaim profit, tapi **basis datanya belum terbukti PIT-safe**).
- **Event-response evaluator (`event_response.py`):** secara desain benar (pre = close
  strictly before event; post = first close ≥ event+horizon; tidak interpolasi). **TAPI**
  ia memakai `event_ts = scheduled_ts`. Bila `scheduled_ts` adalah waktu **periode**
  (bukan waktu **rilis/embargo**), maka bar "pre" bisa sudah memuat informasi rilis →
  look-ahead. **Tidak ada parameter `available_at`** untuk memisahkan ini.
- **Evaluator model (learning pipeline):** sudah punya purge/embargo berbasis bar
  (`purge_bars`, `split_indices`) dan timing contract no-look-ahead untuk fitur harga —
  **aman untuk price-derived**. Namun begitu data **eksternal** dimasukkan sebagai fitur,
  purge berbasis bar **tidak** menangani jam rilis/embargo event → **celah PIT khusus
  data eksternal**.
- **`data_quality` & `is_synthetic`** ada di event/news/CB tetapi **tidak dipakai** sebagai
  gate di bridge/evaluator → data berlabel `UNVERIFIED`/`SYNTHETIC` tidak diblok/ditandai
  saat dirutekan.

---

## 4. RISK REPORT (berdasarkan severity)

### CRITICAL
- **C-1. Tidak ada `available_at` / point-in-time availability pada data eksternal.**
  `ext_economic_events`, `ext_central_bank_docs`, `ext_news_records` menyimpan waktu fakta
  + ingestion, tetapi tidak waktu **ketersediaan pasar** (embargo rilis / revisi).
  Konsekuensi: backtest event/berita **berisiko look-ahead** dan **tidak dapat
  diverifikasi** PIT-safe. (Schema: hanya `scheduled_ts`+`retrieved_at_utc`.)

### HIGH
- **H-1. `lane` tidak terstruktur di research DB.** Tidak ada kolom `lane` di
  `research_hypotheses`/`research_experiments`/`research_evaluations`/`research_failures`/
  `research_knowledge`. Lane hanya di `go_criteria_json` (hypothesis external) atau hilang.
- **H-2. Lane hilang di akhir pipeline.** `research_failures` dan `research_evaluations`
  tidak membawa lane → pengetahuan/verdict tidak dapat dipisah INFO vs PRICE.
- **H-3. INFO_ACQUISITION & PRICE_DERIVED tercampur di `research_knowledge`** (hanya
  dibedakan oleh isi `detail_json`, bukan kolom).
- **H-4. `event_response` menggunakan `scheduled_ts` sebagai event_ts tanpa `available_at`.**
  Risiko look-ahead bila `scheduled_ts` = waktu periode, bukan waktu rilis.
- **H-5. `data_quality`/`is_synthetic` tidak dipakai sebagai gate PIT** di bridge/evaluator.

### MEDIUM
- **M-1. `ext_research_proposals.lane` tanpa `CHECK` constraint** (laundering dicegah hanya
  oleh kode P1, bukan skema).
- **M-2. Timestamp "sumber asli" vs "ingestion" tidak dipisah** secara eksplisit di
  `ext_raw_records` (hanya `retrieved_at_utc`, tidak ada `published_at` sumber).
- **M-3. Vintages/revisi tidak disimpan** (`revised_previous` berupa angka, tanpa
  `vintage`/`revision_as_of`) → tidak bisa rekonstruksi nilai as-of.
- **M-4. Default implisit lane `"PRICE_DERIVED"`** di control_loop untuk hypothesis yang
  tidak menyertakan lane di `go_criteria` → record tanpa lane diperlakukan price-derived
  secara diam-diam (dapat menyembunyikan salah-klasifikasi).

### LOW
- **L-1. Timezone diasumsikan UTC** dari string; validasi hanya rentang (tidak memaksa
  suffix `Z`/offset). Data non-UTC yang salah-format bisa lolos sebagai "naif".
- **L-2. `ext_source_snapshots`/`ext_audit_log` tidak menyimpan versi skema** sumber saat
  capture (minor reproducibility).

---

## 5. PERUBAHAN SCHEMA YANG DIPERLUKAN (USULAN — BELUM DIEKSEKUSI)

> **Semua di bawah adalah USULAN. TIDAK ada migrasi dijalankan. Menunggu persetujuan.**

### 5.1 P2-A — Lane terstruktur
1. **`research_hypotheses`**: tambah kolom `lane TEXT NOT NULL DEFAULT 'PRICE_DERIVED'`
   dengan `CHECK(lane IN ('PRICE_DERIVED','INFO_ACQUISITION'))`. Backfill dari
   `go_criteria_json['lane']` bila ada, else `'PRICE_DERIVED'`.
2. **`research_experiments`**: tambah `lane TEXT` (denormalisasi dari hypothesis untuk
   query cepat) — atau VIEW join. `CHECK` sama.
3. **`research_evaluations`** & **`research_failures`**: tambah `lane TEXT` (warisan dari
   experiment) untuk memisahkan verdict/failure per lane.
4. **`research_knowledge`**: tambah `lane TEXT` (null untuk knowledge non-lane).
5. **`ext_research_proposals.lane`**: tambah `CHECK(lane IN ('INFO_ACQUISITION'))`
   (bridge hanya untuk INFO) atau `CHECK(lane IN ('PRICE_DERIVED','INFO_ACQUISITION'))`
   bila kelak dipakai lebih luas; index `(lane, governance_status)`.
6. Hapus ketergantungan default implisit: `store.register_hypothesis` menerima `lane`
   eksplisit; control_loop membaca kolom `lane` (bukan `go_criteria`), dan **menolak**
   hypothesis tanpa lane (fail-closed) alih-alih default ke PRICE_DERIVED.

### 5.2 P2-B — Point-in-time
1. **`ext_economic_events`**: tambah `published_at_utc` (rilis sumber),
   `available_at_utc` (ketersediaan pasar/embargo), `vintage`/`revision_as_of_utc`,
   `ingested_at_utc` (= `retrieved_at_utc`). Pisahkan tegas `scheduled_ts` (periode) vs
   `available_at_utc` (dapat diketahui).
2. **`ext_central_bank_docs`** & **`ext_news_records`**: tambah `available_at_utc`
   (embargo/jam rilis), `first_observed_at_utc`.
3. **`ext_event_responses`**: tambah `as_of_utc` (bar price yang dipakai), `event_available_at_utc`.
4. **`event_response.measure_event_response`**: terima `available_at` (opsional); gunakan
   `max(event_ts, available_at)` sebagai basis penghitungan pre/post → cegah look-ahead
   bila `scheduled_ts` = periode.
5. **Gate PIT di bridge/evaluator**: tolak/tandai record dengan `is_synthetic=1` atau
   `data_quality IN ('UNVERIFIED','SYNTHETIC','CONFLICTING')` saat dirutekan ke
   pre-registration "confirmatory" (atau setidaknya `data_quality` wajib ada + terlihat
   di audit trail). **Tidak** memblok persisten provenance, tetapi memblok klaim "ready".

---

## 6. REKOMENDASI IMPLEMENTASI BERIKUTNYA (berurutan, belum dikerjakan)

**Fase R1 — Lane schema (P2-A) — LOW RISK, additive migration:**
1. Migration `002__research_lane_columns.sql`: `ADD COLUMN lane` (dengan backfill) ke
   `research_hypotheses`/`research_experiments`/`research_evaluations`/`research_failures`/
   `research_knowledge`; `CHECK` + index.
2. Migration `002__external_lane_check.sql`: `CHECK` pada `ext_research_proposals.lane`.
3. Update `store.register_hypothesis(..., lane)` (+ persist), `registry.pre_register`/
   `register_experiment_for` meneruskan lane, `failure_learning.record`+`evaluation`
   mewarisi lane, `control_loop` membaca kolom `lane` (fail-closed), dan `knowledge`
   menyimpan lane.
4. Tes: lane end-to-end (proposal→hypothesis→experiment→evaluation→failure→knowledge);
   query "INFO vs PRICE" terpisah; lane laundering ditolak skema.

**Fase R2 — PIT schema & producer (P2-B) — MEDIUM RISK:**
1. Migration `003__external_pit.sql`: `available_at_utc`, `published_at_utc`,
   `vintage`/`revision_as_of_utc` pada tabel event/CB/news; `as_of_utc` pada responses.
2. Connector/orchestrator mengisi `available_at_utc` **hanya bila sumber menyediakannya**;
   **jangan** menebak. Bila tidak tersedia → `available_at_utc = NULL` dan
   `pit_verified = 0`, dan record **ditandai** bukan PIT-safe.
3. `event_response` memakai `available_at` (bila ada) untuk basis pre/post.
4. Gate PIT di `research_bridge`/evaluator: `is_synthetic`/`data_quality`/`pit_verified`
   menentukan apakah proposal boleh jadi "confirmatory-ready" vs "provenance-only".
5. Tes: event dengan `available_at` > `scheduled_ts` tidak menghasilkan look-ahead;
   record tanpa PIT ditandai; data sintetis tidak pernah "ready".

**Fase R3 — Validation:**
1. Rekonstruksi as-of query ("nilai yang diketahui pada T") untuk satu event nyata bila
   sumber mendukung (mis. FRED/ALFRED vintage) — **tanpa** live acquisition, memakai
   fixture yang sudah ada.
2. Audit ulang PIT integrity matrix menjadi ✅/⚠️ eksplisit per tabel.

**Prasyarat keras:** R2 (PIT) **harus** ada sebelum backtest apa pun yang memakai data
fundamental/berita, karena timestamp saja **tidak** menjamin PIT-safe (lihat §3).

---

## 7. BATASAN YANG DIPATUHI

- ✅ READ-ONLY: hanya `PRAGMA table_info` + `SELECT` baca + pembacaan kode. Tidak ada
  `INSERT/UPDATE/DELETE/ALTER`.
- ✅ Tidak ada training, tuning, promotion, live trading.
- ✅ Scheduler tidak dijalankan.
- ✅ Tidak ada perubahan DB / migrasi.
- ✅ PRICE_DERIVED tetap SUSPENDED (tidak dibuka).
- ✅ ATR baseline tidak diubah.
- ✅ Tidak ada live acquisition (hanya inspeksi data yang sudah ada).
- ✅ Scope tidak melebar ke implementasi.

**STOP — audit selesai. Menunggu persetujuan sebelum implementasi R1/R2/R3.**

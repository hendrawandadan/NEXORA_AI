# R1 — LANE SCHEMA IMPLEMENTATION REPORT (P2-A REMEDIATION)

**Status: IMPLEMENTED (additive migration + end-to-end wiring). READY FOR REVIEW.**
**Scope: P2-A only (structured lane). P2-B (point-in-time) NOT in this phase.**
**Safety: no training, no evaluation, no promotion, no live trading, no scheduler,
PRICE_DERIVED tetap SUSPENDED. ATR baseline tidak berubah.**

---

## 1. Tujuan
Menutup temuan P2-A: `lane` dulu hanya hidup di `go_criteria_json` (atau hilang), tidak
ter-query, dan `INFO_ACQUISITION` vs `PRICE_DERIVED` bisa tercampur. R1 menjadikan `lane`
kolom kelas-satu yang CHECK-constrained di seluruh artefak riset + guard di luar DB eksternal.

## 2. Perubahan Schema (ADDITIVE, non-destruktif)

### 2.1 Research DB — `nexora_research/migrations/002__research_lane_columns.sql`
| Tabel | Kolom baru | Constraint |
|---|---|---|
| `research_hypotheses` | `lane TEXT NOT NULL DEFAULT 'PRICE_DERIVED'` | `CHECK(lane IN ('PRICE_DERIVED','INFO_ACQUISITION'))` |
| `research_experiments` | `lane TEXT` | `CHECK(NULL or in set)` (denormalisasi dari hypothesis) |
| `research_evaluations` | `lane TEXT` | CHECK |
| `research_failures` | `lane TEXT` | CHECK |
| `research_knowledge` | `lane TEXT` | CHECK (nullable) |

- **Backfill**: hypothesis lama yang menyimpan `lane='INFO_ACQUISITION'` di
  `go_criteria_json` dipromosikan ke kolom; sisanya tetap `PRICE_DERIVED` (fail-closed).
- **Index**: `idx_hyp_lane`, `idx_exp_lane`, `idx_fail_lane`, `idx_knowledge_lane`.
- **Non-destruktif**: `ALTER TABLE ADD COLUMN` + `UPDATE` backfill + `CREATE INDEX`;
  tidak ada rebuild tabel/hapus data.

### 2.2 External DB — `nexora_research/external_intelligence/migrations/002__external_lane_guard.sql`
- **Trigger** `trg_ext_proposals_lane_insert` / `trg_ext_proposals_lane_update`: menolak
  `lane` di luar `{INFO_ACQUISITION, PRICE_DERIVED}` (defence-in-depth tanpa rebuild).
- **Index** `idx_proposals_lane(lane, governance_status)`.
- `schema_version` eksternal: **1 → 2**.

## 3. Perubahan Kode

### 3.1 `nexora_research/store.py`
- Konstanta `LANES`, `DEFAULT_LANE`, fungsi `_normalise_lane()` (fail-closed).
- `register_hypothesis(..., lane=DEFAULT_LANE)`: validasi + simpan kolom + masukkan ke body hash.
- `create_experiment(...)`: **mewarisi** `lane` dari hypothesis (denormalisasi).
- `record_evaluation(...)` & `record_failure(...)`: **mewarisi** `lane` dari experiment.
- `record_knowledge(..., lane=None)`: lane opsional; bila `source_experiment_id` diberikan,
  lane diwarisi otomatis. Lane invalid → `ValueError`.
- `list_hypotheses(status=..., lane=...)` & `list_failures(..., lane=...)`: filter lane.

### 3.2 `nexora_research/registry.py`
- `pre_register()` meneruskan `lane = go_criteria["lane"]` (default `PRICE_DERIVED`) ke
  `register_hypothesis`. External bridge bermain lewat `go_criteria["lane"]=INFO_ACQUISITION`
  (sudah ada) → kini tersimpan sebagai kolom.

### 3.3 Tidak diubah (sudah kompatibel)
- `control_loop._proposal_to_hypothesis` sudah menaruh `go_criteria["lane"]=INFO_ACQUISITION`.
- `research_bridge` menolak non-INFO (P1) — tetap.
- `failure_learning.classify_and_record` meneruskan `source_experiment_id` → lane knowledge
  otomatis terisi.

## 4. Backward compatibility
- Semua pemanggil lama (`register_hypothesis`/`create_experiment`/`record_*` tanpa `lane`)
  tetap jalan: default `PRICE_DERIVED` untuk hypothesis, inheritance untuk turunannya.
- Suite penuh: **688 passed** (0 regresi).

## 5. Bukti tes
`tests/test_research_lane_r1.py` (13 tes, semua lulus):
- normalisasi lane (lowercase/whitespace) & reject invalid/None.
- persist + inheritance end-to-end (hypothesis → experiment → evaluation/failure → knowledge).
- default `PRICE_DERIVED` untuk pemanggil lama.
- **pemisahan SQL** INFO vs PRICE pada hypotheses & knowledge.
- reject invalid lane di API (`ValueError`) dan di DB (`sqlite3.IntegrityError` CHECK).
- trigger eksternal: reject `BOGUS`, terima `INFO_ACQUISITION`.
- **migration upgrade preservation**: DB v1 berisi row → migrate v2 → row utuh + lane default.
- **backfill promote**: `go_criteria lane=INFO_ACQUISITION` → kolom `INFO_ACQUISITION`.
- klosed set `LANES`.

## 6. Verifikasi DB
| DB | Sebelum | Sesudah | Catatan |
|---|---|---|---|
| `nexora_state.db` (produksi) | `7d945b4d…` | `7d945b4d…` | **TIDAK BERUBAH** |
| `nexora_research.db` | `877ba913…` | `93492ed1…` | migrasi v2 diterapkan; 0 rows (utuh) |
| `nexora_external_intel.db` | `17c8…`/`b715…`* | `b7154223…` | migrasi v2 (trigger+index); 1 event / 1 proposal utuh |

\*external hash bergeser ke `b715…` saat repository default-path membootstrap v2 (additive);
**isi data utuh**: events=1, proposals=1 (sama dengan audit P2).

## 7. Apa yang TIDAK dikerjakan (di luar R1)
- **P2-B (point-in-time)**: `available_at`, `published_at`, `vintage`, `as_of`, gate
  `is_synthetic`/`data_quality` — **belum** (tahap R2).
- Tidak ada perubahan pada observability ATR, evaluator harga, atau learning pipeline.
- PRICE_DERIVED tetap SUSPENDED; tidak ada auto-reopen.

## 8. Risiko & batasan tersisa (defer ke R2)
- Lane sudah struktural, tetapi **PIT integrity** belum (lihat `P2_LANE_AND_PIT_AUDIT.md` §3).
- `control_loop` masih membaca lane dari `go_criteria` untuk decision (sinkron dengan kolom
  karena `pre_register` menulis keduanya); kandidat peningkatan R2: baca kolom langsung.
- Tidak ada query index khusus untuk `research_evaluations.lane` (bisa ditambah bila perlu).

**STOP — R1 selesai. Menunggu persetujuan sebelum R2 (point-in-time).**

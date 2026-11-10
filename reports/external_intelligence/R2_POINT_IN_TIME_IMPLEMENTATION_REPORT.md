# R2 — POINT-IN-TIME (PIT) IMPLEMENTATION REPORT (P2-B REMEDIATION)

**Status: IMPLEMENTED (additive migration + PIT-aware producers + leadership gate). READY FOR REVIEW.**
**Scope: P2-B only (point-in-time safety). Builds on R1 (lane schema).**
**Safety: no training, no evaluation, no promotion, no live trading, PRICE_DERIVED tetap
SUSPENDED. ATR baseline & price-derived evaluator tidak berubah.**

---

## 1. Tujuan
Menutup temuan P2-B: data eksternal hanya menyimpan satu *fact time* (scheduled/published)
dan satu *ingestion time* (retrieved_at). Tidak ada *release/availability* time (embargo)
maupun *vintage/revision* marker, sehingga rekonstruksi "as-of" historis — dan karenanya
keamanan look-ahead — tidak dapat dibuktikan dari data. R2 menambahkan kolom PIT eksplisit
dan membuat pipeline menghormatinya tanpa pernah mengarang timestamp.

## 2. Perubahan Schema — `nexora_research/external_intelligence/migrations/003__external_pit.sql`
ADDITIVE (kolom nullable + default aman + backfill lossless):

| Tabel | Kolom baru |
|---|---|
| `ext_economic_events` | `published_at_utc`, `available_at_utc`, `ingested_at_utc`, `vintage`, `revision_as_of_utc`, `pit_verified (0/1 CHECK)` |
| `ext_central_bank_docs` | `available_at_utc`, `first_observed_at_utc`, `pit_verified` |
| `ext_news_records` | `available_at_utc`, `first_observed_at_utc`, `pit_verified` |
| `ext_event_responses` | `as_of_utc` (basis harga yang dipakai), `event_available_at_utc` |

- **Backfill**: `ingested_at_utc = retrieved_at_utc` dan `first_observed_at_utc = retrieved_at_utc` (lossless).
- `pit_verified` default `0` (data lama = belum terverifikasi PIT → fail-closed).
- Index: `idx_event_available`, `idx_event_pit`, `idx_cb_available`, `idx_news_available`.
- **Semantik**: `available_at_utc` = waktu data menjadi DIKETAHUI pasar (≥ published,
  memperhitungkan embargo/delay). `pit_verified=1` HANYA jika `available_at_utc` berasal
  dari timestamp sumber.
- `schema_version` eksternal: **2 → 3**.

## 3. Perubahan Kode

### 3.1 `event_response.py` (anti-leakage basis)
- `measure_event_response(..., available_at=None)`: bila `available_at` lebih lambat dari
  `event_ts`, **basis anti-leakage** menjadi `available_at`; "pre price" = close terakhir
  SEBELUM basis, dan horizon dihitung dari basis. Ini mencegah kebocoran ketika
  `scheduled_ts` menandakan periode (bukan instant rilis).
- `EventResponse` kini membawa `basis_ts` & `event_available_at` (transparansi).

### 3.2 `repository.py` (producers — tidak pernah mengarang)
- `insert_economic_event(..., published_at_utc, available_at_utc, vintage, revision_as_of_utc)`:
  validasi timestamp jika diisi; `pit_verified = 1` hanya bila `available_at_utc` ada;
  `ingested_at_utc = retrieved_at_utc`. Field PIT masuk **content hash** (perubahan
  availability/vintage = baris BARU, riwayat append-only terjaga).
- `insert_central_bank_doc(..., available_at_utc)` & `insert_news(..., available_at_utc)`:
  set `pit_verified` + `first_observed_at_utc`; invalid → `ValueError`.
- `insert_event_response(..., as_of_utc, event_available_at_utc)`.

### 3.3 `orchestrator.py`
- `_ingest_events` meneruskan field PIT dari input (hanya jika sumber menyediakan).
- Event-response: memakai `row["available_at_utc"]` sebagai basis; menyimpan `as_of_utc` &
  `event_available_at_utc`; menambahkan `pit_verified/data_quality/is_synthetic` ke evidence
  proposal agar gate R2 dapat menilai.

### 3.4 `research_bridge.py` (leadership gate R2)
- `assess_pit_safety(evidence)`: menelusuri evidence; `pit_safe/confirmatory_ready=True`
  HANYA bila semua `pit_verified==1`, tidak ada `is_synthetic`, dan tidak ada
  `data_quality ∈ {UNVERIFIED,SYNTHETIC,CONFLICTING,STALE}`. Tanpa metadata → **fail-closed**
  (tidak aman).
- `BridgeResult` kini membawa `pit_ready` & `pit_reasons`.
- `prepare_hypothesis` menyertakan `go_criteria.pit_ready`/`pit_reasons` + `evidence.pit_assessment`.
- `route_to_research_memory` menghitung PIT, mengisi `pit_ready` di semua jalur, dan
  menyimpan `pit_assessment` di knowledge detail. **Gate ini TIDAK memblokir provenance**:
  lead non-PIT tetap dipersist & dilacak, hanya ditandai `confirmatory_ready=False`
  (tidak boleh dipromosikan ke klaim GO).

## 4. Backward compatibility
- Semua pemanggil lama tetap jalan: parameter PIT opsional (default `None` →
  `pit_verified=0`, tanpa mengarang). `measure_event_response` default = perilaku lama.
- Suite penuh: **701 passed** (0 regresi; hanya `test_schema_version` di-update 2→3).

## 5. Bukti tes — `tests/test_external_pit_r2.py` (13 tes, semua lulus)
- **Migration upgrade preservation**: DB v2 berisi row → migrate v3 → row utuh; kolom PIT ada; `pit_verified=0`, `ingested_at` = retrieved.
- **Never fabricate**: event/news/cb tanpa `available_at` → `pit_verified=0`; dengan → `1`; invalid availability → `ValueError`.
- **PIT basis anti-leakage**: tanpa availability → pre = close sebelum `event_ts`; dengan availability=13:34 → pre = close sebelum 13:34 (bukan 13:30) & post dari target berbasis 13:34.
- **Gate**: unverified/synthetic → `confirmatory_ready=False` + reasons; bersih → `True`; tanpa metadata → fail-closed.
- **Bridge**: `pit_ready=False` untuk unverified (provenance tetap dipersist); `True` untuk verified.

## 6. Verifikasi DB
| DB | Sebelum | Sesudah | Catatan |
|---|---|---|---|
| `nexora_state.db` (produksi) | `7d945b4d…` | `7d945b4d…` | **TIDAK BERUBAH** |
| `nexora_external_intel.db` | `4f77…` ¹ | `4f77…` | migrasi 003 (PIT) diterapkan; rows utuh (events=1, news=2, responses=7, proposals=1) |

¹ Migrasi 003 aplikatif-additive; hash stabil dan jumlah baris identik (rows preserved=True).
(Bootstrap default-path sempat menerapkan 003 lebih awal; isi data tidak berubah.)

## 7. Apa yang TIDAK dikerjakan
- Tidak mengubah **nilai fakta** maupun menghapus baris (append-only utuh).
- Tidak ada backfill *kebenaran* `available_at` untuk data lama — dibiarkan NULL & `pit_verified=0`
  (kami tidak mengarang availability). Pengisian hanya bila sumber menyediakannya.
- Tidak ada training/evaluasi/promosi/live; PRICE_DERIVED tetap SUSPENDED.

## 8. Risiko & batasan tersisa (defer)
- **Kebijakan embargo per-sumber**: mapping default `available_at = published_at + delay`
  belum ada; saat ini menunggu timestamp eksplisit dari sumber. Kandidat R3.
- **Revision/vintage chaining**: kolom tersedia tetapi dedup `event_key` belum memisahkan
  vintage di unique-key (masih via `content_sha256`). Bisa dipertajam bila perlu.
- **`pit_verified` propagasi**: proposal hanya PIT-safe bila SEMUA fakta terkait verified;
  event tanpa availability otomatis menandai lead non-confirmatory (disengaja, fail-closed).

**STOP — R2 selesai. Menunggu persetujuan sebelum tahap berikutnya.**

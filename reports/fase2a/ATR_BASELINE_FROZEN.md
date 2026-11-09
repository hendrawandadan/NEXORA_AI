# FASE 2A — ATR TRIPLE-BARRIER BASELINE (FROZEN)

**Status:** FROZEN baseline. **Tanggal freeze:** 2026-11-08. **Commit:** f884039.

Dokumen ini menandai **triple-barrier berbasis ATR** (v2, hasil koreksi) sebagai
**baseline resmi yang dibekukan**. Baseline ini **tidak dihapus dan tidak diubah**.
Eksperimen adaptive barrier yang akan datang **wajib** membandingkan diri terhadap
baseline ini secara apple-to-apple.

---

## 1. Apa yang dibekukan

| Artefak | Blob hash (git) | Peran |
|---|---|---|
| `nexora_laboratory/triple_barrier.py` | `0440e0dc3258f9d0687a325ac9461a0a1ca61d2f` | ATR barrier + executable side-aware labeling |
| `nexora_laboratory/cost_engine.py` | `22454fb54b1970375ae5a3b464e0f29f8c1a945e` | Cost engine v2 (komponen, no double count) |
| `nexora_laboratory/event_attribution.py` | `ea79b4dadbad14d2f7bce3daaede7d2c3429490b` | net/meta, uniqueness, overlap purging |

Test penjaga baseline:
- `tests/test_triple_barrier.py` (12)
- `tests/test_cost_engine.py` (7)
- `tests/test_event_attribution.py` (5)
- **Total 24 test lolos** pada saat freeze.

---

## 2. Spesifikasi baseline (tidak boleh berubah dalam eksperimen pembanding)

- Barrier: `upper = entry + 1.5×ATR_t`, `lower = entry − 1.0×ATR_t`, `vertical = 16` bar M30.
- ATR: Wilder, span 14, **trailing (≤ t)** — anti-leakage.
- Entry: open bar t+1; eksekusi executable (BUY entry=ask/exit=bid, SELL sebaliknya).
- Status: UPPER_HIT / LOWER_HIT / VERTICAL_EXIT / AMBIGUOUS / INVALID.
- Cost: executable mode (spread tertanam) + hanya non-spread components; reference=entry_price.
- net_return = gross_return − transaction_cost; meta_label = 1 iff net_return > 0.

---

## 3. Aturan freeze

1. **Tidak ada perubahan** pada tiga file baseline di atas untuk keperluan eksperimen
   adaptive barrier. Jika perlu perbaikan bug kritis, harus lewat koreksi terdokumentasi
   + test, dan baseline **dire-freeze** dengan hash baru.
2. Eksperimen adaptive barrier **tidak menyentuh** file baseline; ia memakai interface
   yang sama (`label_events`-style output schema) agar perbandingan valid.
3. Semua evaluasi adaptive barrier **wajib** melaporkan hasil baseline ATR pada split
   & biaya identik (side-by-side), bukan berdiri sendiri.

---

## 4. Mengapa baseline ini layak dijadikan patokan

- Sudah melewati audit 9-temuan dan 24 unit test.
- Sudah direkonsiliasi biaya pada data nyata (spread dibayar sekali, no double count).
- Bebas look-ahead (ATR trailing, entry t+1, event window) — dibuktikan test.

---

## 5. Tags

Git tag: `fase2a-atr-baseline-frozen` menunjuk commit `f884039`.

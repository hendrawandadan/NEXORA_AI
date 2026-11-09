# FASE 2A — Tahap 2 (Triple-Barrier) & Tahap 5 (Cost Engine) — Validasi

**Status:** Read-only validation run (data nyata EURUSD M30 + M1 intrabar). Belum eksperimen/training model.
**Tanggal:** 2026-11-08

---

## 1. Cost Engine (`nexora_laboratory/cost_engine.py`)

Asumsi penelitian yang disetujui (BUKAN biaya broker aktual), satuan EURUSD 5-digit
(1 pip = 0,0001; 1 point = 0,00001), dinyatakan sebagai **fraksi return** agar
dibandingkan langsung dengan gross return (open→open).

| Skenario | Round-trip | Slippage | **Total** | Return fraction (@1.0) |
|---|---|---|---|---|
| optimistic | 1.0 pip | 0.2 pip | **1.2 pip** | 0.000120 |
| baseline | 1.5 pip | 0.2 pip | **1.7 pip** | 0.000170 |
| stress | 2.0 pip | 0.2 pip | **2.2 pip** | 0.000220 |

- **Anti double counting:** kolom `<SPREAD>` (88,8% = 0) **tidak** dipakai sebagai biaya.
  Cost diterapkan **satu kali** per trade (round-trip + slippage).
- Tests: `tests/test_cost_engine.py` (6) — totals, satuan, reference-price scaling,
  single-subtraction, assumption tag. ✅

---

## 2. Triple-Barrier (`nexora_laboratory/triple_barrier.py`)

Konfigurasi awal: upper **1,5×ATR**, lower **1,0×ATR**, vertical **16 bar M30**, ATR span 14.
Entry = open bar t+1 (execution-aligned). ATR trailing (≤ t) — anti-leakage.
Intrabar resolved via **M1** (terverifikasi 1-menit).

### 2.1 Hasil pada data nyata (70.677 event)
| Outcome | n | % |
|---|---|---|
| +1 (upper) | 25.191 | 35,6% |
| −1 (lower) | 39.704 | 56,2% |
| 0 (vertical) | 5.782 | 8,2% |
| **ambiguous** | **110** | **0,16%** |

- **Ambiguitas 0,16%** → resolusi M1 efektif.
- Mean gross semua-event = **+0,000012** (~0,12 bps) → nyaris nol (konsisten pasar efisien).
- Gross per outcome: −1 → −0,000883 (winrate 0% by construction), +1 → +0,001360 (100%),
  0 → +0,000288. Asimetri barrier (1,5/1,0 ATR) menghasilkan payoff asimetris.

### 2.2 Implikasi biaya (krusial)
- Cost baseline = **0,00017**, sedangkan edge naive (semua event) = **0,000012**.
- **Biaya ~14× edge naive.** Tanpa seleksi sinyal cerdas (meta-labeling), tidak mungkin profitable.

### 2.3 Anti-leakage (tests: `tests/test_triple_barrier.py`, 7)
- `exit_time > signal_time` dan `entry_time > signal_time` (tidak ada label "masa kini").
- Entry = open bar t+1.
- Barrier = ATR_t (info ≤ t); ATR tidak berubah saat future bar diubah (verified).
- First-touch order dihormati (single-bar spike); vertical fallback benar.
- Ambiguous dipisah dari outcome bersih.

---

## 3. Kesimpulan Tahap 2 & 5

- ✅ Cost engine & triple-barrier **lolos** semua test dan validasi data nyata.
- ✅ Tidak ada kebocoran waktu (dibuktikan unit test).
- ⚠️ Edge naif ≈ 0, biaya jauh lebih besar → **beban sepenuhnya pada meta-labeling** untuk
  menemukan sinyal yang layak. Ini sesuai ekspektasi; bukan jaminan berhasil.

**Berikutnya:** Tahap 3 — Layer 1 Kronos-inspired ensemble (forecast + dispersion,
confidence terkalibrasi) lalu **Gate 0** (uji standalone apakah ada edge cost-aware).

---

*Tidak ada model produksi, signal, atau artefak Fase 2 yang diubah. Semua read-only.*

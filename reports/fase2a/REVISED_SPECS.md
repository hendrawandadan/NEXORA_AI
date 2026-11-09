# FASE 2A — Triple-Barrier & Cost Engine: REVISED SPECIFICATION

**Versi:** v2 (correction pass). **Tanggal:** 2026-11-08.
**Status:** Selesai koreksi kode + unit test. **Belum ada training/tuning/eksperimen trading.**

---

## 1. REVISED TRIPLE-BARRIER SPECIFICATION

### 1.1 Fungsi
`label_events(bars, atr, cfg: BarrierConfig, exec_cfg: ExecutionConfig, side: int, m1=None) -> DataFrame`

### 1.2 Konfigurasi
| Param | Default | Makna |
|---|---|---|
| `k_up` | 1.5 | barrier atas = entry + 1.5×ATR |
| `k_dn` | 1.0 | barrier bawah = entry − 1.0×ATR |
| `vertical` | 16 | exit waktu (bar M30) |
| `atr_span` | 14 | Wilder ATR trailing (≤ t) |
| `side` | +1/−1 | BUY / SELL |
| `half_spread_price` | 0.0 | asumsi half-spread simulasi (price units) |
| `entry_at_next_open` | True | entry = bar t+1 |

### 1.3 Eksekusi (executable, SIMULATED)
- OHLC diperlakukan sebagai **mid**.
- Rekonstruksi quote: `ask = mid + half_spread`, `bid = mid − half_spread`.
- **BUY**: entry=ask, exit=bid. **SELL**: entry=bid, exit=ask.
- Deteksi barrier memakai **exit-side executable quote** (bukan mid).
- **Tidak ada bid/ask historis di data** → hasil = SIMULATED EXECUTION (asumsi eksplisit).

### 1.4 Sisi (side-aware)
- BUY: barrier atas = **profit**, bawah = **loss**.
- SELL: barrier bawah = **profit**, atas = **loss**.
- `gross_return = side × (exit − entry)/entry`.

### 1.5 Status (terpisah, tidak digabung)
`UPPER_HIT`, `LOWER_HIT`, `VERTICAL_EXIT`, `AMBIGUOUS`, `INVALID`.
`AMBIGUOUS` **tidak** diubah menjadi VERTICAL_EXIT.

### 1.6 Ekonomi vertical exit
Vertical exit menghasilkan return executable aktual (bisa profit/loss).
`barrier_outcome ∈ {+1 profit, −1 loss, 0 vertical/ambiguous}` — **tidak** disamakan dengan P/L.

### 1.7 Atribusi event
Kolom: `signal_time, entry_time, exit_time, entry_price, exit_price,
event_start_time, event_end_time, atr, upper, lower, vertical_time,
barrier_outcome, event_status, side, ambiguous, gross_return, exec_mid_gross_return`.

---

## 2. REVISED COST ENGINE SPECIFICATION

### 2.1 Komponen (terpisah, masing-masing sekali)
`total = spread + commission + slippage + swap` (dalam pip).
Status eksplisit: spread=`ASSUMED`, slippage=`ASSUMED`, commission=`NOT_AVAILABLE`,
swap=`ASSUMED_ZERO_INTRADAY` (bukan nol empiris).

### 2.2 Skenario (disetujui)
| Skenario | spread (pip) | slippage (pip) | total (mode flat) |
|---|---|---|---|
| optimistic | 1.0 | 0.2 | 1.2 |
| baseline | 1.5 | 0.2 | 1.7 |
| stress | 2.0 | 0.2 | 2.2 |

### 2.3 Dua mode (pilih SATU)
- **EXECUTABLE** (`spread_already_in_prices=True`): spread sudah tertanam di harga;
  kurangi **hanya** non-spread components (slippage/commission/swap).
- **FLAT** (`spread_already_in_prices=False`): gross pakai mid; kurangi total termasuk spread.

### 2.4 reference_price
Selalu `entry_price` aktual (bukan 1.0) — `cost_fraction = pips×0.0001 / entry_price`.

### 2.5 No double count (dibuktikan test)
`flat_total − exec_total == spread`, persis sekali.

### 2.6 Net & meta-label
`net_return = gross_return − transaction_cost` (mode executable: hanya non-spread).
`meta_label = 1 if net_return > 0 else 0` (objective ekonomi, bukan arah barrier).

### 2.7 Slippage
Baseline **0.2 pip konstan** (asumsi). Vol-adaptive = rencana penelitian berikutnya,
**belum dikalibrasi** (tidak diklaim).

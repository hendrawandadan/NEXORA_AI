# STAGE 3 — Transaction Cost Analysis

**Status:** ✅ Selesai (read-only, isolasi). Descriptive economics — **bukan klaim profit**.
**Runner:** `tools/run_transaction_cost_analysis.py`
**Output:** `transaction_cost_analysis.json` + `transaction_cost_analysis_manifest.json`
**Tes:** `tests/test_cost_model.py` — 16 lulus. Full suite: **391 passed** (tanpa regresi).

---

## 0. Ringkasan

Mengubah distribusi spread **nyata** dari STAGE 2 menjadi **skenario biaya eksplisit** dan
analisis **cost-vs-move** per horizon. Model biaya = `spread (terukur) + slippage (asumsi
eksplisit) + komisi (NOT_AVAILABLE = 0 di band utama)`. Temuan inti: **emas (XAUUSD) sangat
murah secara relatif** (cost drag 2–5% dari move), sedangkan **EURUSD mahal** (cost drag
13–27%); FX majors punya **sesi LATE yang mahal**, emas tidak.

---

## 1. Model biaya (auditable)

```
cost_round_trip_pips = spread + slippage + commission
```

| Komponen | Sumber | Catatan |
|---|---|---|
| **spread** | **terukur** dari tick (GBPUSDm/USDJPYm/XAUUSDm) atau estimasi (EURUSD) | skenario: optimistic=p50, baseline=p90, **stress=p99** |
| **slippage** | **asumsi eksplisit** per kelas (fx 0.2/0.2/0.5; metal 0.5/0.5/1.5 pip) | bukan dari data; didokumentasikan |
| **commission** | **NOT_AVAILABLE** (tipe akun Exness `m` tidak diketahui) | band utama = 0; akun ber-komisi hanya akan **menaikkan** biaya |

**Kenapa baseline = p90, bukan median?** Sikap konservatif: biaya yang dipakai untuk
kelayakan sebaiknya condong ke atas (bukan median) agar tidak menipu diri. Median & p99
tetap dilaporkan (optimistic & stress).

---

## 2. Skenario biaya per instrumen (round-trip pips, komisi=0)

| Instrumen | Optimistic (p50) | **Baseline (p90)** | Stress (p99) |
|---|---|---|---|
| GBPUSDm | 1.35 | **1.75** | 7.35 |
| USDJPYm | 1.25 | **1.35** | 8.35 |
| XAUUSDm | 2.55 | **3.55** | 10.55 |
| EURUSD (estimasi) | 3.2 | **5.0** | 9.5 |
| XAUUSD (proxy tick) | 2.55 | **3.55** | 10.55 |

Catatan: gap besar baseline→stress = ekor spread (rollover/news). Baseline dipakai untuk
kelayakan; stress menguji ketahanan.

---

## 3. Biaya per sesi eksekusi (round-trip pips, baseline slip)

| Instrumen | ASIA | LONDON | NY | LATE | Termahal |
|---|---|---|---|---|---|
| GBPUSDm | 1.35 | 1.35 | 1.35 | **1.75** | LATE |
| USDJPYm | 1.25 | 1.25 | 1.25 | **2.05** | LATE |
| XAUUSDm | 2.55 | 2.55 | 2.55 | 2.55 | **flat** |

**Observasi eksekusi:**
- **FX majors (GBP/USDJPY):** LATE (rollover ~21–24 UTC) ~30–60% lebih mahal → **hindari
  LATE** untuk eksekusi.
- **Emas:** spread datar antar sesi (median 2.05 di semua sesi) → **aturan "hindari LATE"
  TIDAK berlaku untuk emas** (spread-nya rata; mean LATE sedikit lebih tinggi saja).

---

## 4. Cost drag vs median move (baseline RT / move)

**Cost drag** = biaya sebagai fraksi move median; **crossover** = biaya ≥ move (struktural
tidak menarik).

### XAUUSD / XAUUSDm (tick — murah)
| Horizon | RT | median move | drag | move/cost |
|---|---|---|---|---|
| H4:h12 | 3.55 | 154.67 | **2.3%** | 43.6 |
| H4:h8 | 3.55 | 120.7 | 2.9% | 34.0 |
| D1:h2 | 3.55 | 132.9 | 2.7% | 37.4 |
| H1:h12 | 3.55 | 69.34 | 5.1% | 19.5 |

→ **emas: biaya hanya "menggerus" 2–5% dari move.** Tidak ada crossover.

### EURUSD (estimasi — lebih mahal)
| Horizon | RT | median move | drag | move/cost |
|---|---|---|---|---|
| H4:h12 | 5.0 | 39.4 | **12.7%** | 7.9 |
| H4:h8 | 5.0 | 31.9 | 15.7% | 6.4 |
| M30:h24 | 5.0 | 18.4 | **27.2%** | 3.7 |

→ **EURUSD: biaya menggerus 13–27% move** (tak ada crossover, tapi margin jauh lebih tipis).

### GBPUSDm / USDJPYm
Tidak ada bar economics di STAGE 2 (tick-only), jadi cost-drag per-horizon belum
dihitung; namun baseline RT (1.75 / 1.35) **< EURUSD 5.0** → biaya lebih ringan dari EURUSD
begitu bar tersedia (lihat STAGE 4/5).

---

## 5. Kesimpulan STAGE 3 (jujur)

1. **Biaya nyata (tick) jauh lebih ringan** dari asumsi bar STAGE 1 — khususnya emas
   (baseline RT 3.55 vs asumsi lama setara ~25+ pip). Ini penting: apa yang di STAGE 1
   tampak "infeasible" bisa berubah saat biaya sebenarnya dipakai.
2. **Emas = kandidat paling murah secara relatif** — cost drag 2–5% pada horizon panjang.
   Tetapi **murah ≠ edge**; IC OOS belum diuji (STAGE 5).
3. **EURUSD paling mahal** secara relatif (drag 13–27%); margin tipis. Jika ada edge di
   EURUSD, ia harus lebih kuat untuk mengalahkan biaya.
4. **Eksekusi: hindari LATE untuk FX majors**; emas tidak perlu aturan ini.
5. **Komisi belum diketahui** (NOT_AVAILABLE). Dijalankan sebagai band 0; bila akun aktual
   berkomisi (mis. raw spread), **tambahkan** ke semua angka di atas — arahnya selalu
   menaikkan biaya. Tidak ada angka komisi yang dikarang.

**Verdict:** model biaya eksplisit & auditable siap dipakai STAGE 6 (skoring). **Belum ada**
klaim peluang/profit — hanya cost & "ketersediaan move bersih biaya".

---

## 6. Reproduksibilitas

- `.\.venv\Scripts\python.exe tools/run_transaction_cost_analysis.py` (butuh STAGE 2 JSON).
- `--commission-pips N` untuk menguji akun ber-komisi (mis. 0.7 pip).
- Manifest: SHA256 `instrument_discovery.json` (input) + `transaction_cost_analysis.json` (output).

---

## 7. Catatan/pertanyaan terbuka untuk STAGE 4 & 5

- **Komisi Exness** untuk simbol `m`: perlu dikonfirmasi (raw vs standard). Bila ada, jalankan
  ulang dengan `--commission-pips` dan ulangi skoring.
- **Slippage**: saat ini asumsi; data tick memungkinkan estimasi slippage nyata (perbandingan
  harga eksekusi vs mid) tetapi butuh log eksekusi — belum tersedia.
- XAUUSD bar `spread` kolom (0.20) vs tick (2.05 pip) — gunakan **tick** sebagai sumber
  kanonik untuk emas (sudah diterapkan).

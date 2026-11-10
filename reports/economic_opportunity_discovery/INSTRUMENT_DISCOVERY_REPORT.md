# STAGE 2 — Instrument Discovery Report

**Status:** ✅ Selesai (read-only, isolasi). Discovery only — bukan klaim profit.
**Runner:** `tools/run_instrument_discovery.py`
**Output:** `instrument_discovery.json` + `instrument_discovery_manifest.json`
**Tes:** `tests/test_instrument_discovery.py` — 11 lulus. Full suite: **375 passed** (tanpa regresi).

---

## 0. Ringkasan satu paragraf

Kami menganalisis kualitas data + biaya spread **nyata** untuk 4 instrumen yang datanya
ada di disk (EURUSD, XAUUSD lewat bar; GBPUSDm, USDJPYm, XAUUSDm lewat tick Bid/Ask asli
Exness), serta menandai AUDUSD/USDCAD/USDCHF sebagai **DATA_UNAVAILABLE**. Temuan terpenting
**bukan** "temuan profit", melainkan **koreksi asumsi biaya**: spread tick nyata jauh lebih
kecil dari asumsi bar (muka emas: 2.05 pip nyata vs 25 pip asumsi — 12× overestimate).
Ini menaikkan movement-to-cost secara material dan *wajib* dipakai untuk evaluasi lanjutan,
tanpa mengubah fakta bahwa ini masih **"ketersediaan move", BUKAN prediktabilitas**.

---

## 1. Instrumen & sumber data

| Simbol | Sumber | Cakupan | Spread | Data quality |
|---|---|---|---|---|
| EURUSD | bar MT5 | 2020–2026 | ❌ estimasi (kolom jarang) | **C (0.65)** daily-prefix + spread unreliable |
| XAUUSD | bar | 2020–2026 | ❌ estimasi (bar) | **A (1.0)** bersih, tanpa prefix |
| GBPUSDm | **tick Bid/Ask** (zip) | 2020–2025 | ✅ nyata | — (tick) |
| USDJPYm | **tick Bid/Ask** (zip) | 2020–2025 | ✅ nyata | — (tick) |
| XAUUSDm | **tick Bid/Ask** (zip) | 2020–**2025-07-20** | ✅ nyata | — (tick) |
| AUDUSD, USDCAD, USDCHF | — | — | — | **DATA_UNAVAILABLE** |

Catatan: tick ditangani lewat **streaming chunk** (`.zip`), hanya menyimpan agregat —
tidak pernah memuat ~1.5 GB/tahun ke memori. `invalid` (Ask<Bid / non-finite) = 0 di
semua instrumen (data tick bersih).

---

## 2. Spread NYATA dari tick (median pips, 6 tahun)

| Instrumen | Ticks | Median | Mean | p90 | p99 | Range |
|---|---|---|---|---|---|---|
| GBPUSDm | 96.8 jt | **1.15** | 1.33 | 1.55 | 6.85 | 2020-01-02 → 2025-12-31 |
| USDJPYm | 98.0 jt | **1.05** | 1.26 | 1.15 | 7.85 | 2020-01-02 → 2025-12-31 |
| XAUUSDm | 166.7 jt | **2.05** | 2.36 | 3.05 | 9.05 | 2020-01-02 → 2025-07-20 |

**Per sesi (median pips):**

| Instrumen | ASIA | LONDON | NY | LATE (rollover) |
|---|---|---|---|---|
| GBPUSDm | 1.15 | 1.15 | 1.15 | 1.55 (mean 4.28) |
| USDJPYm | 1.05 | 1.05 | 1.05 | 1.85 (mean 4.22) |
| XAUUSDm | 2.05 | 2.05 | 2.05 | 2.05 |

**Observasi:** spread stabil lintas sesi utama (ASIA/LONDON/NY), tapi **meledak di sesi
LATE (~21:00–24:00 UTC)** = rollover/low-liquidity (mean 4+ pip). Ini isyarat kuat untuk
**menghindari eksekusi di jendela LATE** pada riset lanjut. XAUUSDm paling stabil
antar-sesi (median konstan 2.05).

---

## 3. Koreksi asumsi biaya (penting untuk STAGE 3 & lanjutan)

| Instrumen | Asumsi baseline (bar) | **Spread tick nyata** | Rasio overestimate |
|---|---|---|---|
| GBPUSDm | 3.0 pip | 1.15 pip | 2.6× |
| USDJPYm | 2.0 pip | 1.05 pip | 1.9× |
| XAUUSDm | 25.0 pip | 2.05 pip | **12.2×** |

**Konsekuensi:** untuk instrumen tick-tersedia, biaya round-trip realistis **jauh lebih
rendah** dari model bar. Untuk EURUSD/XAUUSD (tanpa tick), spread tetap **estimasi
eksplisit** (label `ESTIMATE`), bukan kebenaran per-bar.

---

## 4. Movement-to-cost (baseline; bar, HOMOGENEOUS intraday segment)

### EURUSD (quality C — daily-prefix di-exclude)
| TF | h | median move | move/cost | required acc (sym) |
|---|---|---|---|---|
| M30 | 24 | 18.4 pip | 5.75 | 0.587 |
| M30 | 48 | 27.9 pip | 8.72 | 0.557 |
| H1 | 12 | 18.4 pip | 5.75 | 0.587 |
| H1 | 24 | 28.0 pip | 8.75 | 0.557 |
| **H4** | **12** | **39.4 pip** | **12.31** | **0.541** |

### XAUUSD (quality A — data bersih)
| TF | h | median move | move/cost* | required acc (sym) |
|---|---|---|---|---|
| H1 | 24 | 106.7 pip | 4.23 | 0.618 |
| **H4** | **12** | **154.7 pip** | **6.14** | **0.582** |
| D1 | 2 | 132.9 pip | 5.27 | 0.595 |

\*XAUUSD memakai baseline asumsi 25 pip (bar); dengan **spread tick nyata 2.05 pip**,
rasio sebenarnya **≈12× lebih baik** (mis. H4/h12: move/cost nyata ≈ 75×, butuh akurasi
hanya ~50.5% symmetric). **Ini kandidat kuat** — namun tetap harus dibuktikan IC OOS,
bukan diasumsikan.

---

## 5. Skor kualitas data

| Instrumen | Skor | Grade | Catatan |
|---|---|---|---|
| XAUUSD (bar) | 1.00 | **A** | bersih, no prefix, missing ~1–9% |
| EURUSD (bar) | 0.65 | **C** | daily-prefix di-exclude + kolom spread 88% nol |

EURUSD sengaja tidak "dinaikkan" skornya — masalah granularitas & spread jarang adalah
fakta data, bukan sesuatu untuk disembunyikan.

---

## 6. Kesimpulan STAGE 2 (jujur, tanpa overclaim)

1. **Spread nyata jauh lebih rendah** dari asumsi untuk instrumen tick-tersedia; ini
   mengubah ekonomi secara material. Mulai STAGE 3, gunakan angka tick nyata ini, bukan
   asumsi bar.
2. **XAUUSD (emas)** menonjol: data grade A + movement besar vs biaya tick (2.05 pip).
   Ini menjadikannya **kandidat riset prioritas** untuk uji IC OOS — *bukan* bukti untung.
3. **EURUSD** datanya grade C; H4/h12 tetap kandidat terbaik untuk EURUSD (konsisten
   STAGE 1), tetapi spread-nya tetap estimasi.
4. **Sesi LATE (rollover) mahal** di semua FX tick → hindari dalam desain eksekusi.
5. **3 pair (AUD/USD/CAD/CHF)** tidak ada data → `DATA_UNAVAILABLE`, tidak dikarang.

**Verdict:** semua klaim = "ketersediaan move & biaya nyata". **Tidak ada** instrumen yang
diklaim profitable. Langkah berikutnya adalah STAGE 3 (Transaction Cost Analysis) yang
menggabungkan spread tick nyata ini lintas skenario, lalu STAGE 5 (New Information
Assessment) untuk menguji apakah **IC OOS** benar-benar ada — satu-satunya jalan menuju
"peluang".

---

## 7. Reproduksibilitas

- Runner full: `.\.venv\Scripts\python.exe tools/run_instrument_discovery.py`
  (≈6 menit; 3 instrumen tick × 6 tahun).
- Partial: `--instruments GBPUSDm,XAUUSDm --years 2024` atau `--skip-ticks` (bar saja).
- Manifest (`instrument_discovery_manifest.json`) berisi SHA256 input (semua file bar) +
  SHA256 output JSON + daftar instrumen/tahun yang dianalisis.

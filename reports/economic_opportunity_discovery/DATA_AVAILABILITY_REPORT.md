# STAGE 4 — Data Availability & Quality Report

**Status:** ✅ Selesai (read-only, isolasi). Audit ketersediaan data — **bukan klaim profit**.
**Runner:** `tools/run_data_availability.py` (butuh STAGE 2 + 3 JSON)
**Output:** `data_availability.json` + `data_availability_manifest.json`
**Tes:** `tests/test_availability.py` — 13 lulus. Full suite: **404 passed** (tanpa regresi).

---

## 0. Ringkasan

Mengkonsolidasikan hasil STAGE 2 (ketersediaan + kualitas) & STAGE 3 (sumber biaya)
menjadi **profil kesiapan per instrumen** + **daftar gap eksplisit**. Skor kesiapan
adalah aturan transparan (bukan black box) yang menjawab: *instrumen & horizon mana yang
punya data cukup & tepercaya untuk uji New-Information (IC OOS) di STAGE 5 — dan apa yang
masih hilang?*

**Hasil:** Emas (XAUUSD/XAUUSDm) READY (1.00/0.98), EURUSD READY (0.78, tapi spread
estimasi + grade C), GBPUSDm/USDJPYm PARTIAL (tick lengkap **tapi tanpa bar OHLC**),
AUD/USD/CAD/CHF NOT_READY (tidak ada file).

---

## 1. Peringkat kesiapan

| Rank | Instrumen | Verdict | Readiness | Data |
|---|---|---|---|---|
| 1 | **XAUUSDm** | **READY** | **1.00** | bars+tick, grade A, 5.55 th, 41,839 bar intraday |
| 2 | XAUUSD | READY | 0.98 | bars (grade A) + tick via sibling |
| 3 | EURUSD | READY | 0.777 | bars (grade C), 6.84 th, 113,680 bar; spread **estimasi** |
| 4 | GBPUSDm | PARTIAL | 0.675 | **tick lengkap, tanpa bar OHLC** |
| 5 | USDJPYm | PARTIAL | 0.675 | **tick lengkap, tanpa bar OHLC** |
| 6 | AUDUSD | NOT_READY | 0.00 | DATA_UNAVAILABLE |
| 7 | USDCAD | NOT_READY | 0.00 | DATA_UNAVAILABLE |
| 8 | USDCHF | NOT_READY | 0.00 | DATA_UNAVAILABLE |

---

## 2. Skor kesiapan (transparan)

Readiness = rata-rata berbobot dari 4 komponen (bobot didokumentasikan):

| Komponen | Bobot | Definisi |
|---|---|---|
| quality | 0.35 | grade bar (A=1.0, B=0.8, C=0.55, D=0.3) |
| history_depth | 0.30 | min(tahun/3, bar_intraday/3000) |
| cost_credibility | 0.20 | tick=1.0, proxy=0.9, estimate=0.5, none=0.0 |
| coverage | 0.15 | fraksi pasangan (TF, horizon) referensi yang tersedia |

**Contoh (XAUUSDm):** quality 1.0 · depth 1.0 · cost 1.0 · coverage 1.0 → **1.00**.
**EURUSD:** quality 0.65 · depth 1.0 · cost 0.5 (estimasi) · coverage 1.0 → **0.777**.
**GBPUSDm:** quality 0.5 (tick tanpa grade) · depth 1.0 · cost 1.0 · coverage 0.0 (tak ada
bar → tak ada horizon move) → **0.675 → PARTIAL**.

---

## 3. Gap eksplisit (tidak disembunyikan)

| Gap | Instrumen terdampak | Dampak untuk STAGE 5 |
|---|---|---|
| **Komisi NOT_AVAILABLE** (tipe akun Exness) | semua | biaya = band 0; bila akun berkomisi, tambahkan → hanya menaikkan biaya |
| **Spread ESTIMASI** (tanpa tick) | EURUSD | cost credibility rendah; angka spread tak sekuat tick |
| **Tidak ada bar OHLC** (hanya tick) | GBPUSDm, USDJPYm | **tidak bisa** hitung move/feature/horizon → perlu **bangun bar dari tick** dulu |
| **Tick coverage terpotong** | XAUUSDm (s/d **2025-07-20**; bar ada s/d 2026) | periode pasca-2025-07-20 tak ter-tick-cover (spread/slippage) |
| **DATA_UNAVAILABLE** | AUDUSD, USDCAD, USDCHF | tidak ada file (bar/tick) — tidak bisa apa pun |

> Catatan penting: gap "tidak ada bar OHLC" untuk **GBPUSDm/USDJPYm** sudah saya verifikasi
> langsung — di disk **hanya ada tick zip**, tanpa CSV bar M30/H1/H4. Ini prasyarat nyata
> untuk STAGE 5: harus **membangun bar dari tick** (hati-hati memori) sebelum uji IC.

---

## 4. Cakupan per instrumen

| Instrumen | Bar | Tick | Timeframe | Horizon | Rentang |
|---|---|---|---|---|---|
| XAUUSDm | ✅ | ✅ | H1, H4, D1 | H1:12/24, H4:4/8/12, D1:1/2 | 2020-01-02 → 2025-07-20 |
| XAUUSD | ✅ | — | H1, H4, D1 | sama | 2020-01-02 → 2025-07-20 |
| EURUSD | ✅ | ❌ | M30, H1, H4 | M30:24/48, H1:12/24, H4:4/8/12 | 2020-01-02 → 2026-11-06 |
| GBPUSDm | ❌ | ✅ | — (bangun dari tick) | — | tick 2020-01-02 → 2025-12-31 |
| USDJPYm | ❌ | ✅ | — (bangun dari tick) | — | tick 2020-01-02 → 2025-12-31 |

---

## 5. Implikasi untuk STAGE 5 (New Information Assessment)

1. **Prioritas uji IC:** **XAUUSD** (READY 0.98; grade A + tick untuk biaya + histories
   H4 41k bar) — instrumen paling siap untuk uji fitur OOS.
2. **EURUSD** siap menguji IC (6.8 th, banyak bar) tetapi dengan **cost = estimasi**;
   hasil harus diperlakukan lebih hati-hati.
3. **GBPUSDm/USDJPYm**: prasyarat → **bangun bar OHLC dari tick** (M30/H1/H4) agar move
   & fitur bisa dihitung. Tick-nya lengkap 6 tahun, jadi ini layak dikerjakan.
4. **AUD/USD/CAD/CHF**: tetap `DATA_UNAVAILABLE`; tidak diuji.
5. **Komisi**: bila user mengonfirmasi tipe akun, ulangi STAGE 3 dengan `--commission-pips`.

**Verdict:** data siap untuk uji IC pada **XAUUSD (utama)** & **EURUSD (cadangan, cost
estimasi)**. GBP/USDJPY butuh langkah turunan bar dulu. **Tidak ada** klaim profit/peluang —
hanya audit kesiapan data.

---

## 6. Reproduksibilitas

- `.\.venv\Scripts\python.exe tools/run_data_availability.py` (butuh STAGE 2 + 3 JSON).
- Manifest: SHA256 `instrument_discovery.json` + `transaction_cost_analysis.json` (input),
  `data_availability.json` (output).

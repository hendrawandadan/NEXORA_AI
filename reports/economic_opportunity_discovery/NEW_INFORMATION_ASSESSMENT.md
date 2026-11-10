# STAGE 5 — New Information Assessment (IC OOS)

**Status:** ✅ Selesai (read-only, isolasi). Diagnostik IC — **bukan klaim profit/edge**.
**Runner:** `tools/run_new_information_assessment.py`
**Output:** `new_information_assessment.json` + `new_information_assessment_manifest.json`
**Tes:** `tests/test_information.py` (lihat bagian 7). Full suite **404+** (lihat bagian 7).

---

## 0. Ringkasan eksekusi (jujur — termasuk hasil buruk)

Kami menguji **tanpa model**: apakah fitur turunan harga kausal punya **Informasi
out-of-sample** soal forward return, via **Spearman IC** pada split temporal **TRAIN/TEST**
(70/30), dengan **koreksi multiple-comparison** (Benjamini-Hochberg + Bonferroni).

**Hasil utama — dan peringatan penting:**
- Secara statistik, **banyak fitur "signifikan" OOS** (mis. XAUUSD H1: 15/36 lolos BH).
  **TAPI** mayoritas punya **IC TRAIN ≈ 0** dan **IC TEST signifikan**, dan **tanda IC
  sering berbalik** antara train vs test dan **antar-tahun**. Ini **bukan** bukti edge
  stabil — ini **informasi bergantung-rezim (regime-specific)**, kemungkinan besar
  **artefak periode**, bukan sinyal yang dapat diandalkan.
- **Tidak ada fitur dengan IC train & test yang besar, searah, dan stabil lintas tahun.**
  Magnitudo IC juga kecil (|IC| ~0.05–0.17). Untuk IC sekecil itu pun, konversi ke
  ekonomi (net-of-cost) belum dibuktikan.
- **Kesimpulan STAGE 5: BELUM ada bukti informasi forward yang stabil & andal.** Tidak
  layak lanjut ke klaim peluang. Temuan ini **valid dan berharga negatif** (menghindari
  overfit).

---

## 1. Metode (model-free, tanpa look-ahead)

| Elemen | Detail |
|---|---|
| **Fitur** (kausal, ≤ t) | `ret_k`, `zclose_k`, `vol_k`, `rng_k`, `posrng_k`, `rsi_k` untuk k∈{5,20,60} |
| **Target** | forward return `close[t+h]/close[t]−1` (label, tak masuk fitur) |
| **Split** | temporal 70% TRAIN (awal) / 30% TEST (akhir) — tanpa leak |
| **IC** | Spearman rank correlation fitur(t) vs forward-return(t), terpisah TRAIN & TEST |
| **Signifikansi** | p dua-sisi + **BH-FDR** & **Bonferroni** pada p TEST (bukti OOS saja) |
| **Prinsip** | **No model, no training**, no look-ahead; IC = asosiasi, bukan profit |

Instrumen & horizon:
- **XAUUSDm (utama)** → OHLC bar XAUUSD (grade A): H1 [12,24], H4 [4,8,12], D1 [1,2].
  *Catatan: OHLC dari bar spot XAUUSD; tidak ada bar turunan tick XAUUSDm.*
- **EURUSD (cadangan)** → bar (grade C, spread estimasi): H1 [12,24], H4 [4,8,12].

---

## 2. Hasil per instrumen/timeframe (BH survivors = lolos koreksi FDR)

| Instrumen | TF | Baris | Tes | **BH survivors** | Bonferroni | Catatan |
|---|---|---|---|---|---|---|
| XAUUSD | H1 | 31,618 | 36 | **15** | 8 | IC test negatif, train≈0/positif |
| XAUUSD | H4 | 8,559 | 54 | **4** | 2 | semua `rng/vol` negatif |
| XAUUSD | D1 | 1,662 | 36 | **2** | 1 | `ret_20/rsi_20` h2 (n kecil) |
| EURUSD | H1 | 36,733 | 36 | **32** | 19 | IC test positif, train≈0 |
| EURUSD | H4 | 9,555 | 54 | **22** | 13 | `vol/rng` positif, train≈0 |

**Permukaan:** banyak "survivor" — TAPI lihat bagian 3: itu **jebakan**.

---

## 3. Mengapa "signifikan" ≠ "informasi nyata" (analisis kejujuran)

Fitur teratas di XAUUSD/H4 (testIC terbesar in-sample tampak besar) lalu **dipecah
per-tahun di periode TEST**:

### XAUUSD H4 `rng_60` → h12
| Segmen | IC | p | n |
|---|---|---|---|
| TRAIN | **−0.007** | 0.61 | 5932 |
| TEST (gabungan) | −0.081 | 4e-5 | 2556 |
| ─ 2023 | **−0.249** | 8e-7 | 383 |
| ─ 2024 | −0.027 | 0.31 (tak sig) | 1387 |
| ─ 2025 | −0.076 | 0.03 | 786 |

### XAUUSD H1 `rng_20` → h24
| Segmen | IC | p | n |
|---|---|---|---|
| TRAIN | **+0.020** | 0.003 | 22114 |
| TEST (gabungan) | **−0.083** | 6e-16 | 9461 |
| ─ 2023 | −0.260 | 2e-23 | 1422 |
| ─ 2024 | −0.067 | 1e-6 | 5113 |
| ─ 2025 | −0.069 | 2e-4 | 2926 |

### EURUSD H4 `vol_60` → h12
| Segmen | IC | p | n |
|---|---|---|---|
| TRAIN | −0.002 | 0.89 | 6629 |
| TEST (gabungan) | +0.125 | 1.8e-11 | 2854 |
| ─ 2025 | **+0.167** | 9e-11 | 1495 |
| ─ 2026 | **+0.002** | 0.94 (**hilang**) | 1359 |

**Diagnosis (kritis):**
1. **Tanda IC berbalik train vs test** (XAUUSD rng: train +0.02 → test −0.08). Sinyal yang
   benar-benar stabil harusnya **searah**. Balik tanda = **bukan edge**, melainkan
   karakteristik rezim berbeda.
2. **IC terkonsentrasi 1 tahun** (XAUUSD 2023 = −0.26; EURUSD 2025 = +0.17) lalu **hilang**
   tahun berikutnya (EURUSD 2026 = +0.002). Ini **regime artifact**, tidak dapat diandalkan.
3. **IC train ≈ 0** untuk hampir semua "survivor" → informasi itu **hanya muncul di periode
   test**, menandakan **overfitting ke satu periode** atau efek makro spesifik.
4. Magnitudo **kecil** (|IC| 0.05–0.17) → bahkan bila stabil, konversi net-of-cost belum
   tentu layak (lihat STAGE 3: drag biaya EURUSD 13–27%).

---

## 4. Instrumen terbaik: XAUUSD (bukan EURUSD)

- **XAUUSD** punya IC yang secara statistik lebih kuat & konsisten-searah di beberapa
  fitur `rng/vol` H1/H4 (semua **negatif**: range/vol tinggi → forward return cenderung
  bawah pada horizon tsb). Tapi **train IC ≈ 0** → belum bisa disebut "informasi stabil".
- **EURUSD** "signifikan" lebih banyak tapi **cost = estimasi** dan IC train ≈ 0 + hilang
  di 2026 → lebih rapuh lagi.
- **Tidak ada** kombinasi (fitur, horizon) dengan IC train & test **keduanya besar, searah,
  dan stabil per-tahun**.

---

## 5. Kesimpulan STAGE 5 (jujur, tanpa overclaim)

1. **BELUM ada bukti informasi forward stabil** yang lolos uji kejujuran (konsistensi tanda
   train/test + stabilitas per-tahun). Yang signifikan = **regime-specific**, bukan edge.
2. **XAUUSD** tetap instrumen paling menjanjikan untuk penyelidikan (IC searah di
   `rng/vol`, data grade A) — **tapi ini hipotesis, bukan hasil**.
3. **EURUSD** rapuh (IC hilang 2026 + cost estimasi).
4. **Rekomendasi:** bila ingin lanjut, **bukan** langsung strategi — melainkan uji khusus
   `rng/vol` pada XAUUSD dengan **walk-forward** (bukan satu split), **stabilitas rezim**,
   dan **net-of-cost** (STAGE 3 band). Jika walk-forward juga tidak stabil → **tutup jalur**.
5. **Tidak ada klaim peluang/profit.** STAGE 5 secara eksplisit **gagal** menemukan sinyal
   stabil — dan itu dilaporkan apa adanya.

---

## 6. Implikasi untuk STAGE 6 (Economic Opportunity Assessment)

STAGE 6 harus jujur:
- Skor peluang **rendah** kecuali XAUUSD `rng/vol` terbukti stabil di **walk-forward**
  (belum dilakukan; STAGE 5 = single split).
- Kandidat yang layak disorot untuk uji lanjut: **XAUUSD H1/H4 `rng/vol` (negatif IC)** —
  sebagai **hipotesis** yang perlu validasi walk-forward + net-of-cost.
- Jangan menaikkan skor hanya karena "lolos BH" — pengecekan tanda & stabilitas per-tahun
  **membatalkan** klaim itu.

---

## 7. Reproduksibilitas

- `.\.venv\Scripts\python.exe tools/run_new_information_assessment.py`
  (opsi: `--instruments XAUUSD`, `--test-frac 0.3`, `--alpha 0.05`, `--windows 5,20,60`).
- Manifest: SHA256 tiap file bar (input) + JSON output.
- Metode BH & Bonferroni diimplementasi murni (tanpa statsmodels; scipy untuk Spearman).

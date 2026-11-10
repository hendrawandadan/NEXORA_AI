# Walk-Forward Multi-Split Validation (Post-STAGE 7)

**Status:** ✅ Selesai (read-only, penelitian baru — **bukan** STAGE 8).
**Runner:** `tools/run_walkforward_validation.py`
**Modul baru:** `nexora_laboratory/opportunity_discovery/walkforward.py`
**Output:** `walkforward_validation.json` + `walkforward_validation_manifest.json`
**Tes:** `tests/test_walkforward.py` — 13 lulus. Full suite: **481 passed**.
**Input:** hasil STAGE 5/6/7 (tanpa mengubahnya). Tidak ada training, tidak ada perubahan produksi.

---

## 0. Ringkasan eksekusi (jujur — hasilnya adalah "tidak stabil")

Walk-forward **multi-fold expanding-window** dijalankan untuk menguji apakah IC kandidat
STAGE-6 **stabil lintas split** (bukan artefak satu split). Kriteria stabilitas ketat:
tanda konsisten ≥80%, signifikan di ≥60% fold, tak didominasi satu fold (≤60%), |median
IC| ≥0.02.

**Hasil: 0 dari 20 uji feature×horizon yang STABIL secara robust.**

- **Kandidat tertinggi STAGE 6 (XAUUSD D1 h1/h2) GAGAL.** 0/8 stabil. `ret_5` **tanda
  berbalik** (4/6); `zclose_5`/`rng_60` tanda konsisten 6/6 **tetapi 0 fold signifikan**
  (|IC| ~0.03–0.04, terlalu lemah).
- **XAUUSD H4:** 0/8 — IC antar-fold melompat ekstrem (−0.145 … +0.058).
- **EURUSD H4 h12:** satu kandidat `rng_60` sempat "STABLE" di **6 fold** (sign 5/6, sig
  0.83, median +0.080) — **TETAPI** rapuh terhadap jumlah fold (lihat bagian 3).

**Kesimpulan:** **Tidak ada edge stabil.** Ini **membenarkan** verdict STAGE 7
(`READY_WITH_CONDITIONS`) → kondisi validasi **TIDAK terpenuhi** → rekomendasi:
**tutup jalur** (close the line). Lihat bagian 6.

---

## 1. Desain walk-forward (strict, anti-leak, anti-overfit)

- **Expanding window, K fold.** Timeline dibagi `n_folds` blok TEST kontigu di ujung seri;
  fold ke-k: TRAIN = semua baris sebelumnya, TEST = blok ke-k (OOS sejati).
- **Purging:** `horizon` bar terakhir tiap blok dibuang agar forward-return label tak
  bocor ke blok berikutnya.
- **Per fold:** hitung Spearman IC pada blok TEST (OOS terhadap train expanding-nya).
- **Stabilitas** mensyaratkan **semua**: (1) `sign_consistency` ≥ 0.80; (2)
  `majority_significant` ≥ 0.60; (3) `not_dominated` ≤ 0.60; (4) `magnitude` |median IC| ≥ 0.02.
- **Fitur kausal** (reuse STAGE 5), **no look-ahead** (diuji unit test).

> Catatan: rata-rata IC **tidak** dipakai sebagai kriteria stabilitas (rata-rata bisa
  membatalkan artefak rezim yang berlawanan tanda). Verdict berdiri di atas konsistensi
  antar-fold.

---

## 2. Hasil per instrumen (6 fold, alpha 0.05)

### XAUUSD D1 (h1, h2) — KANDIDAT UTAMA STAGE 6 → **GAGAL (0/8)**
| Fitur | h | sign | sig-frac | dom | median IC | fold IC |
|---|---|---|---|---|---|---|
| ret_5 | 1 | 4/6 | 0.00 | 0.35 | −0.036 | −.071 −.046 +.030 +.002 −.025 −.092 |
| zclose_5 | 1 | **6/6** | **0.00** | 0.32 | −0.040 | −.019 −.052 −.083 −.002 −.075 −.028 |
| rng_60 | 1 | **6/6** | **0.00** | 0.30 | −0.037 | −.042 −.031 −.004 −.032 −.077 −.068 |
| ret_5 | 2 | 4/6 | 0.00 | 0.27 | −0.035 | −.103 −.067 +.057 +.075 −.003 −.114 |
| zclose_5 | 2 | **6/6** | **0.00** | 0.42 | −0.032 | −.042 −.111 −.052 −.013 −.021 −.023 |

→ Tanda konsisten untuk sebagian fitur (6/6), **tetapi tidak ada fold yang signifikan**
dan |IC| ~0.03–0.04. **Sinyal terlalu lemah + sebagian tanda berbalik** → bukan edge.

### XAUUSD H4 (h8, h12) — **GAGAL (0/8)**
IC antar-fold berbalik arah dan bervariasi ekstrem (mis. `ret_60` h8: −.002 −.087 +.042
+.052 −.102 −.042). Tidak ada yang lolos.

### EURUSD H4 (h12) — **3/4 gagal, 1 "survivor" rapuh**
| Fitur | sign | sig-frac | dom | median IC | verdict (6 fold) |
|---|---|---|---|---|---|
| zclose_60 | 6/6 | 0.33 | 0.29 | −0.051 | unstable |
| ret_60 | 6/6 | 0.33 | 0.34 | −0.039 | unstable |
| vol_60 | 4/6 | 0.67 | 0.35 | +0.050 | unstable |
| **rng_60** | 5/6 | 0.83 | 0.26 | **+0.080** | **STABLE (6 fold)** |

---

## 3. KERAPUHAN survivor: `rng_60` EURUSD H4 h12 vs jumlah fold

Pengujian ulang survivor terhadap berbagai jumlah fold — **hasilnya tidak stabil**:

| n_folds | stable | sign | sig-frac | median IC | gagal karena |
|---|---|---|---|---|---|
| 4 | ❌ | 4/4 | 0.50 | +0.051 | majority_significant |
| **5** | ✅ | 4/5 | 0.80 | +0.099 | — |
| **6** | ✅ | 5/6 | 0.83 | +0.080 | — |
| 7 | ❌ | 7/7 | 0.43 | +0.047 | majority_significant |
| 8 | ❌ | 6/8 | 0.63 | +0.064 | sign_consistency |
| 10 | ❌ | 8/10 | 0.50 | +0.071 | majority_significant |

**Interpretasi jujur:** sinyal yang **benar-benar stabil** semestinya lolos di berbagai
jumlah fold. `rng_60` **hanya lolos di fold=5,6** dan gagal di 4,7,8,10 untuk alasan
berbeda. Ini **tanda kerapuhan**, bukan stabilitas. Ditambah biaya EURUSD **masih
estimasi**, survivor ini **tidak dapat dipercaya** sebagai edge.

---

## 4. Mengapa kandidat STAGE 6 gagal (diagnosis)

- STAGE 5/6 menggunakan **satu** split 70/30 → kandidat `ret_5`/`zclose_5` XAUUSD D1 tampak
  "searah". Namun pada **banyak fold**, tanda berbalik dan/atau |IC| kolaps ke ~0.03 yang
  **tidak signifikan**.
- Artinya "searah di satu split" adalah **kebetulan split** (split luck), bukan informasi
  yang bertahan. Walk-forward mengekspos ini — persis tujuan validasi.
- Survivor tunggal (EURUSD rng_60) pun **fold-count fragile**.

---

## 5. Status lima dimensi (tidak berubah, diperkuat)

| Dimensi | Status |
|---|---|
| Technical Implementation | ✅ SUCCESS (walk-forward reproducible, teruji) |
| Research Execution | ✅ SUCCESS (validasi dijalankan sesuai desain) |
| **Predictive Edge Evidence** | ❌ **NOT ESTABLISHED** (diperkuat: 0/20 robust) |
| Training Readiness | ❌ NOT READY |
| Production / Live Readiness | ❌ NOT READY |

---

## 6. Kesimpulan & rekomendasi

**Kondisi STAGE 7 untuk melanjutkan (walk-forward stabil) TIDAK terpenuhi.**

- **Tidak ada** fitur dengan IC stabil kuat lintas fold. Kandidat top (XAUUSD D1) gagal;
  survivor tunggal (EURUSD rng_60) rapuh terhadap jumlah fold + biaya estimasi.
- **Rekomendasi: TUTUP JALUR** untuk Economic Opportunity Discovery pada dataset yang ada.
  Jangan memaksakan strategi dari sinyal yang tidak stabil.

**Yang masih bisa membuka jalur (butuh keputusan user terpisah — bukan otomatis):**
1. **Data baru:** tick EURUSD (ganti cost estimasi); bar OHLC dari tick GBPUSDm/USDJPYm
   (agar bisa diuji IC — saat ini sama sekali belum bisa).
2. **Hipotesis baru** (bukan fitur momentum/mean-reversion yang sudah gagal) diuji dengan
   protokol walk-forward yang sama.
3. **Net-of-cost** tetap relevan **hanya jika** ada sinyal stabil — saat ini tidak ada.

**Pernyataan tegas.** Tidak ada klaim profit/edge. Tidak ada rekomendasi live trading.
Walk-forward ini adalah **penelitian baru** (bukan STAGE 8 resmi/otomatis). STAGE 0–7 +
validasi ini = bukti bahwa **belum ada edge**, dan langkah jujur berikutnya adalah menutup
jalur momentum/price-derived pada data saat ini.

---

## 7. Reproduksibilitas

- `.\.venv\Scripts\python.exe tools/run_walkforward_validation.py` (`--folds 6 --alpha 0.05`).
- Manifest: SHA256 input file + `walkforward_validation.json`.
- Kriteria & ambang terdokumentasi di `walkforward.py` (SIGN_CONSIST_MIN, SIG_MIN,
  DOMINANCE_MAX, IC_MIN) dan di JSON (`criteria`).

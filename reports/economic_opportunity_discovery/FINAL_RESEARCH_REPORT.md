# NEXORA AI — ECONOMIC OPPORTUNITY DISCOVERY
# FINAL RESEARCH REPORT (STAGE 7)

**Versi:** 1.0 · **Status:** COMPLETE · **Ruang lingkup:** STAGE 0–6 (konsolidasi)
**Sifat pekerjaan:** READ-ONLY terhadap hasil penelitian sebelumnya. Tanpa training,
tanpa eksperimen baru, tanpa perubahan produksi.
**Tanggal:** konsolidasi audit.

> **Prinsip final:** NEXORA tidak mengejar hasil yang terlihat bagus. Laporan ini
> menyimpulkan kondisi penelitian **apa adanya**, termasuk bila kesimpulannya: *belum ada
> edge yang terbukti, data sebagian belum cukup, dan hipotesis tertentu gagal.*

---

## A. EXECUTIVE SUMMARY

**Tujuan.** Menentukan apakah NEXORA memiliki **peluang ekonomi yang dapat diteliti**
— bukan apakah NEXORA bisa memprediksi. Fokus: karakteristik instrumen, ketersediaan &
kualitas data, biaya transaksi nyata, informasi prediktif out-of-sample, dan kelayakan
setelah biaya.

**Ruang lingkup STAGE 0–6.**

| Stage | Fokus | Hasil |
|---|---|---|
| 0 | Inspeksi proyek & data | Inventaris data, audit loader, kualitas spread |
| 1 | Horizon discovery (EURUSD) | Movement-to-cost naik dengan horizon; H4 h12 kandidat |
| 2 | Instrument discovery | Spread tick nyata GBP/USDJPY/XAU; grade A (XAU) / C (EURUSD) |
| 3 | Transaction cost | Model biaya eksplisit; baseline XAU 3.55 / EUR 5.0 pip |
| 4 | Data availability | Readiness: XAU READY; EURUSD READY (cost estimasi); GBP/JPY PARTIAL |
| 5 | New information | IC OOS signifikan tapi **TIDAK STABIL** (regime artifact) |
| 6 | Opportunity scoring | 3 RESEARCH_CANDIDATE (hipotesis), 8 WATCH, 1 WATCH_ECONOMICS_ONLY |

**Hasil utama.**
- **Ada ruang ekonomi** (movement jauh melebihi biaya, terutama emas: move/cost hingga
  ~34× baseline), **tetapi**
- **Belum ada bukti informasi forward yang STABIL** out-of-sample setelah koreksi
  multiple-comparison dan uji konsistensi tanda antar train/test/tahun.

**Temuan positif.**
- Data emas grade **A** (bersih), tick Bid/Ask nyata untuk GBP/USDJPY/XAU → biaya
  terukur, bukan asumsi.
- Biaya round-trip nyata **jauh lebih rendah** dari asumsi bar STAGE 1 (koreksi besar:
  emas 25→3.55 pip).
- Infrastruktur riset **reproducible & teraudit**: setiap stage punya JSON + manifest SHA256,
  runner read-only, dan tes.

**Temuan negatif.**
- **IC tidak stabil:** contoh XAUUSD `rng_20` h24 TRAIN **+0.020** → TEST **−0.083**
  (tanda berbalik); EURUSD `vol_60` h12 2025 **+0.167** → 2026 **+0.002** (hilang).
- Banyak fitur "lolos" BH **tetapi** dengan IC TRAIN ≈ 0 → artefak periode, bukan edge.
- EURUSD cost masih **estimasi** (tanpa tick); **komisi Exness NOT_AVAILABLE**.
- GBPUSDm/USDJPYm **tidak punya bar OHLC** (hanya tick) → belum bisa diuji IC.

**Risiko terbesar.** **Menyalahartikan signifikansi statistik sebagai edge.** Kandidat
skor tinggi didominasi oleh "ekonomi murah" (movement besar, biaya kecil), bukan oleh
sinyal prediktif yang tervalidasi. Overfitting/regime-specific artifact adalah ancaman
utama; tanpa walk-forward multi-split, kandidat tidak boleh diperlakukan sebagai peluang.

**Kesimpulan akhir.** Penelitian STAGE 0–6 **berhasil secara teknis & eksekusi**, tetapi
**belum menghasilkan bukti edge prediktif yang stabil.** Status: *research-eligible dengan
kondisi* terhadap 3 kandidat hipotesis; **bukan** kandidat training/live. (Lihat
`FINAL_RESEARCH_DECISION.md`.)

---

## B. RESEARCH METHODOLOGY

**Sumber data.**
- EURUSD: bar MT5 (`data/raw/EURUSD/*`), prefix daily terdeteksi & dibuang saat analisis.
- XAUUSD: bar (`data/raw/XAUUSD_H*.csv`, `XAUUSD_D1.csv`) + tick `XAUUSDm` (zip, untuk spread).
- GBPUSDm / USDJPYm: **tick Bid/Ask** hanya (tanpa bar OHLC).
- AUDUSD/USDCAD/USDCHF: **tidak tersedia**.

**Pipeline penelitian.** STAGE 0 (inspeksi) → 1 (horizon) → 2 (instrumen) → 3 (biaya) →
4 (kesiapan) → 5 (informasi) → 6 (skor) → 7 (konsolidasi). Setiap stage read-only; output
di `reports/economic_opportunity_discovery/` + package `nexora_laboratory/opportunity_discovery/`.

**Metode pengujian (STAGE 5).** Model-free:
- **Temporal split** TRAIN 70% (awal) / TEST 30% (akhir) — tanpa leak.
- **OOS IC:** Spearman rank (utama) + Pearson (dicatat); dihitung **terpisah** train & test.
- **Multiple comparison:** Benjamini–Hochberg FDR + Bonferroni pada p TEST.
- **Uji tambahan:** konsistensi tanda train↔test; stabilitas per-tahun.

**IC calculation.** `IC = Spearman(feature(t), forward_return(t))`, forward return
`close[t+h]/close[t]−1` (label saja; tidak masuk fitur).

**Transaction cost methodology (STAGE 3).**
`cost_round_trip = spread + slippage + commission`.
- Skenario dari spread terukur tick: **optimistic=P50, baseline=P90, stress=P99**.
- Slippage asumsi eksplisit (FX 0.2/0.5 pip; metal 0.5/1.5 pip).
- Commission = **NOT_AVAILABLE** (tipe akun Exness tidak diketahui) → band 0, arahnya
  **hanya menaikkan** biaya.
- **Penting:** full Bid/Ask spread dihitung **satu kali** sebagai biaya spread round-trip
  (bukan digandakan). Slippage ditambahkan terpisah; komisi terpisah.

**Opportunity scoring (STAGE 6).**
`score = 0.25·economics + 0.20·cost_burden + 0.20·data_readiness + 0.35·signal_quality`.
`signal_quality = max_over_features( base · train_factor · sign_factor )` — **strict**,
menghukum IC train≈0 / tanda berbalik. Gating: signal <0.10 → WATCH_ECONOMICS_ONLY;
<0.30 → WATCH; ≥0.30 & score≥0.65 → RESEARCH_CANDIDATE. Economics+data **tak bisa**
sendiri menjadi kandidat.

**Anti-lookahead safeguards.** Fitur memakai `.shift/rolling` kausal saja (≤ t) — diuji
unit test (`test_information.py::test_features_are_causal_no_lookahead`,
`test_assess_no_is_lookahead_in_features`). Forward return hanya sebagai label.

---

## C. DATA INTELLIGENCE

| Instrumen | Availability | Cakupan bar | Tick | Grade | Spread source | Readiness |
|---|---|---|---|---|---|---|
| XAUUSDm | bar+tick | 2020-01-02→2025-07-20 | ✅ tick (s/d 2025-07-20) | A | tick | **1.00 READY** |
| XAUUSD | bar | 2020-01-02→2025-07-20 | — (proxy tick XAUUSDm) | A | tick (proxy) | 0.98 READY |
| EURUSD | bar | 2020-01-02→2026-11-06 | ❌ | C | **estimate** | 0.777 READY |
| GBPUSDm | tick only | tick 2020-01-02→2025-12-31 | ✅ | — | tick | 0.675 PARTIAL |
| USDJPYm | tick only | tick 2020-01-02→2025-12-31 | ✅ | — | tick | 0.675 PARTIAL |
| AUDUSD | — | — | — | — | none | 0.00 NOT_READY |
| USDCAD | — | — | — | — | none | 0.00 NOT_READY |
| USDCHF | — | — | — | — | none | 0.00 NOT_READY |

**Data gaps.**
- **XAUUSDm:** OHLC berasal dari **bar spot XAUUSD** (sibling), **bukan** turunan tick
  XAUUSDm. Tick XAUUSDm hanya untuk spread. Tick coverage berhenti 2025-07-20.
- **GBPUSDm / USDJPYm:** hanya tick, **tidak ada bar OHLC** → IC belum bisa dihitung.
- **EURUSD:** tanpa tick → spread estimasi; bar grade C (prefix + kolom spread 88% nol).
- **Komisi:** NOT_AVAILABLE untuk semua.
- **AUD/USD/CAD/CHF:** tidak ada file.

---

## D. HORIZON & ECONOMIC FEASIBILITY

**EURUSD (STAGE 1, baseline cost 3.2 pip — asumsi bar):**

| TF | h | median move (pip) | move/cost | required acc (sym) |
|---|---|---|---|---|
| H4 | 12 | 39.4 | **12.31** | 0.541 |
| H4 | 8 | 31.9 | 9.97 | 0.550 |
| H1 | 24 | 28.0 | 8.75 | 0.557 |
| M30 | 8 | 9.3 | 2.91 | 0.672 |
| M30 | 24 | 18.4 | 5.75 | 0.587 |

**XAUUSD (STAGE 2 median move; STAGE 3 biaya nyata 3.55 pip baseline):**

| TF | h | median move (pip) | move/cost (nyata) | cost drag |
|---|---|---|---|---|
| H4 | 12 | 154.7 | **~43.6** | ~2.3% |
| H1 | 24 | 106.7 | ~30.1 | ~3.3% |
| H4 | 8 | 120.7 | ~34.0 | ~2.9% |
| H4 | 4 | 78.2 | ~22.0 | ~4.5% |

**Analisis.**
- **Movement-to-cost naik** dengan horizon (semua instrumen).
- **Emas termurah relatif**: cost drag baseline **~2–5%** dari move → margin sangat lebar.
- **EURUSD termahal relatif**: drag baseline **~13–27%** (M30 h24 27%, H4 h12 12.7%) →
  margin tipis; **biaya estimasi** membuat makin tak pasti.
- **Sesi LATE (rollover) mahal untuk FX majors** (GBP LATE 1.75 vs ASIA 1.35) → hindari
  LATE. **Emas spread relatif datar antar sesi** → aturan LATE **tidak** berlaku untuk emas.
- **Tidak ada crossover** (biaya ≥ move) di semua horizon.
- **Peringatan:** movement besar **≠** prediktabilitas (lihat F).

---

## E. TRANSACTION COST ANALYSIS

**Skenario round-trip (commission = 0, NOT_AVAILABLE):**

| Instrumen | spread source | optimistic | **baseline** | stress | slip (base) |
|---|---|---|---|---|---|
| XAUUSD | tick (proxy) | 2.55 | **3.55** | 10.55 | 0.5 |
| EURUSD | **estimate** | 3.2 | **5.0** | 9.5 | 0.2 |
| GBPUSDm | tick | 1.35 | **1.75** | 7.35 | 0.2 |
| USDJPYm | tick | 1.25 | **1.35** | 8.35 | 0.2 |

**Komisi:** `NOT_AVAILABLE`. Nilai nol = **asumsi baseline**, **bukan** tarif broker.
Bila akun berkomisi, tambahkan (`--commission-pips`) → biaya hanya naik.

**Klarifikasi perhitungan:** full Bid/Ask spread dihitung **satu kali** sebagai biaya spread
round-trip (bukan digandakan). Round-trip = spread(posisi buka+tutup, sudah mencerminkan
full spread sekali) + slippage + komisi.

**Sensitivity.**
- Baseline (P90) → stress (P99): emas 3.55→10.55 pip (×3), GOLD tetap move/cost ≥6.5×
  di h12. EURUSD 5.0→9.5 → M30 h24 drag→52% (margin habis di stress).
- **Emas** tahan terhadap stress; **EURUSD** rapuh di stress (cost estimasi + drag tinggi).

---

## F. NEW INFORMATION ASSESSMENT

**Fitur (kausal):** `ret`, `zclose`, `vol`, `rng`, `posrng`, `rsi`; lookback k∈{5,20,60}.
**Split:** TRAIN 70 / TEST 30 temporal. **Koreksi:** BH-FDR + Bonferroni pada p TEST.

**Survivor BH (bukan bukti edge — lihat di bawah):**

| Instrumen | TF | Tes | BH survivors | Bonferroni |
|---|---|---|---|---|
| XAUUSD | H1 | 36 | 15 | 8 |
| XAUUSD | H4 | 54 | 4 | 2 |
| XAUUSD | D1 | 36 | 2 | 1 |
| EURUSD | H1 | 36 | 32 | 19 |
| EURUSD | H4 | 54 | 22 | 13 |

**Mengapa "signifikan" ≠ "informasi stabil" (bukti, termasuk yang GAGAL):**

| Fitur (contoh) | TRAIN IC | TEST IC | Per-tahun | Diagnosis |
|---|---|---|---|---|
| XAUUSD `rng_20` h24 | **+0.020** | **−0.083** | 2023 −0.26 / 2024 −0.07 / 2025 −0.07 | **tanda berbalik** train→test |
| XAUUSD `rng_60` h12 | −0.007 | −0.081 | 2023 **−0.25** / 2024 −0.03 (n.s.) | terkonsentrasi 2023 |
| EURUSD `vol_60` h12 | −0.002 | +0.125 | 2025 **+0.167** / 2026 **+0.002** | hilang tahun berikutnya |
| EURUSD `rng_60` h12 | +0.003 | +0.105 | — | train≈0 → artefak test |
| XAUUSD `ret_5` D1 h2 | −0.034 | −0.052 | — | **searah** (kandidat, tapi sampel tipis) |

**Ukuran sampel (OOS test):** XAUUSD D1 h1/h2 **n≈497/498** (tipis); XAUUSD H4 ~2556; EURUSD
H4 ~2854 (paling tebal).

**Kesimpulan STAGE 5.** **Belum ada bukti informasi forward yang stabil.** Sebagian besar
"survivor" adalah **regime-specific artifact** (tanda berbalik / train≈0 / terkonsentrasi
satu tahun). Fitur signifikan **tidak** boleh dianggap trading edge.

---

## G. ECONOMIC OPPORTUNITY SCORING

Bobot: economics 0.25 · cost 0.20 · data 0.20 · **signal 0.35**. Gating ketat (lihat B).

| # | Instrumen | TF | h | econ | cost | data | sig | Score | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | XAUUSD | D1 | 2 | 1.000 | 0.973 | 0.980 | 0.523 | 0.824 | RESEARCH_CANDIDATE |
| 2 | XAUUSD | D1 | 1 | 1.000 | 0.958 | 0.980 | 0.375 | 0.769 | RESEARCH_CANDIDATE |
| 3 | XAUUSD | H1 | 24 | 1.000 | 0.967 | 0.980 | 0.194 | 0.707 | WATCH |
| 4 | XAUUSD | H4 | 12 | 1.000 | 0.977 | 0.980 | 0.179 | 0.704 | WATCH |
| 5 | EURUSD | H4 | 12 | 0.788 | 0.873 | 0.777 | 0.471 | 0.692 | RESEARCH_CANDIDATE |
| 6 | XAUUSD | H4 | 8 | 1.000 | 0.971 | 0.980 | 0.130 | 0.686 | WATCH |
| 7 | XAUUSD | H4 | 4 | 1.000 | 0.955 | 0.980 | 0.100 | 0.672 | WATCH |
| 8 | XAUUSD | H1 | 12 | 1.000 | 0.949 | 0.980 | 0.055 | 0.655 | WATCH_ECONOMICS_ONLY |
| 9 | EURUSD | H4 | 8 | 0.638 | 0.843 | 0.777 | 0.391 | 0.621 | WATCH |
| 10 | EURUSD | H1 | 24 | 0.560 | 0.821 | 0.777 | 0.305 | 0.566 | WATCH |
| 11 | EURUSD | H1 | 12 | 0.368 | 0.728 | 0.777 | 0.415 | 0.538 | WATCH |
| 12 | EURUSD | H4 | 4 | 0.426 | 0.765 | 0.777 | 0.327 | 0.530 | WATCH |

**Mengapa skor mentah tinggi bisa DITURUNKAN oleh hard gate:**
- XAUUSD **H1 h24** skor mentah 0.707 (>0.65) tetapi `signal_quality=0.194` (<0.30) → fitur
  terbaiknya **tanda berbalik** (train +0.02 → test −0.08) → verdict **WATCH**, **bukan**
  kandidat. Ini mencegah false positive.
- XAUUSD **H1 h12** skor 0.655 tapi signal 0.055 → **WATCH_ECONOMICS_ONLY**.

---

## H. CANDIDATE EVALUATION (3 RESEARCH_CANDIDATE = hipotesis)

**1. XAUUSD D1 h2 — score 0.824, signal 0.523**
- *Bukti pendukung:* `ret_5` searah (train −0.034 / test −0.052); data grade A; biaya sangat
  murah (drag ~1–3%).
- *Keterbatasan:* **n_test ≈ 497** (D1 hanya 1662 bar) → CI lebar, sampel **tipis**.
- *Kualitas data:* OHLC dari bar spot XAUUSD (grade A), spread dari tick XAUUSDm (proxy).
- *Stabilitas informasi:* `ret_5` searah (lebih baik dari kandidat lain) tapi belum diuji
  walk-forward.
- *Ketidakpastian biaya:* rendah untuk emas (move/cost sangat besar), tapi komisi N/A.
- *Risiko overfitting:* tinggi bila dioptimalkan pada sampel kecil D1.
- *Penelitian lanjut:* walk-forward multi-split pada `ret_5`/`zclose_5` D1/H4 + net-of-cost.

**2. XAUUSD D1 h1 — score 0.769, signal 0.375**
- Mirip #1; `ret_5`/`zclose_5` searah. **n_test ≈ 498** (tipis). Keterbatasan sama: sampel
  kecil, risiko overfitting tinggi, butuh walk-forward.

**3. EURUSD H4 h12 — score 0.692, signal 0.471**
- *Bukti pendukung:* `zclose_60`/`ret_60` searah; **sampel paling tebal (n_test≈2854)**.
- *Keterbatasan:* **spread = estimasi** (tanpa tick); biaya drag baseline ~13%, rapuh di
  stress (52% M30, tapi H4 h12 lebih baik). Kualitas bar grade C.
- *Ketidakpastian biaya:* tinggi (estimasi + komisi N/A).
- *Risiko:* IC EURUSD lain pada periode sama hilang 2026 (regime) — perlu walk-forward.
- *Penelitian lanjut:* dapatkan tick EURUSD atau konfirmasi komisi; walk-forward `ret_60`.

---

## I. FAILURE & LIMITATION ANALYSIS (tidak disembunyikan)

1. **PREP-001:** tidak menunjukkan edge ekonomis setelah biaya (temuan sebelumnya; dicatat,
   tidak diubah).
2. **Adaptive Barrier R1:** tidak mengalahkan ATR baseline (temuan sebelumnya; dicatat).
3. **IC signifikan ≠ stabil:** banyak survivor BH tetapi tanda berbalik / train≈0 /
   terkonsentrasi satu tahun → artefak rezim.
4. **Risiko regime-specific artifact:** terbukti (XAUUSD 2023, EURUSD 2025 → 2026).
5. **Sampel OOS tipis:** XAUUSD D1 (n≈497) → CI lebar.
6. **Spread EURUSD estimasi:** tanpa tick Bid/Ask.
7. **Komisi Exness belum diketahui:** NOT_AVAILABLE (band 0 = asumsi).
8. **OHLC XAUUSDm dari sibling XAUUSD:** bukan turunan tick XAUUSDm.
9. **AUDUSD/USDCAD/USDCHF tidak tersedia:** tidak dapat diuji.
10. **Keterbatasan histori tick XAUUSDm:** berhenti 2025-07-20.
11. **GBPUSDm/USDJPYm tanpa bar OHLC:** IC belum bisa dihitung.

---

## J. FINAL RESEARCH RECOMMENDATION

**Instrumen prioritas.** **XAUUSD** (data grade A, biaya nyata murah, cakupan kuat).
Sekunder: **EURUSD** (sampel tebal, tapi biaya estimasi).

**Horizon prioritas.** **H4 h12** (jumlah sampel vs biaya seimbang) dan **H1 h24** —
sebagai *bidang uji walk-forward*, bukan janji.

**Kandidat yang perlu ditunda (WATCH).** XAUUSD H1 h24, H4 h12/h8/h4; EURUSD H4 h8,
H1 h24/h12, H4 h4 — ekonomi kuat tetapi sinyal belum stabil.

**Kandidat yang perlu ditolak (saat ini).** XAUUSD H1 h12 (WATCH_ECONOMICS_ONLY): tak ada
sinyal stabil → jangan dijadikan dasar.

**Data yang perlu diperbaiki.**
- Dapatkan **tick EURUSD** (atau konfirmasi komisi) agar biaya EURUSD bukan estimasi.
- **Bangun bar OHLC GBPUSDm/USDJPYm dari tick** agar bisa diuji IC.
- Konfirmasi **tipe akun Exness** → biaya komisi nyata.
- (Opsional) bangun bar dari tick XAUUSDm untuk OHLC "murni"-murni tick.

**Eksperimen lanjutan yang layak (JIKA disetujui terpisah).**
- **Walk-forward validation** multi-split (rolling) untuk XAUUSD `ret_5`/`zclose_5`
  (D1/H4) & EURUSD `ret_60` (H4 h12).
- **Net-of-cost** dengan band STAGE 3 (optim/baseline/stress) + komisi nyata.
- Uji stabilitas lintas rezim volatilitas.

**Kondisi untuk melanjutkan ke tahap berikutnya.**
1. Walk-forward menunjukkan IC **searah & stabil** lintas split & rezim. **DAN**
2. Setelah **net-of-cost** (dengan komisi nyata) masih ada margin ekonomi. **DAN**
3. Sampel cukup (bukan D1 tipis).
Bila salah satu gagal → **tutup jalur** (jangan paksakan strategi).

**Catatan tegas.** **Tidak ada** klaim profit, edge terbukti, atau rekomendasi live trading.
Dokumen ini = audit bukti, bukan ajakan bertrading.

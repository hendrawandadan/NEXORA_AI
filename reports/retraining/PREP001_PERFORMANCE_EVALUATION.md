# PREP-001 Performance Evaluation — EURUSD M30 h2 (T3)

**Status:** Evaluasi read-only (tanpa training ulang, tanpa mengubah produksi)
**Sumber data:** model `models/t3/individual/EURUSD/M30/h2/model.joblib`,
`reports/t3/individual/EURUSD/M30/h2/report.json`, `signals/t3/EURUSD/M30/h2/individual_signals.csv`
**Target:** T3 (`open_to_open`), `effective_horizon=3`, `target_hash=d5f2c434…`
**Model:** LightGBM, 29 fitur, kelas [0,1]

---

## 1. Ringkasan Eksekutif (Jujur)

| Pertanyaan | Jawaban |
|---|---|
| Apakah model mengalahkan tebakan mayoritas? | **Ya, tapi marginal** (52,3% vs 51,2% di test) |
| Apakah ada edge statistik nyata? | **Sangat lemah / praktis tidak ada** (AUC ~0,519, korelasi ~0,019) |
| Apakah profitable setelah biaya transaksi? | **Tidak.** Untung kecil di 0 bps; **rugi berat** mulai 1 bps ke atas |
| Layak jadi dasar perluasan (Fase 3)? | **Belum.** NO-GO terhadap gerbang §8.6 |

**Verdict: NO-GO.** Model belajar *sesuatu* yang sangat tipis, tetapi tidak cukup
untuk mengalahkan biaya. Ini hasil yang wajar dan justru berharga: membuktikan
pipeline bekerja end-to-end sekaligus menutup pintu overclaim.

---

## 2. Metrik Klasifikasi (dari report.json)

| Split | n | Accuracy | Bal. Acc | AUC | Brier | LogLoss |
|---|---|---|---|---|---|---|
| Validation | 14.098 | 0,5184 | 0,5192 | 0,5277 | 0,2495 | 0,6921 |
| Test (OOS) | 14.051 | 0,5110 | 0,5102 | 0,5188 | 0,2498 | 0,6928 |

Walk-forward (3 folds): AUC 0,518 / 0,525 / 0,526 (mean ~0,523, **stabil tapi rendah**).

**Konfirmasi independen dari file signals (test window 2025-09-22 → 2026-11-06):**
- Confusion: TP=1362, TN=5982, FP=1216, FN=5491
- Model accuracy = **0,5227**; baseline mayoritas = **0,5123** → selisih **+1,0 poin**
- `metrics()` (sklearn) AUC = 0,5149

> Catatan: accuracy signals (0,523) sedikit berbeda dari report test (0,511) karena
> `direction=0` (tidak ada trade) dihitung berbeda. Secara substansi sama: edge tipis.

---

## 3. Metrik Trading Cost-Aware (signals, 5.509 trade aktif)

| Biaya (bps) | Trades | Win rate | Profit Factor | Expectancy/trade | Total Return | Max DD |
|---|---|---|---|---|---|---|
| **0** | 5.509 | 0,522 | **1,066** | +0,000015 | **+8,6%** | −3,8% |
| 1 | 5.509 | 0,433 | 0,700 | −0,000085 | −37,4% | −37,5% |
| 2 | 5.509 | 0,343 | 0,463 | −0,000185 | −63,9% | −63,9% |
| 3 | 5.509 | 0,271 | 0,311 | −0,000285 | −79,2% | −79,2% |
| 5 | 5.509 | 0,167 | 0,151 | −0,000485 | −93,1% | −93,1% |
| 10 | 5.509 | 0,056 | 0,036 | −0,000985 | −99,6% | −99,6% |

**Titik kritis:** expectancy gross hanya **+0,000015** (~0,15 basis poin per trade).
Artinya **biaya round-trip 1 bps saja sudah menghapus seluruh edge.** Spread/koma
EURUSD M30 realistis **jauh di atas 0,15 bps** → praktis tidak tradeable.

---

## 4. Analisis Edge (kenapa tipis)

**Expectancy per arah (gross, 0 cost):**

| Arah | n | Mean return | Win rate |
|---|---|---|---|
| Short (−1) | 2.931 | −0,000017 | 0,477 |
| Flat (0) | 8.542 | −0,000010 | 0,479 |
| Long (+1) | 2.578 | +0,000013 | 0,528 |

- Long sedikit lebih baik daripada short, tapi keduanya **mendekati nol**.
- **Korelasi `prob_up` vs realized return = 0,019** dan `direction` vs return = 0,013
  → sinyal hampir ortogonal terhadap hasil. Model nyaris tidak "melihat" arah masa depan.

**Kalibrasi probabilitas (bucket prob_up → mean realized return):**
Bucket tertinggi (0,55–1,0) memang punya mean return positif terbesar
(+0,000041), dan bucket terendah negatif — jadi **ada urutan (monotonik) tipis**,
tapi besarnya terlalu kecil.

**Trade "percaya diri" (|prob−0,5| > 0,05):** n=2.489, mean +0,000030,
win rate 0,544, gross total +7,7%. Penyaringan kepercayaan **memperbaiki** sedikit,
tapi tetap di bawah biaya realistis.

**Baseline naif (gross, seluruh bar):**
- Always-long: −0,000007/trade (total −9,8%)
- Always-short: +0,000007/trade (total +10,0%) ← kebetulan pasar turun periode ini

→ Model (gross +8,6%) **tidak jelas mengalahkan "always-short"** (+10%). Edge model
sebagian bisa jadi hanya *bias arah periode* (`positive_rate` test 0,488 < 0,5).

---

## 5. Kesimpulan terhadap Exit Criteria Fase 2 (Roadmap §8)

| Kriteria | Status |
|---|---|
| §8.1 Metrik OOS dilaporkan | ✅ dilakukan |
| §8.1 Mengalahkan baseline naif | ⚠️ Marginal (+1,0 pt vs mayoritas), **tidak** vs always-short |
| §8.1 Walk-forward stabil | ✅ stabil tetapi level rendah (AUC ~0,52) |
| §8.2 Cost-aware realistis | ❌ **Gagal** — profit hanya pada biaya ~0 |
| §8.3 A/B/C | ⏳ belum (hanya A) |
| §8.4 Experiment history reproducible | ⏳ sebagian (baru di-sync ke DB) |
| §8.5 Governance/audit | ✅ `READY_FOR_TRAINING` |
| **§8.6 Go/No-Go** | ❌ **NO-GO** — jangan perluas ke Fase 3 |

---

## 6. Rekomendasi (tanpa memperlebar pekerjaan)

1. **Jangan lanjut ke Fase 3** berdasarkan hasil ini.
2. **Ubah target/hipotesis, bukan tambah arsitektur.** Kemungkinan akar masalah:
   - Target arah biner `sign(open[t+h]/open[t]-1)` untuk h=2 di M30 ≈ **noise**.
     Edge tipis + korelasi ~0,02 konsisten dengan "memprediksi noise".
   - Pertimbangkan target yang lebih "belajar-able": horizon lebih panjang,
     **triple-barrier / meta-labeling**, atau target **return bertingkat** alih-alih biner.
3. **Uji kandidat B & C** (§8.3) dengan protokol split identik **sebelum** menyimpulkan
   bahwa arsitektur yang salah — bisa jadi konfigurasi A saja yang lemah.
4. **Wajib cost-aware sejak awal.** Edge < 0,15 bps tidak akan pernah lolos spread;
   metrik utama harus *net-of-cost*, bukan accuracy.
5. **Dokumentasikan sebagai temuan negatif** yang sah — ini menutup jalan buntu
   lebih cepat daripada overclaim.

---

## 7. Catatan Metodologis / Batasan

- Evaluasi memakai `realized_forward_return` yang sudah ada di file signals
  (gross). Bukan backtest eksekusi (SL/TP/sizing) — murni directional edge.
- `direction=0` = tidak ada sinyal; metrik trading hanya menghitung bar aktif.
- Biaya 1–10 bps adalah asumsi ilustratif; spread EURUSD M30 nyata umumnya
  lebih besar → kesimpulan "tidak tradeable" makin kuat, bukan sebaliknya.
- Semua perhitungan read-only; tidak ada training ulang atau penulisan produksi.

---

*Dibuat sebagai bagian penutupan Fase 2 (evaluasi). Keputusan NO-GO menahan
perluasan fase sampai arsitektur/target ditinjau ulang.*

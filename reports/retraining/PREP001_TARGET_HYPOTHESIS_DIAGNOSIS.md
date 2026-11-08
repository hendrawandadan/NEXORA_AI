# PREP-001 Target / Hypothesis Diagnosis — EURUSD M30

**Status:** Diagnosis read-only (tanpa training produksi, tanpa ubah artefak)
**Pertanyaan:** Apakah target biner yang dipakai mengandung sinyal yang bisa
dipelajari, atau pada dasarnya noise? Apakah masalahnya di target/horizon/fitur?

**Data:** `EURUSD_M30_202001020000_202611062130.csv` (70.694 bar), T3 & T1.

---

## 1. Ringkasan

**Ada sinyal statistik tipis yang nyata (~AUC 0,53), tetapi jauh di bawah biaya
transaksi.** Ini bukan bug pipeline, bukan salah hyperparameter (dibuktikan A/B/C),
bukan salah horizon (dibuktikan di bawah). Pasar EURUSD M30 pada fitur ini hampir
efisien. **Ini temuan negatif yang sah** dan menutup jalur "tuning".

---

## 2. Bukti

### 2.1 Label sehat & seimbang
- positive_rate = 0,496 (T3 h2) → tidak ada bias kelas.
- Entropy label ≈ 1,0 bit (maksimum ketidakpastian).

### 2.2 Return tidak persisten (koreksi artefak overlap)
| Lag (T3 h2) | Autokorelasi naif | **Non-overlap (stride=3)** |
|---|---|---|
| 1 | +0,4908 | **+0,0006** |
| 2 | −0,0075 | −0,0057 |
| 3 | −0,0016 | +0,0143 |

→ Autokorelasi +0,49 hanyalah **overlap labeling** (bar berbagi antar-label).
Setelah non-overlap, return masa lalu **tidak memprediksi** return masa depan.

### 2.3 Fitur hampir tanpa informasi tentang label
- Fitur tunggal terkuat: `rsi14` |AUC−0,5| = **0,018**; `dist_sma50` 0,017; dst.
- **Total Mutual Information 29 fitur = 0,038 nats** vs entropy label 0,69 nats
  → fitur menjelaskan **< 6%** informasi label secara longgar.
- Fitur teratas: `spread_relative` MI=0,0053, `vol20` 0,0044 — nyaris nol.

### 2.4 Ceiling predictability (multivariat benar-benar diuji)
| Model | Test AUC |
|---|---|
| Logistic Regression (29 fitur) | 0,5184 |
| HistGradientBoosting (kompleks) | **0,5298** |
| **HGB pada label di-shuffle (kontrol)** | **0,5022** |

→ 0,530 **bukan** overfit acak (kontrol shuffle tepat 0,50). Ada sinyal tipis nyata,
tapi ceiling ~0,53 ≈ edge ~0,3 bps → tidak menutup spread.

### 2.5 Horizon sweep T1 — semua gagal mengalahkan baseline
| Horizon | Test AUC | Accuracy | Baseline | Edge |
|---|---|---|---|---|
| h=2 | 0,5161 | 0,5082 | 0,5136 | **−0,0054** |
| h=4 | 0,5212 | 0,5116 | 0,5130 | **−0,0014** |
| h=8 | 0,4990 | 0,4929 | 0,5148 | **−0,0219** |
| h=12 | 0,5071 | 0,4982 | 0,5209 | **−0,0227** |
| h=24 | 0,5057 | 0,4951 | 0,5314 | **−0,0363** |

→ Horizon lebih panjang **tidak** memperbaiki sinyal; edge accuracy negatif semua.

---

## 3. Interpretasi

1. **Ini pasar efisien di resolusi fitur ini.** Return ~martingale; 29 fitur teknikal
   konvensional hanya menangkap <6% informasi label.
2. **Ceiling ~AUC 0,53** konsisten dengan edge ~0,3 bps — **di bawah biaya realistis**.
   Bahkan model "sempurna" untuk fitur ini tidak akan profitable setelah spread.
3. **Bukan masalah model/hyperparameter/horizon.** A/B/C identik (AUC ~0,523 WF);
   semua horizon gagal. Masalahnya di **sumber informasi** (fitur/target), bukan model.

---

## 4. Rekomendasi (prioritas, tanpa memperlebar arsitektur)

1. **Jangan tuning model/fitur yang ada** — diuji, hasilnya negatif konsisten.
2. **Ubah jenis informasi, bukan jenis model.** Untuk mencari edge yang mengalahkan
   biaya, perlu sumber informasi baru:
   - **Multimodal/makro** (berita, sentimen, kalender ekonomi, DXY/yield) → ini yang
     memang jadi alasan Fase 4 (Global Market Intelligence) ada.
   - **Target yang lebih lunak**: triple-barrier / meta-labeling (prediksi *apakah
     sinyal layak diperdagangkan*, bukan arah mentah).
   - **Resolusi/venue lain**: horizon intraday berbeda, atau instrumen dengan
     karakter edge berbeda (mis. komoditas/news-driven).
3. **Tetapkan ekspektasi realistis:** di M30 fitur teknikal saja, edge>biaya **tidak
   ada**. Perluasan nilai harus datang dari informasi yang **belum** ada di fitur saat ini.
4. **Dokumentasikan sebagai batas baseline.** Ini menjejakkan "lantai" proyek:
   versi ini bukan edge; versi berikutnya harus mengalahkannya **secara net-of-cost**.

---

## 5. Catatan Metodologis

- Semua perhitungan read-only; tidak ada training ke produksi atau penulisan artefak.
- Split kronologis dengan embargo (purge=max(effective_horizon, embargo_bars)).
- Kontrol shuffle label memakai RNG ber-seed; AUC 0,502 mengonfirmasi tidak ada kebocoran.
- MI diestimasi via `sklearn.feature_selection.mutual_info_classif` (kNN-based);
  nilai absolut kecil, gunakan sebagai *ranking* & magnitude relatif.

---

*Diagnosis penutup Fase 2: baseline tidak tradeable karena keterbatasan informasi,
bukan keterbatasan model. Langkah berikutnya memerlukan sumber informasi baru
(Fase 4) atau target yang lebih lunak.*

# FASE 2A — ADAPTIVE BARRIER EXPERIMENT (DESIGN ONLY)

**Status:** DESAIN. **Belum ada kode implementasi, training, atau eksperimen.**
**Tanggal:** 2026-11-08.
**Baseline pembanding:** `fase2a-atr-baseline-frozen` (ATR triple-barrier, frozen).

> Dokumen ini mendefinisikan **eksperimen terpisah**: bisakah AI memprediksi batas
> profit/loss (barrier) yang **lebih adaptif** daripada ATR, dengan hanya memakai
> informasi yang tersedia pada waktu sinyal? Dokumen ini **tidak** mengubah baseline
> ATR dan **tidak** menjalankan apa pun.

---

## 1. PERTANYAAN RISET (satu kalimat)

Apakah barrier profit/loss yang **diprediksi model dari informasi ≤ waktu sinyal**
menghasilkan **net_return out-of-sample yang lebih baik** daripada barrier ATR
(1.5/1.0×ATR, vertical 16), pada split, cost engine, dan aturan eksekusi yang identik?

---

## 2. HIPOTESIS

- **H0 (null):** adaptive barrier **≤** ATR barrier pada net_return OOS (tidak lebih baik).
- **H1 (alt):** adaptive barrier **>** ATR barrier secara konsisten & signifikan.

Ekspektasi jujur: literatur menyarankan ATR sulit dikalahkan OOS setelah biaya. **H0
kemungkinan besar tidak ditolak** — itu hasil yang sah dan menutup hipotesis. **Tidak
ada klaim kemenangan AI sebelum terbukti.**

---

## 3. DEFINISI BARRIER YANG ADAPTIF (dan apa yang BUKAN)

**Yang BUKAN:** membungkus indikator teknikal lain (Bollinger, Keltner, dll.) dan
menyebutnya "AI". Itu hanya mengganti ATR dengan indikator lain — bukan pertanyaan riset.

**Yang DIMAKSUD:** model memprediksi **parameter barrier** (mis. jarak target & stop
sebagai kelipatan ATR, atau sebagai kuantil volatilitas masa depan) dari fitur yang
tersedia di waktu t, dengan label dihitung **offline** dari data masa lalu untuk
training. Barrier adaptif = fungsi(fitur ≤ t) → (k_up_t, k_dn_t, vertical_t).

### 3.1 Bentuk target yang dapat diuji (pilih satu, pra-registrasi)
1. **Volatility-targeted barrier:** prediksi volatilitas ke depan (mis. realized range
   horizon H), barrier = k × prediksi_vol. (Model = forecast volatility.)
2. **Regime-conditional barrier:** klasifikasikan rezim (tenang/bergejolak) dari fitur ≤ t,
   barrier = skala per rezim, di-fit pada data lampau.
3. **Economically-optimal multiplier (careful):** untuk tiap event di data lampau,
   cari (k_up, k_dn) yang memaksimalkan net_return; latih model memprediksi multiplier ini
   dari fitur ≤ t. **WAJIB** label dari periode lampau & evaluasi pada periode masa depan
   (walk-forward), tanpa kebocoran.

> Semua target **dihitung dari masa lalu** dan diprediksi untuk **masa depan**. Prediksi
> waktu t **tidak boleh** memakai outcome event yang sedang/telah dievaluasi.

---

## 4. PROTOKOL ANTI-LEAKAGE (sama ketat untuk kedua sisi)

1. **Chronological split** (train → val → test) — tidak boleh diacak.
2. **Purged walk-forward** dengan embargo ≥ vertical barrier (≥16 bar M30) **dan**
   ≥ panjang event window; purging berbasis `event_start_time`/`event_end_time`
   (sudah tersedia di `event_attribution.py`).
3. **Label barrier adaptif** untuk training dihitung dari bar masa lalu **saja**.
4. **Prediksi** barrier untuk event di test dibuat dari fitur ≤ signal_time, tanpa
   menyentuh outcome ke depan.
5. **Overlap-aware** — tidak ada event overlap lintas train/val/test (test `purge_overlapping_between`).
6. **Tidak ada tuning pada test.** Test disentuh satu kali di evaluasi akhir.

Bukti wajib (unit test tambahan sebelum eksperimen dijalankan):
- Fitur barrier adaptif di waktu t **tidak berubah** bila bar t+1..t+N diubah.
- Prediksi barrier event di test **tidak** memakai outcome event tsb.

---

## 5. PROTOKOL PERBANDINGAN ADIL (apple-to-apple)

Kedua sisi **identik** kecuali cara menentukan barrier:

| Komponen | ATR baseline | Adaptive |
|---|---|---|
| Split / walk-forward / embargo | ✅ identik | ✅ identik |
| Entry timing (open t+1) | ✅ | ✅ |
| Executable bid/ask (simulated) | ✅ | ✅ |
| Cost engine + scenarios | ✅ identik | ✅ identik |
| Status & net_return logic | ✅ identik | ✅ identik |
| **Barrier determination** | **1.5/1.0×ATR, V=16** | **model-predicted** |

Evaluasi melaporkan **side-by-side** pada split & biaya identik, per skenario
(optimistic/baseline/stress), bukan berdiri sendiri.

---

## 6. KRITERIA GO / NO-GO (PRA-REGISTRASI)

Adaptive barrier dinyatakan **GO (lebih baik)** hanya bila **semua**:
1. net_return OOS **>** ATR baseline di **≥3 walk-forward folds** (median net positif
   relatif), di skenario **baseline** biaya.
2. Kenaikan **signifikan**: bootstrap 95% CI selisih (adaptive − ATR) **tidak** melewati 0.
3. Konsisten di skenario **stress** (tidak hanya untung di optimistic).
4. Jumlah trade memadai (bukan hasil dari sedikit trade).
5. Tidak bergantung pada satu periode/rezim (uji per rezim).
6. Tidak ada leakage (dibuktikan test §4).

Jika salah satu gagal → **NO-GO**: ATR tetap baseline; laporkan diagnosis. (Ini hasil
yang sah, bukan kegagalan proyek.)

---

## 7. FITUR YANG BOLEH vs DILARANG

**Boleh (≤ waktu sinyal):** OHLC trailing, wick/body/range, ATR/realized vol trailing,
momentum/return trailing, hour/dow, spread_relative, fitur rezim dari window lampau.

**Dilarang:** harga/return/volatilitas **masa depan**, outcome event itu sendiri,
label yang dihitung dari periode evaluasi, statistik yang di-fit pada test.

---

## 8. RISIKO & KONTROL

| Risiko | Kontrol |
|---|---|
| Overfit multiplier optimal | walk-forward, purged CV, pra-registrasi kriteria |
| Leakage lewat label | label dari masa lalu, prediksi masa depan, test anti-leak |
| "AI" = indikator dibungkus ML | target = forecast/prediksi barrier, bukan indikator lain |
| Klaim berlebihan | side-by-side vs ATR, CI, stress, no edge tanpa bukti |
| ATR memang lebih baik | hasil NO-GO sah; ATR tetap baseline |

---

## 9. DELIVERABLE MASA DEPAN (setelah persetujuan, belum sekarang)

- `nexora_laboratory/adaptive_barrier.py` (model prediksi barrier, interface = skema
  output triple-barrier).
- Unit test anti-leak untuk fitur & prediksi barrier.
- Runner eksperimen side-by-side (ATR vs adaptive) dengan purged walk-forward.
- Laporan per-bandingkan (net_return, folds, CI, per-regime).

**Catatan:** dokumen ini hanya desain. Implementasi & eksperimen menunggu persetujuan
eksplisit terpisah.

# NEXORA AI — FINAL RESEARCH DECISION (STAGE 7)

**Ruang lingkup:** keputusan berbasis bukti STAGE 0–6.
**Sifat:** READ-ONLY. Tanpa training, tanpa perubahan produksi, tanpa eksperimen baru.

---

## VERDICT UTAMA

# `READY_WITH_CONDITIONS`

**Arti:** Penelitian STAGE 0–6 **berhasil secara teknis & eksekusi**, menghasilkan
infrastruktur riset yang reproducible dan **kandidat hipotesis yang layak diuji lebih
lanjut** — **tetapi** *belum* ada bukti edge prediktif yang stabil. "READY_WITH_CONDITIONS"
berarti: **layak melanjutkan penelitian** (walk-forward + net-of-cost) **dengan kondisi
ketat**, **bukan** izin training model atau live trading.

**Alasan:**
- ✅ Ada ruang ekonomi nyata (movement ≫ biaya, terutama emas) → kelayakan biaya terpenuhi.
- ✅ Data emas grade A, biaya terukur (tick), infrastruktur teraudit.
- ⛔ Belum adainformasi forward yang **stabil** OOS (artefak rezim, tanda berbalik).
- ⛔ Ketidakpastian biaya (EURUSD estimasi, komisi N/A) + sampel tipis (XAU D1).
→ Cukup untuk **lanjut riset bersyarat**, tidak cukup untuk training/production.

*(Verdict alternatif yang TIDAK dipilih: `READY_FOR_NEXT_RESEARCH` — terlalu kuat karena
sinyal tidak stabil; `NOT_READY`/`RESEARCH_BLOCKED` — terlalu keras karena infrastruktur
dan kandidat ekonomi jelas ada.)*

---

## LIMA STATUS TERPISAH (jangan disamakan)

### 1. Technical Implementation Success — ✅ **SUCCESS**
**Alasan:** Semua STAGE 0–6 dibangun sebagai modul terisolasi read-only
(`opportunity_discovery/`), masing-masing dengan runner, JSON, dan manifest SHA256. Full
test suite **433 lulus**. Tidak ada perubahan pada `data/`, `database/`, `models/`,
`reports/fase2a/`, `reports/t3/`. Pipeline reproducible.

### 2. Research Execution Success — ✅ **SUCCESS**
**Alasan:** Seluruh pertanyaan riset dieksekusi sesuai desain: horizon discovery, instrument
discovery, cost analysis, availability, IC OOS dengan split temporal + BH/Bonferroni +
anti-lookahead, dan scoring transparan. Tidak ada look-ahead (diuji unit test). Koreksi
multiple-comparison diterapkan. Hasil dilaporkan jujur (termasuk negatif).

### 3. Predictive Edge Evidence — ❌ **NOT ESTABLISHED**
**Alasan:** Banyak fitur signifikan statistik **tetapi** tidak stabil OOS:
- XAUUSD `rng_20` h24: TRAIN +0.020 → TEST −0.083 (**tanda berbalik**).
- EURUSD `vol_60` h12: 2025 +0.167 → 2026 +0.002 (**hilang**).
Sebagian besar survivor punya IC TRAIN ≈ 0 (artefak periode). **Tidak ada** fitur dengan
IC train & test besar, searah, dan stabil lintas tahun. **Belum ada bukti edge.**

### 4. Training Readiness — ❌ **NOT READY**
**Alasan:** Training membutuhkan sinyal yang stabil & tervalidasi OOS (walk-forward), plus
biaya yang pasti. Saat ini: sinyal tidak stabil, EURUSD cost estimasi, komisi N/A, XAU D1
sampel tipis. Melatih model sekarang berisiko overfitting artefak rezim.

### 5. Production / Live Trading Readiness — ❌ **NOT READY / NOT AUTHORIZED**
**Alasan:** Belum ada edge terbukti, belum ada validasi net-of-cost nyata, komisi tidak
diketahui, dan secara eksplisit **tidak ada rekomendasi live trading**. Tidak ada otorisasi
eksekusi.

---

## RINGKASAN KEPUTUSAN

| Dimensi | Status |
|---|---|
| Technical implementation | ✅ SUCCESS |
| Research execution | ✅ SUCCESS |
| Predictive edge evidence | ❌ NOT ESTABLISHED |
| Training readiness | ❌ NOT READY |
| Production / live readiness | ❌ NOT READY |

**Verdict utama: `READY_WITH_CONDITIONS`** — lanjut riset bersyarat, bukan training/live.

---

## KONDISI (syarat melanjutkan)

1. **Walk-forward multi-split** membuktikan IC searah & stabil lintas split & rezim untuk
   kandidat (XAUUSD `ret_5`/`zclose_5` D1/H4; EURUSD `ret_60` H4 h12).
2. **Net-of-cost** dengan band STAGE 3 + **komisi nyata** masih menghasilkan margin.
3. **Perbaikan data**: tick EURUSD atau konfirmasi komisi; bar OHLC dari tick untuk
   GBP/USDJPY.

Bila kondisi tidak terpenuhi → **hentikan jalur** (tidak memaksakan strategi).

---

## PERNYATAAN TEGAS

- **Tidak ada** rekomendasi live trading.
- **Tidak ada** klaim profit atau edge terbukti.
- Kandidat STAGE 6 = **hipotesis penelitian**, bukan peluang yang terbukti.
- STAGE 8 / training otomatis **tidak dimulai** tanpa keputusan terpisah.

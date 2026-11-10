# STAGE 6 — Economic Opportunity Assessment (Skoring)

**Status:** ✅ Selesai (read-only, isolasi). Skor peluang transparan — **BUKAN klaim
profit/backtest/signal**.
**Runner:** `tools/run_opportunity_assessment.py`
**Output:** `opportunity_assessment.json` + `opportunity_assessment_manifest.json`
**Tes:** `tests/test_scoring.py` — 17 lulus. Full suite: **433 passed** (tanpa regresi).

> Catatan: dokumen ini memuat **STAGE 6 (skoring)**. Laporan riset final (STAGE 7)
> akan merangkum seluruh STAGE 0–6.

---

## 0. Ringkasan

Menggabungkan bukti STAGES 1–5 menjadi **skor peluang transparan** per
(instrumen × timeframe × horizon). Kunci desain: **movement-to-cost & cost-drag
memakai biaya NYATA dari STAGE 3** (bukan asumsi bar STAGE 2), dan **signal quality
STRICT** dari STAGE 5 — sehingga artefak rezim tidak bisa disamarkan sebagai peluang.

**Hasil:** 3 `RESEARCH_CANDIDATE` (XAUUSD D1 h2/h1, EURUSD H4 h12), 8 `WATCH`, 1
`WATCH_ECONOMICS_ONLY`. XAUUSD D1 unggul skor tapi sampel test tipis (n≈497);
EURUSD H4 h12 sampel paling tebal (n≈2854) meski cost estimasi. **Semua tetap hipotesis.**

---

## 1. Model skor (transparan, berbobot)

`score = 0.25·economics + 0.20·cost_burden + 0.20·data_readiness + 0.35·signal_quality`

| Komponen | Bobot | Definisi |
|---|---|---|
| economics | 0.25 | `move_to_cost_ratio` (median move / **biaya nyata STAGE 3**), saturasi 10× |
| cost_burden | 0.20 | `1 − min(cost_drag,1)`; cost_drag = biaya/median move |
| data_readiness | 0.20 | skor kesiapan STAGE 4 per instrumen |
| **signal_quality** | **0.35** | **stabilitas IC STAGE 5 (STRICT)** |

**Signal quality STRICT** (per fitur):
```
base         = min(1, |test_ic| / 0.10)
train_factor = min(1, |train_ic| / 0.03)     # train IC harus non-trivial
sign_factor  = 1.0 bila tanda train==test, else 0.35
feature_score = base · train_factor · sign_factor
signal_quality = max(feature_score)
```
→ Fitur yang "lolos BH" tapi **train≈0** atau **tanda berbalik** → skor ~0. Ini sengaja.

**Verdict (gating konservatif):**
- `signal_quality < 0.10` → paling tinggi `WATCH_ECONOMICS_ONLY` (atau `REJECT`).
- `0.10 ≤ signal_quality < 0.30` → paling tinggi `WATCH` (tak bisa jadi kandidat).
- `signal_quality ≥ 0.30`: `score≥0.65` → `RESEARCH_CANDIDATE`; `≥0.45` → `WATCH`; else `REJECT`.
- **Economics + data + cost tak bisa sendiri menjadikan kandidat** — floor sinyal wajib.

---

## 2. Peringkat (cost = baseline)

| # | Instrumen | TF | h | econ | cost | data | sig | **Skor** | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | XAUUSD | D1 | 2 | 1.000 | 0.973 | 0.980 | 0.523 | **0.824** | RESEARCH_CANDIDATE |
| 2 | XAUUSD | D1 | 1 | 1.000 | 0.958 | 0.980 | 0.375 | **0.769** | RESEARCH_CANDIDATE |
| 3 | XAUUSD | H1 | 24 | 1.000 | 0.967 | 0.980 | 0.194 | 0.707 | WATCH |
| 4 | XAUUSD | H4 | 12 | 1.000 | 0.977 | 0.980 | 0.179 | 0.704 | WATCH |
| 5 | EURUSD | H4 | 12 | 0.788 | 0.873 | 0.777 | 0.471 | **0.692** | RESEARCH_CANDIDATE |
| 6 | XAUUSD | H4 | 8 | 1.000 | 0.971 | 0.980 | 0.130 | 0.686 | WATCH |
| 7 | XAUUSD | H4 | 4 | 1.000 | 0.955 | 0.980 | 0.100 | 0.672 | WATCH |
| 8 | XAUUSD | H1 | 12 | 1.000 | 0.949 | 0.980 | 0.055 | 0.655 | WATCH_ECONOMICS_ONLY |
| 9 | EURUSD | H4 | 8 | 0.638 | 0.843 | 0.777 | 0.391 | 0.621 | WATCH |
| 10 | EURUSD | H1 | 24 | 0.560 | 0.821 | 0.777 | 0.305 | 0.566 | WATCH |
| 11 | EURUSD | H1 | 12 | 0.368 | 0.728 | 0.777 | 0.415 | 0.538 | WATCH |
| 12 | EURUSD | H4 | 4 | 0.426 | 0.765 | 0.777 | 0.327 | 0.530 | WATCH |

---

## 3. Tiga `RESEARCH_CANDIDATE` (dengan caveat jujur)

| Kandidat | Skor | Signal | Fitur pendorong | Sampel test | Caveat |
|---|---|---|---|---|---|
| **XAUUSD D1 h2** | 0.824 | 0.523 | `ret_5` test −0.052 / train −0.034 (searah) | **n≈497** | sampel **tipis**; D1 hanya 1662 bar |
| **XAUUSD D1 h1** | 0.769 | 0.375 | `ret_5`, `zclose_5` searah | **n≈498** | sampel **tipis** |
| **EURUSD H4 h12** | 0.692 | 0.471 | `zclose_60`/`ret_60` searah | **n≈2854** | **cost = estimasi** (tanpa tick) |

**Bacaan jujur:**
- **XAUUSD D1** unggul skor karena sinyal `ret_5` **konsisten-searah** dan train-IC
  non-trivial. **TAPI** sampel test D1 hanya ~500 → CI lebar; "signifikan" harus
  diperlakukan hati-hati.
- **EURUSD H4 h12** sampel paling tebal & fitur searah, tetapi **biaya estimasi** (STAGE
  3) → hasil net-of-cost belum pasti.
- **WATCH** (H1 h24, H4 h8/h12): fitur terbaik **tanda berbalik** (train +0.02 → test
  −0.08) → **sengaja diturunkan** dari kandidat, walau skor mentah tinggi. Inilah
  kejujuran yang mencegah false positive.

---

## 4. Sensitivitas biaya (stress)

Karena biaya baseline emas sangat kecil, kandidat emas tetap tinggi di baseline.
Uji `--cost-scenario stress` (spread p99) untuk memastikan verdict tidak rapuh. EURUSD
lebih sensitif karena biaya estimasi 5.0 pip (STAGE 3).

---

## 5. Kesimpulan STAGE 6 (jujur)

1. **3 kandidat riset** — tapi **semua = hipotesis** yang butuh **walk-forward multi-split**
   (STAGE 5 hanya 1 split) + **net-of-cost** sebelum boleh disebut peluang nyata.
2. **XAUUSD D1** paling tinggi skor tapi **sampel tipis** — prioritas validasi: walk-forward
   `ret_5`/`zclose_5` pada D1/H4 dengan lebih banyak split.
3. **EURUSD H4 h12** sampel tebal tapi **biaya estimasi** — perlu tick atau konfirmasi
   komisi (STAGE 3) sebelum skor net-of-cost dipercaya.
4. **WATCH_ECONOMICS_ONLY** (XAUUSD H1 h12): secara ekonomi menarik (move besar, biaya
   kecil) **tetapi** tak ada sinyal stabil → jangan dijadikan kandidat.
5. **Tidak ada** klaim profit, backtest, atau signal. Skor = ringkasan bukti, bukan janji.

---

## 6. Rekomendasi untuk STAGE 7 / langkah lanjut

- **Walk-forward validation** (rolling train/test, banyak split) untuk XAUUSD `ret_5`
  (D1/H4) & EURUSD `ret_60` (H4 h12) — uji stabilitas lintas rezim, bukan 1 split.
- **Net-of-cost** dengan band STAGE 3 (optim/baseline/stress) + konfirmasi komisi nyata.
- Bila walk-forward **juga tidak stabil** → tutup jalur (jangan paksakan strategi).
- STAGE 7 = laporan riset final merangkum STAGE 0–6 + rekomendasi ini secara eksplisit.

---

## 7. Reproduksibilitas

- `.\.venv\Scripts\python.exe tools/run_opportunity_assessment.py`
  (`--cost-scenario optimistic|baseline|stress`).
- Manifest: SHA256 STAGES 1–5 JSON (input) + `opportunity_assessment.json` (output).
- Komponen & bobot terdokumentasi di kode (`scoring.py`) dan JSON (`weights`).

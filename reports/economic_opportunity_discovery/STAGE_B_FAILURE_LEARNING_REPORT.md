# Tahap B — Failure Learning : Implementation Report

**Status:** ✅ Selesai (implementasi + tes). Non-produksi. Isolated.
**Referensi desain:** `AUTONOMOUS_RESEARCH_ARCHITECTURE.md` (§3.6, §5.6).
**Tes:** `tests/test_failure_learning.py` — 24 lulus. Full suite: **352 passed** (tanpa regresi).

---

## 1. Apa yang dibangun

Classifier **Failure Learning** (kemampuan #6): memetakan bukti terukur dari tahap
discovery/evaluasi/feature-power menjadi **satu** `failure_type` (berprioritas) +
**recommendation** konkret, lalu menyimpannya ke Knowledge Memory.

### File baru
- `nexora_research/failure_learning.py`
  - `classify_failure(evidence)` — **fungsi murni** (tanpa DB/IO). Input dict bukti → `FailureDiagnosis`.
  - `classify_and_record(store, experiment_id, evidence, ...)` — klasifikasi + persist ke `research_failures` + entri `research_knowledge`.
- `nexora_research/__init__.py` — expose `store`, `failure_learning`.

### 6 tipe kegagalan + fallback (prioritas berurutan)
| Prioritas | `failure_type` | Pemicu (bukti) | Recommendation inti |
|---|---|---|---|
| 1 | `DATA_QUALITY` | missing>10% / spread-zero>50% / granularity break | perbaiki/akuisi data (pakai tick asli) |
| 2 | `STRUCTURAL_INFEASIBILITY` | tak ada horizon feasible / move_to_cost_ratio<1.0 | jangan latih; naikkan horizon/instrumen |
| 3 | `NO_PREDICTIVE_POWER` | n_usable=0 / IC OOS gagal | akuisisi **informasi baru** |
| 4 | `EDGE_BELOW_COST` | auc_net>0.52 tapi edge_pips<cost |  edge nyata tapi kecil; perpanjang horizon/lower cost |
| 5 | `OVERFIT` | train-test gap>0.10 / walk-forward tak stabil | perketat purge, sederhanakan fitur |
| 6 | `REGIME_FRAGILE` | regime/year fail fraction>1/3 | kondisikan regime / tolak |
| — | `UNKNOWN` | tak ada bukti mengisolasi | akuisisi pengukuran lebih dulu |

**Prioritas penting**: sebab lebih awal = prasyarat. Data buruk membatalkan segalanya;
target yang struktural-infeasible tidak "sampai" ke overfit. Sebab pertama yang didukung
bukti menang.

---

## 2. Guardrail yang dienforce

| Guardrail (§5) | Implementasi | Tes |
|---|---|---|
| **Failure must teach** (§5.6) | `failure_type` valid + `recommendation` non-kosong **selalu** (including UNKNOWN) | `test_always_has_recommendation_and_valid_type` (8 kasus) |
| Berbasis bukti, bukan karangan | hanya memetakan bukti terukur; ambang eksplisit & terdokumentasi | test per-cause |
| Tanpa overclaim | tidak mengklaim profit; recommendation menyuruh verifikasi/akuisisi | — |
| Tidak sentuh produksi | hanya lewat `ResearchMemoryStore` (DB riset terpisah) | integrasi pakai tmp DB |

**Ambang eksplisit** (bukan magic): `DATA_MISSING_MAX=0.10`, `DATA_SPREAD_ZERO_MAX=0.50`,
`FEASIBILITY_RATIO_MIN=1.0`, `EDGE_AUC_MIN=0.52`, `OVERFIT_TRAIN_TEST_GAP=0.10`,
`STABILITY_FAIL_FRACTION_MAX=0.34`.

---

## 3. Integrasi dengan Tahap A

`classify_and_record` menulis dua hal ke Knowledge Memory:
1. **`research_failures`** (wajib) — `failure_type`, `recommendation`, `evidence` (termasuk `reasons`).
2. **`research_knowledge`** (opsional, default on) — entri `CONSTRAINT` (untuk
   DATA_QUALITY/STRUCTURAL_INFEASIBILITY) atau `DEAD_END` (lainnya), sehingga pelajaran
   bisa di-query oleh Strategy Evolution nanti.

Contoh (dari kasus nyata EURUSD M30/h2):
```python
classify_and_record(store, experiment_id=eid,
    evidence={"edge": {"auc_net": 0.55, "edge_pips_per_sd": 0.097, "cost_pips": 3.2}})
# -> failure_type="EDGE_BELOW_COST"
# -> knowledge (DEAD_END): "edge nyata tapi < cost; perpanjang horizon / lower cost"
```

---

## 4. Batasan yang disengaja

- Classifier **menerima** bukti; ia tidak menghitung feasibility/feature-power sendiri.
  Penyambungan otomatis dari hasil evaluasi dilakukan di Tahap D (Control Loop).
- Belum ada *reasoner* multi-sebab (mis. "EDGE_BELOW_COST **dan** REGIME_FRAGILE");
  saat ini mengembalikan **satu sebab primer** + `reasons` list untuk transparansi.
  Multi-sebab bisa ditambah bila dibutuhkan.
- Tidak mempromosikan/menolak model secara otomatis — hanya mendiagnosis.

---

## 5. Verifikasi

```
$ pytest tests/test_failure_learning.py -q   -> 24 passed
$ pytest tests/ -q                           -> 352 passed (40 warnings, no regressions)
```

## 6. Langkah berikutnya

Rekomendasi desain §6: setelah A & B → **Tahap C — Hypothesis/Experiment repositories**
(sebagian sudah tercakup `store.py`; Tahap C melengkapinya dengan helper pre-registration
yang lebih eksplisit + generator hipotesis deterministik berbasis aturan+bukti), lalu
**Tahap D — Control Loop** (orkestrasi di `nexora_scheduler`) yang menyambungkan semuanya.

**Pertanyaan terbuka (desain §6):**
- Generator hipotesis (Tahap C/E): deterministik berbasis aturan+bukti (rekomendasi) atau LLM?
- Setelah C: lanjut D (Control Loop) langsung, atau E (Strategy Evolution) dulu?

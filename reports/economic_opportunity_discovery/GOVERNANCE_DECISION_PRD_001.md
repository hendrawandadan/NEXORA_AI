# RESEARCH GOVERNANCE DECISION — PRICE-DERIVED RESEARCH LANE SUSPENSION

**Decision ID:** NEXORA-GOV-PRD-001
**Effective Date:** 2026-11-09
**Status:** `SUSPENDED`
**Policy:** Temporary Suspension — Option A
**Reopenability:** REOPENABLE WITH EVIDENCE AND AUTHORIZATION

> Machine-enforced. Registry: `config/governance/price_derived_lane_suspension.json`.
> Guard: `nexora_laboratory/governance/lane_suspension.py`. Tes:
> `tests/test_governance_lane_suspension.py`.

---

## 1. Background

Economic Opportunity Discovery **STAGE 0–7** dan **Walk-Forward Multi-Split Validation**
telah diselesaikan. Hasil validasi (`walkforward_validation.json`, 8 fold):

- **0/20** kandidat memenuhi kriteria robust.
- **XAUUSD D1 h1/h2** gagal memenuhi stabilitas (0/8; `ret_5` tanda berbalik; `zclose_5`/
  `rng_60` 0 fold signifikan).
- **XAUUSD H4 h8/h12** menunjukkan pembalikan IC antar-fold (IC −0.145 … +0.058).
- **EURUSD H4 h12** sensitif terhadap jumlah fold (`rng_60` hanya lolos di fold=5,6; gagal
  di fold=4,7,8,10).
- **Belum ada predictive edge yang terbukti stabil.**

Bukti rujukan: `WALKFORWARD_VALIDATION_REPORT.md`, `FINAL_RESEARCH_DECISION.md`,
`final_research_report.json`, `new_information_assessment.json`, `opportunity_assessment.json`.

## 2. Decision

NEXORA menetapkan status **PRICE-DERIVED RESEARCH LANE** menjadi **SUSPENDED**.

Keputusan ini **bukan** penghapusan sistem, **bukan** penutupan permanen seluruh penelitian
price-derived, dan **bukan** penghentian proyek NEXORA AI.

## 3. Scope of Suspension

Hipotesis & konfigurasi yang telah diuji:

- Momentum dan return-based features.
- Z-score price-derived.
- Range dan position-in-range.
- Volatility-derived features yang telah diuji.
- Kandidat **XAUUSD D1** dan **H4** dari STAGE 6.
- Kandidat **EURUSD H4** dari STAGE 6.
- Hipotesis terkait yang gagal dalam Walk-Forward Validation.

**Kandidat tersuspensi (5):**

| Instrumen | TF | h | STAGE-6 score | WF stable |
|---|---|---|---|---|
| XAUUSD | D1 | 1 | 0.769 | ❌ |
| XAUUSD | D1 | 2 | 0.824 | ❌ |
| XAUUSD | H4 | 8 | 0.686 | ❌ |
| XAUUSD | H4 | 12 | 0.704 | ❌ |
| EURUSD | H4 | 12 | 0.692 | ❌ |

## 4. Prohibited Activities

Selama status **SUSPENDED** (ditegakkan oleh `assert_can()` — fail-closed):

- ❌ Tidak menjalankan **training** berdasarkan kandidat yang gagal.
- ❌ Tidak melakukan **hyperparameter tuning** untuk memaksakan hasil positif.
- ❌ Tidak **mempromosikan model** dari jalur penelitian ini.
- ❌ Tidak **mengaktifkan strategi** terkait untuk **live trading**.
- ❌ Tidak **menghapus/menimpa** laporan kegagalan.
- ❌ Tidak **mengubah** hasil eksperimen historis.
- ❌ Tidak ada scheduler / autonomous agent / training runner yang boleh **auto-reopen**.

*(Aksi read/audit/document/review/propose tetap diizinkan — tindakan manajemen pengetahuan.)*

## 5. Preserved Assets

Seluruh kode, dataset, hipotesis, eksperimen, laporan, manifest, dan hasil pengujian
**wajib dipertahankan**. Hasil negatif menjadi bagian dari **Research Knowledge Base**
NEXORA dan digunakan untuk mencegah pengulangan eksperimen yang sama.

## 6. Reopening Conditions

Jalur dapat diajukan dibuka kembali bila minimal salah satu:

1. Sumber data baru yang memberikan informasi tambahan.
2. Hipotesis baru yang **berbeda secara substantif** dari hipotesis gagal.
3. Bukti kualitas data yang sebelumnya tidak tersedia.
4. Metode pengukuran baru dengan alasan ilmiah yang dapat diuji.

**Prosedur wajib:** dokumentasi alasan → pemeriksaan data & leakage → hipotesis baru →
**pre-registration** → penetapan kriteria **GO/NO-GO** → **walk-forward validation** →
evaluasi **net-of-cost** → **persetujuan pengguna** sebelum training/promosi model.

## 7. Governance Authority

Status **SUSPENDED** hanya dapat diubah melalui **keputusan eksplisit pengguna**.
Tidak ada scheduler, autonomous research agent, maupun training runner yang boleh
mengaktifkan kembali jalur ini secara otomatis.

## 8. Final Statement

NEXORA tidak menghapus penelitian yang gagal. NEXORA mempertahankan hasilnya sebagai
pengetahuan, menghentikan pengulangan yang tidak produktif, dan hanya membuka kembali
penelitian ketika terdapat alasan dan bukti baru.

**Final Status:** `SUSPENDED` — REOPENABLE WITH EVIDENCE AND AUTHORIZATION.

---

### Enforcement (ringkas)

```python
from nexora_laboratory.governance.lane_suspension import assert_can, GovernanceViolation
assert_can("train")          # raises GovernanceViolation while SUSPENDED
assert_can("read")           # allowed
```

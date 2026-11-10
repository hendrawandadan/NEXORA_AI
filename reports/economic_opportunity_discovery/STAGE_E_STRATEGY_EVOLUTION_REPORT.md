# Tahap E — Strategy Evolution : Implementation Report

**Status:** ✅ Selesai (implementasi + tes). Non-produksi. Isolated.
**Referensi desain:** `AUTONOMOUS_RESEARCH_ARCHITECTURE.md` (§3.8, §4 Tahap E, §5 guardrails, §6 reopening).
**Tes:** `tests/test_strategy_evolution.py` → **14 lulus**. Full suite: **534 passed** (tanpa regresi).

---

## 1. Apa yang dibangun

Generator **usulan strategi berbasis bukti** (kemampuan #8): membaca **Knowledge Memory**,
mengklasifikasi pola kegagalan/keberhasilan, lalu **mengusulkan hipotesis turunan** yang
**berbeda secara substantif** dari yang gagal — sesuai **kondisi reopening** governance.

### File baru
- `nexora_research/strategy_evolution.py`
  - `evolve_proposals(store, ...)` — fungsi utama (baca memori → usulan).
  - `EvolutionProposal` — dataclass usulan (serializable, `.allowed`, `.to_hypothesis()`).
  - `_governance_status(...)` — gate per-usulan (sadar lane suspension).
- `nexora_research/__init__.py` — expose `strategy_evolution`.
- `tests/test_strategy_evolution.py` — 14 tes.

---

## 2. Aturan evolusi (masing-masing wajib "change basis")

| rule_id | Pemicu bukti | Usulan | Change basis (kondisi reopening) |
|---|---|---|---|
| `R_EVOLVE_NEW_INFO_SOURCE` | `NO_PREDICTIVE_POWER` (fitur price-derived gagal) | Akuisisi **sumber informasi baru** (order-flow/makro/cross-asset) | Kondisi #1: sumber data baru — **lane INFO_ACQUISITION, tidak tersuspensi** |
| `R_EVOLVE_HORIZON_SHIFT` | `EDGE_BELOW_COST` / `OVERFIT` / `REGIME_FRAGILE` | Uji horizon **kelas berbeda** (2×) | Kondisi #2: horizon berbeda (bukan pengulangan) — **lane PRICE_DERIVED** |
| `R_EVOLVE_INSTRUMENT_TRANSFER` | ada entri **GO** untuk sebuah family | Uji family yang menang di **instrumen lain** | Kondisi #2: transfer instrumen (pasar berbeda) — **lane PRICE_DERIVED** |

**Guardrail:** (a) setiap usulan **wajib** punya `change_basis` (tes menegakkan); (b) usulan
yang **sama persis** dengan signature dead-end **ditolak**; (c) deterministik (urutan stabil);
(d) usulan **tidak** melatih/meregistrasi sendiri — caller yang mengubah ke hipotesis via
`to_hypothesis()` lalu `registry.pre_register()` (gate pre-registration).

---

## 3. Governance gating — HASIL PENTING (jujur)

Karena **Price-Derived lane = SUSPENDED (NEXORA-GOV-PRD-001)**, gate usulan:

| Contoh usulan | Lane | Status governance |
|---|---|---|
| `R_EVOLVE_NEW_INFO_SOURCE` (GBPUSDm — price features gagal) | INFO_ACQUISITION | ✅ **ALLOWED** |
| `R_EVOLVE_HORIZON_SHIFT` (EURUSD H4 h12→h24) | PRICE_DERIVED | 🚫 **BLOCKED_GOVERNANCE** |
| `R_EVOLVE_HORIZON_SHIFT` (XAUUSD D1 h1→h2, h2 adalah kandidat tersuspensi) | PRICE_DERIVED | 🚫 **BLOCKED** + alasan menyebut kandidat |

**Interpretasi:** "horizon shift" memang *berbeda*, tetapi masih **price-derived** pada lane
yang **SUSPENDED** → **tidak boleh** dijalankan otomatis; butuh **otorisasi reopening
eksplisit pengguna**. Hanya **`R_EVOLVE_NEW_INFO_SOURCE`** yang lolos — dan itu **persis
kondisi reopening #1** (sumber data baru). Ini jalur jujur ke depan.

> Catatan: bila lane **tidak** tersuspensi, usulan price-derived yang berbeda akan `ALLOWED`
> (logic `_governance_status` menanganinya; diuji lewat gate). Saat ini sengaja BLOCKED.

---

## 4. Bukti smoke test (data memori nyata)

Seed failure memori yang **mencerminkan temuan STAGE 6/7** (XAUUSD D1 OVERFIT, EURUSD H4
EDGE_BELOW_COST, GBPUSDm NO_PREDICTIVE_POWER):

```
=== 4 proposals ===
[R_EVOLVE_NEW_INFO_SOURCE]  GBPUSDm   lane=INFO_ACQUISITION  status=ALLOWED
[R_EVOLVE_HORIZON_SHIFT]    EURUSD H4 h24  lane=PRICE_DERIVED  status=BLOCKED_GOVERNANCE
[R_EVOLVE_HORIZON_SHIFT]    XAUUSD D1 h2   lane=PRICE_DERIVED  status=BLOCKED (candidate)
[R_EVOLVE_HORIZON_SHIFT]    XAUUSD D1 h4   lane=PRICE_DERIVED  status=BLOCKED_GOVERNANCE
```

---

## 5. Non-produksi (diverifikasi tes)

- Read-only terhadap DB riset **kecuali** `record_proposals=True` → menulis entri
  `STRATEGY_LEAD` **append-only berversi** (tes `test_recording_is_append_only_versions`).
- Tidak menyentuh `models/`, `nexora_state.db`, `reports/fase2a/`, `reports/t3/`
  (git status protected dirs = kosong).
- Tidak melatih, tidak promosi, tidak live.

---

## 6. Yang BELUM (di luar Tahap E)

- **Eksekusi training nyata** = Tahap F (butuh izin manusia terpisah).
- **Akuisisi data baru** (`R_EVOLVE_NEW_INFO_SOURCE`) = tindakan nyata yang menuntut
  keputusan pengguna (repo data baru + prosedur reopening §6).
- **Scheduler** otomatis (loop/usulan callable manual).

---

## 7. Kesimpulan

Tahap E menutup loop kognitif: **belajar dari gagal → usul langkah baru berbasis bukti** —
tetapi **setia pada governance**: usulan price-derived pada lane SUSPENDED **ditolak
otomatis**, dan satu-satunya yang diizinkan adalah **akuisisi informasi baru** (kondisi
reopening #1). Tidak ada pengulangan dead-end buta, tidak ada klaim untung, tidak ada
training otomatis.

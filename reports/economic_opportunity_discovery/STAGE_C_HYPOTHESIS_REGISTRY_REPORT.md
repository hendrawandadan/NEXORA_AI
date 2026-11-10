# Tahap C — Hypothesis / Experiment Registry : Implementation Report

**Status:** ✅ Selesai (implementasi + tes + demo pada data nyata). Non-produksi. Isolated.
**Referensi desain:** `AUTONOMOUS_RESEARCH_ARCHITECTURE.md` (§3.2, §3.3, §5.1, §3.8).
**Tes:** `tests/test_hypothesis_registry.py` — 12 lulus. Full suite: **364 passed** (tanpa regresi).

---

## 1. Apa yang dibangun

Generator hipotesis **deterministik berbasis aturan+bukti** (kemampuan #2) + **registry
pre-registration** (kemampuan #3). Tidak ada LLM, tidak ada penciptaan bebas: setiap
hipotesis adalah aturan yang dipicu bukti terukur → teraudit & reproducible.

### File baru
- `nexora_research/knowledge_query.py` — query read-only memori; `dead_end_signatures()`.
- `nexora_research/hypothesis_generator.py` — `generate_hypotheses(...)` (fungsi murni; hanya **membaca** store untuk skip dead-end).
- `nexora_research/registry.py` — `pre_register()`, `build_experiment_spec()`, `register_experiment_for()`, `generate_and_register()`.
- `nexora_research/__init__.py` — expose semua modul.

### 3 aturan generator (rule_id)
| Aturan | Pemicu (bukti) | GO criteria pre-registered |
|---|---|---|
| `R_HORIZON_FEASIBLE` | move/cost ≥ 5× **dan** required-acc ≤ 62% | OOS directional accuracy ≥ req+0.01 **dan** net-expectancy CI-lower > 0 |
| `R_FEATURE_INFO` | ada fitur OOS-usable dengan \|IC\| ≥ 0.02 | OOS \|IC\| ≥ ambang + net-expectancy CI-lower > 0 |
| `R_CROSS_TF_AGREEMENT` | move wall-clock sama konsisten lintas TF (≤1 pip) | net-expectancy CI-lower > 0 + OOS accuracy ≥ 0.52 |

Ambang eksplisit: `FEASIBLE_RATIO_MIN=5.0`, `REACHABLE_ACC_MAX=0.62`, `FEATURE_MIN_ABS_IC=0.02`, `CROSS_TF_MEDIAN_TOL_PIPS=1.0`.

---

## 2. Alur pre-registration (auditable, frozen)

```
generate_hypotheses(evidence)              # rules fire (deterministik)
   -> pre_register(store, hyp)             # PRE_REGISTERED + content_sha256
   -> build_experiment_spec(hyp)           # spec deterministik (split, cost, target, GO)
   -> register_experiment_for(store, ...)  # CREATED + spec_sha256
```

`build_experiment_spec` menyimpan `pre_registered_go_criteria` + `evidence_at_spec` di
dalam spec, lalu spec di-hash (`spec_sha256`) oleh `store.create_experiment` → **tidak
bisa diubah diam-diam setelah melihat hasil** (guardrail §5.1).

---

## 3. Guardrail yang dienforce

| Guardrail (§5) | Implementasi | Tes |
|---|---|---|
| **Pre-registration dulu** (§5.1) | spec hash + GO criteria dibekukan di depan | `test_register_experiment_binds_spec_hash`, `test_pre_register_embeds_signature_in_go_criteria` |
| **Deterministik** | urutan stabil (rule priority + key); input sama → output sama | `test_generation_is_deterministic`, `test_build_experiment_spec_deterministic` |
| **Tak ulang dead-end** (§3.8) | `dead_end_signatures()` → skip, kecuali `allow_dead_ends=True` | `test_dead_end_skipped_unless_allowed` |
| **Falsifiable** | setiap hipotesis punya GO criteria eksplisit (metrik+ambang+cost) | semua tes generator |
| Tidak sentuh produksi | hanya `ResearchMemoryStore` | dry-run + tmp DB |

---

## 4. Demo pada data NYATA (dry-run, tanpa tulis DB)

Dijalankan pada `reports/economic_opportunity_discovery/horizon_discovery.json`:

- **7 hipotesis `R_HORIZON_FEASIBLE`** dipicu: H4 h4/h8/h12, H1 h12/h24, M30 h24/h48.
  - H4 h12 (48 jam): ratio **12.31×**, GO threshold **55.06%** (paling dekat coin-flip).
  - H4 h4: ratio 6.66×, GO 58.5% (horizon pendek butuh akurasi lebih tinggi).
- **4 hipotesis `R_CROSS_TF_AGREEMENT`** — memvalidasi koherensi data:
  4h≈9.3, 8h≈13.9, 12h≈18.4, 24h≈27.9 pips lintas TF.
- **Correctly excluded**: M30 h8/h16 (ratio 2.9×/4.4× < 5) dan semua h=2 (infeasible).

Ini menunjukkan generator **secara otomatis** mereproduksi kesimpulan STAGE 1 yang
sebelumnya dibuat manual (H4/48h = kandidat terbaik) — bukti bahwa aturan+ambang konsisten.

---

## 5. Batasan yang disengaja

- Generator **membaca bukti**, tidak menghitung feasibility/feature-power sendiri.
  Penyambungan otomatis antara evaluator → generator → registry → training adalah
  **Tahap D (Control Loop)**.
- Belum ada LLM brainstorming (sesuai rekomendasi §6: deterministik dulu; LLM opsional
  nanti dengan pre-registration tetap wajib).
- `R_CROSS_TF_AGREEMENT` menandai TF gabungan (mis. "H1/M30"); saat training nyata
  (Tahap D/F) perlu dipecah per-TF — dicatat sebagai pekerjaan Tahap D.

---

## 6. Verifikasi

```
$ pytest tests/test_hypothesis_registry.py -q  -> 12 passed
$ pytest tests/ -q                            -> 364 passed (40 warnings, no regressions)
demo generate_hypotheses(horizon_discovery.json) -> 11 hipotesis (7 feasible + 4 cross-tf)
```

## 7. Progres keseluruhan Autonomous Research

| Tahap | Status |
|---|---|
| A — Knowledge Memory | ✅ |
| B — Failure Learning | ✅ |
| C — Hypothesis/Experiment registry | ✅ |
| D — Control Loop (orkestrasi) | ⬜ berikutnya (rekomendasi) |
| E — Strategy Evolution | ⬜ |
| F — Auto-training nyata (butuh izin) | ⬜ |

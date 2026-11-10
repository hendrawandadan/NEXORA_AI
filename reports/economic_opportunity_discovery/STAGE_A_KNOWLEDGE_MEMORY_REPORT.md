# Tahap A — Knowledge Memory : Implementation Report

**Status:** ✅ Selesai (implementasi + tes). Non-produksi. Isolated.
**Referensi desain:** `AUTONOMOUS_RESEARCH_ARCHITECTURE.md` (§4 Tahap A, §5 guardrails).
**Tes:** `tests/test_research_memory.py` — 13 lulus. Full suite: **328 passed** (tanpa regresi).

---

## 1. Apa yang dibangun

Fondasi **Knowledge Memory** (kemampuan #7) — memori riset durable & append-only yang
dipakai semua tahap berikutnya (Failure Learning, Hypothesis/Experiment registry,
Control Loop, Strategy Evolution).

### Package baru (isolated)
- `nexora_research/__init__.py`
- `nexora_research/config.py` — path DB riset **terpisah**:
  `database/nexora_research.db` (≠ produksi `nexora_state.db`).
- `nexora_research/migrations/001__research_memory_schema.sql` — 5 tabel memori.
- `nexora_research/store.py` — `ResearchMemoryStore` (append-only, content-hashed).

### Database (terpisah dari produksi)
`database/nexora_research.db` (dibuat otomatis via `MigrationManager` yang sudah ada).
Tabel:
| Tabel | Peran |
|---|---|
| `research_hypotheses` | Hipotesis pre-registered + `content_sha256` |
| `research_experiments` | Spesifikasi eksperimen deterministik + `spec_sha256`, terikat hypothesis |
| `research_evaluations` | Verdict net-of-cost + hasil + `result_sha256` |
| `research_failures` | Klasifikasi sebab + **recommendation wajib** (failure must teach) |
| `research_knowledge` | Memori immutable, **berversi** (key, version) — tidak pernah overwrite |

---

## 2. Guardrail yang DIENFORCE di kode (bukan sekadar dokumen)

| Guardrail (desain §5) | Implementasi | Tes |
|---|---|---|
| Pre-registration dulu | `create_experiment` menolak jika hypothesis bukan `PRE_REGISTERED`/`UNDER_TEST`/`EVALUATED` | `test_experiment_requires_existing_hypothesis` |
| Provenance / content-hash | Setiap entri di-hash kanonik SHA256 (skema `experiment_freeze`) | `test_register_hypothesis_returns_sha_and_id` |
| Immutable / append-only | Tidak ada API update; perubahan = versi baru; versi lama utuh | `test_knowledge_is_versioned_append_only` |
| Failure must teach | `record_failure` mewajibkan `recommendation` non-kosong | `test_failure_requires_recommendation` |
| Tidak sentuh produksi | Hanya membuka `RESEARCH_DATABASE_PATH`; default ≠ produksi | `test_default_db_path_is_research_not_production` |
| Ordinalitas record | eval butuh experiment; failure butuh experiment | `test_evaluation_requires_experiment`, dst. |

---

## 3. Reuse (tidak bikin ulang)

- `nexora_state_db.connection.SQLiteConnectionManager` — koneksi WAL/FK/busy_timeout.
- `nexora_state_db.migrations.MigrationManager` — migrasi ber-checksum, atomic.
- `nexora_laboratory.experiment_freeze._hash_payload` — skema hash kanonik sama
  dengan freeze/verify produksi → provenance konsisten satu ekosistem.

---

## 4. API utama `ResearchMemoryStore`

```python
store = ResearchMemoryStore()                         # bootstraps research DB
h = store.register_hypothesis(hypothesis_key=..., instrument=..., timeframe=...,
                              horizon_bars=12, claim=..., go_criteria={...})
e = store.create_experiment(experiment_key=..., hypothesis_id=h["id"], spec={...})
ev = store.record_evaluation(experiment_id=e["id"], verdict="NO_GO", result={...},
                             auc_net=0.51, lower_ci=-0.002, upper_ci=0.001)
store.record_failure(experiment_id=e["id"], failure_type="EDGE_BELOW_COST",
                     recommendation="naikkan horizon / cari informasi baru", evidence={...})
store.record_knowledge(knowledge_key="eurusd_m30", kind="DEAD_END",
                       summary="M30/h2 infeasible: edge≈0.097 pip/sd vs cost 3.2 pip")
store.knowledge_versions("eurusd_m30")                # [v1, v2, ...]
store.list_failures(experiment_id=e["id"])
```

---

## 5. Batasan yang disengaja (belum termasuk Tahap A)

- **Belum ada** integrasi otomatis ke pipeline evaluasi/training — Tahap A murni
  *storage & provenance*. Penyambungan terjadi di Tahap B–D.
- **Belum** ada generator hipotesis / evolusi strategi (Tahap C/E).
- **Belum** ada scheduler loop (Tahap D) — `nexora_scheduler` masih kosong.
- Verdict maksimum tetap `READY_FOR_CONFIRMATORY_EXPERIMENT` oleh desain; modul ini
  hanya menyimpan verdict, tidak memutuskan promosi.

---

## 6. Verifikasi

```
$ pytest tests/test_research_memory.py -q        -> 13 passed
$ pytest tests/ -q                               -> 328 passed (40 warnings, no regressions)
research DB tables   = research_hypotheses, research_experiments, research_evaluations,
                       research_failures, research_knowledge (+ schema_migrations)
research DB path     = database/nexora_research.db  (terpisah dari nexora_state.db)
```

## 7. Langkah berikutnya

Tahap berikutnya menunggu konfirmasi Anda (desain §6 urutan). Rekomendasi:
**Tahap B — Failure Learning classifier** (fungsi murni yang mengklasifikasikan sebab
NO_GO ke `FAILURE_TYPES` + mengisi recommendation), lalu **Tahap C — Hypothesis/Experiment
repositories** yang sudah sebagian tercakup oleh store ini.

**Pertanyaan terbuka (dari desain §6):**
- Penyimpanan: pakai SQLite riset (SUDAH dipilih) — konfirmasi.
- Generator hipotesis (Tahap C/E): deterministik berbasis aturan+bukti (rekomendasi)
  atau LLM (dengan pre-registration tetap wajib)?
- Setelah A: lanjut B (Failure Learning) atau C (registry)?

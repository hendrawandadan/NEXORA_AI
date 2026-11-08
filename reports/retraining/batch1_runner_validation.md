# Batch 1 Runner Validation

## Ringkasan

Validasi dilakukan dengan data dummy/simulasi. Tidak ada training produksi yang dijalankan.

Runner yang diuji: `batch1_execution_runner.py`

Artefak simulasi:

- `reports/retraining/simulations/batch1_runner_validation/batch_execution_log_test.csv`
- `reports/retraining/simulations/batch1_runner_validation/runner_self_test_result.json`

## Hasil Verifikasi Terkini

Perintah yang dijalankan:

```powershell
.venv\Scripts\python.exe -m py_compile batch_checkpoint_manager.py batch1_execution_runner.py
.venv\Scripts\python.exe batch1_execution_runner.py --self-test
```

Hasil utama self-test:

- `dry_run_log_unchanged = true`
- `promote_manifest_exists = true`
- `rollback_partial_failure_ok = true`
- `promoted_lock_ok = true`
- `resume_skips_promoted = true`
- `lock_error_message_clear = true`
- `lock_failure_original_preserved = true`
- `replace_after_unlock_ok = true`
- `resume_promoted_not_replayed = true`
- `production_model_unchanged = true`
- `training_executed = false`
- `integration_started_log_failure_blocks_training = true`
- `integration_started_failure_status_unchanged = true`
- `integration_started_result = PREP-001: STARTED_LOG_PERMISSION_FAILED (reason=locked_or_busy ...)`

## Cakupan Uji sesuai Permintaan

1. Dispatch setiap status (`QUEUED/STARTED/TRAIN_DONE/VALIDATED/FAILED/RETRY_PENDING/PROMOTED`) -> **PASS**
2. Proses terhenti per checkpoint dan resume -> **PASS**
3. Promosi gagal sebagian + rollback -> **PASS**
4. Resume tanpa mengulang `PROMOTED` -> **PASS**
5. `PROMOTED` tidak bisa didowngrade -> **PASS**
6. Dry-run tidak mengubah log produksi -> **PASS**
7. CSV terkunci menghasilkan error jelas -> **PASS**
8. Replace berhasil setelah lock dilepas -> **PASS**
9. Kegagalan replace tidak merusak CSV asli -> **PASS**
10. Logging `STARTED` gagal menghentikan training sebelum dispatch pipeline -> **PASS**
11. Status run tetap tidak ambigu saat `STARTED` gagal -> **PASS**
12. Tidak ada perubahan model produksi -> **PASS**
13. Tidak ada training berjalan saat pengujian -> **PASS**

## Verifikasi Dry-Run Read-Only pada Log Produksi

Perintah:

```powershell
$h1=(Get-FileHash reports/retraining/batch_execution_log.csv -Algorithm SHA256).Hash
.venv\Scripts\python.exe batch1_execution_runner.py --resume --limit 5 | Out-Null
$h2=(Get-FileHash reports/retraining/batch_execution_log.csv -Algorithm SHA256).Hash
```

Hasil:

- `before = D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8`
- `after  = D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8`
- `same   = True`

## Kesimpulan

Status: **PASS**

Template runner siap untuk eksekusi bertahap saat diizinkan, dengan syarat tetap menggunakan `--execute` eksplisit untuk training nyata.

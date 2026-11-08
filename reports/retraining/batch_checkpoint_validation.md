# Batch 1 Checkpoint Automation Validation

## Scope

Validasi ini hanya menguji mekanisme checkpoint menggunakan data dummy, tanpa menjalankan training produksi.

## Artefak Uji

- Log produksi (schema-upgraded): [batch_execution_log.csv](./batch_execution_log.csv)
- Log simulasi: [batch_execution_log_simulation.csv](./simulations/batch1_checkpoint_v2/batch_execution_log_simulation.csv)
- Ringkasan simulasi: [simulation_result.json](./simulations/batch1_checkpoint_v2/simulation_result.json)
- Script automation: [batch_checkpoint_manager.py](../../batch_checkpoint_manager.py)

## Skenario Pengujian

1. **Schema upgrade**: menambah kolom checkpoint tanpa mengubah 37 run Batch 1 dari `PENDING/QUEUED`.
2. **Normal flow**: `QUEUED -> STARTED -> TRAIN_DONE -> VALIDATED -> PROMOTED`.
3. **Failure flow**: `FAILED -> RETRY_PENDING -> STARTED -> TRAIN_DONE -> VALIDATED -> PROMOTED`.
4. **Resume safety**: run `PROMOTED` harus di-skip saat resume.
5. **No downgrade**: status `PROMOTED` tidak boleh kembali ke `QUEUED/PENDING`.
6. **Duplicate key guard**: key `(scope,symbol,timeframe,horizon)` harus unik.

## Hasil

- **PASS** Schema berhasil di-upgrade menjadi 38 kolom.
- **PASS** Tidak ada duplikasi key run (`NO_DUPLICATE_KEYS`).
- **PASS** Simulasi sukses untuk 2 run dummy (`PREP-001`, `PREP-002`) hingga `PROMOTED`.
- **PASS** Resume mengembalikan 35 run pending (2 run promoted terskip otomatis).
- **PASS** Uji downgrade menghasilkan error terkontrol: `Run with PROMOTED status cannot be downgraded.`
- **PASS** Promosi memakai atomic move dari `temp_*` ke `final_*` dan menolak overwrite final path yang sudah ada.

## Ringkasan Status Simulasi

- `checkpoint_status=PROMOTED`: 2 run
- `checkpoint_status=QUEUED`: 35 run
- `run_status=COMPLETED`: 2 run
- `run_status=PENDING`: 35 run

## Kesimpulan

Status validasi: **PASS**.

Mekanisme checkpoint memenuhi syarat utama:

- update status langsung tercatat di CSV,
- pencatatan timestamp mulai/selesai tersedia,
- validasi metadata/config dilakukan sebelum promosi,
- model lama aman karena promosi final ditunda sampai validasi lulus,
- resume dapat lanjut dari checkpoint terakhir tanpa mengulang run `PROMOTED`.

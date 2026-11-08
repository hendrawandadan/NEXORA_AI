# SQLite Initialization Audit

Tanggal audit: 2026-11-07  
Kesimpulan: **INCONCLUSIVE**

## Ringkasan

Belum ditemukan database SQLite pada pohon `D:\NEXORA_AI_v2`, dan kode aplikasi belum menetapkan path database produksi. `SQLiteConnectionManager` menerima path dari pemanggil; tidak ada default, environment variable, atau konfigurasi aplikasi yang memilih lokasi. Karena itu audit tidak dapat menyimpulkan bahwa database produksi sudah pernah dibuat di lokasi lain atau menetapkan satu lokasi produksi yang pasti.

Audit ini hanya membaca kode, konfigurasi, dan metadata direktori. Tidak ada koneksi SQLite, bootstrap, migrasi, training, atau perubahan file produksi yang dilakukan.

## Lokasi yang seharusnya

- **Path database produksi saat ini:** belum ditentukan oleh aplikasi.
- **Path database test:** path sementara yang diberikan masing-masing tes di dalam `tempfile.TemporaryDirectory()`; direktori tersebut dihapus ketika tes selesai.
- **Path database development:** tidak ada default development. Fungsi bootstrap menerima path eksplisit dari caller.
- `data/` hanya berisi direktori `processed/`, `raw/`, dan `raw_fast/`; `database/`, `state/`, `data/db/`, dan `data/state/` tidak ada.
- Pencarian rekursif pada `D:\NEXORA_AI_v2` tidak menemukan file berekstensi `.db`, `.sqlite`, atau `.sqlite3`.

Path produksi yang aman masih perlu dipilih dan dicatat sebagai path absolut yang eksplisit sebelum inisialisasi pertama. Jangan menebak lokasi dari current working directory.

## Konfigurasi dan perilaku path

### `nexora_state_db/connection.py`

- Konstruktor `SQLiteConnectionManager(db_path, ...)` mewajibkan caller memberikan `db_path`.
- `Path(db_path)` mempertahankan path absolut atau relatif; tidak ada resolusi ke konfigurasi tertentu.
- Bila path relatif diberikan, `sqlite3.connect(str(self.db_path))` menafsirkannya relatif terhadap current working directory proses.
- Saat `connect()` dipanggil, `db_path.parent.mkdir(parents=True, exist_ok=True)` membuat direktori parent jika belum ada, lalu `sqlite3.connect()` membuat file jika belum ada. Karena itu menjalankan koneksi dapat mengubah filesystem.
- Tidak ada fallback path, env var, atau konstanta lokasi pada modul ini.

### `nexora_state_db/bootstrap.py`

`create_dev_database(db_path)` meneruskan path dari caller ke connection manager dan langsung menjalankan `MigrationManager.migrate()`. Bootstrap bukan sekadar deklarasi: ketika dipanggil, migrasi membuat tabel versi dan dapat membuat file database serta schema.

### `nexora_state_db/constants.py`

Modul ini hanya mendefinisikan status checkpoint dan alur transisi. Tidak ada konstanta path database.

### Konfigurasi aplikasi

Pencarian kode, konfigurasi, dan dokumentasi proyek untuk `db_path`, `DATABASE_URL`, `DB_PATH`, nama file state DB, dan pemanggilan bootstrap tidak menemukan konfigurasi produksi atau wiring runner ke SQLite. Tidak ada environment variable database yang ditemukan dalam file konfigurasi yang diperiksa.

## Apakah database/bootstrap pernah dibuat atau dijalankan?

- **Database SQLite produksi:** tidak ditemukan di dalam pohon proyek dan tidak ada path produksi yang ditetapkan. Keberadaan di lokasi lain tidak dapat dipastikan karena kode tidak menunjuk ke lokasi tersebut.
- **Bootstrap development:** tidak ditemukan pemanggilan dari aplikasi/runner produksi.
- **Bootstrap tes:** ya. `create_dev_database()` dipanggil pada tes fondasi dan integration test. Path-path tersebut berasal dari direktori sementara (`temp_db_path`, `integration_state.db`, `busy_timeout.db` di bawah `TemporaryDirectory`). Tes yang dijalankan sebelumnya berakhir dengan sukses dan konteks sementara membersihkan direktori setelah tes.
- Tes dengan bootstrap memang membuat database sementara dan menjalankan migrasi pada database tes. Ini bukan bukti bahwa database produksi pernah diinisialisasi.

## `.gitignore` dan status repository

Tidak ditemukan `.gitignore` pada root proyek atau parent `D:\`, dan `D:\NEXORA_AI_v2` tidak memiliki direktori `.git`. File ignore yang ditemukan hanya milik `.pytest_cache` dan `.venv`, bukan aturan repository untuk database aplikasi. Dengan demikian tidak ada bukti bahwa database dikecualikan oleh aturan `.gitignore` proyek ini. File database mungkin juga belum dibuat; hasil pencarian file di pohon proyek menunjukkan tidak ada file SQLite.

## Perbedaan test dan produksi

| Lingkungan | Sumber path | Perilaku | Status temuan |
|---|---|---|---|
| Test | `tempfile.TemporaryDirectory()` dalam tes | Bootstrap membuat DB dan menjalankan migrasi; file sementara dibersihkan bersama direktori | Pernah dijalankan |
| Development | Harus diberikan oleh pemanggil | Tidak ada path default; bootstrap akan membuat parent dan menerapkan migrasi | Tidak ada pemanggilan aplikasi yang ditemukan |
| Produksi | Belum dikonfigurasi | Runner tidak tampak terhubung ke repository SQLite/bootstrap | Lokasi dan status file tidak dapat diverifikasi |

## Langkah aman untuk inisialisasi pertama

Rekomendasi berikut belum dijalankan:

1. Tetapkan path absolut produksi secara eksplisit, di lokasi lokal yang persisten dan di luar folder sinkronisasi/staging model. Dokumentasikan owner dan kebijakan backup.
2. Pastikan path tersebut memang tujuan baru yang disetujui, folder parent tidak berisi database lain, dan tidak ada database aktif di lokasi yang dipilih.
3. Lakukan inisialisasi pertama pada salinan atau lingkungan staging terlebih dahulu menggunakan path eksplisit dan bootstrap yang menerapkan migrasi. Periksa versi migrasi, `PRAGMA integrity_check`, foreign key, serta izin file.
4. Sebelum produksi, ambil backup terverifikasi dan jalankan duplicate-job audit pada sumber aktual; baru kemudian rencanakan cutover secara terpisah.
5. Jangan mengandalkan relative path: pastikan aplikasi/runner nantinya menerima path absolut dari konfigurasi yang eksplisit.

## Kesimpulan

**INCONCLUSIVE** — database produksi belum dapat dinyatakan ada atau tidak ada pada lokasi tertentu, karena aplikasi belum mendefinisikan lokasi produksinya. Database temporary test memang dibuat oleh tes dan dibersihkan setelah tes. Langkah berikutnya adalah menetapkan dan memverifikasi path produksi secara eksplisit sebelum meminta inisialisasi; inisialisasi tidak dilakukan dalam audit ini.

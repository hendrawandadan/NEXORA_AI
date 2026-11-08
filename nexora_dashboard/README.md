# NEXORA AI — Database Intelligence Console

Dashboard lokal untuk memantau SQLite NEXORA AI v2. Aplikasi hanya menyediakan tampilan baca, grafik status, dan SQL Explorer read-only.

## Instalasi

Dari PowerShell pada root repo:

```powershell
python -m venv .venv-dashboard
.\.venv-dashboard\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r nexora_dashboard/requirements.txt
```

## Menjalankan

```powershell
python -m streamlit run nexora_dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

Buka [http://localhost:8501](http://localhost:8501). Untuk menghentikan server, tekan `Ctrl+C` pada terminal yang menjalankannya.

## Halaman

- **Overview** — koneksi, versi schema, jumlah baris, grafik job/run, aktivitas audit terbaru, dan integrity check.
- **Datasets** — pencarian, filter symbol/timeframe, hash, rentang waktu, dan kolom aktual yang tersedia.
- **Training Jobs** — pencarian, filter status/symbol/timeframe, pagination, detail, dan relasi dataset.
- **Training Runs** — run aktual dari tabel `training_runs`; durasi ditampilkan jika waktu mulai dan selesai tersedia.
- **Checkpoints** — riwayat checkpoint menurut waktu perubahan.
- **Model Artifacts** — metadata artifact; dashboard tidak membuka isi berkas model.
- **Validation** — seluruh kolom hasil validasi yang disimpan.
- **Audit Logs** — peristiwa terbaru terlebih dahulu.
- **SQL Explorer** — `SELECT`, `EXPLAIN QUERY PLAN`, dan daftar PRAGMA baca yang diizinkan.

Halaman memeriksa nama tabel dan kolom pada koneksi saat runtime. Kolom yang tidak ada tidak dibuat-buat; tabel yang tidak ada diberi keterangan.

## Batas keamanan

- Path database dikunci ke `D:\NEXORA_AI_v2\database\nexora_state.db`; pengguna tidak dapat mengubahnya dari UI.
- Koneksi menggunakan URI SQLite `mode=ro`, hanya setelah file yang ditentukan tervalidasi ada. Jika file hilang, dashboard gagal tertutup dan tidak membuat database baru.
- Dashboard tidak menjalankan migrasi, tidak mengubah PRAGMA/WAL, tidak membuat checkpoint SQLite, dan tidak membaca/menulis dataset atau artifact.
- SQL Explorer memvalidasi pernyataan, membatasi authorizer SQLite untuk operasi baca, menolak multi-statement, membatasi hasil ke 1.000 baris, dan menghentikan query setelah 5 detik.
- Server dipasang pada `127.0.0.1:8501`, bukan pada semua antarmuka jaringan.

Operasi baca tetap memakai sumber produksi yang aktif. Integrity check melakukan pembacaan penuh, sehingga dapat memakai I/O disk saat dipilih.

## Tes keamanan dan fungsi

Dari root repo:

```powershell
python -m pytest -q tests/test_nexora_dashboard.py
```

Tes memakai database SQLite fixture sementara dan tidak menulis database produksi.

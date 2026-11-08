# NEXORA AI Multi-Symbol v2.0 — Research Platform

Konfigurasi: semua instrumen yang dipilih/tersedia di Market Watch Exness, arsitektur hybrid
(individual model + global model), seluruh timeframe ekspor yang terdeteksi otomatis, target histori sampai 10 tahun.

**Penting:** ini adalah platform penelitian ML, bukan sistem trading live. "Semua instrumen"
berarti semua simbol yang dapat diakses dan diekspor oleh terminal Exness yang dipakai; tidak
menjamin semua instrumen Exness memiliki histori 10 tahun. Ketersediaan data berbeda per simbol,
kelas aset, timeframe, dan server broker.

## Isi implementasi

- Exporter MQL5 untuk simbol di Market Watch dan timeframe yang dipilih pada exporter.
- Penemuan dataset CSV otomatis.
- Audit per dataset: timestamp, duplikat, OHLC, spread/volume, gap.
- Feature engineering dengan normalisasi ATR, momentum, trend, candle, waktu, spread.
- Model individual untuk setiap simbol-timeframe.
- Model global per timeframe, menggabungkan beberapa simbol dengan identitas simbol.
- Evaluasi kronologis holdout dan walk-forward sederhana.
- Perbandingan hasil individual/global dalam CSV/JSON.
- Tidak ada pengiriman order ke broker.

## Instalasi Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Jika `py -3.12` tidak ada, gunakan Python 3.11/3.12 yang terpasang.

## Ekspor dari MT5

1. Buka MT5 Exness dan pastikan simbol yang diinginkan tampil di Market Watch.
2. MetaEditor (F4) > Scripts > letakkan `nexora_execution/mt5/NEXORA_MultiSymbol_Exporter.mq5`.
3. Compile (F7), kembali ke MT5, jalankan script.
4. Atur FromDate ke 2016.11.07 dan ToDate ke 2026.11.07 (atau tanggal terbaru yang diinginkan).
5. `InpSymbols=""` berarti ekspor semua simbol yang sedang tampil di Market Watch. Untuk daftar tertentu, isi misalnya `EURUSD,GBPUSD,XAUUSD`.
6. `InpTimeframes` berisi seluruh periode standar MT5 secara default; DataHub otomatis menemukan semua timeframe yang diekspor.
7. `InpUseCommonFolder=false` menyimpan ke `MQL5/Files/NEXORA`; salin semua CSV ke `data/raw/`.
8. Periksa Journal. Script melaporkan jumlah bar per kombinasi. Simbol dengan suffix harus memakai nama persis dari Market Watch.

**Batas MT5:** `CopyRates` hanya dapat mengambil histori yang tersedia/diizinkan terminal dan server. Untuk 10 tahun M1 pada banyak simbol, ekspor dapat sangat besar dan memakan waktu. Tingkatkan batas "Max bars in chart" bila perlu, koneksi harus stabil, dan ekspor dapat dilakukan per kelompok simbol/tanggal. Jangan menganggap rentang tanggal yang diminta berarti seluruh data tersedia.

## Audit semua dataset

Letakkan file seperti:
`data/raw/EURUSD_M1.csv`, `data/raw/XAUUSD_H1.csv`, dst.
Nama file dapat berupa `<SYMBOL>_<TIMEFRAME>.csv` atau `<SYMBOL>_<TIMEFRAME>_<YYYYMMDDhhmm>_<YYYYMMDDhhmm>.csv`. Pencarian mencakup `data/raw/<SYMBOL>/` dan semua subfolder. Label Daily/Weekly/Monthly dibaca sebagai D1/W1/MN1.

```powershell
python scripts/audit_all.py
```

Laporan:
- `reports/data_audit.csv`
- `reports/data_inventory.json` (simbol, timeframe, dan status kualitas)
- `reports/data_inventory.json` (simbol, timeframe, jumlah dataset, dan status kualitas)
- `reports/audit/<SYMBOL>_<TF>.json`
- `data/processed/<SYMBOL>_<TF>_normalized.csv`

Status `BASIC_CHECKS_PASS` hanya berarti pemeriksaan dasar lolos, bukan bukti histori lengkap.

## Training hybrid semua dataset

```powershell
python scripts/train_all.py
```

Opsional:

```powershell
python scripts/train_all.py --min-bars 5000 --horizons 1,2,4,8 --max-iter 250
```

Alur:
1. Memindai seluruh CSV yang cocok.
2. Menjalankan model individual per simbol-timeframe.
3. Mengelompokkan dataset per timeframe untuk model global per timeframe.
4. Membuat split berdasarkan waktu (bukan random row split).
5. Mengukur holdout test dan beberapa fold walk-forward.
6. Membandingkan model individual dan global.
7. Menyimpan laporan, model, dan sinyal prediksi.

Model global per timeframe digunakan agar horizon tetap bermakna dalam durasi waktu yang konsisten. Instrumen dengan karakter berbeda dinormalisasi dengan ATR dan fitur identitas simbol.

## Output

- `models/individual/<SYMBOL>/<TF>/model.joblib`
- `models/global/<TF>/model.joblib`
- `reports/individual_results.csv`
- `reports/global_results.csv`
- `reports/model_comparison.csv`
- `reports/run_summary.json`
- `signals/<SYMBOL>/<TF>/signals.csv`

## Catatan metodologi

- Target versi ini adalah arah close setelah H candle: `close[t+H] > close[t]`.
- Probabilitas tidak sama dengan probabilitas profit transaksi.
- Tidak ada simulasi bid/ask tick-by-tick, spread historis intrabar, komisi, slippage, swap, margin, atau TP/SL.
- Untuk lintas instrumen, `spread` MT5 dicatat dalam points; nilainya tidak langsung dibandingkan antar-symbol tanpa tick size/tick value.
- Model global tidak boleh dianggap lebih baik hanya karena pooled dataset lebih besar. Bandingkan pada periode waktu yang sama dan lihat hasil per simbol.
- Eksperimen yang berulang dapat menyebabkan selection bias. Simpan konfigurasi dan jangan mengoptimalkan berdasarkan test.
- Data antar broker/server dapat berbeda. Semua data dalam satu run sebaiknya berasal dari satu sumber yang konsisten.
- Instrumen CFD/crypto/index memiliki sesi dan kalender berbeda; gap tidak otomatis error.
- NEXORA v2.0 belum melakukan live trading dan belum mengaktifkan auto-retraining.

## Jalankan test dasar

```powershell
python -m pytest tests -q
```

## Validasi candle

Audit memeriksa kolom OHLC, timestamp, duplikat, interval aktual terhadap nama timeframe, gap, harga, volume, dan spread. Ketidakcocokan interval ditandai REVIEW. Gap perlu dibaca sesuai sesi instrumen. Audit tidak membuktikan kelengkapan histori. Jalankan `python -m pytest tests -q` untuk test sintetis.

Tidak ada training aktual pada data Exness yang dilakukan dalam revisi ini.

## Periksa dan jalankan di Windows

Dari PowerShell:

```powershell
Set-Location D:\NEXORA_AI_v2
.\.venv\Scripts\Activate.ps1
python -m pytest tests -q
python -m scripts.audit_all
python -m scripts.train_all
```

Audit membandingkan interval candle aktual dengan timeframe nama file. Ketidakcocokan masuk status REVIEW. Gap perlu ditafsirkan sesuai sesi pasar. Revisi ini belum menjalankan training Exness.

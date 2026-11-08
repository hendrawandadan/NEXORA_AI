# SQLite Duplicate Job Audit

Tanggal audit: 2026-11-07  
Status: **INCONCLUSIVE**

## Ringkasan

Constraint tuple pada migration terbaru adalah:

```sql
UNIQUE (scope, ifnull(symbol, ''), timeframe, horizon)
```

Saya tidak menemukan database SQLite sumber (`.db`, `.sqlite`, atau `.sqlite3`) di `D:\NEXORA_AI_v2` saat audit. Karena itu tabel `training_jobs` dari database yang akan dimigrasikan tidak dapat dibaca dan angka total job sumber SQLite tidak dapat diverifikasi. Tidak ada migrasi yang dijalankan.

Sebagai pemeriksaan terbatas, dua CSV legacy yang tersedia diperiksa dengan komponen tuple dan normalisasi simbol yang sama. Keduanya tidak menunjukkan tuple duplikat. Hasil CSV ini bukan bukti bahwa database sumber SQLite bebas konflik.

## Skema dan semantik NULL/kosong

`training_jobs` mendefinisikan `job_key` sebagai unik, lalu kolom tuple sebagai berikut:

| Kolom | Definisi | Makna untuk tuple |
|---|---|---|
| `scope` | `TEXT NOT NULL`, dibatasi ke `individual` atau `global` | Wajib berisi salah satu nilai yang diizinkan |
| `symbol` | `TEXT`, nullable | `NULL` dinormalisasi menjadi string kosong oleh `ifnull` |
| `timeframe` | `TEXT NOT NULL` | Wajib ada; constraint tidak memangkas spasi |
| `horizon` | `INTEGER NOT NULL CHECK(horizon > 0)` | Wajib bilangan bulat positif |

Perilaku SQLite yang relevan:

- `symbol IS NULL` dan `symbol = ''` menghasilkan komponen tuple yang sama (`''`) dan akan bentrok jika tiga kolom lainnya sama.
- Nilai `symbol` berisi spasi saja tidak sama dengan `''`; indeks tidak memakai `trim()`.
- Perbandingan teks indeks memakai kolasi default SQLite (`BINARY`): huruf besar/kecil dan spasi merupakan nilai berbeda. Tidak ada normalisasi case atau whitespace.
- `scope`, `timeframe`, dan `horizon` tidak boleh `NULL` menurut skema, tetapi `NOT NULL` sendiri tidak melarang string kosong pada dua kolom teks itu. Nilai kosong tetap berbeda dari nilai nonkosong dan tidak dikanonisasi.
- SQLite memakai affinity kolom dan aturan perbandingan nilai; variasi tipe input sebaiknya diperiksa langsung pada database sumber sebelum migrasi.

## Query audit untuk database sumber

Query berikut mereproduksi ekspresi indeks dan menampilkan semua baris pada tuple berkonflik beserta informasi pembeda:

```sql
WITH duplicate_tuples AS (
    SELECT scope, ifnull(symbol, '') AS normalized_symbol, timeframe, horizon,
           COUNT(*) AS tuple_count
    FROM training_jobs
    GROUP BY scope, ifnull(symbol, ''), timeframe, horizon
    HAVING COUNT(*) > 1
)
SELECT j.id, j.job_key, j.scope, j.symbol, j.timeframe, j.horizon,
       j.status, j.config_json, j.created_at, j.updated_at,
       d.tuple_count
FROM training_jobs AS j
JOIN duplicate_tuples AS d
  ON d.scope = j.scope
 AND d.normalized_symbol = ifnull(j.symbol, '')
 AND d.timeframe = j.timeframe
 AND d.horizon = j.horizon
ORDER BY j.scope, ifnull(j.symbol, ''), j.timeframe, j.horizon, j.id;
```

Untuk hitungan keseluruhan:

```sql
SELECT COUNT(*) AS total_jobs,
       (SELECT COUNT(*) FROM (
           SELECT scope, ifnull(symbol, ''), timeframe, horizon
           FROM training_jobs
           GROUP BY scope, ifnull(symbol, ''), timeframe, horizon
       )) AS unique_tuples
FROM training_jobs;
```

`job_key`, ID, status, konfigurasi, dan timestamp adalah informasi pembeda untuk menilai konflik secara manual; tidak ada rekonsiliasi atau penghapusan otomatis yang dilakukan.

## Hasil aktual dari kandidat CSV legacy

Penghitungan memakai nilai kolom mentah untuk `scope`, `timeframe`, dan `horizon`; nilai simbol kosong dipetakan ke `''` sebagaimana `ifnull(symbol, '')`. CSV tidak memiliki kolom `job_key`; kolom identitas yang tersedia dicatat di tabel.

| Sumber | Total baris/job kandidat | Tuple unik | Baris berlebih akibat duplikasi | Tuple duplikat | Simbol kosong/NULL | SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| `reports/retraining/batch_retraining_plan.csv` | 47 | 47 | 0 | 0 | 0 | `1bbea13995bdecbe9a37c2481ee0eee74e520c8e241a4f8779258ebda5f7f1f0` |
| `reports/retraining/batch_execution_log.csv` | 37 | 37 | 0 | 0 | 0 | `d73f196d5a313d1ab3fc878ea354b944aecaf8d074e94bc5dda42900e0bf2dd8` |

Kedua CSV juga tidak memiliki simbol yang hanya berisi whitespace. `batch_retraining_plan.csv` berisi 37 baris `individual` dan 10 `global`; `batch_execution_log.csv` berisi 37 baris `individual`. Tidak ada tuple duplikat untuk ditampilkan. Identitas yang tersedia pada plan adalah `order`/`batch`; pada log adalah `execution_id`, `run_id`, dan `batch`.

## Keputusan

**INCONCLUSIVE — database sumber belum tersedia atau belum dapat diverifikasi.** CSV kandidat yang diperiksa menunjukkan 47/47 dan 37/37 tuple unik, tetapi keputusan PASS untuk migrasi memerlukan query dan hitungan atas tabel `training_jobs` database sumber yang sebenarnya, termasuk hash database tersebut. Tidak ada job yang dihapus, digabungkan, atau diubah.

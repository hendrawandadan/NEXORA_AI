# NEXORA Tahap 3 — Optimal Batch Retraining Planner

Dokumen ini adalah rencana eksekusi; tidak menjalankan training dan tidak mengubah kode/konfigurasi produksi.

## 1) Total kombinasi yang perlu dilatih
- To-train (MISSING + usable): **47**
- Backlog data (MISSING + non-usable): **84**
- Investigasi (INCOMPLETE/INVALID): **0**

## 2) Total kombinasi yang akan di-skip
- Skip (TRAINED & valid): **247**

## 3) Jumlah training run per batch
- Batch 1: **37** run | TF: M15, M2, M20, M3, M30, M4, M5, M6 | Horizons: 2, 4, 8, 12, 24
- Batch 2: **0** run | TF: - | Horizons: -
- Batch 3: **10** run | TF: M1, M3 | Horizons: 1, 2, 4, 8, 12, 24

## 4) Urutan eksekusi yang direkomendasikan
| Batch | Order | Scope | Symbol | Timeframe | Horizon | Dataset rows | Data status | Alasan prioritas | Beban |
|---|---|---|---|---|---|---|---|---|---|
| Batch 1 | 1 | individual | EURUSD | M30 | 2 | 70694 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 2 | individual | EURUSD | M30 | 4 | 70694 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 3 | individual | EURUSD | M30 | 8 | 70694 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 4 | individual | EURUSD | M30 | 12 | 70694 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 5 | individual | EURUSD | M30 | 24 | 70694 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 6 | individual | EURUSD | M20 | 2 | 104345 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 7 | individual | EURUSD | M20 | 4 | 104345 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 8 | individual | EURUSD | M20 | 8 | 104345 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 9 | individual | EURUSD | M20 | 12 | 104345 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 10 | individual | EURUSD | M20 | 24 | 104345 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 11 | individual | EURUSD | M15 | 12 | 137995 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 12 | individual | EURUSD | M15 | 24 | 137995 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 13 | individual | EURUSD | M6 | 2 | 339724 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 14 | individual | EURUSD | M6 | 4 | 339724 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 15 | individual | EURUSD | M6 | 8 | 339724 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 16 | individual | EURUSD | M6 | 12 | 339724 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | low |
| Batch 1 | 17 | individual | EURUSD | M6 | 24 | 339724 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 18 | individual | EURUSD | M5 | 2 | 406686 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 19 | individual | EURUSD | M5 | 4 | 406686 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 20 | individual | EURUSD | M5 | 8 | 406686 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 21 | individual | EURUSD | M5 | 12 | 406686 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 22 | individual | EURUSD | M5 | 24 | 406686 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 23 | individual | EURUSD | M4 | 2 | 507344 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 24 | individual | EURUSD | M4 | 4 | 507344 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 25 | individual | EURUSD | M4 | 8 | 507344 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 26 | individual | EURUSD | M4 | 12 | 507344 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 27 | individual | EURUSD | M4 | 24 | 507344 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 28 | individual | EURUSD | M3 | 2 | 674812 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 29 | individual | EURUSD | M3 | 4 | 674812 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 30 | individual | EURUSD | M3 | 8 | 674812 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 31 | individual | EURUSD | M3 | 12 | 674812 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | medium |
| Batch 1 | 32 | individual | EURUSD | M3 | 24 | 674812 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | high |
| Batch 1 | 33 | individual | EURUSD | M2 | 2 | 1008234 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | high |
| Batch 1 | 34 | individual | EURUSD | M2 | 4 | 1008234 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | high |
| Batch 1 | 35 | individual | EURUSD | M2 | 8 | 1008234 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | high |
| Batch 1 | 36 | individual | EURUSD | M2 | 12 | 1008234 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | high |
| Batch 1 | 37 | individual | EURUSD | M2 | 24 | 1008234 | BASIC_CHECKS_PASS | EURUSD missing + usable; preserve trained artifacts; higher TF first for stable checkpointing | high |
| Batch 3 | 1 | global | EURUSD+XAUUSD | M3 | 4 | 631040 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 2 | global | EURUSD+XAUUSD | M3 | 8 | 631040 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 3 | global | EURUSD+XAUUSD | M3 | 12 | 631040 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 4 | global | EURUSD+XAUUSD | M3 | 24 | 631040 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 5 | global | EURUSD+XAUUSD | M1 | 1 | 1889105 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 6 | global | EURUSD+XAUUSD | M1 | 2 | 1889105 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 7 | global | EURUSD+XAUUSD | M1 | 4 | 1889105 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 8 | global | EURUSD+XAUUSD | M1 | 8 | 1889105 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 9 | global | EURUSD+XAUUSD | M1 | 12 | 1889105 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |
| Batch 3 | 10 | global | EURUSD+XAUUSD | M1 | 24 | 1889105 | BASIC_CHECKS_PASS;BASIC_CHECKS_PASS | Global missing + usable on both symbols; requires strict EURUSD+XAUUSD pooled set | high |

## 5) Backlog timeframe yang kekurangan data
| Scope | Symbol | Timeframe | Missing horizon count |
|---|---|---|---|
| global | EURUSD+XAUUSD | D1 | 6 |
| global | EURUSD+XAUUSD | H12 | 6 |
| global | EURUSD+XAUUSD | H8 | 6 |
| global | EURUSD+XAUUSD | MN1 | 6 |
| global | EURUSD+XAUUSD | W1 | 6 |
| individual | EURUSD | D1 | 6 |
| individual | EURUSD | H12 | 6 |
| individual | EURUSD | MN1 | 6 |
| individual | EURUSD | W1 | 6 |
| individual | XAUUSD | D1 | 6 |
| individual | XAUUSD | H12 | 6 |
| individual | XAUUSD | H8 | 6 |
| individual | XAUUSD | MN1 | 6 |
| individual | XAUUSD | W1 | 6 |

## 6) Risiko dan ketergantungan antarbatch
- Batch 3 hanya boleh jalan jika kedua simbol usable pada timeframe yang sama.
- Kombinasi non-usable (insufficient bars) dipisah ke backlog, bukan target retraining normal.
- Jika muncul INCOMPLETE/INVALID baru, hentikan batch terkait dan investigasi artifact terlebih dulu.
- Lanjutkan per-checkpoint group (`batch::timeframe`) agar proses mudah di-resume saat terputus.

## 7) Kriteria keberhasilan setiap batch
- Batch 1 berhasil bila semua EURUSD usable-missing menjadi TRAINED dan report/model sinkron.
- Batch 2 berhasil bila semua XAUUSD usable-missing menjadi TRAINED dan report/model sinkron.
- Batch 3 berhasil bila semua global usable-missing menjadi TRAINED dengan symbol set `EURUSD+XAUUSD` yang benar.
- Final gate: tidak ada duplikasi key, tidak ada orphan artifact, dan evaluasi trading diperbarui dari sinyal baru.

## Coverage audit recap
- Expected total: 378 | Trained: 247 | Missing: 131
- Usable total: 294 | Trained: 247 | Missing: 47
- Non-usable total: 84 | Missing: 84

## Evaluasi biaya komputasi (relatif)
- Quick vs Full berdasarkan `max_iter`: full ≈ **3.75x** quick (faktor iterasi saja).
- Estimasi ini relatif (proxy), bukan durasi absolut, karena tidak mengukur CPU/RAM/I/O runtime aktual.
- Planned total relative weight: quick=3715732269.17, full=13933996009.38

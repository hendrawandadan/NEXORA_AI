# FASE 2A — Unit Test Report, Leakage Test Report & Cost Reconciliation

**Tanggal:** 2026-11-08. **Status:** Seluruh test kritis LOLOS.

---

## 1. UNIT TEST REPORT

Command: `.\.venv\Scripts\python.exe -m pytest tests/test_triple_barrier.py tests/test_cost_engine.py tests/test_event_attribution.py -q`
Result: **24 passed** (synthetic fixtures, hasil diverifikasi matematis).

### 1.1 Triple-barrier & execution (`tests/test_triple_barrier.py`)
| # | Test | Membuktikan |
|---|---|---|
| 1 | `test_buy_upper_hit` | BUY, upper touched → UPPER_HIT, outcome +1 |
| 2 | `test_buy_lower_hit` | BUY, lower touched → LOWER_HIT, outcome −1 |
| 3 | `test_sell_upper_hit_is_loss` | SELL, upper touched → UPPER_HIT fisik, outcome −1 (loss) |
| 4 | `test_sell_lower_hit_is_profit` | SELL, lower touched → LOWER_HIT, outcome +1 (profit) |
| 5 | `test_buy_vertical_profit_and_loss` | BUY vertical exit bisa profit ATAU loss |
| 6 | `test_sell_vertical_profit_and_loss` | SELL vertical exit bisa profit ATAU loss |
| 7 | `test_executable_spread_accounting` | round-trip spread → BUY path sama jadi negatif |
| 8 | `test_executable_entry_exit_sides` | BUY entry=ask, SELL entry=bid |
| 9 | `test_ambiguous_intrabar_event` | range span kedua barrier tanpa M1 → AMBIGUOUS (bukan vertical) |
| 10 | `test_event_window_after_signal` | entry/exit > signal; event_end ≥ event_start |
| 11 | `test_atr_no_future_leak` | ubah future bar → ATR masa lalu tak berubah |
| 12 | `test_invalid_side_raises` | side=0 → ValueError |

### 1.2 Cost engine (`tests/test_cost_engine.py`)
| # | Test | Membuktikan |
|---|---|---|
| 13 | `test_scenario_totals` | 1.2 / 1.7 / 2.2 pip benar |
| 14 | `test_commission_status_not_available` | komisi = NOT_AVAILABLE (bukan nol diam-diam) |
| 15 | `test_cost_uses_reference_price` | cost pakai entry price aktual |
| 16 | `test_no_double_count_spread_in_executable_mode` | `flat−exec == spread` sekali |
| 17 | `test_pips_to_fraction` | 1 pip @1.0 = 0.0001 |
| 18 | `test_reference_price_positive_required` | harga ≤0 → ValueError |
| 19 | `test_unknown_scenario` | skenario asing → KeyError |

### 1.3 Event attribution (`tests/test_event_attribution.py`)
| # | Test | Membuktikan |
|---|---|---|
| 20 | `test_net_return_and_meta_label` | net = gross − cost; meta_label ∈ {0,1} |
| 21 | `test_meta_label_matches_sign_of_net` | meta_label = 1 iff net>0 |
| 22 | `test_average_uniqueness_bounds` | uniqueness ∈ (0,1] |
| 23 | `test_overlap_purge_removes_overlapping_train_events` | event overlap dibuang |
| 24 | `test_overlap_purge_no_overlap_keeps_all` | non-overlap dipertahankan |

---

## 2. LEAKAGE TEST REPORT

| Kontrol | Implementasi | Bukti test |
|---|---|---|
| Chronological split | (pipeline existing) — tidak diubah | — |
| ATR trailing | `EWM` dengan shift(1) pada close | #11 `test_atr_no_future_leak` |
| Entry timing | entry = open t+1 | #10 `test_event_window_after_signal` |
| Event window | `event_end_time ≥ event_start_time > signal_time` | #10 |
| Overlap-aware purging | `purge_overlapping_between` membuang train yang overlap val/test | #23 |
| Event uniqueness (weights) | `average_uniqueness` (López de Prado style) | #22 |

Catatan: purged walk-forward + embargo penuh diterapkan di **runner** tahap berikut
(blocked sampai persetujuan). Koreksi ini menyediakan primitif (`event_start/end`,
`purge_overlapping_between`, `average_uniqueness`) yang **sudah diuji**.

---

## 3. COST ACCOUNTING RECONCILIATION (data nyata EURUSD M30, executable)

Half-spread baseline = 1.5 pip / 2 = 0.000075 price → round-trip tertanam 0.000150 = 1.5 pip.

| Sisi | gross_mean (exec) | net_mean (exec: −0.2 pip slip) | meta_pos_rate |
|---|---|---|---|
| BUY | −0.0001190 | −0.0001371 | 0.3393 |
| SELL | −0.0001497 | −0.0001677 | 0.5147 |

Status proportions (data nyata):
| Status | BUY | SELL |
|---|---|---|
| UPPER_HIT | 29.15% | 42.77% |
| LOWER_HIT | 63.37% | 48.83% |
| VERTICAL_EXIT | 7.34% | 8.25% |
| AMBIGUOUS | 0.14% | 0.15% |

**Rekonsiliasi double-count:**
`mid_gross − exec_gross (mean) = 0.0001176` ≈ round-trip spread yang dibayar **sekali**
(penuh 1.5 pip ≈ 0.000136 pada harga 1.1; selisih karena harga entry bervariasi & exit
kadang di barrier). Test #16 membuktikan `flat − exec == spread` persis sekali → **tidak
ada double counting** antara harga executable dan flat cost engine.

---

## 4. STATUS

- ✅ 24/24 test lolos.
- ✅ Tidak ada leakage pada primitif yang tersedia (ATR, entry, event window, purging).
- ✅ Cost reconciliation konsisten; no double count.
- ⛔ Belum training/eksperimen (sesuai batasan).
- ⛔ Tidak menyentuh artefak Fase 2 / dataset sumber.

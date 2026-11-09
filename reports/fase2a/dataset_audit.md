# FASE 2A - Data Validation Report (EURUSD M30)

- Dataset: `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M30_202001020000_202611062130.csv`
- Rows: **70694** | 2020-01-02 00:00:00 -> 2026-11-06 21:30:00
- **Gate pass: YES** (passed integrity checks)

## Integrity checks (M30)
| Check | Value |
|---|---|
| missing_required | [] |
| ts_is_monotonic_increasing | True |
| duplicate_timestamps | 0 |
| nonpositive_prices | 0 |
| high_lt_low | 0 |
| high_lt_max_oc | 0 |
| low_gt_min_oc | 0 |
| null_ohlc | 0 |
| expected_bar_minutes | 30.0 |
| delta_min_minutes | 30.0 |
| delta_median_minutes | 30.0 |
| delta_max_minutes | 4350.0 |
| sub_bar_deltas | 0 |
| gap_count_gt_1bar | 3660 |
| largest_gaps_minutes | [4350.0, 4350.0, 3060.0, 3060.0, 2970.0] |

## Spread quality (why not a true cost)
`{
"nulls": 0,
"min": 0.0,
"median": 0.0,
"mean": 3.39,
"max": 300.0,
"pct_zero": 88.8,
"pct_nonpositive": 88.8
}`

## M1 granularity & overlap
`{
"rows": 1997692,
"time_start": "2020-01-02 00:00:00",
"time_end": "2026-11-06 21:58:00",
"smallest_delta_minutes": 1.0,
"median_delta_minutes": 1.0,
"is_truly_subhour": true
}`

`{
"m30_rows": 70694,
"m30_bars_with_m1_coverage": 70694,
"coverage_pct": 100.0,
"median_m1_per_m30_bucket": 30.0,
"buckets_with_lt2_m1_bars": 3381,
"sub_30m_row_bars_pct": null
}`

> VERIFIED: EURUSD_M1 is genuinely 1-minute granular (smallest delta = 1 min), so intrabar triple-barrier resolution is feasible. For the small number of 30-min buckets with < 2 M1 bars (thin session edges), barrier order may be ambiguous -> those events are flagged 'ambiguous' rather than forced.

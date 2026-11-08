# NEXORA v2.0 — DataHub revision

- Scope: all instruments exported from Exness MT5 Market Watch. Hybrid architecture: individual model per symbol/timeframe and global model per timeframe.
- Automatic timeframe discovery supports nested folders, timestamp-range filenames, M<n>, H<n>, D1/W1/MN1, and Daily/Weekly/Monthly labels.
- Validates CSV schema, OHLC, timestamps, candle interval, duplicates, gaps, and basic price quality. Creates `reports/data_audit.csv` and `reports/data_inventory.json`.
- Extends exporter defaults to all standard MT5 periods and keeps the existing training entry points.
- Synthetic tests cover nested folders, supported timeframe labels, and wrong candle intervals.

No real Exness training has been run or claimed. Audit of local files does not prove broker history is complete.

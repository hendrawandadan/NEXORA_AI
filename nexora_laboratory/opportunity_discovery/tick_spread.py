"""STAGE 2 — Tick spread analysis (memory-safe, streaming).

Reads Exness tick exports (``Timestamp,Bid,Ask``) either as plain CSV or inside a
ZIP, in CHUNKS, and accumulates only aggregates -- never holds the raw ticks in
memory (files can be >1 GB / ~15M rows per year).

For each chunk we:
  * compute spread = (Ask - Bid) in price units, convert to pips via pip_size,
  * drop obviously invalid rows (Ask < Bid, non-finite),
  * tag each tick with a session bucket (UTC hours) derived from Timestamp,
  * accumulate running histograms / sums sufficient to recompute median & p90
    exactly-ish via binning (we keep both the full spread array only if small, else
    a fixed-bin histogram). We use per-session quantiles estimated from histograms.

This module returns descriptive spread statistics ONLY. It does not trade, model,
or write anywhere. It never assumes commission/swap (marked NOT_AVAILABLE).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Session buckets by UTC hour (documented convention; overlapping not modelled).
SESSIONS = {
    "ASIA":   range(0, 8),      # 00:00–07:59 UTC
    "LONDON": range(8, 13),     # 08:00–12:59 UTC
    "NY":     range(13, 21),    # 13:00–20:59 UTC
    "LATE":   range(21, 24),    # 21:00–23:59 UTC
}


@dataclass
class SpreadAccumulator:
    """Streaming accumulator of spread stats (pips), per session + overall.

    Uses a fixed histogram in price-pip space for exact-enough quantiles without
    storing all ticks. Bin width is 0.1 pip by default; covers 0..(nbins*binwidth).
    """
    bin_width_pips: float = 0.1
    nbins: int = 2000  # covers up to 200 pips spread; overflow clamped to last bin
    n_total: int = 0
    n_invalid: int = 0
    sum_pips: float = 0.0
    sum_sq_pips: float = 0.0
    min_pips: float = float("inf")
    max_pips: float = float("-inf")
    overall_hist: np.ndarray = field(default_factory=lambda: np.zeros(2000, dtype=np.int64))
    session_hist: Dict[str, np.ndarray] = field(default_factory=dict)
    session_n: Dict[str, int] = field(default_factory=dict)
    session_sum: Dict[str, float] = field(default_factory=dict)
    _t_min: Optional[str] = None
    _t_max: Optional[str] = None

    def __post_init__(self):
        self.overall_hist = np.zeros(self.nbins, dtype=np.int64)
        for name in SESSIONS:
            self.session_hist[name] = np.zeros(self.nbins, dtype=np.int64)
            self.session_n[name] = 0
            self.session_sum[name] = 0.0

    def _session_of_hour(self, hour: np.ndarray) -> np.ndarray:
        idx = np.zeros(len(hour), dtype=np.int8) - 1
        for i, (name, hours) in enumerate(SESSIONS.items()):
            lo, hi = min(hours), max(hours)
            m = (hour >= lo) & (hour <= hi)
            idx[m] = i
        return idx

    def add_chunk(self, ts: pd.Series, bid: np.ndarray, ask: np.ndarray, pip_size: float) -> None:
        valid = np.isfinite(bid) & np.isfinite(ask) & (ask >= bid)
        self.n_invalid += int((~valid).sum())
        if not valid.any():
            return
        b = bid[valid]; a = ask[valid]
        spread_pips = (a - b) / pip_size
        ts_v = ts[valid]
        n = len(spread_pips)
        self.n_total += n
        self.sum_pips += float(spread_pips.sum())
        self.sum_sq_pips += float((spread_pips ** 2).sum())
        self.min_pips = min(self.min_pips, float(spread_pips.min()))
        self.max_pips = max(self.max_pips, float(spread_pips.max()))

        # timestamps range
        tmin, tmax = str(ts_v.iloc[0]), str(ts_v.iloc[-1])
        if self._t_min is None or tmin < self._t_min:
            self._t_min = tmin
        if self._t_max is None or tmax > self._t_max:
            self._t_max = tmax

        # histogram (clamp overflow into last bin)
        bins = np.clip((spread_pips / self.bin_width_pips).astype(np.int64), 0, self.nbins - 1)
        self.overall_hist += np.bincount(bins, minlength=self.nbins)

        # per-session
        hours = ts_v.dt.hour.to_numpy()
        sidx = self._session_of_hour(hours)
        for i, name in enumerate(SESSIONS.keys()):
            m = sidx == i
            if not m.any():
                continue
            sp = spread_pips[m]
            self.session_n[name] += int(m.sum())
            self.session_sum[name] += float(sp.sum())
            b2 = bins[m]
            self.session_hist[name] += np.bincount(b2, minlength=self.nbins)

    @staticmethod
    def _quantile_from_hist(hist: np.ndarray, n: int, q: float, bin_width: float) -> Optional[float]:
        if n <= 0 or hist.sum() == 0:
            return None
        cum = np.cumsum(hist)
        target = q * n
        idx = int(np.searchsorted(cum, target, side="left"))
        idx = min(idx, len(hist) - 1)
        # bin midpoint
        return float((idx + 0.5) * bin_width)

    def summary(self) -> Dict[str, object]:
        mean = self.sum_pips / self.n_total if self.n_total else None
        var = (self.sum_sq_pips / self.n_total - mean ** 2) if (self.n_total and mean is not None) else None
        out: Dict[str, object] = {
            "n_ticks": int(self.n_total),
            "n_invalid": int(self.n_invalid),
            "time_start": self._t_min,
            "time_end": self._t_max,
            "spread_pips_mean": round(mean, 5) if mean is not None else None,
            "spread_pips_std": round(np.sqrt(max(var, 0.0)), 5) if var is not None else None,
            "spread_pips_min": round(self.min_pips, 5) if self.n_total else None,
            "spread_pips_max": round(self.max_pips, 5) if self.n_total else None,
            "spread_pips_median": self._quantile_from_hist(self.overall_hist, self.n_total, 0.50, self.bin_width_pips),
            "spread_pips_p90": self._quantile_from_hist(self.overall_hist, self.n_total, 0.90, self.bin_width_pips),
            "spread_pips_p99": self._quantile_from_hist(self.overall_hist, self.n_total, 0.99, self.bin_width_pips),
        }
        per_session = {}
        for name in SESSIONS.keys():
            n = self.session_n[name]
            if n == 0:
                per_session[name] = {"n_ticks": 0}
                continue
            per_session[name] = {
                "n_ticks": int(n),
                "spread_pips_mean": round(self.session_sum[name] / n, 5),
                "spread_pips_median": self._quantile_from_hist(
                    self.session_hist[name], n, 0.50, self.bin_width_pips),
            }
        out["by_session"] = per_session
        return out


# Only the three columns we actually need; the leading "Exness","Symbol" columns are
# skipped for speed/memory. Tick exports always carry this header order.
_TICK_USECOLS = ["Timestamp", "Bid", "Ask"]


def _read_chunks_csv(path: Path, chunksize: int):
    return pd.read_csv(path, chunksize=chunksize, usecols=_TICK_USECOLS)


def _read_chunks_zip(path: Path, chunksize: int):
    zf = zipfile.ZipFile(path)
    inner = zf.namelist()[0]
    with zf.open(inner) as fh:
        for chunk in pd.read_csv(fh, chunksize=chunksize, usecols=_TICK_USECOLS):
            yield chunk


def _normalize_tick_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Lower-case columns and coerce Timestamp/Bid/Ask."""
    c = {col: col.strip().lower() for col in chunk.columns}
    chunk = chunk.rename(columns=c)
    # optional leading 'exness'/'symbol' columns are ignored
    chunk["timestamp"] = pd.to_datetime(chunk["timestamp"], errors="coerce", utc=True)
    chunk["bid"] = pd.to_numeric(chunk["bid"], errors="coerce")
    chunk["ask"] = pd.to_numeric(chunk["ask"], errors="coerce")
    return chunk.dropna(subset=["timestamp", "bid", "ask"])


def analyze_tick_file(
    path: Path,
    pip_size: float,
    *,
    chunksize: int = 2_000_000,
    max_chunks: Optional[int] = None,
) -> Dict[str, object]:
    """Stream a tick CSV or ZIP and return aggregated spread statistics."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        chunk_iter = _read_chunks_zip(path, chunksize)
    else:
        chunk_iter = _read_chunks_csv(path, chunksize)

    acc = SpreadAccumulator()
    rows_seen = 0
    for i, chunk in enumerate(chunk_iter):
        if max_chunks is not None and i >= max_chunks:
            break
        nc = _normalize_tick_chunk(chunk)
        rows_seen += len(nc)
        if len(nc):
            # ensure sorted within chunk for time-range correctness (files are sorted)
            acc.add_chunk(nc["timestamp"].reset_index(drop=True),
                          nc["bid"].to_numpy(), nc["ask"].to_numpy(), pip_size)
    out = acc.summary()
    out["file"] = str(path)
    out["rows_parsed"] = int(rows_seen)
    return out


def analyze_tick_files(paths: List[Path], pip_size: float, *, chunksize: int = 2_000_000) -> Dict[str, object]:
    """Analyse multiple yearly tick files and combine into one summary.

    Combines by summing histograms via a fresh accumulator across all files.
    """
    combined = SpreadAccumulator()
    per_file = []
    for p in paths:
        path = Path(p)
        if path.suffix.lower() == ".zip":
            chunk_iter = _read_chunks_zip(path, chunksize)
        else:
            chunk_iter = _read_chunks_csv(path, chunksize)
        file_acc_rows = 0
        for chunk in chunk_iter:
            nc = _normalize_tick_chunk(chunk)
            file_acc_rows += len(nc)
            if len(nc):
                ts = nc["timestamp"].reset_index(drop=True)
                combined.add_chunk(ts, nc["bid"].to_numpy(), nc["ask"].to_numpy(), pip_size)
        per_file.append({"file": str(path), "rows_parsed": int(file_acc_rows)})
    out = combined.summary()
    out["per_file"] = per_file
    return out

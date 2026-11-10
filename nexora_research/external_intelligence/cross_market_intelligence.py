"""External Information Intelligence — Cross-Market Intelligence.

[Component of the INFO_ACQUISITION lane; enabler for Fase 2, see MASTER_ROADMAP §3a.]

Studies relationships between instruments/markets using CORRELATION-based tools, with
explicit safeguards:

  * Correlation is NOT causation. Every result carries a caveat to that effect and the
    module name/values describe *association*, not a causal claim.
  * Refuses to compute on too-few observations (``min_observations``).
  * Rolling correlation + correlation-breakdown detection (regime dependence).
  * Lead-lag investigation via cross-correlation at bounded lags (association only).
  * Regime-dependent relationship: correlation split by a simple HIGH_VOL/LOW_VOL tag.

Pure functions over aligned float sequences (or pandas Series). No I/O, no DB, no
network. The repository persists computed observations with provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

CAUSATION_CAVEAT = (
    "Correlation is association, not causation. Co-movement can arise from a common "
    "driver (e.g. a third rate or a risk factor) and may break down across regimes."
)


@dataclass
class CorrelationResult:
    pair_a: str
    pair_b: str
    value: Optional[float]
    n_obs: int
    method: str = "pearson"
    available: bool = True
    caveat: str = CAUSATION_CAVEAT
    note: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"pair_a": self.pair_a, "pair_b": self.pair_b, "value": self.value,
                "n_obs": self.n_obs, "method": self.method, "available": self.available,
                "caveat": self.caveat, "note": self.note}


@dataclass
class RollingCorrelationResult:
    pair_a: str
    pair_b: str
    window: int
    series: List[float] = field(default_factory=list)
    n_points: int = 0
    available: bool = True
    caveat: str = CAUSATION_CAVEAT

    def as_dict(self) -> Dict[str, object]:
        return {"pair_a": self.pair_a, "pair_b": self.pair_b, "window": self.window,
                "series": self.series, "n_points": self.n_points,
                "available": self.available, "caveat": self.caveat}


@dataclass
class LeadLagResult:
    leader: str
    follower: str
    best_lag: int
    best_correlation: Optional[float]
    by_lag: Dict[int, Optional[float]] = field(default_factory=dict)
    available: bool = True
    caveat: str = (CAUSATION_CAVEAT + " A leading correlation does not prove the leader "
                   "causes the follower; both may respond to a common information source.")

    def as_dict(self) -> Dict[str, object]:
        return {"leader": self.leader, "follower": self.follower,
                "best_lag": self.best_lag, "best_correlation": self.best_correlation,
                "by_lag": self.by_lag, "available": self.available,
                "caveat": self.caveat}


def _clean(xs: Sequence[float]) -> List[float]:
    out = []
    for x in xs:
        try:
            xv = float(x)
        except (TypeError, ValueError):
            continue
        if xv != xv:  # NaN
            continue
        out.append(xv)
    return out


def _pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = len(a)
    if n < 2:
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / ((va ** 0.5) * (vb ** 0.5))


def correlation(pair_a: str, series_a: Sequence[float], pair_b: str,
                series_b: Sequence[float], *, min_observations: int = 30,
                method: str = "pearson") -> CorrelationResult:
    """Full-sample correlation between two aligned series (association only)."""
    a, b = _clean(series_a), _clean(series_b)
    n = min(len(a), len(b))
    if n < min_observations:
        return CorrelationResult(pair_a, pair_b, None, n, method, available=False,
                                 note=f"insufficient observations ({n} < {min_observations})")
    a, b = a[:n], b[:n]
    if method == "pearson":
        val = _pearson(a, b)
    elif method == "spearman":
        val = _spearman(a, b)
    else:
        raise ValueError(f"unknown method: {method}")
    if val is None:
        return CorrelationResult(pair_a, pair_b, None, n, method, available=False,
                                 note="zero variance in one series")
    return CorrelationResult(pair_a, pair_b, round(val, 6), n, method)


def _ranks(xs: Sequence[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    for rank, idx in enumerate(order, start=1):
        ranks[idx] = float(rank)
    # average ties
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        if j > i:
            avg = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    return _pearson(_ranks(a), _ranks(b))


def rolling_correlation(pair_a: str, series_a: Sequence[float], pair_b: str,
                        series_b: Sequence[float], *, window: int = 60) -> RollingCorrelationResult:
    """Rolling window correlation (tracks regime dependence / breakdowns)."""
    a, b = _clean(series_a), _clean(series_b)
    n = min(len(a), len(b))
    if n < window + 1:
        return RollingCorrelationResult(pair_a, pair_b, window, available=False)
    a, b = a[:n], b[:n]
    out: List[float] = []
    for end in range(window, n + 1):
        val = _pearson(a[end - window:end], b[end - window:end])
        if val is not None:
            out.append(round(val, 6))
    return RollingCorrelationResult(pair_a, pair_b, window, out, len(out))


def detect_correlation_breakdown(rolling: RollingCorrelationResult,
                                 *, change_threshold: float = 0.5) -> Dict[str, object]:
    """Flag a regime-dependent relationship if the rolling correlation swings widely."""
    s = rolling.series
    if len(s) < 5:
        return {"pair_a": rolling.pair_a, "pair_b": rolling.pair_b, "available": False,
                "breakdown": False, "note": "insufficient rolling history",
                "caveat": CAUSATION_CAVEAT}
    mn, mx = min(s), max(s)
    span = mx - mn
    sign_flips = sum(1 for i in range(1, len(s)) if s[i - 1] * s[i] < 0)
    breakdown = span >= change_threshold or sign_flips >= 2
    return {
        "pair_a": rolling.pair_a, "pair_b": rolling.pair_b, "available": True,
        "min": round(mn, 4), "max": round(mx, 4), "span": round(span, 4),
        "sign_flips": sign_flips, "breakdown": bool(breakdown),
        "note": ("Relationship is regime-dependent / unstable." if breakdown
                 else "Relationship relatively stable over the window."),
        "caveat": CAUSATION_CAVEAT,
    }


def lead_lag(leader: str, leader_series: Sequence[float], follower: str,
             follower_series: Sequence[float], *, max_lag: int = 10,
             min_observations: int = 30) -> LeadLagResult:
    """Cross-correlation at lags in [-max_lag, max_lag] (association only).

    Positive lag k means the leader's past values align with the follower's future:
    leader[t-k] vs follower[t]. We report the lag maximising |correlation|.
    """
    a, b = _clean(leader_series), _clean(follower_series)
    n = min(len(a), len(b))
    if n < min_observations + max_lag:
        return LeadLagResult(leader, follower, 0, None, {}, available=False)
    a, b = a[:n], b[:n]
    by_lag: Dict[int, Optional[float]] = {}
    best_lag, best_val = 0, None
    for k in range(-max_lag, max_lag + 1):
        if k >= 0:
            av = a[:n - k]
            bv = b[k:]
        else:
            av = a[-k:]
            bv = b[:n + k]
        val = _pearson(av, bv)
        by_lag[k] = None if val is None else round(val, 6)
        if val is not None and (best_val is None or abs(val) > abs(best_val)):
            best_lag, best_val = k, val
    return LeadLagResult(leader, follower, best_lag,
                         None if best_val is None else round(best_val, 6), by_lag)


def regime_dependent_correlation(pair_a: str, series_a: Sequence[float], pair_b: str,
                                 series_b: Sequence[float], vol_proxy: Sequence[float],
                                 *, min_observations: int = 20) -> Dict[str, object]:
    """Split correlation by a HIGH_VOL/LOW_VOL tag (median split of ``vol_proxy``).

    Association only. If either regime bucket is too small, that bucket is 'unavailable'.
    """
    a, b, v = _clean(series_a), _clean(series_b), _clean(vol_proxy)
    n = min(len(a), len(b), len(v))
    if n < 4:
        return {"pair_a": pair_a, "pair_b": pair_b, "available": False,
                "note": "insufficient data", "caveat": CAUSATION_CAVEAT}
    a, b, v = a[:n], b[:n], v[:n]
    med = sorted(v)[n // 2]
    hi_idx = [i for i in range(n) if v[i] >= med]
    lo_idx = [i for i in range(n) if v[i] < med]

    def _corr(idx):
        if len(idx) < min_observations:
            return None
        return _pearson([a[i] for i in idx], [b[i] for i in idx])

    hi, lo = _corr(hi_idx), _corr(lo_idx)
    return {
        "pair_a": pair_a, "pair_b": pair_b, "available": True,
        "high_vol_corr": None if hi is None else round(hi, 6),
        "low_vol_corr": None if lo is None else round(lo, 6),
        "high_vol_n": len(hi_idx), "low_vol_n": len(lo_idx),
        "diverge": (hi is not None and lo is not None and abs(hi - lo) > 0.3),
        "note": "Correlation split by volatility regime (median split).",
        "caveat": CAUSATION_CAVEAT,
    }

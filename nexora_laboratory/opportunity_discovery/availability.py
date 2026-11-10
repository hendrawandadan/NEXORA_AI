"""STAGE 4 — Data Availability & Quality (pure, read-only consolidation).

Consolidates what STAGES 1-3 measured into a single per-instrument readiness
profile, and explicitly flags GAPS. It answers: "for which instruments and horizons
do we have enough, trustworthy data to even attempt a New-Information (IC) test in
STAGE 5 -- and what is missing?"

Readiness is a TRANSPARENT rule-based score (no black box), computed from:
  * data quality grade (A/B/C/D from bar_quality.quality_score),
  * history depth (years / number of bars vs a minimum),
  * cost-data credibility (real tick spread > estimated spread),
  * coverage (does this instrument have the horizons we care about?).

Gaps are enumerated explicitly (not hidden): missing tick, truncated tick coverage,
unknown commission, absent instruments. This is a data-availability audit, NOT a
predictability or profitability claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Minimum history we consider sufficient to attempt an OOS IC test in STAGE 5.
MIN_YEARS_FOR_IC = 3.0
MIN_INTRADAY_BARS = 3000

# Grade -> base quality points (matches bar_quality grade bands).
GRADE_POINTS = {"A": 1.00, "B": 0.80, "C": 0.55, "D": 0.30}

# Reference horizons we care about per timeframe (from prior stages / rules).
REF_HORIZONS = {"M30": [24, 48], "H1": [12, 24], "H4": [4, 8, 12], "D1": [1, 2]}


def _years_between(first: Optional[str], last: Optional[str]) -> Optional[float]:
    if not first or not last:
        return None
    import pandas as pd
    try:
        a = pd.Timestamp(first)
        b = pd.Timestamp(last)
    except Exception:
        return None
    days = (b - a).total_seconds() / 86400.0
    return round(days / 365.25, 2) if days > 0 else 0.0


def _parse_date(s: Optional[str]) -> Optional[str]:
    """Return 'YYYY-MM-DD' prefix if parseable else None."""
    if not s:
        return None
    return str(s)[:10] if len(str(s)) >= 10 else None


@dataclass
class InstrumentAvailability:
    instrument: str
    source: str                      # 'bars', 'tick', 'bars+tick'
    has_bars: bool = False
    has_tick: bool = False
    tick_spread_source: str = "none"  # 'tick', 'estimate', 'none'
    commission_status: str = "NOT_AVAILABLE"
    timeframes: List[str] = field(default_factory=list)
    bar_start: Optional[str] = None
    bar_end: Optional[str] = None
    tick_start: Optional[str] = None
    tick_end: Optional[str] = None
    quality_grade: Optional[str] = None      # best grade across bar TFs
    quality_score: Optional[float] = None    # best score across bar TFs
    intraday_bars: Optional[int] = None
    years_history: Optional[float] = None
    horizons_available: Dict[str, List[int]] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)

    def readiness(self) -> Dict[str, object]:
        """Transparent 0..1 readiness for a STAGE-5 IC test + component breakdown."""
        comps = {}

        # 1) quality component (0..1). If no bars, fall back to cost-data only base.
        if self.quality_score is not None:
            comps["quality"] = round(float(self.quality_score), 4)
        elif self.has_tick:
            comps["quality"] = 0.50  # tick present but no bar-quality grade measured
        else:
            comps["quality"] = 0.0

        # 2) history depth (0..1): years vs MIN_YEARS, and intraday bars vs MIN_BARS.
        yrs = self.years_history or 0.0
        depth_years = min(1.0, yrs / MIN_YEARS_FOR_IC) if MIN_YEARS_FOR_IC else 1.0
        bars = self.intraday_bars or 0
        depth_bars = min(1.0, bars / MIN_INTRADAY_BARS) if MIN_INTRADAY_BARS else 1.0
        comps["history_depth"] = round(min(depth_years, depth_bars) if bars else depth_years, 4)

        # 3) cost-data credibility: real tick spread is stronger than an estimate.
        comps["cost_credibility"] = {"tick": 1.0, "tick(XAUUSDm proxy)": 0.9,
                                     "estimate": 0.5, "none": 0.0}.get(
            self.tick_spread_source, 0.0)

        # 4) coverage: fraction of reference (tf, horizon) pairs available.
        total_ref, have = 0, 0
        for tf, hs in REF_HORIZONS.items():
            if tf in self.horizons_available:
                total_ref += len(hs)
                have += len([h for h in hs if h in self.horizons_available[tf]])
        comps["coverage"] = round(have / total_ref, 4) if total_ref else 0.0

        # weighted roll-up (documented weights; quality & history dominate).
        weights = {"quality": 0.35, "history_depth": 0.30, "cost_credibility": 0.20,
                   "coverage": 0.15}
        score = sum(weights[k] * float(comps[k]) for k in weights)
        score = round(max(0.0, min(1.0, score)), 3)
        verdict = ("READY" if score >= 0.70 else
                   "PARTIAL" if score >= 0.45 else "NOT_READY")
        return {"readiness_score": score, "verdict": verdict,
                "components": comps, "weights": weights}

    def as_dict(self) -> Dict[str, object]:
        d = {
            "instrument": self.instrument, "source": self.source,
            "has_bars": self.has_bars, "has_tick": self.has_tick,
            "tick_spread_source": self.tick_spread_source,
            "commission_status": self.commission_status,
            "timeframes": self.timeframes,
            "bar_start": self.bar_start, "bar_end": self.bar_end,
            "tick_start": self.tick_start, "tick_end": self.tick_end,
            "quality_grade": self.quality_grade, "quality_score": self.quality_score,
            "intraday_bars": self.intraday_bars, "years_history": self.years_history,
            "horizons_available": self.horizons_available,
            "gaps": self.gaps,
        }
        d.update(self.readiness())
        return d


def build_availability(stage2: Dict[str, object],
                       stage3: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Consolidate STAGE 2 (+ optional STAGE 3) into per-instrument availability."""
    s2_inst = (stage2 or {}).get("instruments", {})
    s3_inst = (stage3 or {}).get("instruments", {}) if stage3 else {}

    # Map tick instrument -> bar sibling for combined view + economics.
    tick_to_bar = {"XAUUSDm": "XAUUSD"}

    avail: Dict[str, InstrumentAvailability] = {}

    def _ensure(name: str) -> InstrumentAvailability:
        if name not in avail:
            avail[name] = InstrumentAvailability(instrument=name, source="bars")
        return avail[name]

    # --- bar instruments ---
    for name, inst in s2_inst.items():
        if inst.get("source") != "bars":
            continue
        a = _ensure(name)
        a.has_bars = True
        a.source = "bars"
        tfs = inst.get("timeframes", {})
        a.timeframes = sorted(tfs)
        best_grade, best_score = None, -1.0
        starts, ends = [], []
        intraday_total = 0
        for tf, t in tfs.items():
            if t.get("status") == "missing":
                a.gaps.append(f"{tf} bar file missing")
                continue
            q = t.get("quality", {})
            qs = q.get("quality", {})
            g = qs.get("grade")
            sc = qs.get("score")
            if sc is not None and sc > best_score:
                best_score = sc
                best_grade = g
            starts.append(_parse_date(q.get("first_ts")))
            ends.append(_parse_date(q.get("last_ts")))
            intraday_total += int(q.get("intraday_rows") or 0)
            # horizons available for this TF from economics rows
            hs = sorted({int(r["horizon_bars"]) for r in t.get("economics", [])
                         if r.get("scenario") == "baseline"})
            a.horizons_available[tf] = hs
        a.quality_grade = best_grade
        a.quality_score = best_score if best_score >= 0 else None
        a.intraday_bars = intraday_total or None
        a.bar_start = min([s for s in starts if s]) if any(starts) else None
        a.bar_end = max([e for e in ends if e]) if any(ends) else None
        a.years_history = _years_between(a.bar_start, a.bar_end)
        # cost source from STAGE 3 if present, else from STAGE 2 quality note.
        s3 = s3_inst.get(name, {})
        a.tick_spread_source = s3.get("spread_source", "estimate")
        a.commission_status = s3.get("commission_status", "NOT_AVAILABLE")
        if a.tick_spread_source == "estimate":
            a.gaps.append("spread is ESTIMATED (no tick Bid/Ask for this instrument)")
        if a.commission_status == "NOT_AVAILABLE":
            a.gaps.append("commission unknown (Exness account type) -> NOT_AVAILABLE")

    # --- tick instruments ---
    for name, inst in s2_inst.items():
        if inst.get("source") != "tick":
            continue
        target_name = name
        a = _ensure(target_name)
        a.has_tick = True
        a.source = "bars+tick" if a.has_bars else "tick"
        sp = inst.get("spread", {})
        a.tick_start = _parse_date(sp.get("time_start"))
        a.tick_end = _parse_date(sp.get("time_end"))
        s3 = s3_inst.get(name, {})
        a.tick_spread_source = s3.get("spread_source", "tick")
        a.commission_status = s3.get("commission_status", "NOT_AVAILABLE")
        # if there's a bar sibling, borrow its quality/horizons (combined view)
        sib = tick_to_bar.get(name)
        if sib and sib in avail:
            ba = avail[sib]
            a.has_bars = ba.has_bars
            a.timeframes = ba.timeframes
            a.quality_grade = ba.quality_grade
            a.quality_score = ba.quality_score
            a.intraday_bars = ba.intraday_bars
            a.horizons_available = ba.horizons_available
            a.bar_start, a.bar_end = ba.bar_start, ba.bar_end
            a.source = "bars+tick"
        if a.commission_status == "NOT_AVAILABLE":
            a.gaps.append("commission unknown (Exness account type) -> NOT_AVAILABLE")
        # detect truncated tick coverage vs bar coverage
        if sib and sib in avail:
            bar_end = avail[sib].bar_end
            if a.tick_end and bar_end and a.tick_end < bar_end:
                a.gaps.append(
                    f"tick coverage ends {a.tick_end} but bars extend to {bar_end} "
                    f"(recent period not tick-covered)")

    # --- fully unavailable instruments ---
    for name in (stage2 or {}).get("data_unavailable", []):
        a = _ensure(name)
        a.source = "none"
        a.has_bars = a.has_tick = False
        a.tick_spread_source = "none"
        a.gaps.append("DATA_UNAVAILABLE: no files on disk")

    # finalize years where only tick (no bars) and compute depth for tick-only
    result = {"instruments": {}}
    for name, a in avail.items():
        if a.years_history is None and a.tick_start and a.tick_end:
            a.years_history = _years_between(a.tick_start, a.tick_end)
        result["instruments"][name] = a.as_dict()

    # ranking
    ranked = sorted(result["instruments"].items(),
                    key=lambda kv: -(kv[1].get("readiness_score") or 0))
    result["ranking"] = [k for k, _ in ranked]
    result["summary"] = {
        "ready": [k for k, v in result["instruments"].items()
                  if v["verdict"] == "READY"],
        "partial": [k for k, v in result["instruments"].items()
                    if v["verdict"] == "PARTIAL"],
        "not_ready": [k for k, v in result["instruments"].items()
                      if v["verdict"] == "NOT_READY"],
    }
    return result

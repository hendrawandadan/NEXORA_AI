"""Fundamental Event Response Intelligence.

Links external events to *measurable* market response across post-release horizons
(1m, 5m, 15m, 30m, 1h, 4h, 1d) using ONLY price data available at/after the event
timestamp. Strict anti-leakage rules:

  * The "pre" price is the last bar CLOSE STRICTLY BEFORE the event timestamp.
  * The "post" price is the first bar close at/after event_ts + horizon.
  * If the required bar for a horizon is unavailable, the response is marked
    ``valid=False`` -- never interpolated or invented.
  * No future data beyond ``event_ts + horizon`` is used to compute that horizon's
    return. Each horizon is independent (no cross-contamination).
  * We do NOT run any trading experiment; we only measure realised returns.

Inputs are bars (list of dicts with 'ts' (ISO or datetime) and 'close'), supplied by
the caller from an ALREADY-AVAILABLE dataset. This module does no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

DEFAULT_HORIZONS: Sequence = (
    ("1m", 1), ("5m", 5), ("15m", 15), ("30m", 30),
    ("1h", 60), ("4h", 240), ("1d", 1440),
)


def _to_dt(x) -> Optional[datetime]:
    if isinstance(x, datetime):
        dt = x
    elif isinstance(x, str):
        try:
            dt = datetime.fromisoformat(x.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class HorizonResponse:
    horizon: str
    horizon_minutes: int
    pre_price: Optional[float]
    post_price: Optional[float]
    return_pct: Optional[float]
    direction: str          # UP / DOWN / FLAT
    valid: bool
    note: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"horizon": self.horizon, "horizon_minutes": self.horizon_minutes,
                "pre_price": self.pre_price, "post_price": self.post_price,
                "return_pct": self.return_pct, "direction": self.direction,
                "valid": self.valid, "note": self.note}


@dataclass
class EventResponse:
    event_id: Optional[int]
    instrument: str
    event_ts: str
    responses: List[HorizonResponse] = field(default_factory=list)
    # R2 (PIT): the timestamp actually used as the anti-leakage basis. Equals event_ts
    # unless a release-availability time (available_at) is later, in which case the pre
    # price is the last close strictly before that later, knowable time.
    basis_ts: str = ""
    event_available_at: Optional[str] = None
    caveat: str = ("Realised response only; direction may reflect confounding news and "
                   "does not establish that the event caused the move.")

    def as_dict(self) -> Dict[str, object]:
        return {"event_id": self.event_id, "instrument": self.instrument,
                "event_ts": self.event_ts, "basis_ts": self.basis_ts,
                "event_available_at": self.event_available_at,
                "responses": [r.as_dict() for r in self.responses],
                "caveat": self.caveat}


def _find_price_before(bars: List[Dict], event_dt: datetime) -> Optional[float]:
    """Last close with timestamp strictly before event_dt (no look-ahead)."""
    best = None
    for b in bars:
        dt = _to_dt(b.get("ts"))
        if dt is None:
            continue
        if dt < event_dt:
            if best is None or dt > best[0]:
                best = (dt, b.get("close"))
    return None if best is None else float(best[1])


def _find_price_at_or_after(bars: List[Dict], target_dt: datetime) -> Optional[float]:
    """First close with timestamp >= target_dt."""
    best = None
    for b in bars:
        dt = _to_dt(b.get("ts"))
        if dt is None:
            continue
        if dt >= target_dt:
            if best is None or dt < best[0]:
                best = (dt, b.get("close"))
    return None if best is None else float(best[1])


def measure_event_response(*, event_id: Optional[int], event_ts: str,
                           instrument: str, bars: List[Dict],
                           horizons: Sequence = DEFAULT_HORIZONS,
                           flat_epsilon: float = 1e-6,
                           available_at: Optional[str] = None) -> EventResponse:
    """Measure post-event returns across horizons using only available bars.

    ``bars``: list of {'ts': <iso|datetime>, 'close': <float>}, unordered OK.

    R2 (PIT): ``available_at`` is the market-knowability time (release/embargo). When it
    is provided and LATER than ``event_ts``, the anti-leakage basis becomes ``available_at``
    (the first bar at/after it must exist for the response to be measured); the "pre"
    price is the last close STRICTLY BEFORE that basis. This prevents look-ahead when
    ``scheduled_ts`` denotes a reporting period rather than the release instant. When
    ``available_at`` is absent we fall back to ``event_ts`` (current behaviour) but the
    response is flagged in ``event_available_at`` so downstream can see it was unverified.
    """
    event_dt = _to_dt(event_ts)
    resp = EventResponse(event_id=event_id, instrument=instrument, event_ts=event_ts)
    if event_dt is None:
        resp.responses.append(HorizonResponse("ALL", 0, None, None, None, "FLAT", False,
                                              note="invalid event timestamp"))
        return resp

    # PIT basis: never earlier than the event; use availability when it is later.
    avail_dt = _to_dt(available_at) if available_at else None
    if avail_dt is not None and avail_dt > event_dt:
        basis_dt = avail_dt
        resp.event_available_at = available_at
    else:
        basis_dt = event_dt
        resp.event_available_at = available_at  # may be None (unverified) or <= event
    resp.basis_ts = basis_dt.isoformat()

    pre = _find_price_before(bars, basis_dt)
    for name, minutes in horizons:
        from datetime import timedelta
        target = basis_dt + timedelta(minutes=int(minutes))
        post = _find_price_at_or_after(bars, target)
        if pre is None or post is None or pre == 0:
            resp.responses.append(HorizonResponse(
                name, int(minutes), pre, post, None, "FLAT", False,
                note="insufficient price data around event for this horizon"))
            continue
        ret = (post - pre) / pre * 100.0
        if abs(ret) < flat_epsilon * 100:
            direction = "FLAT"
        elif ret > 0:
            direction = "UP"
        else:
            direction = "DOWN"
        resp.responses.append(HorizonResponse(
            name, int(minutes), round(pre, 8), round(post, 8), round(ret, 6),
            direction, True))
    return resp


def align_surprise_to_response(surprise: Optional[float], event_response: EventResponse,
                               horizon: str) -> Dict[str, object]:
    """Relate a fundamental surprise to the realised response at a horizon.

    Association only. Returns availability + a coarse aligned/dislocated label.
    """
    if surprise is None:
        return {"available": False, "note": "no surprise value (actual/forecast missing)"}
    h = next((r for r in event_response.responses if r.horizon == horizon), None)
    if h is None or not h.valid or h.return_pct is None:
        return {"available": False, "note": f"no valid response at {horizon}"}
    # For USD-type events higher surprise usually pairs with... we keep it descriptive.
    same_sign = (surprise > 0 and h.return_pct > 0) or (surprise < 0 and h.return_pct < 0)
    return {
        "available": True, "horizon": horizon,
        "surprise": surprise, "return_pct": h.return_pct,
        "direction": h.direction,
        "same_sign_as_surprise": bool(same_sign),
        "note": ("Descriptive association between surprise sign and realised return sign; "
                 "NOT evidence of causation or a tradable edge."),
    }

"""External Information Intelligence — Fundamental Intelligence (evidence-grounded event interpretation).

[Component of the INFO_ACQUISITION lane; enabler for Fase 2, see MASTER_ROADMAP 3a.]

Turns a normalised economic event into a STRUCTURED interpretation, but ONLY when the
inputs are present. It NEVER invents an actual/consensus/surprise:

  * A "surprise" is computed only when BOTH actual and forecast (consensus) exist.
  * Direction is HIGHER/LOWER/INLINE relative to consensus, else UNKNOWN.
  * Confidence is a categorical label (LOW/MEDIUM/HIGH) lowered when a prior-period
    revision contradicts the series.
  * Directional implications are CONDITIONAL and carry an explicit non-causation caveat.

Pure functions (no I/O). Persistence happens in the repository layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

EVENT_CATALOGUE: Dict[str, Dict[str, object]] = {
    "CPI": {"currency": "USD", "domain": "INFLATION", "unit": "index", "importance": "HIGH"},
    "CORE_CPI": {"currency": "USD", "domain": "INFLATION", "unit": "index", "importance": "HIGH"},
    "PPI": {"currency": "USD", "domain": "INFLATION", "unit": "index", "importance": "MEDIUM"},
    "PCE": {"currency": "USD", "domain": "INFLATION", "unit": "index", "importance": "HIGH"},
    "NFP": {"currency": "USD", "domain": "EMPLOYMENT", "unit": "k", "importance": "HIGH"},
    "UNEMPLOYMENT": {"currency": "USD", "domain": "EMPLOYMENT", "unit": "%", "importance": "HIGH"},
    "GDP": {"currency": "USD", "domain": "GROWTH", "unit": "%", "importance": "HIGH"},
    "RETAIL_SALES": {"currency": "USD", "domain": "GROWTH", "unit": "%", "importance": "MEDIUM"},
    "RATE_DECISION": {"currency": "USD", "domain": "MONETARY_POLICY", "unit": "%", "importance": "HIGH"},
    "PMI": {"currency": "USD", "domain": "GROWTH", "unit": "index", "importance": "MEDIUM"},
}


@dataclass
class FundamentalInterpretation:
    interpretation: str
    direction: str = "UNKNOWN"
    confidence: str = "LOW"             # LOW / MEDIUM / HIGH
    surprise: Optional[float] = None
    surprise_present: bool = False
    implications: Dict[str, object] = field(default_factory=dict)
    evidence: List[Dict[str, object]] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "interpretation": self.interpretation, "direction": self.direction,
            "confidence": self.confidence, "surprise": self.surprise,
            "surprise_present": self.surprise_present, "implications": self.implications,
            "evidence": self.evidence, "source_ids": self.source_ids,
        }


def classify_event(event_type: str) -> Dict[str, object]:
    """Return documented metadata for an event_type (known=False if absent)."""
    et = str(event_type or "").upper()
    meta = EVENT_CATALOGUE.get(et)
    if meta is None:
        return {"event_type": et, "known": False, "importance": "UNKNOWN",
                "currency": "", "domain": "", "unit": ""}
    return {"event_type": et, "known": True, "importance": meta["importance"],
            "currency": meta["currency"], "domain": meta["domain"], "unit": meta["unit"]}


def _as_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def interpret_event(event: Dict[str, object]) -> FundamentalInterpretation:
    """Evidence-bound interpretation of an economic event dict."""
    et = str(event.get("event_type", "")).upper()
    country = str(event.get("country", ""))
    currency = str(event.get("currency", ""))
    meta = classify_event(et)

    actual = _as_float(event.get("actual"))
    forecast = _as_float(event.get("forecast"))
    previous = _as_float(event.get("previous"))
    revised = _as_float(event.get("revised_previous"))

    evidence: List[Dict[str, object]] = []
    source_ids: List[str] = []
    if event.get("source_provider"):
        source_ids.append(str(event["source_provider"]))
    if event.get("source_ref"):
        source_ids.append(str(event["source_ref"]))

    caveat = "Directional implications are conditional and not causation."

    if actual is None:
        return FundamentalInterpretation(
            interpretation=("No actual value available for %s; interpretation withheld "
                            "(never fabricated)." % (et or "event")),
            direction="UNKNOWN", confidence="LOW", surprise=None, surprise_present=False,
            implications={"note": "no actual; no directional implication", "_caveat": caveat},
            evidence=evidence, source_ids=source_ids)

    if forecast is None:
        return FundamentalInterpretation(
            interpretation=("Actual=%s but no consensus (forecast) for %s; surprise cannot "
                            "be computed without consensus." % (actual, et or "event")),
            direction="UNKNOWN", confidence="LOW", surprise=None, surprise_present=False,
            implications={"note": "no consensus; surprise undefined", "_caveat": caveat},
            evidence=evidence, source_ids=source_ids)

    surprise = round(actual - forecast, 6)
    if surprise > 0:
        direction = "HIGHER"
    elif surprise < 0:
        direction = "LOWER"
    else:
        direction = "INLINE"
    evidence.append({"kind": "surprise", "actual": actual, "forecast": forecast,
                     "surprise": surprise})

    denom = abs(forecast) if abs(forecast) > 1e-9 else 1.0
    rel = abs(surprise) / denom
    if surprise == 0:
        confidence = "MEDIUM"
    elif rel >= 0.02:
        confidence = "HIGH"
    else:
        confidence = "MEDIUM"

    conf_note = ""
    if previous is not None and revised is not None and previous != revised:
        conf_note = " (prior revision present: %.4f -> %.4f; confidence reduced)" % (previous, revised)
        confidence = "MEDIUM" if confidence == "HIGH" else "LOW"
        evidence.append({"kind": "revision", "previous": previous, "revised_previous": revised})

    interpretation = ("%s %s: actual=%.4f vs consensus=%.4f -> surprise %+.4f (%s)%s."
                      % (et or "event", country or currency or "", actual, forecast,
                         surprise, direction, conf_note))

    domain = meta.get("domain", "")
    implications = {
        "surprise": surprise, "direction": direction, "domain": domain,
        "note": ("A %s surprise may condition, but does not cause, subsequent price "
                 "behaviour; effect is regime- and context-dependent." % direction.lower()),
        "_caveat": caveat,
    }
    return FundamentalInterpretation(
        interpretation=interpretation, direction=direction, confidence=confidence,
        surprise=surprise, surprise_present=True, implications=implications,
        evidence=evidence, source_ids=source_ids)

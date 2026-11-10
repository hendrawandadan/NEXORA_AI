"""External Information Intelligence — Central Bank Intelligence.

[Component of the INFO_ACQUISITION lane; enabler for Fase 2, see MASTER_ROADMAP §3a.]

Reads central-bank documents (statements/minutes/decisions) and produces an
EVIDENCE-BOUND tone assessment (hawkish/dovish/neutral) with CONFIDENCE and support
quotes. Explicitly:

  * Tone classification is NOT treated as fact. It carries confidence + the specific
    lexicon hits (quotes/markers) as evidence.
  * Policy change detection compares the LATEST document with the PREVIOUS one from the
    same institution+type: new/removed hawkish/dovish markers.
  * Rate-expectation shift is inferred only from explicit rate values; never invented.
  * Documents are UNTRUSTED text. We tokenise for analysis only; we never execute them.

This module is pure (no I/O). Persistence happens in the repository layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Lexicons -- deliberately conservative and documented. A match contributes evidence,
# not certainty. Multi-word phrases checked as substrings on normalised text.
HAWKISH_TERMS = (
    "raise rates", "raise interest rates", "increase rates", "tighten", "tightening",
    "inflation remains elevated", "elevated inflation", "persistent inflation",
    "higher for longer", "further tightening", "restrictive", "upside risks to inflation",
    "hike", "increase the target range", "vigilant",
)
DOVISH_TERMS = (
    "lower rates", "cut rates", "reduce rates", "easing", "ease policy", "loosen",
    "accommodative", "downside risks to growth", "slowdown", "recession risk",
    "pause", "hold rates steady", "support the economy", "stimulus", "rate cut",
)
NEUTRAL_TERMS = (
    "data dependent", "monitor", "meeting by meeting", "await further data",
    "unchanged", "assess incoming data",
)

INSTITUTIONS = ("FED", "ECB", "BOJ", "BOE", "SNB", "RBA", "BOC")


@dataclass
class ToneAssessment:
    tone: str                 # HAWKISH / DOVISH / NEUTRAL / UNKNOWN
    confidence: float         # 0..1
    hawkish_score: int
    dovish_score: int
    neutral_score: int
    evidence_quotes: List[str] = field(default_factory=list)
    caveat: str = ("Tone classification is heuristic and NOT a fact; it reflects "
                   "keyword markers in the text, not a policy guarantee.")

    def as_dict(self) -> Dict[str, object]:
        return {
            "tone": self.tone, "confidence": round(self.confidence, 4),
            "hawkish_score": self.hawkish_score, "dovish_score": self.dovish_score,
            "neutral_score": self.neutral_score,
            "evidence_quotes": self.evidence_quotes, "caveat": self.caveat,
        }


@dataclass
class PolicyChange:
    institution: str
    doc_type: str
    latest_published_ts: str
    previous_published_ts: Optional[str]
    tone_latest: str
    tone_previous: Optional[str]
    new_hawkish: List[str] = field(default_factory=list)
    new_dovish: List[str] = field(default_factory=list)
    removed_hawkish: List[str] = field(default_factory=list)
    removed_dovish: List[str] = field(default_factory=list)
    policy_shift: str = "UNCHANGED"   # MORE_HAWKISH / MORE_DOVISH / UNCHANGED / UNKNOWN
    confidence: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        return {
            "institution": self.institution, "doc_type": self.doc_type,
            "latest_published_ts": self.latest_published_ts,
            "previous_published_ts": self.previous_published_ts,
            "tone_latest": self.tone_latest, "tone_previous": self.tone_previous,
            "new_hawkish": self.new_hawkish, "new_dovish": self.new_dovish,
            "removed_hawkish": self.removed_hawkish, "removed_dovish": self.removed_dovish,
            "policy_shift": self.policy_shift,
            "confidence": round(self.confidence, 4),
        }


def _normalise(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _find_terms(norm_text: str, terms: tuple) -> List[str]:
    return [t for t in terms if t in norm_text]


def assess_tone(text: str) -> ToneAssessment:
    """Heuristic hawkish/dovish assessment of UNTRUSTED central-bank text."""
    norm = _normalise(text)
    haw = _find_terms(norm, HAWKISH_TERMS)
    dov = _find_terms(norm, DOVISH_TERMS)
    neu = _find_terms(norm, NEUTRAL_TERMS)
    h, d, n = len(haw), len(dov), len(neu)
    total = h + d + n
    if total == 0:
        return ToneAssessment("UNKNOWN", 0.0, 0, 0, 0, [], caveat=(
            "No recognised policy lexicon found; tone UNKNOWN rather than guessed."))
    # Direction by stronger signal; ties -> NEUTRAL if neutral markers exist else UNKNOWN.
    if h > d and h > n:
        tone = "HAWKISH"
        conf = h / (h + d + n + 1)  # +1 dampens overconfidence
    elif d > h and d > n:
        tone = "DOVISH"
        conf = d / (h + d + n + 1)
    elif n >= h and n >= d and n > 0:
        tone = "NEUTRAL"
        conf = n / (h + d + n + 1)
    else:
        tone = "UNKNOWN"
        conf = 0.0
    quotes = (haw if tone == "HAWKISH" else dov if tone == "DOVISH" else neu)[:5]
    return ToneAssessment(tone, min(conf, 1.0), h, d, n, quotes)


def _rate_value(text: str) -> Optional[float]:
    """Extract an explicit policy rate if stated like 'target range of 5.25-5.50%' or
    'kept at 4.00%'. Returns midpoint / value, else None (never invented)."""
    import re
    norm = str(text or "").replace("\n", " ")
    m = re.search(r"(\d{1,2}\.\d{1,2})\s*[-–to]+\s*(\d{1,2}\.\d{1,2})\s*%", norm, re.I)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return round((lo + hi) / 2.0, 4)
    m = re.search(r"(?:at|to|of)\s+(\d{1,2}\.\d{1,2})\s*%", norm, re.I)
    if m:
        return float(m.group(1))
    return None


def detect_policy_change(latest: Dict[str, object],
                         previous: Optional[Dict[str, object]]) -> PolicyChange:
    """Compare two documents (dicts with body/text + published_ts) for a policy shift.

    ``latest``/``previous`` should carry the raw text under 'body_text' (or 'text').
    Never asserts a shift without lexicon evidence.
    """
    inst = str(latest.get("institution", "UNKNOWN"))
    doc_type = str(latest.get("doc_type", "STATEMENT"))
    latest_ts = str(latest.get("published_ts", ""))
    latest_text = _normalise(latest.get("body_text") or latest.get("text") or "")
    latest_tone = assess_tone(latest_text)

    if previous is None:
        return PolicyChange(
            institution=inst, doc_type=doc_type, latest_published_ts=latest_ts,
            previous_published_ts=None, tone_latest=latest_tone.tone,
            tone_previous=None, policy_shift="UNKNOWN", confidence=0.0,
        )

    prev_ts = str(previous.get("published_ts", ""))
    prev_text = _normalise(previous.get("body_text") or previous.get("text") or "")
    prev_tone = assess_tone(prev_text)

    latest_haw = set(_find_terms(latest_text, HAWKISH_TERMS))
    latest_dov = set(_find_terms(latest_text, DOVISH_TERMS))
    prev_haw = set(_find_terms(prev_text, HAWKISH_TERMS))
    prev_dov = set(_find_terms(prev_text, DOVISH_TERMS))

    new_haw = sorted(latest_haw - prev_haw)
    new_dov = sorted(latest_dov - prev_dov)
    rem_haw = sorted(prev_haw - latest_haw)
    rem_dov = sorted(prev_dov - latest_dov)

    # Policy shift: more hawkish if new hawkish > new dovish AND/OR hawkish terms added
    # while dovish removed; symmetric for dovish.
    hawk_pressure = (len(new_haw) + len(latest_haw)) - (len(prev_haw))
    dov_pressure = (len(new_dov) + len(latest_dov)) - (len(prev_dov))

    # Rate change is a strong, explicit signal if both parse.
    latest_rate = _rate_value(latest.get("body_text") or latest.get("text") or "")
    prev_rate = _rate_value(previous.get("body_text") or previous.get("text") or "")

    shift = "UNCHANGED"
    conf = 0.0
    if latest_rate is not None and prev_rate is not None:
        if latest_rate > prev_rate:
            shift, conf = "MORE_HAWKISH", 0.8
        elif latest_rate < prev_rate:
            shift, conf = "MORE_DOVISH", 0.8
        else:
            shift = "UNCHANGED"
            conf = 0.3
    else:
        if len(new_haw) > len(new_dov) and len(new_haw) > 0:
            shift = "MORE_HAWKISH"
            conf = min(0.5 + 0.1 * (len(new_haw) - len(new_dov)), 0.85)
        elif len(new_dov) > len(new_haw) and len(new_dov) > 0:
            shift = "MORE_DOVISH"
            conf = min(0.5 + 0.1 * (len(new_dov) - len(new_haw)), 0.85)

    return PolicyChange(
        institution=inst, doc_type=doc_type, latest_published_ts=latest_ts,
        previous_published_ts=prev_ts, tone_latest=latest_tone.tone,
        tone_previous=prev_tone.tone, new_hawkish=new_haw, new_dovish=new_dov,
        removed_hawkish=rem_haw, removed_dovish=rem_dov,
        policy_shift=shift, confidence=conf,
    )


def rate_expectation_signal(docs: List[Dict[str, object]]) -> Dict[str, object]:
    """Summarise whether consecutive explicit policy rates move (up/down/flat).

    Only uses explicitly-stated rates; refuses to infer from prose. Returns a dict with
    'available', 'series' and 'direction' -- 'available': False when no rates parsed.
    """
    parsed = []
    for d in docs:
        r = _rate_value(d.get("body_text") or d.get("text") or "")
        if r is not None:
            parsed.append({"published_ts": d.get("published_ts", ""), "rate": r})
    parsed.sort(key=lambda x: str(x["published_ts"]))
    if len(parsed) < 2:
        return {"available": False, "series": parsed, "direction": "UNKNOWN",
                "note": "fewer than two explicit policy rates; no expectation shift."}
    direction = "FLAT"
    if parsed[-1]["rate"] > parsed[-2]["rate"]:
        direction = "UP"
    elif parsed[-1]["rate"] < parsed[-2]["rate"]:
        direction = "DOWN"
    return {"available": True, "series": parsed, "direction": direction,
            "note": "Derived strictly from explicitly stated policy rates."}

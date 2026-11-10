"""External Information Intelligence — News & Geopolitical Intelligence.

[Component of the INFO_ACQUISITION lane; enabler for Fase 2, see MASTER_ROADMAP 3a.]

Classifies news headline/text into categories, extracts simple entities, maps to
currencies/countries, assigns an impact hint, and derives a reliability tag from the
source registry. Text is treated as UNTRUSTED input (never commands). Pure functions;
no I/O, no DB, no network.

Categories are constrained to the repository's VALID_NEWS_CATEGORY set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Category keyword rules. Order matters: first match wins. Specific/clear categories
# (sanctions -> trade -> geopolitical) are checked before broad ones so that e.g.
# "tariffs in escalating trade war" classifies as TRADE, not GEOPOLITICAL.
_CATEGORY_RULES = [
    ("SANCTIONS", ("sanction", "embargo", "blacklist", "export ban", "asset freeze")),
    ("TRADE", ("tariff", "trade war", "trade deal", "export", "import", "quota", "wto")),
    ("GEOPOLITICAL", ("war", "conflict", "military", "missile", "attack", "invasion",
                      "coup", "geopolitical")),
    ("FINANCIAL_CRISIS", ("default", "bank run", "bailout", "insolvency", "crisis",
                          "collapse", "bankruptcy")),
    ("SUPPLY_CHAIN", ("supply chain", "shipping", "port", "logistics", "shortage",
                      "container", "suez", "freight")),
    ("ECONOMIC", ("inflation", "cpi", "ppi", "gdp", "unemployment", "payroll", "jobs",
                  "retail sales", "pmi", "recession", "growth")),
    ("GOVERNMENT_POLICY", ("budget", "fiscal", "tax", "stimulus", "subsid", "regulation",
                           "policy")),
]

# Country keyword -> (ISO code, currency).
_COUNTRY_MAP = {
    "united states": ("US", "USD"), "u.s.": ("US", "USD"),
    "fed": ("US", "USD"), "federal reserve": ("US", "USD"), "america": ("US", "USD"),
    "euro area": ("EU", "EUR"), "eurozone": ("EU", "EUR"), "ecb": ("EU", "EUR"),
    "european central bank": ("EU", "EUR"), "germany": ("DE", "EUR"), "france": ("FR", "EUR"),
    "united kingdom": ("GB", "GBP"), "boe": ("GB", "GBP"),
    "bank of england": ("GB", "GBP"), "britain": ("GB", "GBP"),
    "japan": ("JP", "JPY"), "boj": ("JP", "JPY"), "bank of japan": ("JP", "JPY"),
    "china": ("CN", "CNY"), "chinese": ("CN", "CNY"),
    "canada": ("CA", "CAD"), "australia": ("AU", "AUD"),
    "switzerland": ("CH", "CHF"), "new zealand": ("NZ", "NZD"),
}

_ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+(?:of|[A-Z][a-zA-Z]+)){0,3})\b")
_IMPACT_HINTS = ("HIGH", "MEDIUM", "LOW")


@dataclass
class NewsClassification:
    category: str
    countries: List[str] = field(default_factory=list)
    currencies: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    impact: str = "UNKNOWN"
    reliability: str = "UNKNOWN"
    source_provider: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"category": self.category, "countries": self.countries,
                "currencies": self.currencies, "entities": self.entities,
                "impact": self.impact, "reliability": self.reliability,
                "source_provider": self.source_provider}


def _reliability_for_provider(source_provider: str) -> str:
    if not source_provider:
        return "UNKNOWN"
    try:
        from . import source_registry as sr
        prov = sr.get_provider(source_provider)
        return prov.reliability or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _classify_category(text: str) -> str:
    low = text.lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in low for kw in keywords):
            return category
    return "OTHER"


def _extract_countries_currencies(text: str):
    low = " " + text.lower() + " "
    countries: List[str] = []
    currencies: List[str] = []
    for kw, (cc, cur) in _COUNTRY_MAP.items():
        if kw in low:
            if cc not in countries:
                countries.append(cc)
            if cur not in currencies:
                currencies.append(cur)
    return countries, currencies


def _extract_entities(text: str) -> List[str]:
    found = _ENTITY_RE.findall(text)
    stop = {"The", "A", "An", "This", "That", "In", "On", "At", "After", "Before"}
    out: List[str] = []
    for e in found:
        e = e.strip()
        if e in stop:
            continue
        if e not in out:
            out.append(e)
    return out


def classify_news(headline: str, body: str = "", *, source_provider: str = "mock",
                  impact_hint: Optional[str] = None) -> NewsClassification:
    """Classify a news item deterministically. Text is UNTRUSTED."""
    text = (headline or "") + " " + (body or "")
    category = _classify_category(text)
    countries, currencies = _extract_countries_currencies(text)
    entities = _extract_entities(headline or body or "")
    reliability = _reliability_for_provider(source_provider)
    if impact_hint is not None and str(impact_hint).upper() in _IMPACT_HINTS:
        impact_val = str(impact_hint).upper()
    else:
        impact_val = "HIGH" if category in ("GEOPOLITICAL", "SANCTIONS", "TRADE",
                                            "FINANCIAL_CRISIS") else "MEDIUM"
    return NewsClassification(category=category, countries=countries,
                              currencies=currencies, entities=entities,
                              impact=impact_val, reliability=reliability,
                              source_provider=source_provider)


def _normalise_headline(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (h or "").lower()).strip()


def find_duplicate(headline: str, existing: List[Dict[str, object]]) -> Optional[int]:
    """Return the id of an existing item whose normalised headline matches, else None."""
    target = _normalise_headline(headline)
    if not target:
        return None
    for item in existing:
        if _normalise_headline(str(item.get("headline", ""))) == target:
            try:
                return int(item.get("id")) if item.get("id") is not None else None
            except (TypeError, ValueError):
                return None
    return None

"""External Information Intelligence — External Source Registry.

[Component of the INFO_ACQUISITION lane; enabler for Fase 2, see MASTER_ROADMAP §3a.]

A curated, machine-readable catalogue of external information providers. Each entry
documents, HONESTLY: tier, access method, auth requirement, rate limits, coverage,
historical depth, update frequency, cost, license, reliability, and failure-handling.
Nothing is assumed to be free or always-available -- the ``access_status`` field makes
the *documented reality* explicit, and ``available`` reflects whether the current
build can actually reach it with configured credentials.

Design:
  * Pure data + lookups. No network here.
  * ``PROVIDERS`` is the single source of truth; ``providers.json`` is emitted from it
    for human auditability (see ``dump_registry``).
  * Tiers: 1 = official, 2 = reputable financial data, 3 = news.
  * Every provider declares whether an API key is required and the env var name.

The registry NEVER stores secrets; it only names the env var a connector would read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

Tier = int  # 1, 2, 3

TIER_NAMES = {
    1: "OFFICIAL",
    2: "FINANCIAL_DATA",
    3: "NEWS",
}


@dataclass(frozen=True)
class Provider:
    """Documented description of one external information provider."""

    provider_id: str
    name: str
    tier: Tier
    category: str                     # macro / central_bank / market_data / news / cross_asset
    homepage: str
    access_method: str                # api / public_dataset / rss / html / bulk_download
    auth: str                         # "none" | "api_key:<ENV_VAR>" | "oauth"
    rate_limits: str
    coverage: str
    historical_coverage: str
    update_frequency: str
    cost: str                         # "free" | "freemium" | "paid" | "unknown"
    license: str
    reliability: str                  # HIGH | MEDIUM | LOW | UNKNOWN
    failure_handling: str
    notes: str = ""
    # Whether THIS build ships a working connector for it (honest capability flag):
    connector_available: bool = False
    # Whether the source is reachable without violating ToS / licensing:
    tos_safe_to_scrape: bool = False

    @property
    def auth_env_var(self) -> Optional[str]:
        if self.auth.startswith("api_key:"):
            return self.auth.split(":", 1)[1]
        return None

    def as_dict(self) -> Dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "tier": self.tier,
            "tier_name": TIER_NAMES.get(self.tier, "UNKNOWN"),
            "category": self.category,
            "homepage": self.homepage,
            "access_method": self.access_method,
            "auth": self.auth,
            "auth_env_var": self.auth_env_var,
            "rate_limits": self.rate_limits,
            "coverage": self.coverage,
            "historical_coverage": self.historical_coverage,
            "update_frequency": self.update_frequency,
            "cost": self.cost,
            "license": self.license,
            "reliability": self.reliability,
            "failure_handling": self.failure_handling,
            "notes": self.notes,
            "connector_available": self.connector_available,
            "tos_safe_to_scrape": self.tos_safe_to_scrape,
        }


# --------------------------------------------------------------------------- #
# The catalogue. Access status reflects documented reality, not aspiration.
# --------------------------------------------------------------------------- #
_PROVIDERS: List[Provider] = [
    # ---------------------------- TIER 1: OFFICIAL ----------------------------
    Provider(
        "fred", "Federal Reserve Economic Data (FRED)", 1, "macro",
        "https://fred.stlouisfed.org",
        "api", "api_key:NEXORA_FRED_API_KEY",
        "120 requests/min (keyed); 30/min demo",
        "800k+ US + intl series (CPI, NFP, yields, GDP, rates)",
        "Decades per series (varies)",
        "Real-time + revision history (ALFRED)",
        "free",
        "FRED Terms of Use: attribution required; redistribution limits",
        "HIGH",
        "Retry with backoff; honour 429; degrade to cached; mark stale; never fabricate",
        notes="Official aggregator of BLS/BEA/Treasury series. Revisions available via ALFRED -- "
              "must use as-of data for backtests to avoid look-ahead.",
        connector_available=True,
    ),
    Provider(
        "ecb_data", "European Central Bank Data Portal", 1, "central_bank",
        "https://data.ecb.europa.eu",
        "api", "none",
        "Fair-use; data-portal API is public",
        "Euro area rates, HICP, GDP, ECB policy decisions",
        "From 1999",
        "Daily / per release",
        "free",
        "ECB reuse policy: free reuse with attribution",
        "HIGH",
        "Retry; cache; validate schema version; mark stale",
        notes="Public SDW / data API. ECB key rate series and HICP inflation.",
        connector_available=True,
    ),
    Provider(
        "ecb_press", "ECB Press & Governing Council Statements", 1, "central_bank",
        "https://www.ecb.europa.eu/press",
        "rss", "none",
        "Fair-use",
        "Monetary policy decisions, speeches, minutes",
        "Recent",
        "Per release",
        "free",
        "ECB reuse with attribution",
        "HIGH",
        "RSS parse guard; treat body as UNTRUSTED text",
        notes="Key source for ECB policy tone. Text is untrusted input, never commands.",
        connector_available=True,
    ),
    Provider(
        "fed_press", "Federal Reserve Press Releases", 1, "central_bank",
        "https://www.federalreserve.gov/feeds",
        "rss", "none",
        "Fair-use",
        "FOMC statements, minutes, speeches",
        "Recent",
        "Per release",
        "free",
        "US federal government works: public domain",
        "HIGH",
        "RSS parse guard; untrusted text handling",
        notes="FOMC statement source. Public domain (US Gov).",
        connector_available=True,
    ),
    Provider(
        "boj_press", "Bank of Japan Statements", 1, "central_bank",
        "https://www.boj.or.jp/en",
        "html", "none",
        "Fair-use",
        "BOJ policy statements, outlook reports",
        "Recent",
        "Per release",
        "free",
        "BOJ copyright with reuse guidance",
        "MEDIUM",
        "HTML parse guard; untrusted text",
        notes="HTML-based; parsing fragile. Manual verification advised.",
        connector_available=False,
    ),
    Provider(
        "boe_press", "Bank of England News", 1, "central_bank",
        "https://www.bankofengland.co.uk/news",
        "rss", "none",
        "Fair-use",
        "BoE MPC decisions, minutes",
        "Recent",
        "Per release",
        "free",
        "BoE Open Government Licence with attribution",
        "MEDIUM",
        "RSS parse guard; untrusted text",
        connector_available=False,
    ),
    Provider(
        "bls", "U.S. Bureau of Labor Statistics", 1, "macro",
        "https://www.bls.gov/developers",
        "api", "api_key (optional):BLS_API_KEY",
        "Varies; keyed series higher",
        "CPI, PPI, NFP, unemployment, claims",
        "From series inception",
        "Per release",
        "free",
        "Public domain (US Gov)",
        "HIGH",
        "Retry; validate; mark stale; never fabricate revisions",
        notes="Official US labour & price statistics. BLS key optional (rate-limited).",
        connector_available=False,
    ),
    Provider(
        "bea", "U.S. Bureau of Economic Analysis", 1, "macro",
        "https://apps.bea.gov/api",
        "api", "api_key:BEA_API_KEY",
        "Reasonable use",
        "GDP, PCE, income",
        "From series inception",
        "Per release (quarterly/monthly)",
        "free",
        "Public domain (US Gov)",
        "HIGH",
        "Retry; validate; mark stale",
        connector_available=False,
    ),
    Provider(
        "eurostat", "Eurostat", 1, "macro",
        "https://ec.europa.eu/eurostat",
        "public_dataset", "none",
        "Fair-use",
        "EU CPI, GDP, unemployment, production, sentiment",
        "From series inception",
        "Monthly/quarterly",
        "free",
        "Eurostat reuse policy with attribution",
        "HIGH",
        "Bulk download validation; mark stale",
        connector_available=False,
    ),
    Provider(
        "treasury", "U.S. Department of the Treasury", 1, "market_data",
        "https://home.treasury.gov",
        "public_dataset", "none",
        "Fair-use",
        "Treasury yield curve (nominal & real/TIPS)",
        "From 1990 (par yield curve)",
        "Daily",
        "free",
        "Public domain (US Gov)",
        "HIGH",
        "CSV/XML validation; mark stale",
        notes="Real yields (TIPS) for gold/real-rate analysis.",
        connector_available=False,
    ),
    Provider(
        "imf", "International Monetary Fund", 1, "macro",
        "https://www.imf.org/en/Data",
        "public_dataset", "none",
        "Fair-use",
        "Global macro, balance of payments, WEO",
        "Decades; WEO projections",
        "Periodic",
        "free",
        "IMF terms with attribution",
        "HIGH",
        "Bulk download validation; mark stale",
        connector_available=False,
    ),
    Provider(
        "worldbank", "World Bank Open Data", 1, "macro",
        "https://data.worldbank.org",
        "api", "none",
        "Fair-use",
        "Global development macro indicators",
        "Decades",
        "Periodic",
        "free",
        "CC-BY 4.0",
        "HIGH",
        "Retry; validate",
        connector_available=False,
    ),
    Provider(
        "bis", "Bank for International Settlements", 1, "cross_asset",
        "https://www.bis.org/statistics",
        "public_dataset", "none",
        "Fair-use",
        "Cross-border banking, FX turnover, credit",
        "Decades",
        "Periodic",
        "free",
        "BIS terms with attribution",
        "HIGH",
        "Bulk validation",
        connector_available=False,
    ),
    Provider(
        "oecd", "OECD Data", 1, "macro",
        "https://data.oecd.org",
        "api", "none",
        "Fair-use",
        "Leading indicators, PMI-type, sentiment, macro",
        "Decades",
        "Monthly/quarterly",
        "free",
        "OECD terms with attribution",
        "HIGH",
        "Retry; validate",
        connector_available=False,
    ),
    # ---------------------- TIER 2: REPUTABLE FINANCIAL DATA ----------------------
    Provider(
        "tradingeconomics", "Trading Economics", 2, "macro",
        "https://tradingeconomics.com/api",
        "api", "api_key:NEXORA_TRADINGECONOMICS_KEY",
        "Guest limited; paid tiers higher",
        "Economic calendar with consensus (actual/forecast/previous)",
        "Recent via API; deeper on paid",
        "Real-time calendar",
        "freemium",
        "Commercial license; redistribution restricted",
        "MEDIUM",
        "Retry; honour quotas; degrade gracefully; never fabricate consensus",
        notes="One possible CONSENSUS source. Consensus values are third-party -- mark provenance.",
        connector_available=False,
    ),
    Provider(
        "fred_yields", "FRED -- Treasury yields/real yields series", 2, "market_data",
        "https://fred.stlouisfed.org",
        "api", "api_key:NEXORA_FRED_API_KEY",
        "Same as FRED",
        "Nominal & real yields, DXY proxy, rates",
        "Decades",
        "Daily",
        "free",
        "FRED Terms",
        "HIGH",
        "Retry; mark stale",
        notes="Derived from FRED; same key. Useful for cross-market/real-yield work.",
        connector_available=True,
    ),
    Provider(
        "nasdaq_data_link", "Nasdaq Data Link (Quandl)", 2, "market_data",
        "https://data.nasdaq.com",
        "api", "api_key:NASDAQ_DATA_LINK_KEY",
        "Varies by dataset",
        "Commodities, FX, macro datasets",
        "Varies",
        "Varies",
        "freemium",
        "Per-dataset license",
        "MEDIUM",
        "Retry; quota guard",
        connector_available=False,
    ),
    # ------------------------------ TIER 3: NEWS ------------------------------
    Provider(
        "reuters", "Reuters", 3, "news",
        "https://www.reuters.com",
        "rss", "none (RSS) / paid (full)",
        "RSS fair-use",
        "Global financial & geopolitical news",
        "Recent via RSS",
        "Continuous",
        "freemium",
        "Reuters license; automated scraping of site PROHIBITED -- RSS only",
        "MEDIUM",
        "RSS parse guard; dedupe; untrusted text",
        notes="RSS only. Do NOT scrape reuters.com HTML (ToS). Full newswire is paid.",
        connector_available=False,
    ),
    Provider(
        "ft", "Financial Times", 3, "news",
        "https://www.ft.com",
        "rss", "none (headline RSS)",
        "RSS fair-use",
        "Financial news (headlines)",
        "Recent via RSS",
        "Continuous",
        "paid",
        "FT license; body scraping PROHIBITED",
        "MEDIUM",
        "RSS parse guard; untrusted text",
        notes="Headline RSS only under license. No article-body scraping.",
        connector_available=False,
    ),
    Provider(
        "cnbc", "CNBC", 3, "news",
        "https://www.cnbc.com",
        "rss", "none",
        "RSS fair-use",
        "Markets & macro news",
        "Recent via RSS",
        "Continuous",
        "free",
        "CNBC terms; RSS only",
        "MEDIUM",
        "RSS parse guard; untrusted text",
        connector_available=False,
    ),
    Provider(
        "bloomberg", "Bloomberg", 3, "news",
        "https://www.bloomberg.com",
        "api", "paid/enterprise",
        "Enterprise licensing",
        "Financial news & data",
        "Paid depth",
        "Continuous",
        "paid",
        "Bloomberg license; scraping PROHIBITED",
        "HIGH",
        "N/A (not integrated without license)",
        notes="Requires enterprise subscription; NOT reachable in this build. Do not scrape.",
        connector_available=False,
    ),
    Provider(
        "newsapi", "NewsAPI.org (aggregator)", 3, "news",
        "https://newsapi.org",
        "api", "api_key:NEXORA_NEWSAPI_KEY",
        "100 req/day free tier",
        "Aggregated news headlines across outlets",
        "Recent (~1 month free)",
        "Continuous",
        "freemium",
        "NewsAPI terms; developer tier non-commercial",
        "MEDIUM",
        "Retry; honour daily quota; untrusted text",
        notes="Aggregator -- reliability depends on underlying outlet. Mark source per article.",
        connector_available=True,
    ),
]

_PROVIDER_INDEX: Dict[str, Provider] = {p.provider_id: p for p in _PROVIDERS}


# --------------------------------------------------------------------------- #
# Lookups.
# --------------------------------------------------------------------------- #
def all_providers() -> List[Provider]:
    return list(_PROVIDERS)


def get_provider(provider_id: str) -> Provider:
    try:
        return _PROVIDER_INDEX[provider_id]
    except KeyError:
        raise KeyError(f"unknown provider_id: {provider_id}") from None


def providers_by_tier(tier: Tier) -> List[Provider]:
    return [p for p in _PROVIDERS if p.tier == tier]


def providers_by_category(category: str) -> List[Provider]:
    return [p for p in _PROVIDERS if p.category == category]


def available_connectors() -> List[Provider]:
    """Providers for which this build actually ships a working connector."""
    return [p for p in _PROVIDERS if p.connector_available]


def tos_safe_sources() -> List[Provider]:
    return [p for p in _PROVIDERS if p.tos_safe_to_scrape]


def registry_summary() -> Dict[str, object]:
    by_tier: Dict[int, int] = {}
    for p in _PROVIDERS:
        by_tier[p.tier] = by_tier.get(p.tier, 0) + 1
    return {
        "total_providers": len(_PROVIDERS),
        "by_tier": {TIER_NAMES.get(t, str(t)): n for t, n in sorted(by_tier.items())},
        "connectors_available": len(available_connectors()),
        "source_ids": [p.provider_id for p in _PROVIDERS],
    }


def registry_as_dicts() -> List[Dict[str, object]]:
    return [p.as_dict() for p in _PROVIDERS]


def dump_registry(out_path: Path) -> Path:
    """Write the registry as JSON for human audit (documents limitations)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(registry_as_dicts(), indent=2, sort_keys=True), encoding="utf-8")
    return out

"""External Information Intelligence — External Data Connectors.

[Component of the INFO_ACQUISITION lane; enabler for Fase 2, see MASTER_ROADMAP 3a.
 NOT a Fase-4 opening. No training/edge claim.]

A connector interface plus a MOCK provider (deterministic, offline, for tests) and a
small set of REAL provider adapters (FRED, RSS). Every connector obeys strict
robustness rules and FAILS CLOSED:

  * Never fabricates data. If a source is unavailable / unconfigured / rate-limited /
    times out, it returns a status describing reality -- it never returns invented rows.
  * Every result is content-hashed so provenance is auditable.
  * Records are tagged with a ``provenance`` marker ("SYNTHETIC" for mocks, otherwise
    the provider id) so synthetic fixtures cannot be mistaken for real data.
  * Rate limiting and timeouts are enforced per the config, never silently ignored.

This module performs NO network I/O at import time and stores NO secrets. Real
connectors read credentials strictly from the environment via ``config.read_secret``.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .config import DEFAULT_CONFIG, ExternalIntelConfig, has_secret


class FetchStatus(str, Enum):
    """Honest outcome of a fetch attempt."""

    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


def _content_sha(payload) -> str:
    """Canonical content hash (stable across key order)."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class FetchResult:
    """A structured, auditable fetch outcome. ``ok`` is True only on status OK."""

    status: FetchStatus
    provider_id: str = ""
    resource: str = ""
    records: List[Dict[str, object]] = field(default_factory=list)
    message: str = ""
    content_sha256: str = ""

    @property
    def ok(self) -> bool:
        return self.status is FetchStatus.OK

    def as_dict(self) -> Dict[str, object]:
        return {
            "status": self.status.value,
            "provider_id": self.provider_id,
            "resource": self.resource,
            "n_records": len(self.records),
            "message": self.message,
            "content_sha256": self.content_sha256,
        }


class RateLimiter:
    """A simple per-minute fixed-window rate limiter (deterministic, injectable clock)."""

    WINDOW_S = 60.0

    def __init__(self, per_min: int) -> None:
        if per_min < 0:
            raise ValueError("per_min must be >= 0")
        self.per_min = int(per_min)
        self._window_start: Optional[float] = None
        self._count = 0

    def try_acquire(self, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.monotonic()
        if self._window_start is None or (now - self._window_start) >= self.WINDOW_S:
            self._window_start = now
            self._count = 0
        if self._count >= self.per_min:
            return False
        self._count += 1
        return True


class Connector:
    """Base connector. Subclasses implement ``_fetch``."""

    provider_id: str = "base"

    def __init__(self, config: ExternalIntelConfig = DEFAULT_CONFIG) -> None:
        self.config = config
        self.limiter = RateLimiter(per_min=config.rate_limit_per_min)

    def fetch(self, *, resource: str, now: Optional[float] = None, **kwargs) -> FetchResult:
        if not self.limiter.try_acquire(now=now):
            return FetchResult(status=FetchStatus.RATE_LIMITED, provider_id=self.provider_id,
                               resource=resource,
                               message="rate limit exceeded (%d/min)" % self.config.rate_limit_per_min)
        try:
            records = self._fetch(resource=resource, **kwargs)
        except TimeoutError as exc:
            return FetchResult(status=FetchStatus.TIMEOUT, provider_id=self.provider_id,
                               resource=resource, message="timeout: %s" % exc)
        except NotImplementedError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            return FetchResult(status=FetchStatus.ERROR, provider_id=self.provider_id,
                               resource=resource, message="%s: %s" % (type(exc).__name__, exc))

        if records is None:
            return FetchResult(status=FetchStatus.UNAVAILABLE, provider_id=self.provider_id,
                               resource=resource, message="resource unavailable")
        return FetchResult(status=FetchStatus.OK, provider_id=self.provider_id,
                           resource=resource, records=list(records),
                           content_sha256=_content_sha(records))

    def _fetch(self, *, resource: str, **kwargs) -> Optional[List[Dict[str, object]]]:
        raise NotImplementedError("connector must implement _fetch")


class MockConnector(Connector):
    """Deterministic, offline connector over an in-memory mapping."""

    provider_id = "mock"

    def __init__(self, data: Optional[Dict[str, List[Dict[str, object]]]] = None,
                 config: ExternalIntelConfig = DEFAULT_CONFIG) -> None:
        super().__init__(config)
        self.data: Dict[str, List[Dict[str, object]]] = data or {}

    def _fetch(self, *, resource: str, **kwargs) -> Optional[List[Dict[str, object]]]:
        if resource not in self.data:
            return None
        tagged = []
        for rec in self.data[resource]:
            r = dict(rec)
            r.setdefault("provenance", "SYNTHETIC")
            tagged.append(r)
        return tagged


class FredConnector(Connector):
    """FRED adapter skeleton. Requires ``NEXORA_FRED_API_KEY`` in the environment."""

    provider_id = "fred"
    REQUIRED_ENV = "NEXORA_FRED_API_KEY"

    def fetch(self, *, resource: str, now: Optional[float] = None, **kwargs) -> FetchResult:
        # Explicit, honest message when the credential is absent (fail-closed).
        if not has_secret(self.REQUIRED_ENV, self.config):
            return FetchResult(
                status=FetchStatus.UNAVAILABLE, provider_id=self.provider_id,
                resource=resource,
                message="%s not set; FRED connector cannot fetch (no fabrication)."
                        % self.REQUIRED_ENV)
        return super().fetch(resource=resource, now=now, **kwargs)

    def _fetch(self, *, resource: str, **kwargs) -> Optional[List[Dict[str, object]]]:
        if not has_secret(self.REQUIRED_ENV, self.config):
            return None
        raise NotImplementedError(
            "FRED live fetch not enabled in this build; supply data via fixtures/MockConnector.")


class RssConnector(Connector):
    """Generic RSS adapter skeleton (headline-only, untrusted text)."""

    provider_id = "rss"

    def _fetch(self, *, resource: str, **kwargs) -> Optional[List[Dict[str, object]]]:
        raise NotImplementedError(
            "RSS live fetch not enabled in this build; supply items via fixtures.")


_CONNECTOR_BUILDERS = {
    "mock": lambda cfg: MockConnector({}, cfg),
    "fred": lambda cfg: FredConnector(cfg),
    "fred_yields": lambda cfg: FredConnector(cfg),
    "ecb_data": lambda cfg: MockConnector({}, cfg),
    "ecb_press": lambda cfg: RssConnector(cfg),
    "fed_press": lambda cfg: RssConnector(cfg),
    "newsapi": lambda cfg: MockConnector({}, cfg),
}


def build_connector(provider_id: str,
                    config: ExternalIntelConfig = DEFAULT_CONFIG) -> Connector:
    """Build a connector for ``provider_id``; raises NotImplementedError if none."""
    builder = _CONNECTOR_BUILDERS.get(provider_id)
    if builder is None:
        raise NotImplementedError(
            "no connector available for provider '%s' in this build" % provider_id)
    return builder(config)


def connector_status(config: ExternalIntelConfig = DEFAULT_CONFIG) -> Dict[str, str]:
    """Honest, human-readable status per connector in this build."""
    status: Dict[str, str] = {}
    status["mock"] = "READY (offline mock)"
    fred_state = "CONFIGURED" if has_secret("NEXORA_FRED_API_KEY", config) else "UNCONFIGURED"
    status["fred"] = fred_state + " (live fetch disabled in this build)"
    status["fred_yields"] = fred_state + " (live fetch disabled in this build)"
    status["ecb_data"] = "SKELETON (fixtures only)"
    status["ecb_press"] = "SKELETON (fixtures only)"
    status["fed_press"] = "SKELETON (fixtures only)"
    status["newsapi"] = "SKELETON (fixtures only)"
    return status

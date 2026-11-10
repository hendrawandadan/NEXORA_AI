"""Configurable provider rate limiting (Item 2.5, Phase 1).

A small, in-process, sliding-window rate limiter keyed by provider id. The scheduler
uses it to gate external-intelligence acquisition so a discovery job can never hammer a
provider. Limits are configurable via ``SchedulerConfig.provider_rate_limit_per_min``.

This is deliberately simple and dependency-free. It is NOT a distributed limiter; that
is adequate for a single-process, discovery-only scheduler. State is in-memory and resets
on restart (which is safe — it can only ever make the scheduler *more* conservative
immediately after a restart because the window starts empty).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

from .config import DEFAULT_CONFIG, SchedulerConfig


class ProviderRateLimiter:
    def __init__(self, config: SchedulerConfig = DEFAULT_CONFIG, *,
                 clock=time.monotonic) -> None:
        self.config = config
        self._clock = clock
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)

    def _limit_for(self, provider_id: str) -> int:
        limits = self.config.provider_rate_limit_per_min
        return int(limits.get(provider_id, limits.get("default", 30)))

    def try_acquire(self, provider_id: str) -> bool:
        """Attempt one request. Returns True if allowed, False if rate-limited."""
        limit = self._limit_for(provider_id)
        if limit <= 0:
            return False
        now = self._clock()
        window = self._windows[provider_id]
        # Drop entries older than 60s.
        while window and (now - window[0]) >= 60.0:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def remaining(self, provider_id: str) -> int:
        limit = self._limit_for(provider_id)
        now = self._clock()
        window = self._windows[provider_id]
        while window and (now - window[0]) >= 60.0:
            window.popleft()
        return max(0, limit - len(window))

    def reset(self, provider_id: str | None = None) -> None:
        if provider_id is None:
            self._windows.clear()
        else:
            self._windows.pop(provider_id, None)

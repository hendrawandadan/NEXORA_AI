"""Read-only query helpers over the Knowledge Memory.

Used by the deterministic hypothesis generator (Tahap C) and, later, by Strategy
Evolution (Tahap E) so the loop does not blindly re-run combinations already known
to be dead-ends -- the guardrail "no repeat of recorded failures without a recorded
change" (design §3.8).

Pure reads; never writes to the research DB or production.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from .store import ResearchMemoryStore


def _latest_by_key(rows: List[dict]) -> List[dict]:
    """Keep only the highest-version row per knowledge_key."""
    best: Dict[str, dict] = {}
    for r in rows:
        k = r["knowledge_key"]
        if k not in best or int(r["version"]) > int(best[k]["version"]):
            best[k] = r
    return list(best.values())


def list_knowledge(
    store: ResearchMemoryStore,
    *,
    kind: Optional[str] = None,
    latest_only: bool = True,
) -> List[Dict[str, object]]:
    """Return knowledge entries (optionally filtered by kind, latest version only)."""
    q = "SELECT * FROM research_knowledge"
    args: tuple = ()
    if kind:
        q += " WHERE kind=?"
        args = (kind,)
    q += " ORDER BY knowledge_key, version"
    with store.manager.open() as conn:
        rows = [dict(r) for r in conn.execute(q, args).fetchall()]
    return _latest_by_key(rows) if latest_only else rows


def dead_end_signatures(store: ResearchMemoryStore) -> List[str]:
    """Signatures (instrument|timeframe|horizon) already recorded as DEAD_END.

    The generator skips these unless the caller provides an explicit 'changed'
    reason. Signature is read from the entry's detail_json when present, else from
    the summary prefix "key: ..." convention used by failure_learning.
    """
    sigs: List[str] = []
    for entry in list_knowledge(store, kind="DEAD_END", latest_only=False):
        try:
            detail = json.loads(entry.get("detail_json") or "{}")
        except (TypeError, ValueError):
            detail = {}
        sig = detail.get("signature")
        if not sig:
            # fall back: try hypothesis_spec embedded by the generator
            hs = detail.get("hypothesis_spec") or {}
            if hs.get("instrument") and hs.get("timeframe") and hs.get("horizon_bars"):
                sig = f"{hs['instrument']}|{hs['timeframe']}|{hs['horizon_bars']}"
        if sig:
            sigs.append(str(sig))
    return sigs


def had_failure_for_signature(store: ResearchMemoryStore, signature: str) -> bool:
    """True if any failure was recorded whose evidence references this signature."""
    for f in store.list_failures():
        try:
            ev = json.loads(f.get("evidence_json") or "{}")
        except (TypeError, ValueError):
            ev = {}
        if ev.get("signature") == signature:
            return True
    return False

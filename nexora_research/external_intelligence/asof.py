"""R3 — As-Of Reconstruction & Point-In-Time (PIT) Re-Audit.

The purpose of this module is to *prove* — not merely assume — that historical NEXORA
data can be reconstructed using ONLY information that was genuinely knowable at a
decision cutoff, with no look-ahead leakage.

Core rule (fail-closed): a fact is usable at cutoff T **iff**:
  * ``available_at_utc`` is present AND ``available_at_utc <= T`` (market-knowability),
  * ``pit_verified == 1`` (the availability timestamp is source-backed), and
  * it is NOT synthetic.

``scheduled_ts`` / ``published_ts`` / ``event_ts`` are NEVER treated as availability.
A record with a missing ``available_at_utc`` is ``UNVERIFIED`` and is excluded from a
confirmatory as-of view (it may still be surfaced for provenance, flagged).

Revision rule: a row whose ``revision_as_of_utc > T`` (a revision made after the cutoff)
MUST NOT be usable at T. Among rows sharing a logical key, only revisions whose
``revision_as_of_utc <= T`` are eligible; the freshest eligible vintage wins.

This module performs READ-ONLY queries over the isolated external-intelligence DB. It
never writes, never fetches live data, never fabricates timestamps, and never mutates
facts. Deterministic given the same rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .repository import ExternalKnowledgeRepository

# Provenance classes (mutually exclusive, ordered by trust).
VERIFIED = "VERIFIED"        # pit_verified==1 and not synthetic and available_at present
UNVERIFIED = "UNVERIFIED"    # no source-backed availability (NULL pit_verified=0)
SYNTHETIC = "SYNTHETIC"      # is_synthetic==1 (mock/backtest fixtures, never confirmatory)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def classify_provenance(record: Dict[str, object]) -> str:
    """Classify a stored record as VERIFIED / UNVERIFIED / SYNTHETIC (fail-closed)."""
    if record.get("is_synthetic"):
        return SYNTHETIC
    if record.get("pit_verified") and record.get("available_at_utc"):
        return VERIFIED
    return UNVERIFIED


def _revision_eligible(record: Dict[str, object], cutoff: datetime) -> bool:
    """A row is eligible only if its revision happened at/before the cutoff.

    ``revision_as_of_utc`` absent is treated as 'original' (eligible at its availability).
    A revision made AFTER the cutoff is NOT usable at the cutoff (no hindsight).
    """
    rev = _parse_iso(record.get("revision_as_of_utc"))
    if rev is None:
        return True
    return rev <= cutoff


def is_usable_as_of(record: Dict[str, object], cutoff_ts: str) -> bool:
    """True iff ``record`` is genuinely knowable at ``cutoff_ts`` with no look-ahead.

    Requires: source-backed availability (pit_verified==1), a present available_at,
    available_at <= cutoff, not synthetic, and revision (if any) made <= cutoff.
    Missing/invalid cutoff -> False (fail-closed).
    """
    cutoff = _parse_iso(cutoff_ts)
    if cutoff is None:
        return False
    if classify_provenance(record) != VERIFIED:
        return False
    avail = _parse_iso(record.get("available_at_utc"))
    if avail is None or avail > cutoff:
        return False
    return _revision_eligible(record, cutoff)


@dataclass
class AsOfView:
    """Result of an as-of reconstruction at a decision cutoff."""

    cutoff_ts: str
    rows: List[Dict[str, object]] = field(default_factory=list)
    excluded_unverified: int = 0
    excluded_synthetic: int = 0
    excluded_future: int = 0          # available_at strictly after cutoff
    excluded_stale_revision: int = 0  # revision_as_of > cutoff
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "cutoff_ts": self.cutoff_ts,
            "usable": len(self.rows),
            "excluded_unverified": self.excluded_unverified,
            "excluded_synthetic": self.excluded_synthetic,
            "excluded_future": self.excluded_future,
            "excluded_stale_revision": self.excluded_stale_revision,
            "notes": self.notes,
            "row_count": len(self.rows),
        }


def reconstruct_events_as_of(repo: ExternalKnowledgeRepository, *, cutoff_ts: str,
                             event_type: Optional[str] = None,
                             currency: Optional[str] = None) -> AsOfView:
    """Return economic events genuinely knowable at ``cutoff_ts`` (fail-closed).

    Enforces PIT rules and de-duplicates revisions by logical key (the freshest eligible
    vintage wins). Rows that are UNVERIFIED / SYNTHETIC / future / stale-revision are
    counted and excluded — never silently dropped without accounting.
    """
    view = AsOfView(cutoff_ts=cutoff_ts)
    cutoff = _parse_iso(cutoff_ts)
    if cutoff is None:
        view.notes.append("invalid cutoff; nothing usable")
        return view

    raw = repo.list_events(event_type=event_type, currency=currency)
    # Group by logical key, then pick the freshest revision eligible at cutoff.
    by_key: Dict[str, List[Dict[str, object]]] = {}
    for r in raw:
        # Logical key without availability: revisions share event_key prefix (country|type|period|scheduled)
        key = f"{r.get('country')}|{r.get('event_type')}|{r.get('period')}|{r.get('scheduled_ts')}"
        by_key.setdefault(key, []).append(r)

    for key, rows in by_key.items():
        # First account for every row's exclusion reason (transparency).
        eligible_rows = []
        saw_verified = False
        for r in rows:
            prov = classify_provenance(r)
            if prov == SYNTHETIC:
                view.excluded_synthetic += 1
                continue
            if prov != VERIFIED:
                view.excluded_unverified += 1
                continue
            saw_verified = True
            avail = _parse_iso(r.get("available_at_utc"))
            if avail is None or avail > cutoff:
                view.excluded_future += 1
                continue
            if not _revision_eligible(r, cutoff):
                view.excluded_stale_revision += 1
                continue
            eligible_rows.append(r)
        if not eligible_rows:
            continue
        # Freshest eligible vintage by revision_as_of (then by availability) wins.
        def _rank(x):
            rev = _parse_iso(x.get("revision_as_of_utc")) or _parse_iso(x.get("available_at_utc"))
            return rev or cutoff
        eligible_rows.sort(key=_rank)
        view.rows.append(eligible_rows[-1])

    view.rows.sort(key=lambda r: str(r.get("available_at_utc") or ""))
    return view


def reconstruct_news_as_of(repo: ExternalKnowledgeRepository, *, cutoff_ts: str,
                           category: Optional[str] = None) -> AsOfView:
    """Return news genuinely knowable at ``cutoff_ts`` (fail-closed)."""
    view = AsOfView(cutoff_ts=cutoff_ts)
    cutoff = _parse_iso(cutoff_ts)
    if cutoff is None:
        view.notes.append("invalid cutoff; nothing usable")
        return view
    for r in repo.list_news(category=category):
        prov = classify_provenance(r)
        if prov == SYNTHETIC:
            view.excluded_synthetic += 1
            continue
        if prov != VERIFIED:
            view.excluded_unverified += 1
            continue
        avail = _parse_iso(r.get("available_at_utc"))
        if avail is None or avail > cutoff:
            view.excluded_future += 1
            continue
        view.rows.append(r)
    view.rows.sort(key=lambda r: str(r.get("available_at_utc") or ""))
    return view


def verify_no_leakage(view: AsOfView) -> List[str]:
    """Return a list of leakage violations (empty == clean). Deterministic audit."""
    violations: List[str] = []
    cutoff = _parse_iso(view.cutoff_ts)
    if cutoff is None:
        return ["invalid cutoff"]
    for r in view.rows:
        avail = _parse_iso(r.get("available_at_utc"))
        if avail is None:
            violations.append(f"row {r.get('id')}: missing available_at in usable set")
        elif avail > cutoff:
            violations.append(f"row {r.get('id')}: available_at {avail} > cutoff {cutoff}")
        if r.get("is_synthetic"):
            violations.append(f"row {r.get('id')}: synthetic in usable set")
        rev = _parse_iso(r.get("revision_as_of_utc"))
        if rev is not None and rev > cutoff:
            violations.append(f"row {r.get('id')}: revision {rev} > cutoff {cutoff}")
    return violations


def pit_integrity_matrix(repo: ExternalKnowledgeRepository) -> Dict[str, Dict[str, int]]:
    """Count VERIFIED / UNVERIFIED / SYNTHETIC per PIT-bearing table (re-audit)."""
    matrix: Dict[str, Dict[str, int]] = {}
    for table, lister in (
        ("ext_economic_events", lambda: repo.list_events()),
        ("ext_news_records", lambda: repo.list_news()),
        ("ext_central_bank_docs", lambda: repo.list_central_bank_docs()),
    ):
        counts = {VERIFIED: 0, UNVERIFIED: 0, SYNTHETIC: 0}
        for r in lister():
            counts[classify_provenance(r)] += 1
        matrix[table] = counts
    return matrix

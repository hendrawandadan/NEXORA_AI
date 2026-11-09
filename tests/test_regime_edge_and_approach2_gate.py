"""FASE 2A — Regime-conditional edge audit + Approach #2 gate.

Two things are locked here:

1. Directional edge does NOT concentrate in a regime (AUC ~0.51 everywhere, net
   negative everywhere) on the R1 OOS signal — using SYNTHETIC fixtures so the test
   is deterministic and does not depend on the large signal file. We replicate the
   audit's essence: a regime with no real edge yields AUC ~0.5 and net-negative
   returns regardless of regime label.

2. The Approach #2 gate: a decision helper says a barrier experiment is only worth
   pre-registering if some regime has BOTH AUC_net > 0.55 AND net mean > 0. This
   encodes the assessment rule so future drift is caught.
"""

from __future__ import annotations

import numpy as np

from nexora_laboratory.directional_edge_audit import audit_directional_edge


def _gate(audit_by_regime: dict, min_auc: float = 0.55) -> dict:
    """Approach #2 is worth testing iff SOME regime has AUC_net>min_auc AND net mean>0."""
    qualifying = []
    for regime, a in audit_by_regime.items():
        auc = a["discrimination"]["auc_dir_net"]
        buckets = a["buckets"]  # DataFrame
        net_mean = float((buckets["mean_ret_net"] * buckets["n"]).sum() / buckets["n"].sum())
        if (auc is not None and auc > min_auc) and net_mean > 0:
            qualifying.append(regime)
    return {"approach2_worth_testing": len(qualifying) > 0, "qualifying_regimes": qualifying}


def test_no_edge_across_all_regimes_blocks_approach2():
    rng = np.random.default_rng(7)
    n = 3000
    # Pure noise in every regime: p independent of return.
    audits = {}
    for i, regime in enumerate(("calm", "mid", "high")):
        p = rng.uniform(0.3, 0.7, n)
        ret = rng.normal(0, 3e-4, n)
        audits[regime] = audit_directional_edge(p, ret, round_trip_cost_pips=1.7,
                                                reference_price=1.10, n_buckets=5)
    gate = _gate(audits)
    assert gate["approach2_worth_testing"] is False
    for regime, a in audits.items():
        assert (a["discrimination"]["auc_dir_net"] is None
                or a["discrimination"]["auc_dir_net"] < 0.55)


def test_gate_triggers_only_with_real_regime_edge():
    rng = np.random.default_rng(8)
    n = 4000
    audits = {}
    # calm: real edge (p predicts return); mid/high: noise.
    p = rng.uniform(0.5, 0.8, n)
    ret = (p - 0.55) * 3e-3 + rng.normal(0, 2e-4, n)  # strong gross edge
    audits["calm"] = audit_directional_edge(p, ret, round_trip_cost_pips=0.5,
                                            reference_price=1.10, n_buckets=5)
    for regime in ("mid", "high"):
        p2 = rng.uniform(0.3, 0.7, n)
        r2 = rng.normal(0, 2e-4, n)
        audits[regime] = audit_directional_edge(p2, r2, round_trip_cost_pips=1.7,
                                                reference_price=1.10, n_buckets=5)
    gate = _gate(audits)
    assert gate["approach2_worth_testing"] is True
    assert gate["qualifying_regimes"] == ["calm"]

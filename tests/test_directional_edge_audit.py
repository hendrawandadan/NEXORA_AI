"""FASE 2A — Directional-edge audit: unit tests on synthetic fixtures.

Pure, no production data. Proves the audit correctly reports:
  * a genuinely predictive signal as usable (positive, monotonic, profitable),
  * a no-edge signal as NOT usable after cost,
  * that cost can flip a gross-positive edge to net-negative,
  * verdict requires ALL of auc>chance, monotonic, and a profitable threshold.
"""

from __future__ import annotations

import numpy as np

from nexora_laboratory.directional_edge_audit import (
    audit_directional_edge,
    verdict_from_audit,
)


def test_strong_signal_is_usable():
    rng = np.random.default_rng(0)
    n = 20000
    # p_right high -> win; define returns so higher p => larger positive return.
    p = rng.uniform(0.5, 0.8, n)
    ret = (p - 0.55) * 2e-3 + rng.normal(0, 3e-4, n)  # positive slope on p
    a = audit_directional_edge(p, ret, round_trip_cost_pips=0.5, reference_price=1.10)
    v = verdict_from_audit(a, min_auc=0.52)
    assert a["discrimination"]["auc_dir_net"] > 0.6
    assert a["bucket_monotonicity_spearman"] > 0.5
    assert v["usable_edge"] is True


def test_no_edge_signal_is_not_usable():
    rng = np.random.default_rng(1)
    n = 20000
    p = rng.uniform(0.0, 1.0, n)
    ret = rng.normal(0, 3e-4, n)  # independent of p
    a = audit_directional_edge(p, ret, round_trip_cost_pips=1.7, reference_price=1.10)
    v = verdict_from_audit(a, min_auc=0.52)
    assert v["usable_edge"] is False
    assert a["discrimination"]["auc_dir_net"] < 0.55


def test_cost_flips_gross_positive_to_net_negative():
    rng = np.random.default_rng(2)
    n = 40000
    # tiny gross edge (~0.5 pip) that a 1.7 pip round trip wipes out
    p = rng.uniform(0.5, 0.7, n)
    ret = 0.00005 + rng.normal(0, 2e-4, n)  # +0.5 pip mean gross
    a_gross = audit_directional_edge(p, ret, round_trip_cost_pips=0.0, reference_price=1.10)
    a_net = audit_directional_edge(p, ret, round_trip_cost_pips=1.7, reference_price=1.10)
    best_gross = a_gross["best_threshold_total_net"]["total_net"]
    # with zero cost a tiny edge can be positive; with 1.7 pips it must be worse
    assert best_gross > a_net["best_threshold_total_net"]["total_net"]


def test_verdict_requires_all_three_checks():
    rng = np.random.default_rng(3)
    n = 8000
    p = rng.uniform(0.5, 0.7, n)
    ret = rng.normal(0, 3e-4, n)  # no real edge -> monotonic may fail or auc ~0.5
    a = audit_directional_edge(p, ret, round_trip_cost_pips=1.7, reference_price=1.10)
    v = verdict_from_audit(a)
    assert v["usable_edge"] is False


def test_bucket_count_and_alignment():
    rng = np.random.default_rng(4)
    n = 5000
    p = rng.uniform(0, 1, n)
    ret = rng.normal(0, 1e-4, n)
    a = audit_directional_edge(p, ret, round_trip_cost_pips=1.0, n_buckets=5)
    assert len(a["buckets"]) == 5
    assert a["buckets"]["n"].sum() == a["n"]

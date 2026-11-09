"""FASE 2A v2 tests: net return, meta-label, uniqueness weights, overlap purging."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.cost_engine import components_for_scenario
from nexora_laboratory.event_attribution import (
    add_net_and_meta,
    average_uniqueness,
    purge_overlapping_between,
)
from nexora_laboratory.triple_barrier import (
    BarrierConfig,
    ExecutionConfig,
    atr_from_bars,
    label_events,
)


def _flat_bars(n, price=1.1, start="2021-01-04 00:00"):
    ts = pd.date_range(start, periods=n, freq="30min")
    return pd.DataFrame({"ts": ts, "open": np.full(n, price), "high": np.full(n, price),
                         "low": np.full(n, price), "close": np.full(n, price)})


def test_net_return_and_meta_label():
    n = 20
    b = _flat_bars(n, 1.1)
    atr = pd.Series(np.full(n, 0.01), index=b.index)
    cfg = BarrierConfig(k_up=10, k_dn=10, vertical=5)
    b2 = b.copy(); b2.loc[5, "close"] = 1.1005; b2.loc[5, "high"] = 1.1005
    lab = label_events(b2, atr, cfg, ExecutionConfig(), side=1)
    out = add_net_and_meta(lab, components_for_scenario("baseline"), spread_already_in_prices=True)
    assert "transaction_cost" in out and "net_return" in out and "meta_label" in out
    # net = gross - (only non-spread components in executable mode)
    diff = out["gross_return"] - out["net_return"]
    assert np.allclose(diff, out["transaction_cost"])
    assert set(out["meta_label"].unique()).issubset({0, 1})


def test_meta_label_matches_sign_of_net():
    n = 20
    b = _flat_bars(n, 1.1)
    atr = pd.Series(np.full(n, 0.01), index=b.index)
    cfg = BarrierConfig(k_up=10, k_dn=10, vertical=5)
    lab = label_events(b, atr, cfg, ExecutionConfig(), side=1)  # flat -> vertical ~0 gross
    out = add_net_and_meta(lab, components_for_scenario("baseline"), spread_already_in_prices=True)
    # net likely negative (cost) -> meta_label 0 where net<=0
    assert ((out["net_return"] > 0).astype(int) == out["meta_label"]).all()


def test_average_uniqueness_bounds():
    n = 40
    b = _flat_bars(n, 1.1)
    atr = pd.Series(np.full(n, 0.001), index=b.index)
    lab = label_events(b, atr, BarrierConfig(vertical=5), ExecutionConfig(), side=1)
    u = average_uniqueness(lab)
    assert len(u) == len(lab)
    assert (u > 0).all() and (u <= 1.0 + 1e-9).all()


def test_overlap_purge_removes_overlapping_train_events():
    """Overlapping events between train and other must be removed (leakage control)."""
    # two events with overlapping windows
    train = pd.DataFrame({
        "event_start_time": pd.to_datetime(["2021-01-04 00:00", "2021-01-04 10:00"]),
        "event_end_time": pd.to_datetime(["2021-01-04 02:00", "2021-01-04 12:00"]),
    })
    other = pd.DataFrame({
        "event_start_time": pd.to_datetime(["2021-01-04 01:00"]),  # overlaps train[0]
        "event_end_time": pd.to_datetime(["2021-01-04 01:30"]),
    })
    purged = purge_overlapping_between(train, other)
    # first train event overlaps other -> removed; second does not -> kept
    assert len(purged) == 1
    assert purged.iloc[0]["event_start_time"] == pd.Timestamp("2021-01-04 10:00")


def test_overlap_purge_no_overlap_keeps_all():
    train = pd.DataFrame({
        "event_start_time": pd.to_datetime(["2021-01-04 00:00"]),
        "event_end_time": pd.to_datetime(["2021-01-04 00:30"]),
    })
    other = pd.DataFrame({
        "event_start_time": pd.to_datetime(["2021-02-01 00:00"]),
        "event_end_time": pd.to_datetime(["2021-02-01 00:30"]),
    })
    assert len(purge_overlapping_between(train, other)) == 1

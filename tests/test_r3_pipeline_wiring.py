"""R3 wiring tests: verify pipeline.walk_forward_scores honours the purge param.

SAFETY: Tiny synthetic arrays that produce NO folds (remaining < folds*100), so
create_model/model.fit are never called. No dataset/DB/CSV access.
"""
from __future__ import annotations

import inspect

import numpy as np

import nexora_learning.pipeline as pipe


def test_purge_param_exists_and_defaults_none():
    sig = inspect.signature(pipe.walk_forward_scores)
    assert "purge" in sig.parameters
    assert sig.parameters["purge"].default is None


def test_train_one_wires_purge_from_embargo():
    src = inspect.getsource(pipe.train_one)
    assert "wf_purge" in src
    assert "embargo_bars" in src
    assert "purge=wf_purge" in src


def test_no_folds_no_fit_on_tiny_input():
    # n eligible is tiny -> initial=max(0,1000)=1000 > n -> remaining<0 -> no folds.
    n = 50
    X = np.random.RandomState(0).rand(n, 3)
    y = np.array([0, 1] * (n // 2))
    mask = np.ones(n, dtype=bool)
    # If fit were called this would attempt to train; it must not.
    out = pipe.walk_forward_scores(X, y, mask, horizon=2, engine="sklearn",
                                   seed=42, max_iter=1, folds=3, purge=24)
    assert out == []

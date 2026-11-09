"""FASE 2A — R1 result-freeze integrity + ATR-retained-as-baseline guarantees.

Read-only. Verifies the official R1 freeze manifest:
  * recomputes cleanly (no bound file has changed since freeze),
  * records the NO-GO verdict,
  * keeps ATR as the baseline (frozen config present, not replaced by adaptive).

If the artifact is absent (fresh checkout), the value checks skip rather than
fabricate a result; the manifest-structure checks still run on a synthetic input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexora_laboratory.experiment_freeze import (
    build_freeze_manifest,
    verify_manifest,
    write_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
R1_MANIFEST = ROOT / "reports/fase2a/adaptive_vs_atr/R1_FREEZE_MANIFEST.json"


# ---------------------------------------------------------------------------
# 1. Synthetic round-trip: build -> verify -> tamper -> detect
# ---------------------------------------------------------------------------
def test_manifest_detects_tampering(tmp_path):
    result = tmp_path / "res.json"
    result.write_text(json.dumps({"verdict": "NO-GO", "n_folds": 3}), encoding="utf-8")
    code = tmp_path / "code.py"
    code.write_text("x = 1\n", encoding="utf-8")

    m = build_freeze_manifest(
        tmp_path, experiment_id="TEST", result_path=result, code_paths=[code],
        frozen_config={"baseline_atr": {"k_up": 1.5}}, protocol={"folds": 3},
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert verify_manifest(tmp_path, m)["ok"] is True

    # Tamper the code -> verification must fail.
    code.write_text("x = 2\n", encoding="utf-8")
    v = verify_manifest(tmp_path, m)
    assert v["ok"] is False
    assert any("code file changed" in p for p in v["problems"])


def test_manifest_is_deterministic_modulo_timestamp(tmp_path):
    result = tmp_path / "res.json"
    result.write_text(json.dumps({"verdict": "GO"}), encoding="utf-8")
    code = tmp_path / "c.py"
    code.write_text("pass\n", encoding="utf-8")
    a = build_freeze_manifest(tmp_path, experiment_id="T", result_path=result,
                              code_paths=[code], frozen_config={}, protocol={},
                              created_at="2026-01-01T00:00:00+00:00")
    b = build_freeze_manifest(tmp_path, experiment_id="T", result_path=result,
                              code_paths=[code], frozen_config={}, protocol={},
                              created_at="2030-12-31T00:00:00+00:00")
    assert a["manifest_hash"] == b["manifest_hash"]


def test_manifest_copies_verdict_not_rederives(tmp_path):
    result = tmp_path / "res.json"
    result.write_text(json.dumps({"verdict": "NO-GO", "reasons": ["x"]}), encoding="utf-8")
    m = build_freeze_manifest(tmp_path, experiment_id="T", result_path=result,
                              code_paths=[], frozen_config={}, protocol={})
    assert m["verdict"] == "NO-GO"
    assert m["reasons"] == ["x"]


# ---------------------------------------------------------------------------
# 2. The OFFICIAL R1 freeze (if present)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not R1_MANIFEST.is_file(), reason="R1 freeze not present")
def test_r1_freeze_verifies_clean():
    manifest = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    v = verify_manifest(ROOT, manifest)
    assert v["ok"] is True, v["problems"]


@pytest.mark.skipif(not R1_MANIFEST.is_file(), reason="R1 freeze not present")
def test_r1_verdict_is_no_go_and_atr_retained():
    manifest = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["verdict"] == "NO-GO"
    # ATR baseline is frozen and recorded; adaptive did not replace it.
    assert "baseline_atr" in manifest["frozen_config"]
    assert manifest["frozen_config"]["baseline_atr"]["k_up"] == 1.5
    assert manifest["frozen_config"]["baseline_atr"]["k_dn"] == 1.0

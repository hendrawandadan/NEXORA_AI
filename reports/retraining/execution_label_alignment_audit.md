# PREP-001 Execution Label Alignment Audit (T1 vs T2)

Date: 2026-11-07
Scope: TASK B — **audit only.** This document does NOT decide timing. Per the standing rule, timing decisions
belong to the human and are still **NOT ratified** (`governance.present=false`, TIMING_READY=UNRESOLVED).

Ground truth re-verified from source: `nexora_vision/features.py`, `nexora_learning/pipeline.py`,
`nexora_evaluator/metrics.py`, dataset structure. No training. Read-only.

---

## 1. Definitions used in this audit

The label is constructed in `pipeline.prepare`:

```python
fwd[:-h] = close[h:] / close[:-h] - 1     # forward (gross) return over h bars
y        = (fwd > 0).astype(int)           # target
mask     = X.notna().all(axis=1) & isfinite(fwd)
```

So the label for the bar at index `t` uses `close[t]` and `close[t+h]`. Two candidate interpretations of "the
execution timestamp that the label is aligned to":

- **T1 (current proposal in `execution_timing_contract.md`)** — *decision at bar t close, execution at bar
  t+1 open.* The label `sign(close[t+h]/close[t]-1)` is treated as a **gross directional** signal measured from
  the bar that produced features (`t`), evaluated over the next `h` bars. Executing at `t+1 open` is a
  *separate, hypothetical* execution policy; it does not change the label.
- **T2 (label-aligned-to-fill)** — *the label's start price should be the actual executable price.* Under T2, the
  forward return would be recomputed from the **execution reference** (e.g. `open[t+1]`) rather than
  `close[t]`, i.e. `fwd_exec = sign(close[t+h]/open[t+1]-1)` or `sign(open[t+1+h]/open[t+1]-1)`.

These are **different label definitions**, not merely different execution clocks.

---

## 2. Label alignment matrix

Let `h = 2` (M30). Bars indexed `t`.

| Aspect | T1: label from `close[t]` (current) | T2: label from execution ref `open[t+1]` |
|---|---|---|
| label numerator ref | `close[t+h]/close[t]` | `close[t+h]/open[t+1]` (or `open[t+1+h]/open[t+1]`) |
| what the target measures | gross move over `[t, t+h]` from the **feature bar close** | gross move over `[t+1 open, t+h]` from the **fill price** |
| relationship to executed P&L | **not** the same window (misses the `close[t]→open[t+1]` gap) | closer to executed P&L window |
| leakage risk | none (label uses future only; features use ≤ t) — **PROVEN** | none if computed carefully, but label now depends on `open[t+1]` which is also "future" relative to t — must stay TRAIN-ONLY |
| consistency with `signals.csv` | `realized_forward_return = fwd[t]` matches label horizon `[t,t+h]` | would require changing `realized_forward_return` to the fill-based window |
| evaluation currently implemented | **yes** (`metrics` on `fwd[te]`) | **no** |
| requires a cost-aware backtest | no (gross) | no (still gross), but requires a fill price |

---

## 3. Alignment consequences (facts, not a decision)

1. **The current code implements T1 semantics.** `fwd` and `realized_forward_return` are built from
   `close[t]`. Nothing in the repo uses `open[t+1]` for the label. So adopting T2 would require a **code change**
   to `prepare()`/`train_one()` (label construction and the reported `realized_forward_return`), and would
   invalidate direct comparison with any T1 metrics.
2. **T1 keeps prediction and label on the same reference bar (`t`).** This is the cleanest for a *directional
   model*: `P(up over [t,t+h])`. It is internally consistent with how `signals.csv` reports
   `realized_forward_return`.
3. **T2 aligns the label to a fill price but introduces a "decision-to-fill" gap that the model cannot exploit
   unless features/decision clock are also redefined.** Under T2, `close[t]→open[t+1]` slippage/gap becomes part
   of neither the label (if using `open[t+1]`→`close[t+h]`) nor the features — it is silently dropped unless a
   cost model is added.
4. **Neither T1 nor T2 is "wrong"; they answer different questions.** T1 ≈ "will price be higher in `h` bars
   than at the feature-bar close?" T2 ≈ "if I fill at next open, will price be higher `h` bars later than my
   fill?"
5. **No leakage in either** *provided* the label stays future-only and mask excludes the last `h` rows. Current
   PROVEN no-look-ahead facts (`features.py` trailing-only; 11 purge tests) are independent of T1/T2 choice.

---

## 4. What the human must decide (NOT decided here)

The timing contract's `decision_timestamp` / `earliest_executable_timestamp` / `execution_price_model` fields are
**NEW_DESIGN**. This audit only surfaces the alignment question the user requested ("audit T1 vs T2"). The
decision points for ratification are:

- **D-timing-1:** Label reference for *training/evaluation*: keep `close[t]` (T1) or switch to fill-based
  (`open[t+1]`, T2)? Switching is a **code change** with comparison/story impact.
- **D-timing-2:** Decision clock (proposed bar t close).
- **D-timing-3:** Earliest executable (proposed bar t+1 open).
- **D-timing-4:** Execution price model (proposed bar t+1 open).
- **D-timing-5:** spread / slippage / cost usage (proposed feature-only / none / gross).

**Recommendation framing (not a decision):** keeping T1 for the *research label* while defining execution
timing (T2-style `open[t+1]`) purely inside a **future cost-aware backtest** avoids invalidating current
metrics and keeps the directional model semantics stable. Adopting T2 as the training label would require
re-running everything and documenting the change. **This recommendation requires human sign-off.**

---

## 5. Ratification state (unchanged)

- `execution_timing_contract.md` hash `f460fa9f…b0111f`, `ratified:false`, 6 NEW_DESIGN fields.
- `governance.present = false` (no `prep001_ratification.json`).
- TIMING_READY = **UNRESOLVED**; readiness = **BLOCKED**.
- This audit does not change any of the above. Timing remains pending human decision.

# Price-Derived Lane — Reopening Procedure (NEXORA-GOV-PRD-002)

**Current status: `SUSPENDED`.** This folder documents how reopening is *proposed and
ratified* — it does **not** reopen anything. The machine-enforced guard
(`nexora_laboratory/governance/lane_suspension.py`) keeps blocking
train / tune / promote / live / auto_reopen for as long as
`config/governance/price_derived_lane_suspension.json` says `SUSPENDED`.

> Authority (from the suspension file): *"explicit user decision only; no scheduler /
> autonomous agent / training runner may reopen."* Nothing in this flow is automatic.

## The chain (fail-closed at every step)

| Step | Artifact | Tool | Registry touched? |
|---|---|---|---|
| 1. Propose | `proposal*.json` | `tools/build_lane_reopening_proposal.py` | No |
| 2. Ratify | `ratification*.json` | `tools/ratify_lane_reopening.py` | No |
| 3. Apply (owner, `--write`) | updated registry + backup | `tools/apply_lane_reopening.py` | **Yes — only here** |

The helpers live in `nexora_laboratory/governance/lane_reopening.py`.

## Why a ratification keeps the lane SUSPENDED

`lane_reopening.assess_lifecycle()` reports a *stage*
(`SUSPENDED → REOPENING_PROPOSED → RATIFIED → REOPENED`). Reaching `RATIFIED` does
**not** flip `status`; `is_suspended()` still returns `True` and `assert_can("train")`
still raises. Only the owner-only `apply_lane_reopening.py --write` changes the
registry, and it:

1. requires `--i-am-the-owner-and-want-to-reopen-the-lane`,
2. verifies the HMAC on **both** proposal and ratification with `NEXORA_GOVERNANCE_KEY`,
3. requires `decision == APPROVED` and a matching `proposal_hash`,
4. re-validates the proposal against the registry conditions/procedure,
5. **backs up** the original registry (the backup is the preserved failure evidence),
6. atomically sets `status = REOPENED_WITH_AUTHORIZATION` and appends a `reopening`
   provenance block — it **never deletes** `suspended_candidates` or `background`.

## What a proposal MUST contain (enforced by `validate_proposal`)

- `decision_id == NEXORA-GOV-PRD-001`;
- at least one `conditions_satisfied` cited **verbatim** from the registry
  `reopening_conditions`;
- a non-empty `new_hypothesis` **and** `distinct_from_failed_hypothesis`;
- a `procedure_status` entry for **every** registry `reopening_procedure` step;
- `candidates_requested` ⊆ the registry `suspended_candidates` (e.g. `EURUSD H4 h12`,
  `XAUUSD H4 h12` … — **not** arbitrary timeframes).

## Owner quick-start (dry-run by default)

```powershell
# 1. Build a proposal (writes nothing to governance config)
python tools/build_lane_reopening_proposal.py `
    --approver "Your Name" --decided-at "2026-11-10T00:00:00Z" `
    --hypothesis-file reports/governance/reopening/NEW_HYPOTHESIS_PRD_002.md `
    --candidate EURUSD,H4,12 `
    --out reports/governance/reopening/proposal.DRAFT.json

# 2. Ratify it (binds to the proposal hash)
$env:NEXORA_GOVERNANCE_KEY = "<your signing key>"
python tools/ratify_lane_reopening.py `
    --proposal reports/governance/reopening/proposal.DRAFT.json `
    --approver "Your Name" --decided-at "2026-11-11T00:00:00Z" --decision APPROVED `
    --out reports/governance/reopening/ratification.DRAFT.json

# 3. Apply — DRY-RUN first (no files change)
python tools/apply_lane_reopening.py `
    --proposal reports/governance/reopening/proposal.DRAFT.json `
    --ratification reports/governance/reopening/ratification.DRAFT.json `
    --i-am-the-owner-and-want-to-reopen-the-lane

# 4. Apply for real (ONLY the owner; performs backup + atomic status change)
python tools/apply_lane_reopening.py `
    --proposal reports/governance/reopening/proposal.DRAFT.json `
    --ratification reports/governance/reopening/ratification.DRAFT.json `
    --write --i-am-the-owner-and-want-to-reopen-the-lane
```

## Even after reopening…

Training on a specific candidate still requires the **PREP-001** execution
authorization gate (`nexora_audit.authorization.authorize_execution` + a signed
sign-off). Reopening the *lane* removes the blanket suspension; it does **not**
authorize any particular training run, promotion, or live enablement.

## Files here

- `NEW_HYPOTHESIS_PRD_002.md` — the human-readable justification (conditions + pre-registered GO/NO-GO).
- `proposal.DRAFT.json` — generated unsigned DRAFT for review (owner must re-sign).
- `ratification.DRAFT.json` — (owner creates in step 2).

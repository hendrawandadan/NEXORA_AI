# PREP-001 Execution Authorization Gate (Implementation Report)

Date: 2026-11-08
Scope: Implement a **job-scoped, fail-closed** authorization gate that refuses to
dispatch, claim, retry, resume, or recover any PREP-001 job unless the execution
is fully bound to a human-ratified governance sign-off, the canonical config
hash, the versioned feature/target/split contracts, the ratified timing
contract, the selected experiment candidate, and a `READY_FOR_TRAINING`
readiness decision.

**No training was executed. No production DB / CSV / dataset / model / backup was
mutated. PLANNED was never flipped to QUEUED. No queue was created.**

---

## 1. What was added

| File | Change |
|---|---|
| `nexora_audit/authorization.py` | NEW. The single authorization funnel: `authorize_execution()`, `require_authorized()`, `verify_signoff_integrity()`, `assert_gate_precedes()`. |
| `nexora_audit/__init__.py` | Exports the authorization API. |
| `nexora_audit/cli.py` | New `authorize` command + `--execution-id` / `--batch` flags (review-only, read-only). |
| `batch1_execution_runner.py` | `RunnerConfig.authorization_root` + `enforce_authorization`; new `guard_execution_authorized()` called at the top of the dispatch path in `process_run()` (before any STARTED transition / training / validation / promotion). |
| `tests/test_execution_authorization.py` | NEW. 15 isolated tests (temp roots only; no production touch). |

---

## 2. The binding chain (all checks must pass — no "allow" default)

1. **Job-scoped** — exactly one `execution_id` may be authorized. Batch-wide /
   `--limit` substitute / multi-id dispatch is rejected (`MULTI_OR_UNSCOPED_DISPATCH`).
2. **Execution id** — must equal the bound `PREP-001`.
3. **Batch** — must equal `Batch 1`.
4. **Job identity** — row `(scope,symbol,timeframe,horizon)` must equal the
   canonical proposal identity (`individual, EURUSD, M30, 2`).
5. **Sign-off present / valid / ratified** — file must exist, be structurally
   valid **and** carry a *verified* integrity mechanism.
6. **Config hash** — signed canonical config hash == live proposal hash.
7. **Timing** — ratified timing hash == signed timing hash.
8. **Versions** — signed feature/target/split ids == frozen contract ids.
9. **Candidate** — sign-off candidate is `A|B|C` and matches the row.
10. **Readiness** — full gate set (CONFIG/DATASET/TIMING/RUNNER/RECOVERY) must
    resolve to `READY_FOR_TRAINING`.

---

## 3. Integrity: "valid JSON" is NOT authorization

The repository provides **no key management and no detached signature** for
`config/governance/prep001_ratification.json`. The gate makes this explicit:

* `verify_signoff_integrity()` supports an optional `integrity` block with
  `mechanism: "hmac-sha256"` verified against the `NEXORA_GOVERNANCE_KEY`
  environment variable (never committed).
* A structurally valid but unsigned/unverifiable sign-off is reported as
  `status = UNVERIFIED` (or `INVALID` on a bad signature) and is **rejected** —
  it does **not** silently authorize.

This is the central safety property: a file that merely parses can never unlock
execution.

---

## 4. Residual blockers (explicitly NOT resolved here)

These are real gaps that a human decision or key-management step must close;
the gate refuses to pretend they are solved:

1. **No cryptographic sign-off mechanism exists in-repo.** Until a signing
   workflow (detached signature or HMAC with managed key) is adopted, the only
   path to authorization is an HMAC-signed sign-off with `NEXORA_GOVERNANCE_KEY`
   provisioned out-of-band. Without it, every run stays BLOCKED.
2. **No real ratification content.** `prep001_ratification.json` does not exist
   in the repo (only a `TEMPLATE`). Absent a signed file the gate blocks.
3. **The binding hashes are only as trustworthy as the signed payload.** If a
   valid sign-off omits `config_hash`/`timing_contract_hash`/version ids, those
   bindings fail-closed (by design).
4. **Dry-run is intentionally exempt.** `--dry-run` / no `--execute` returns
   before the gate and never mutates anything; that is unchanged. The gate binds
   *real dispatch only*.

---

## 5. Runner wiring detail

`process_run()` ordering (unchanged for dry-run/terminal states):

```
PROMOTED -> SKIP, FAILED -> BLOCKED, dry_run -> DRY_RUN_<cp>
   -> guard_execution_authorized(row, cfg)   # <-- gate, fail-closed
   -> QUEUED/RETRY_PENDING -> STARTED -> train -> validate -> promote
```

`guard_execution_authorized()` delegates to `authorize_execution()` +
`require_authorized()`. Any failed check raises `AuthorizationError` **before**
the STARTED transition, so no checkpoint is written and no training is invoked.

The isolated dummy self-test suite (`--self-test`) sets
`enforce_authorization=False` because it uses a fake train pipeline and dummy
artifacts and never touches the real dataset/model/backup; it exercises
log-locking, not real dispatch.

---

## 6. Verification

* New tests: `tests/test_execution_authorization.py` — **15 passed**.
  Covers: full-binding PASS, absent sign-off, unsigned sign-off, wrong execution
  id, wrong batch, config-hash mismatch, timing unratified, wrong candidate,
  unscoped dispatch, multi-id dispatch, readiness blocked, HMAC `INVALID`,
  missing key `UNVERIFIED`, runner refuses without ratification, runner refuses
  when unscoped.
* Full suite: **185 passed** (was 170; +15 new), 37 warnings, 0 failures.
* `python -m nexora_audit readiness` -> decision `BLOCKED`
  (CONFIG_READY=FAIL, TIMING_READY=UNRESOLVED) — unchanged and correct.
* `python -m nexora_audit authorize --execution-id PREP-001` -> `authorized:false`
  on the real project (no signed sign-off) — correct fail-closed behavior.

---

## 7. Status

* Job-scoped authorization gate: **IMPLEMENTED and fail-closed.**
* Cryptographic sign-off: **NOT YET PROVISIONED** (residual blocker; requires
  key management + a signed `prep001_ratification.json`).
* Production dispatch: **STILL BLOCKED** until a verified sign-off and a
  `READY_FOR_TRAINING` readiness decision both exist.

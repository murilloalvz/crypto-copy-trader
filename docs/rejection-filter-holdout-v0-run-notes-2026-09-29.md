# Rejection Filter Holdout V0 — Run Notes — 2026-09-29

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

## Freeze record

- Protocol: `docs/rejection-filter-prospective-holdout-v0-preregistration-2026-09-29.md`
- Freeze commit: `7384c9411531d0fdeb5256829d73f06c133c6ceb` on `research/exit-hypothesis-bankroll-sim-v0`
- File SHA-256 at freeze: `f7c9a10e2fcd43e1dc5f05f2a0db4186c0fd4b1ea43f71954c3209add938961c`
- Frozen at the owner's explicit request. This run-notes file was committed after the freeze commit.
  Any later change to the protocol file voids the preregistration for the affected runs.

## Run key reservation

Base: `rejection-filter-v0-20260929-01`

| Cohort | Run key | Status |
|---|---|---|
| F1 | `rejection-filter-v0-20260929-01-F1` | RESERVED, not started |
| F2 | `rejection-filter-v0-20260929-01-F2` | not reserved for use yet |
| F3 | `rejection-filter-v0-20260929-01-F3` | not reserved for use yet |
| F4 | `rejection-filter-v0-20260929-01-F4` | not reserved for use yet |

"Reserved" is only a name. No database row, provider call or acquisition exists for it. The key must
be unused when acquisition starts (fresh-run preflight: zero decisions/outcomes under it). If F1 is
started and fails technically, the classification is INCONCLUSIVE and the failed key is not reused.

## What is NOT ready

- Runner: `rejection_filter_holdout_v0_collect.py` (added after the freeze; it is not part of the
  frozen protocol file and changes none of its parameters). It acquires ONE cohort per invocation
  with the frozen parameters as constants, verifies the protocol SHA-256 first, requires a fresh run
  key, enforces F1 -> F4 order, and computes no verdict. Not yet run live; reviewed only by offline
  tests with stubbed providers.
- Acquisition needs live providers (Jupiter, RPC, WSS) and the owner's database, which are not
  available in this cloud session. This session did not and will not start acquisition.
- Analysis: `rejection_filter_holdout_v0_analyze.py` implements only the frozen gates. It refuses to
  run (no interim or partial analysis) until F1..F4 all have a PASS acquisition report carrying the
  frozen protocol hash. Tested on synthetic data only; no F1 result exists.
  Interpretation used for gate 4 ("KEPT between 30% and 85% of classified episodes"): classified
  = known impact and no hard exclusion, counted before requiring a 900s outcome. This reading
  is documented in the script and was CONFIRMED by the owner on 2026-09-29, before any F1 data
  existed. This is a clarification recorded here; the frozen protocol file is unchanged.

## Scientific state

Untouched: V48 FAIL/CLOSED; V55 COMPLETE/CLEAN, burned for V68 validation; V68 NOT_EVALUATED;
Native Participant Quality V1 `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`.
This protocol releases no funded BUY, shadow execution or live money.

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

## F1 technical outcome (recorded 2026-09-29; no return values read)

- Runner classification: `PASS_REJECTION_FILTER_HOLDOUT_V0_ACQUISITION` (bridge PASS, 39 decisions,
  117 scheduled = 3 x 39, exact three horizons, forward 300/900 collector completed).
- 300s: 36 AVAILABLE, 3 PROVIDER_ERROR (2 x HTTP 400 "Failed to get quotes", 1 x HTTP 429). Lateness p95 1s.
- 900s: 10 AVAILABLE, 29 PROVIDER_ERROR (27 x HTTP 429 "[API Gateway] Too many requests",
  2 x HTTP 400 "Failed to get quotes"). 9 of the 10 AVAILABLE were collected ~1005-1024s late.
- Timeline (UTC `updated_at`): first 900s outcome on time at 21:06:49; then no writes until
  21:23:53, when the remaining 38 due outcomes were requested within ~8s and 27 hit the Jupiter
  rate limit. Interpretation: the collector process stalled ~17 minutes (cause on the owner's
  machine not yet identified: console QuickEdit pause, OS sleep or similar), and the backlog burst
  then exceeded the Jupiter gateway rate limit.
- Rule-input coverage (entry price impact known): 39/39. Support counts (no returns):
  REJECTED 21 episodes / 6 with 900s AVAILABLE; KEPT 18 episodes / 4 with 900s AVAILABLE.
- Consequence under the frozen protocol: support gate "REJECTED and KEPT >= 5 paired in every
  cohort" cannot pass for F1 (KEPT = 4). PROVIDER_ERROR is a terminal status and is never
  converted or retried. The frozen analysis will therefore end
  `INCONCLUSIVE_REJECTION_FILTER_V0_SUPPORT` whatever F2..F4 show.
- F1 return values have NOT been read or analyzed. No verdict exists.
- The frozen protocol has no replacement mechanism for a technically degraded cohort and no lateness
  cap; it is not amended here. Options for the owner are a decision, not recorded as taken.

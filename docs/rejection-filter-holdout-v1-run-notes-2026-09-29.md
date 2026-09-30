# Rejection Filter Holdout V1 — Run Notes — 2026-09-29

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

## Freeze record

- Protocol: `docs/rejection-filter-prospective-holdout-v1-preregistration-2026-09-29.md`
- Freeze commit: `6132363e65143d6e308548240a81807f9b310067` on `research/exit-hypothesis-bankroll-sim-v0` (owner-authorized, 2026-09-29)
- File SHA-256 at freeze (CRLF-normalized): `b2fc2ae9861cbcf5bfdef26cbc1bafe72e71250cf9127ca6f641d479ff31a568`
- The SHA-256 was recorded in `rejection_filter_holdout_v1_collect.py` (`PROTOCOL_SHA256`) in a commit
  AFTER the freeze commit, as the protocol's freeze procedure requires. Any later edit of the
  protocol file voids the preregistration for affected runs.

## Run keys

Base: `rejection-filter-v1-20260929-01`

| Cohort | Run key | Status |
|---|---|---|
| G1..G4 | `rejection-filter-v1-20260929-01-G1` .. `-G4` | not started |
| G5, G6 | `...-G5`, `...-G6` | reserved replacements for DEGRADED cohorts only |

The runner picks the next label itself; no cohort argument exists. Names are reservations only: no
database row, provider call or acquisition exists for any of them.

## Not started

- No V1 acquisition has been run. Running is the owner's decision on the owner's machine.
- Before running: fresh bootstrap (< 24h), `.env` with RPC and Jupiter key, `.venv` Python with
  python-dotenv, database backup, QuickEdit disabled in the console (the runner also guards it),
  no other SQLite writers.

## Scientific state

V0 closed `INCONCLUSIVE_REJECTION_FILTER_V0_SUPPORT` (F1 technically degraded; no return value read,
no verdict). V0 F1 return values must not be read or analyzed before the V1 verdict. Untouched:
V48 FAIL/CLOSED; V55 COMPLETE/CLEAN and burned for V68 validation; V68 NOT_EVALUATED; Native Participant
Quality V1 `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`. This protocol releases no funded
BUY, shadow execution or live money.

## Result recorded 2026-09-30

G1..G4 acquired VALID with no replacement; frozen-gate analysis returned
`KEEP_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE`. Details and limits:
`docs/rejection-filter-prospective-holdout-v1-result-2026-09-30.md`. KEEP authorizes only a separately
preregistered independent replication; the KEPT group is not profitable in route-only terms.

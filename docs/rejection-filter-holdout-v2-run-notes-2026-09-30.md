# Rejection Filter Holdout V2 (Replication) — Run Notes — 2026-09-30

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

## Freeze record

- Protocol: `docs/rejection-filter-prospective-holdout-v2-replication-preregistration-2026-09-30.md`
- Freeze commit: `6e1c81457f1098cb69d99d08ec6c9f3e686152d5` on `research/exit-hypothesis-bankroll-sim-v0` (owner-authorized, 2026-09-30)
- File SHA-256 at freeze (CRLF-normalized): `c775a1a38d056ab356f4128f8c6fddf5b61940ebf7f8bca7369f5482dba905a3`
- The SHA-256 was recorded in `rejection_filter_holdout_v2_collect.py` (`PROTOCOL_SHA256`) in a commit AFTER
  the freeze commit, as the freeze procedure requires. Any later edit of the protocol file voids the
  preregistration for affected runs.

## Run keys

Base: `rejection-filter-v2-20260930-01`. Cohorts `-H1`..`-H5`; `-H6`, `-H7` are reserved replacements for
technically DEGRADED cohorts only. The runner picks the next label itself. Names are reservations only: no
database row, provider call or acquisition exists for any of them.

## Collection rules (enforced by the runner before any data is created)

- Never on 2026-09-29 or 2026-09-30 (UTC): those are the V1 collection days.
- At most three cohorts started per UTC day; valid cohorts must span at least two UTC days.
- Before running: fresh bootstrap (<= 24h), `.env` with dedicated RPC and Jupiter key, `.venv` Python with
  python-dotenv, database backup, QuickEdit disabled (the runner also guards it), no other SQLite writers.

## Not started

No V2 acquisition has been run. Running is the owner's decision on the owner's machine.

## Scientific state

V1: `KEEP_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE` (tail-risk candidate only; KEPT group not profitable
route-only). V0 closed `INCONCLUSIVE` (F1 return values unread). Untouched: V48 FAIL/CLOSED; V55
COMPLETE/CLEAN and burned for V68 validation; V68 NOT_EVALUATED; Native Participant Quality V1
`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`. This protocol releases no funded BUY, shadow
execution or live money.

## Infrastructure note: RPC provider change (recorded 2026-09-30, before any V2 acquisition)

- V1 acquisitions (G1..G4) ran with the RPC configured at the time (effective host observed at the time of
  the G1 pre-run check: `solana-mainnet.g.alchemy.com`); the identity bootstraps already used
  `mainnet.helius-rpc.com`.
- For V2 the owner intentionally switched the primary RPC to `mainnet.helius-rpc.com` (dry-run check on
  2026-09-30: `rpc host: mainnet.helius-rpc.com`, Jupiter key set).
- This is an operational infrastructure difference, not a frozen protocol parameter. It touches token
  authority reads (hazard evidence) and RPC latency, and is disclosed so that any V1-vs-V2 difference can be
  read with it in mind. It changes no rule, gate, label or threshold, and the protocol file is untouched.
- Cohort-level acquisition quality is still judged only by the frozen criteria (on-time label, technical
  share <= 20%); no result may be attributed to the provider without evidence.

## Result recorded 2026-10-02

H1..H5 acquired VALID with no replacement (UTC days 2026-10-01 and 2026-10-02); frozen-gate analysis returned
`REPLICATED_REJECTION_FILTER_V2_TAIL_RISK`. Details and limits:
`docs/rejection-filter-prospective-holdout-v2-result-2026-10-02.md`. REPLICATED authorizes only the filter as a
research precondition and a separately preregistered selection study conditional on KEPT; it is not edge.

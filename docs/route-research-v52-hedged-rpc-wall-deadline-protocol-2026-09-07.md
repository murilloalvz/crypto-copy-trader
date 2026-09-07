# Route Research v52 — PumpSwap hedged RPC wall-deadline protocol

Date: 2026-09-07
Branch: `feat/exit-engine-v1`
Mode: **PAPER / RESEARCH / READ ONLY**

## Why v52 exists

The live v51 systems-only run failed the unchanged same-run systems gate at 10/11:

- Pump p95: 1.577s — PASS
- PumpSwap p95: 7.658s — FAIL
- global prefix normalization barrier p95: 7.655s
- self normalization max: 10.497s
- v41 parallel hydration service p95: 4.353s, max: 6.981s
- configured PumpSwap RPC timeout: 3s
- no worker errors, drops, hydration-budget skips or reservation-superset violations
- no forward economic collector

v51's stateful-ready priority was active and reduced the earlier v50c downstream ready-queue problem. The remaining live failure was upstream in unknown-pool identity hydration/global reservation ordering.

## Safety investigation before amendment

### Rejected: pool-only conflict domains

The causal scheduler conflicts on canonical opportunity `token_mint`, not pool address. The repository does not prove `token_mint -> exactly one PumpSwap pool`. Therefore two distinct pools may still normalize to the same opportunity token. Replacing token-level ordering with per-pool FIFO could let a later same-token notification overtake an earlier one and is rejected.

### Deferred: causal-availability watermark redesign

The persistence model has a defensible causal-availability concept: a network-hydrated trade uses

`effective_observed_at = max(notification.observed_at, mapping.observed_at)`.

The radar also reads only observations with `observed_at <= token_as_of`, and the episode store rejects retroactive overlapping enrollment. This suggests the raw global ingress watermark may be more conservative than strictly necessary.

However, replacing it safely requires additional machinery for equal-second ties, historical mapping reuse, multi-pool/multi-asset notifications and transaction-wide cycle freedom. v52 does **not** make that scheduling change.

## Measured implementation gap

v33/v41 call each hedge endpoint with the configured `SolanaClient.timeout` and `max_attempts=1`, but the hedge coordinator itself has no wall-clock deadline. `SolanaClient.call` may perform a TLS-1.2 fallback transport after an SSL failure even inside one logical attempt. A failed first hedge plus a slow/fallback second hedge can therefore keep one batch alive materially longer than the configured 3s RPC timeout.

That extended external wait is enough for one sequence hole to block many already-normalized successors through the unchanged global reservation watermark.

## v52 amendment

v52 changes **only the wall-clock acceptance window of one hedged unknown-pool batch**.

Frozen rule:

- overall hedge wall deadline = the already configured PumpSwap `rpc_timeout_seconds` / `client.timeout`;
- no new numeric tuning parameter is introduced;
- all configured hedge endpoints still start concurrently;
- the first valid response that arrives inside the wall deadline wins;
- endpoint errors remain explicit;
- if no valid response arrives before the wall deadline, the existing resolver failure/unresolved path is used;
- no retry or later backfill is added;
- late endpoint completion is not accepted as evidence for the already-timed-out notification;
- existing negative-cache, hydration-budget and single-flight semantics remain in force.

This makes the declared RPC timeout a true end-to-end wall bound for the hedge instead of merely a per-transport timeout.

## What v52 does NOT change

v52 does not change:

- Pump/PumpSwap websocket ingestion;
- detector thresholds/version;
- transaction parsing;
- pool mapping identity/replay rules;
- mapping `observed_at` semantics;
- global reservation order;
- per-asset FIFO;
- v51 stateful-ready priority;
- SQLite persistence/replay;
- episode assignment/no-retroactive-enrollment;
- wallet/flow/hazard feature definitions;
- provider pacing;
- route-only notional/slippage/horizons;
- Flow60 bins, horizon, support gate or PASS rule;
- 120s systems deadline;
- 5s Pump/PumpSwap systems gate;
- forward SELL collection.

## Missingness / comparability note

A batch that does not produce a valid identity inside the already-configured 3s timeout becomes explicitly unresolved for that notification. This can reduce observed PumpSwap coverage relative to accepting a transport result after the declared timeout. Missingness must remain visible in `unresolved_pumpswap_trades`, resolver failure counters and coverage/backlog metrics.

The change is treated as enforcement of the pre-existing provider timeout contract, not an economic filter. It must not be selected or tuned from Flow60/P&L outcomes.

## Diagnostics

v52 must print at least:

- `hedge_wall_deadline_seconds`
- `hedge_wall_deadline_expirations`
- `hedge_fetch_ms` p50/p95/max
- inherited hedged calls / endpoint requests / all-failed counts
- inherited v41 batch service diagnostics
- v50 causal-clock diagnostics
- v51 stateful/demoted ready-lane diagnostics
- unchanged v43 11-gate result

## Unit/regression requirements before live

Tests must prove:

1. a valid fast hedge still wins immediately;
2. a fast failure plus a hung peer returns by the configured overall wall deadline rather than waiting for the hung peer;
3. no valid response before deadline yields explicit `SolanaRPCError` to every batch item;
4. a valid response inside the deadline is accepted;
5. endpoint calls remain `max_attempts=1`;
6. the v52 resolver remains a drop-in v41 resolver and does not increase `max_concurrent_resolutions`;
7. the v52 smoke installs/restores the resolver patch;
8. v51 scheduler semantics/tests remain unchanged;
9. Flow60/economic evaluator code is untouched.

## Live gate

Use one fresh systems-only run key after CI.

A v52 systems PASS requires the unchanged v43 same-run result **11/11**, no forward collector, v52 diagnostic present and no scheduler/resolver fatal error.

v50 exact trace completeness is diagnostic evidence and remains separate from the systems verdict; a frozen-deadline partial trace must not overwrite the independent 11/11 or 10/11 systems result.

If v52 passes, stop latency tuning and wire the validated systems profile into the frozen v48 acquisition path with regression tests before any prospective economic collection.

If v52 fails, do not relax the 5s gate and do not reroll blindly. Use the same-run v50/v51/v52 clocks to decide whether the remaining problem truly requires the deferred causal-availability watermark redesign.

# Wallet Forward Network Resilience — 2026-09-02

Status: IMPLEMENTED + TESTED. PAPER / RESEARCH / READ ONLY.

## Incident that motivated the patch

Long enrollment-aware forward run:

- run key: `wallet-forward-1788316945-b4981e16`
- runtime: `wallet_forward_runtime_v5_enrollment_followup_rotating_poll_confirmed_commitment`
- cohort: 3 wallets
- polling: 10 s
- RPC commitment: `confirmed`
- planned protocol: 4 h economic enrollment + 6 h observational follow-up
- Jupiter quote delays: 0/15/30/60/120 s
- copy notional: USDC 25
- planned duration: 10 h
- observed duration before abort: approximately 8 h 54 m 19 s
- enrollment completed: 4 h / 4 h
- observed follow-up: approximately 4 h 54 m 19 s / 6 h
- final status: `ABORTED`
- baseline observation id: 31
- enrollment cutoff observation id: 31
- end observation id: 31
- economic BUY enrollments: 0

The run therefore contains no new economic sample and must not be used to infer P&L, slippage, copyability edge or profitability. It remains valid engineering evidence about the collector and run-boundary behavior.

## Failure sequence

At the end of the run the local machine lost network connectivity. Both configured RPC paths initially failed with DNS resolution errors (`getaddrinfo failed`). Those failures were normalized into `SolanaRPCError`, so `wallet_watch_forward.py` continued polling as designed.

A later request raised raw `http.client.RemoteDisconnected: Remote end closed connection without response`. That exception escaped the RPC transport boundary, terminated `wallet_watch_forward.py`, and caused `wallet_forward_experiment.py` to stop the quote watcher and finalize the manifest as `ABORTED`.

Stopping the quote watcher on a fatal forward-watcher failure was correct and prevented creation of a misaligned quote cohort.

## Confirmed root cause

The generic `SolanaClient.call()` already has a retry/fallback policy for urllib transport failures such as `URLError`, but `RemoteDisconnected` can surface as a `ConnectionError` without being wrapped by urllib on every path.

`WalletForwardSolanaClient` now normalizes `ConnectionError` raised by `_read_payload()` into `URLError`. This keeps abrupt TCP disconnects inside the existing bounded retry/fallback path while deliberately avoiding a broad `except Exception` that could hide programming bugs.

Expected behavior after the patch:

1. transient disconnect -> retry current endpoint;
2. exhausted endpoint -> try configured fallback;
3. all endpoints unavailable -> raise `SolanaRPCError`;
4. forward watcher records that polling failure and remains alive;
5. later successful sync records recovery and collection continues.

## RPC degradation audit trail

A new SQLite table, `wallet_forward_rpc_health_events`, records run-scoped network health events:

- `run_key`
- `observed_at`
- `wallet_address`
- `phase` (`bootstrap` or `poll`)
- `status` (`FAILURE` or `RECOVERED`)
- recovered RPC endpoint when applicable
- error type and error message for failures

`wallet_watch_forward.py` also prints UTC timestamps on RPC failures and recoveries. This makes a future connectivity gap auditable rather than allowing a run that reached its nominal deadline to look observationally perfect.

The health telemetry is descriptive. It does not fabricate observations, fill missing chain data, or automatically turn a degraded run into valid economic evidence.

## Tests

GitHub Actions validated the integrated patch on Python 3.11 / Ubuntu 24.04:

- Python compilation: PASS
- complete unit-test suite: PASS
- 428 tests run
- result: `OK`

Specific new coverage includes:

- retry after `RemoteDisconnected`;
- fallback after primary disconnect;
- total endpoint disconnect -> `SolanaRPCError`, not raw `RemoteDisconnected`;
- persistence and ordering of RPC `FAILURE` / `RECOVERED` events;
- run-key isolation of RPC health telemetry;
- direct wallet-watcher loop validation: a poll fails with `SolanaRPCError`, the failure is recorded, a later poll recovers, recovery is recorded, and the process completes normally instead of crashing.

The direct loop test produced the expected sequence in CI: one RPC failure, one recovery, two cycles, return code 0, and the full suite remained green.

## Integrated repository state

The patch was developed on `fix/wallet-forward-network-resilience` from `aad893f1d1c6e7f2c1278b68010924368c282831` and then fast-forwarded into `feat/exit-engine-v1` after CI passed.

Core integration head:

`cf86ef9f8e74791e3c338d881e1ac8c267ebbbeb`

The integration was a non-forced fast-forward. Additional documentation and direct-loop regression coverage were then committed directly on `feat/exit-engine-v1`.

Latest validated code/test head before this documentation refresh:

`4b6654ed7c5f3202661245b3b54a67dc696b4cd0`

## Methodological interpretation

The aborted 10 h run must remain `ABORTED` and must not be resumed across the network gap.

What it did validate:

- manifest isolation;
- causal baseline creation;
- 4 h enrollment cutoff execution with an empty enrollment set;
- no economic enrollment after the cutoff;
- quote watcher shutdown on fatal forward-watcher failure;
- ABORTED finalization rather than false COMPLETED status.

What it did not validate:

- enrollment-aware behavior with a real enrolled BUY;
- complete 6 h follow-up;
- Jupiter quote latency/drift economics for this run;
- P&L, slippage or profitability.

The zero-enrollment result is a separate experimental-design issue from network resilience. The 3-wallet cohort can be bursty, so cohort size / enrollment-window adequacy must be assessed without selecting wallets based on future activity.

## Next validation gate

Do not start another long 10 h collection immediately.

First run a short local resilience validation after syncing `feat/exit-engine-v1`:

- target: 15–30 minutes;
- use the same RPC-forward collector path;
- intentionally interrupt local connectivity briefly and restore it;
- success requires no raw `RemoteDisconnected` traceback, the watcher remaining alive, at least one persisted `FAILURE` event, a later `RECOVERED` event, and normal continuation after recovery.

Only after this gate passes should another long enrollment/follow-up run be considered. The enrollment `n=0` design question should then be handled separately and predeclared before the next economic collection.

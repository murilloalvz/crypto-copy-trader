# Rust Signal Plane Live Shadow V1 — Async PumpSwap Identity Plane

Status: **systems-only shadow; no economic verdict; V68 remains frozen**.

## Motivation

Live Shadow V0 proved:

- Rust/Python Radar parity = 100% on live traffic;
- Rust materially lowers Signal Plane latency;
- no PumpSwap trade was missing after a causally observed live CreatePool identity;
- most PumpSwap MISSING_CONTEXT rows came from pools without identity available at event T0.

V1 tests whether unknown PumpSwap pool identities can be resolved asynchronously outside the
Signal Plane hot path so that only **future** trades become usable.

## Frozen path

```text
Solana logsSubscribe (confirmed)
  -> frozen Carbon streaming decoder
  -> causal canonical Pump / PumpSwap adapters
  -> Rust + Python indexed Radar in parallel

Unknown PumpSwap pool
  -> enqueue once
  -> async getMultipleAccounts on configured primary SOLANA_RPC_URL
  -> decode PumpSwap Pool account
  -> in-memory causal identity cache
  -> usable only for events received at/after RPC response wall time
```

## Causal safety

The trade that triggers an unknown-pool lookup remains MISSING.

There is no retrospective backfill.

An async RPC identity receives `observed_wall_ns` only after the RPC response is locally
available. The existing `identities_available_before_v0` gate decides whether a later event
may use it.

CreatePool identity remains preferred naturally by evidence time when available.

No SQLite write, research snapshot, Jupiter call, outcome work, or real-money execution is added
to the Signal Plane hot path.

## Provider discipline

Identity resolution uses only the configured primary `SOLANA_RPC_URL` for this experiment.
No silent fallback provider is allowed.

RPC commitment is `confirmed`.

Batch size is fixed at 64 pools, below Solana getMultipleAccounts' 100-account request limit.

Each unknown pool is enqueued at most once per run unless queue admission itself fails.

## V1 evaluation

The existing live parity/systems gates remain required:

1. Pump/PumpSwap subscriptions active;
2. live events observed;
3. canonical events decoded;
4. adapted trades reach both kernels;
5. trade decision points observed;
6. Python/Rust trigger parity exactly 100%;
7. zero decode failures;
8. zero fatal or signal-worker errors;
9. at least one unknown pool is enqueued;
10. at least one async RPC pool request is attempted;
11. at least one causal pool identity is resolved;
12. zero Identity Plane queue overflow;
13. zero async RPC batch failure.

V1 additionally reports, without retrospective threshold tuning:

- async pools enqueued;
- requested pools;
- resolved identities;
- RPC failures;
- account/decode/owner failures;
- async-identity adapted trade count;
- remaining MISSING_CONTEXT count;
- unique pools adapted/missing;
- Identity Plane queue high-water/depth.

A V1 systems PASS does not by itself establish economic edge. The operational question is whether
coverage improves while Rust/Python parity and low hot-path latency remain intact.

## Prohibited interpretation

Do not use this run to:

- authorize V68;
- modify V68 Flow60 bins or thresholds;
- modify Participant Quality;
- backfill old missing trades;
- retry runs until a preferred coverage number appears;
- claim profitable edge from systems coverage alone.

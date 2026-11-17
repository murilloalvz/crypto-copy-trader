# Rust Signal Plane Live Shadow V0 — Frozen Systems Protocol

Status: **systems-only shadow; no economic verdict; V68 remains frozen**.

## Purpose

Test whether the Rust indexed Signal Plane preserves the Python indexed Radar on the
same live canonical market observations while removing persistence, RPC enrichment,
audit, Jupiter and outcome work from the hot path.

This protocol does **not** test or alter economic edge. It tests operational latency
and semantic parity only.

## Frozen path

```text
Solana standard logsSubscribe (confirmed)
  -> frozen Carbon streaming decoder
  -> causal canonical Pump / PumpSwap adapters
  -> same MarketTradeObservation / MarketLifecycleObservation
      -> Python IndexedWindowRadarState
      -> Rust indexed stream worker
```

Both paths receive the same canonical observation and sequence.

## External state

- PumpSwap identity bootstrap must already be a real PASS.
- Bootstrap identities must predate shadow start.
- CreatePool identities learned during the shadow may be used from their exact local
  receive time forward.
- No synchronous pool RPC hydration is allowed in the Signal Plane.
- Missing causal PumpSwap identity remains MISSING; there is no retrospective backfill.

## Provider / timing

- Provider is the configured `SOLANA_RPC_URL`, converted to its supported WebSocket
  endpoint by the existing provider mapping.
- Commitment is frozen to `confirmed`.
- Default duration: 120 seconds.
- Default max notifications: unlimited within the duration.
- This is operational coverage only; no chain-complete coverage claim is made.

## Frozen PASS gates

PASS requires all of the following:

1. Pump and PumpSwap subscriptions both acknowledge successfully.
2. At least one Pump log notification is observed.
3. At least one PumpSwap log notification is observed.
4. At least one Carbon canonical event is decoded.
5. At least one causal adapted trade reaches both Signal Planes.
6. At least one trade decision point is compared.
7. Python vs Rust trigger/features parity is exactly 100% with zero mismatches.
8. Carbon decode failures are zero.
9. No fatal process, stream, or signal-worker errors occur.

The following are reported but are not allowed to rescue a failed semantic gate:

- Rust speed;
- Python speed;
- source->signal latency;
- canonical->signal latency;
- PumpSwap missing-context count;
- notification volume.

## Interpretation

A PASS only makes Rust eligible for further systems shadow / integration work.

It does **not**:

- authorize V68;
- establish profitable edge;
- modify Participant Quality;
- modify Flow60 Buy-Share V68;
- modify any economic threshold;
- authorize real-money execution.

The operational-edge question after PASS is whether the same causal trigger can be
made available materially earlier under real load, without drops or semantic drift.

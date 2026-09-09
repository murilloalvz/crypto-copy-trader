# Helius Standard WSS Shadow v0

Research-only operational shadow acquisition using Helius Free Standard WebSockets.

## What it does

- opens the standard mainnet WSS endpoint using `HELIUS_API_KEY` from the environment;
- subscribes to Pump logs, PumpSwap logs, and slot liveness;
- uses `processed` commitment for earliest-observation research;
- records raw log arrays, signature, slot, local receive time, subscription ACKs, session transitions, reconnect errors, and slot notifications;
- keeps failed-transaction log notifications instead of silently discarding them;
- uses protocol ping/pong through the `websockets` client;
- never calls `getTransaction` in the live collector.

## Critical coverage semantics

This trace is **not chain-complete coverage evidence**.

Every header/session/footer explicitly records:

```text
coverage_classification = operational_only_not_chain_complete
chain_complete_coverage_claimed = false
```

An active Standard WSS connection therefore MUST NOT be converted into
`MarketCoverageInterval(coverage_kind="continuous_observed")` and MUST NOT turn empty
seconds into numeric zero for the coverage-aware Page-Hinkley experiment.

The trace is useful for:

- actually observed events;
- first local observation timestamps;
- connection/reconnect behavior;
- operational slot liveness;
- downstream decoder experiments;
- later reconciliation against historical chain truth.

## Install

From the repository root:

```powershell
python -m pip install -r benchmarks\helius_standard_wss_shadow_v0\requirements.txt
```

Keep the key in the environment only:

```powershell
$env:HELIUS_API_KEY = "<YOUR_KEY>"
```

The collector redacts the key from transport errors and never writes the endpoint query
string into the trace.

## 60-second smoke

```powershell
python -m benchmarks.helius_standard_wss_shadow_v0.collect `
  --out "artifacts\helius_standard_wss_shadow_v0\shadow-60s.jsonl" `
  --duration-seconds 60 `
  --max-log-notifications 1000
```

A successful operational smoke ends with a footer containing:

```text
valid_operational_shadow = true
valid_chain_complete_coverage = false
```

The second value being false is intentional.

## Longer research shadow

```powershell
python -m benchmarks.helius_standard_wss_shadow_v0.collect `
  --out "artifacts\helius_standard_wss_shadow_v0\shadow-30m.jsonl" `
  --duration-seconds 1800 `
  --max-log-notifications 20000
```

Do not start a long run until the 60-second smoke has been inspected.

## Next scientific gate

Reduce the raw WSS log arrays through the existing contextual Pump/PumpSwap log-stack
parser, decode target events with the pinned Carbon decoders, and reconcile a run window
against historical chain truth. Only empirical recall plus a stronger delivery contract
could justify promoting operational WSS liveness into any completeness-grade coverage.

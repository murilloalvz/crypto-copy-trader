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
- reconciliation against finalized chain truth.

## Clock-domain rule

`received_wall_ns` / derived `observed_at` is the local evidence-availability clock.
Carbon event `timestamp` / `chain_time` is the Solana market-time clock. They are not
assumed synchronized and MUST NOT be ordered against each other or subtracted to claim
latency without an explicit calibration method.

Local time decides whether evidence was available by a decision T0. Chain time decides
which on-chain market window an already-available event belongs to.

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

## Short smoke

Use a duration large enough to inspect behavior, but remember the event cap may stop the
run before the requested wall duration. Always trust the collector footer's actual
elapsed time rather than the filename.

```powershell
python -m benchmarks.helius_standard_wss_shadow_v0.collect `
  --out "artifacts\helius_standard_wss_shadow_v0\shadow-60s.jsonl" `
  --duration-seconds 60 `
  --max-log-notifications 10000
```

A successful operational smoke ends with:

```text
valid_operational_shadow = true
valid_chain_complete_coverage = false
```

The second value being false is intentional.

## Reducer + Carbon + adapter audit

```powershell
python -m benchmarks.helius_standard_wss_shadow_v0.reduce `
  --in "artifacts\helius_standard_wss_shadow_v0\shadow-60s.jsonl" `
  --carbon-input "artifacts\helius_standard_wss_shadow_v0\shadow-60s-carbon-input.jsonl" `
  --manifest "artifacts\helius_standard_wss_shadow_v0\shadow-60s-manifest.jsonl"
```

Decode the reducer output with the pinned Carbon runner, then audit the Carbon output
through the protocol/matched-unit adapters. PumpSwap pool identities can be supplied as
an independently timestamped cache; identities observed after an event are never
backfilled into it.

## PumpSwap pool identity feasibility

`bootstrap_pools.py` uses `getMultipleAccounts` only for exact pools already observed in
a source corpus. It is a feasibility probe, not causal context for that same historical
T0. Raw account bytes are decoded with the pinned Carbon PumpSwap Pool account decoder.

## Lazy pool-context replay

Before putting RPC or account decoding anywhere near the hot path, measure the structural
value of lazy lookup with fixed counterfactual response delays:

```powershell
python -m benchmarks.helius_standard_wss_shadow_v0.lazy_pool_context_replay `
  --manifest "artifacts\helius_standard_wss_shadow_v0\cache-shadow-60s-manifest.jsonl" `
  --carbon-output "artifacts\helius_standard_wss_shadow_v0\cache-shadow-60s-carbon-output.jsonl" `
  --pool-identities "artifacts\helius_standard_wss_shadow_v0\shadow-60s-pool-identities.jsonl" `
  --delays-ms "50,100,250,500,1000"
```

This replay is explicitly **counterfactual**, assumes successful lookup/decode, and never
recovers the first cache-miss trade retroactively. It measures only how many later trades
would have context after a hypothetical lookup response.

## Finalized block recall reference

Measure the Standard WSS program-mention signature boundary against finalized blocks for
the exact slot range observed by the shadow:

```powershell
python -m benchmarks.helius_standard_wss_shadow_v0.reconcile_finalized_blocks `
  --shadow "artifacts\helius_standard_wss_shadow_v0\cache-shadow-60s.jsonl" `
  --candidates-out "artifacts\helius_standard_wss_shadow_v0\cache-shadow-finalized-candidates.jsonl" `
  --rps 5
```

The reconciler:

1. derives the exact min/max slot from Pump/PumpSwap WSS log notifications;
2. calls `getBlocks` at `finalized` commitment;
3. fetches each finalized block with `transactionDetails="accounts"`;
4. filters transactions whose account keys mention Pump or PumpSwap;
5. compares those signatures to the processed WSS signature sets.

If any block/RPC reference fetch is incomplete, recall percentages remain `null`; missing
truth is never converted to zero. A WSS signature absent from finalized truth is surfaced
for follow-up and is not automatically labeled a rollback.

This is signature/program-mention recall only. Instruction/event semantic recall remains a
separate later audit.

## Long-run policy

Do not assume a requested duration will actually be reached under a notification cap.
Estimate the cap from the measured event rate first, and do not start a long run until:

- reducer/Carbon/adapter correctness is green;
- PumpSwap context strategy has been measured;
- finalized signature recall has been measured on a short run;
- the expected notification volume fits the configured cap and credit budget.

## Current scientific boundary

Standard WSS is still operational-only. Systems health, decoder success, pool-context
coverage, finalized signature recall, and economic edge are independent verdicts. None
implies another.
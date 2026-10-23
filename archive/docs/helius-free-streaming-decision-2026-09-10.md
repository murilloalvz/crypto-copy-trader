# Helius Free streaming decision — 2026-09-10

## Decision

**KEEP + MEASURE Helius Standard WSS as the current zero-cost live acquisition candidate.**

Do not upgrade to paid Helius streaming and do not rewrite around gRPC until the short-run
finalized recall and context-coverage gates are measured.

## Why this is the current best zero-cost Helius path

Helius changed its streaming stack in 2026: Standard WebSockets are now served by the same
LaserStream-backed infrastructure, while retaining the native Solana Standard WSS method
surface. This improves the infrastructure beneath `logsSubscribe`, but does not remove the
method's filtering/content limitations.

Current Helius plan documentation shows:

- Free: Standard WebSockets, 5 concurrent WSS connections, 1,000 subscriptions/connection;
- Developer: adds Helius `transactionSubscribe` / Enhanced WebSockets;
- Business and above: mainnet LaserStream gRPC;
- `getTransactionsForAddress` is Developer+ only, so it is not part of the current zero-cost
  truth-reconciliation path.

The pricing page contains a high-level Free-plan card that can be read as mentioning
LaserStream gRPC, but Helius's detailed capability matrix and March 31, 2026 streaming
announcement explicitly place mainnet gRPC on Business+ and show no Free gRPC connection
allowance. The detailed matrix is the operative evidence for this decision.

## What Standard WSS has already proven in this repo

The current research corpus has established:

- operational connection success;
- high observed event throughput without transport/write errors in short smokes;
- truncation-aware missingness policy;
- Carbon live payload compatibility with zero decode failures on tested accepted events;
- no-backfill pool-identity causality;
- useful persistent pool-cache hits;
- a clock-domain bug discovered by live evidence and structurally corrected.

None of these results establishes chain-complete recall.

## What remains before promotion

### Gate A — finalized program-mention signature recall

Use the exact WSS slot window and an independent finalized block scan:

```text
getBlocks(finalized)
  -> getBlock(transactionDetails=accounts, finalized)
  -> filter Pump/PumpSwap account-key mentions
  -> compare signatures to processed logsSubscribe observations
```

If any block/reference fetch is incomplete, recall is not computed.

### Gate B — PumpSwap identity context coverage

Measure persistent-cache coverage after the dual-clock correction, then compare it to the
counterfactual lazy-lookup replay at fixed delays. The replay is not live latency evidence;
it is only a structural estimate of how many later trades could gain context after the
first miss.

### Gate C — semantic event recall

Only if signature recall shows gaps or if later promotion requires stronger evidence,
hydrate the divergent signatures and compare actual Pump/PumpSwap invocation/target-event
semantics. Do not hydrate the whole window by default.

## Upgrade/replacement triggers

Revisit the acquisition provider/method only if measured evidence shows one or more of:

- unacceptable finalized signature recall;
- truncation materially destroys target-event coverage;
- Standard WSS delivery latency cannot meet the Signal-First use case after measuring with
  a valid same-domain/calibrated method;
- client-side throughput cannot keep up despite the memory-first Carbon/kernel boundary;
- a paid or alternative provider gives a material, benchmarked improvement that justifies
  cost/complexity.

Candidate upgrades must be benchmarked, not adopted from marketing claims. Helius
Developer `transactionSubscribe`, Helius Business LaserStream gRPC, and non-Helius
Yellowstone/gRPC providers remain candidates, not assumptions.

## Non-decisions

This document does **not** claim:

- Standard WSS is chain-complete;
- LaserStream-backed Standard WSS has the same delivery contract as LaserStream gRPC;
- systems health implies economic edge;
- vendor latency claims are bot-measured latency;
- a paid tier is required.

The current rule remains: **measure the free path first, replace it only on evidence.**
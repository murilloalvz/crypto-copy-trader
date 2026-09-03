# Pump Market Stream v1 — live smoke — 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**

This document records the first live bounded smoke of the native Pump bonding-curve stream after `pump_market_stream_smoke.py` was promoted to the main research branch.

## Run

Command family:

```text
python pump_market_stream_smoke.py --run-key pump-smoke-20260903-01 --duration-seconds 120 --commitment confirmed
```

Observed summary supplied from the local run:

```text
elapsed=120.2s
notifications=3476
decoded_events=3688
persisted=3600
unique_tokens=223
unique_wallets=1984
```

## Derived acquisition rates

Over 120.2 seconds:

- ~28.92 log notifications/second;
- ~30.68 decoded Pump TradeEvents/second;
- ~29.95 persisted market observations/second;
- ~1.86 unique tokens/second;
- ~16.51 unique wallets/second;
- 97.61% of decoded events were persisted by the SOL-paired v1 adapter.

The 88 decoded-but-not-persisted events are not automatically classified here. The current adapter can deliberately skip non-SOL-prefix events and can also observe idempotent duplicates; a future smoke/audit must report those causes separately instead of inferring them post hoc.

## Important observation: multi-event transactions

The live output contained signatures with multiple Pump `TradeEvent`s, including several with `events=4 persisted=4`.

Therefore:

- raw TradeEvents remain valid observations and must be preserved;
- event count must **not** automatically be interpreted as independent participant/transaction count;
- the radar bridge must preserve transaction/signature identity so one transaction or bundle cannot silently inflate market breadth/acceleration evidence;
- wallet breadth and transaction breadth should be evaluated separately.

## What this smoke validates

The smoke provides direct operational evidence that the local environment can:

1. connect to the Solana WebSocket RPC;
2. subscribe to the Pump program at `confirmed` commitment;
3. receive a high-volume native log stream;
4. decode official Pump `TradeEvent` payloads;
5. preserve real `chain_time` and local `observed_at`;
6. persist run-scoped market observations into SQLite;
7. obtain orders of magnitude more acquisition candidates than the closed wallet-only forward experiment.

## What this smoke does NOT validate

It does **not** establish:

- economic edge;
- profitability;
- detector precision;
- PumpSwap coverage;
- Jupiter executability;
- hazard/rug filtering quality;
- wallet-intelligence incremental value;
- complete coverage during reconnects;
- finalized status of every observed event;
- independence of every decoded event.

## Decision

**NATIVE PUMP ACQUISITION PLUMBING: LIVE SMOKE PASS.**

The previous economic sample-scarcity problem is no longer the immediate acquisition bottleneck for Pump bonding-curve activity. The next gate is to turn the raw stream into causal market opportunities without mistaking raw event volume for independent evidence.

Next implementation order:

1. preserve transaction identity explicitly in radar input;
2. decode/persist Pump `CreateEvent` as lifecycle evidence for `fresh_market_burst`;
3. bridge `market observation store -> radar -> market opportunity episode`;
4. add a bounded radar smoke and acquisition-quality audit;
5. add PumpSwap with explicit pool->mint resolution;
6. only then connect execution/risk/regime/wallet evidence and run an end-to-end bounded smoke.

No 12h acquisition run is authorized by this smoke alone.

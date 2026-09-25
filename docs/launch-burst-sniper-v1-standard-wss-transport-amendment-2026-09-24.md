# Sniper V1 Standard-WSS Transport Amendment V0 — 2026-09-24

Status: PREREGISTERED SYSTEMS AMENDMENT / NO ECONOMIC OUTCOME YET

## Triggering incident

The first attempt to start the frozen 900-second Sniper V1 screening failed before acquisition became
active.

Observed failure:

- WebSocket handshake rejected with HTTP 429;
- provider message: `max usage reached`;
- endpoint: Helius standard WSS;
- no Sniper wrapper report was produced;
- no economic comparison was produced;
- no threshold or selector result was observed.

This attempt is classified as a technical transport failure, not an economic sample.

## Gap found

The existing read-only Sniper support preflight validated:

- Helius holder discovery;
- Jupiter transaction assembly;
- Solana RPC presence;
- frozen route/policy identities.

It did not open and acknowledge the three standard Solana PubSub subscriptions used by the actual
acquisition collector. Therefore REST/assembly support could PASS while the Helius WSS quota was
already exhausted.

## Amendment

The frozen Sniper selector, route contract, economic benchmark, duration and comparison logic are
unchanged.

A wrapper now resolves the acquisition WebSocket before the frozen runner starts. Candidate order:

1. `SOLANA_LOGS_WSS_URL` when explicitly configured;
2. WSS derived from `SOLANA_RPC_URL`;
3. WSS derived from each `SOLANA_RPC_FALLBACK_URLS` entry in listed order;
4. direct Helius WSS as last resort.

HTTP(S) RPC URLs are converted only by scheme:

- `https://` -> `wss://`
- `http://` -> `ws://`

Path and query are preserved exactly.

Each candidate must open successfully and acknowledge all existing standard subscriptions:

- Pump `logsSubscribe`;
- PumpSwap `logsSubscribe`;
- `slotSubscribe`.

The selected WSS endpoint is then reused by the existing V3/V4 acquisition collector through a
temporary wrapper-level transport substitution. The core Sniper runner remains unchanged.

## Scientific invariants

Unchanged:

- Sniper policy hash and all 9 predicates;
- 900-second screening duration;
- fixed +60 second route-shadow primary benchmark;
- US$25 route-paper contract;
- Jupiter execution semantics;
- SMART-LADDER-25 exploratory-only role;
- causal feature snapshots;
- source-integrity comparator;
- sample gates and replication requirements.

The provider substitution is transport-only. It does not authorize threshold retuning or economic
reinterpretation.

## Failure handling

If no candidate WSS acknowledges all three subscriptions, the wrapper returns
`FAIL_SNIPER_V1_STANDARD_WSS_TRANSPORT_PREFLIGHT` and the 900-second acquisition must not start.

If transport fails after acquisition starts, existing transport/reconnect gates remain authoritative.
A transport-failed run is not an economic verdict.

## Operator sequence

1. Run wrapper with `--transport-preflight-only`.
2. Require `PASS_SNIPER_V1_STANDARD_WSS_TRANSPORT_PREFLIGHT`.
3. Only then run the same wrapper without `--transport-preflight-only` for the frozen 900-second
   screening.
4. Do not use the old direct runner while the Helius WSS quota remains exhausted.

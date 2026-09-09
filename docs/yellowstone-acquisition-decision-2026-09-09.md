# Yellowstone acquisition decision — 2026-09-09

## Decision

Replace high-volume `logsSubscribe -> getTransaction` hydration with a Yellowstone-compatible transaction stream for the next acquisition spike.

Status:

- public JSON-RPC hydration path: **REJECT for high-volume acquisition**;
- Yellowstone-compatible transaction stream: **ADOPT as next benchmark interface**;
- provider: **NOT YET SELECTED for production**;
- first low-cost benchmark candidate: **Alchemy PAYG**;
- Carbon runtime: **NOT YET ADOPTED**;
- Carbon Pump.fun/PumpSwap decoders: **decoder-parity candidates**;
- V68: **still NOT_EVALUATED and frozen**.

## Evidence from rejected raw corpus v1

30-second mainnet run over `api.mainnet.solana.com`:

- notifications seen: 24,916;
- queued for hydration: 2,125;
- queue overflow: 14,509;
- hydrated: 39;
- hydrate errors: 61;
- remaining unhydrated at bounded drain timeout: 2,025;
- all 61 observed hydration errors were HTTP 429 Too Many Requests;
- successful hydration median was ~37.6s;
- successful hydration p95 was ~57.3s;
- corpus validity: false.

Interpretation: a per-signature JSON-RPC fan-out cannot keep up with the target program event rate on the public endpoint and produces latency that is incompatible with early opportunity detection. More workers/retries would increase pressure rather than remove the structural mismatch.

## Existing-solutions-first provider screen

Current public documentation reviewed on 2026-09-09:

| Candidate | Mainnet Yellowstone access | Commercial shape | Current decision |
|---|---|---|---|
| Alchemy | yes | ~$75/TB PAYG, no monthly minimum; PAYG team required | **BENCHMARK FIRST** |
| Helius LaserStream gRPC | yes | Business tier, ~$499/month | defer until edge justifies cost |
| QuickNode Solana gRPC | yes | Scale/Business, ~$499/month | defer until edge justifies cost |
| Chainstack Yellowstone | yes | add-on starting around $49/month | possible later bake-off |
| Shyft Yellowstone | yes | paid plans starting around $199/month | possible later bake-off |

Pricing and product claims are vendor documentation, not performance evidence.

## Why Yellowstone

A Yellowstone transaction update includes the full transaction plus `TransactionStatusMeta`, slot and transaction index in the stream. This removes the rejected signature-to-HTTP hydration fan-out.

Target path:

```text
Yellowstone transaction stream
        |
        v
raw transaction + meta
        |
        v
same-input decoder parity
   /                  \
our decoder        Carbon decoder
   \                  /
        canonical event
             |
             v
      bounded memory kernel
```

## Spike constraints

The first spike is intentionally narrow:

- Pump + PumpSwap only;
- successful non-vote transactions only;
- confirmed commitment initially;
- exact provider `SubscribeUpdate` protobuf preserved;
- no SQLite;
- no Radar;
- no V68;
- no wallet scoring;
- no execution;
- no real money;
- no production provider conclusion from a single short run.

## Promotion gates

A raw stream corpus may enter decoder parity only if:

1. at least one transaction update is captured;
2. full transaction info is present for every stored transaction update;
3. zero local write errors;
4. zero gRPC stream errors during the bounded smoke;
5. provider token is not present in artifacts or repository history.

Decoder parity then requires, on the same raw updates:

- recognized transaction coverage 100%;
- zero silent drops;
- zero duplicates attributable to the decoder;
- zero side inversions;
- zero mint/wallet/amount/lifecycle mismatches.

Only after correctness passes should throughput, delivery latency, reconnect behavior, gaps and provider cost be benchmarked.

# Yellowstone acquisition decision — 2026-09-09

## Decision

Replace high-volume `logsSubscribe -> getTransaction` hydration with a Yellowstone-compatible transaction stream for the next acquisition spike.

Status:

- public JSON-RPC hydration path: **REJECT for high-volume acquisition**;
- Yellowstone-compatible transaction stream: **ADOPT as next benchmark interface**;
- provider: **NOT YET SELECTED for production**;
- first corpus route: **ERPC 1-day free Geyser gRPC trial**;
- second free-trial route: **Helius LaserStream 2-day trial, subject to approval**;
- low-cost recurring route after trials: **Alchemy PAYG (~USD 75/TB)**;
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

| Candidate | Raw mainnet Yellowstone suitable for parity | Free path | Paid shape | Current decision |
|---|---:|---|---|---|
| ERPC Geyser gRPC | yes | 1-day free trial; EUR 5 temporary card authorization for verification | Standard shared gRPC listed around EUR 198/mo promotional / EUR 398 list | **TRY FIRST** |
| Helius LaserStream | yes | 2-day mainnet trial by application/review | Business mainnet access around USD 499/mo | **TRY SECOND IF NEEDED** |
| Alchemy gRPC | yes | no confirmed free mainnet gRPC tier | ~USD 75/TB PAYG, no monthly minimum | **LOW-COST RECURRING CANDIDATE** |
| NoLimitNodes | yes according to current product pages | marketing pages mention trials, but current mainnet pricing is paid | Pro starts around USD 49/mo flat with 2 gRPC streams | **CHEAP FLAT-RATE CANDIDATE; VERIFY BEFORE USE** |
| Subglow | Yellowstone-style interface but output is pre-parsed JSON | free trial/no card advertised | USD 99/mo | **NOT RAW DECODER-PARITY INPUT; INTELLIGENCE/PRODUCTION CANDIDATE LATER** |
| OrbitFlare | full Yellowstone | free gRPC is devnet-only | mainnet shared gRPC ~USD 500/mo | **REJECT FOR FREE MAINNET PARITY** |
| Triport | full Yellowstone on paid tier | 7-day no-card free tier excludes Yellowstone gRPC | Pro ~USD 249/mo | **REJECT FOR FREE MAINNET PARITY** |
| Raiden Vortex | Yellowstone/Geyser compatible | trial on request | ~USD 650/mo/region | **DEFER** |
| Triton | yes | no free public path found | PAYG streaming ~USD 0.08/GB but USD 125 minimum prepaid deposit | **DEFER** |

Provider claims and prices are not performance evidence. They only determine which candidates are economical enough to benchmark.

## Why ERPC first

ERPC's current documentation explicitly states:

- shared Geyser gRPC is full Yellowstone/Geyser for transaction/account/slot/block subscriptions;
- all plans have a 1-day free trial;
- the EUR 5 card event is an authorization used for verification, not an immediate service charge;
- shared endpoints are IP-allowlisted and can run without token metadata;
- HTTPS and plaintext HTTP/2 endpoints are supported.

This gives us the lowest-friction path to a raw **mainnet** corpus while preserving the standard Yellowstone wire interface.

The local collector is provider-neutral: TLS/plaintext and auth metadata are configuration, not architecture.

## Cost posture after the free corpus

Do not select a production provider from one short smoke.

Once decoder correctness is established, compare at least:

- delivery latency / `provider_created_at -> received_at` where available;
- coverage and gaps;
- duplicate rate;
- ordering;
- reconnect/replay behavior;
- filter semantics;
- effective monthly cost for Pump + PumpSwap only.

For low filtered volume, Alchemy's per-bandwidth PAYG model is likely economically attractive. For sustained higher volume, a flat plan such as NoLimitNodes may become cheaper. That crossover must be measured from our actual bytes, not guessed.

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
- bounded by duration and max transaction count;
- no SQLite;
- no Radar;
- no V68;
- no wallet scoring;
- no execution;
- no real money;
- no production provider conclusion from a single short run.

## Promotion gates

A raw stream corpus may enter decoder parity only if:

1. transaction updates are captured;
2. Pump is represented;
3. PumpSwap is represented;
4. full transaction info is present for every stored transaction update;
5. zero local write errors;
6. zero gRPC stream errors during the bounded smoke;
7. provider token is not present in artifacts or repository history.

Decoder parity then requires, on the same raw updates:

- recognized transaction coverage 100%;
- zero silent drops;
- zero duplicates attributable to the decoder;
- zero side inversions;
- zero mint/wallet/amount/lifecycle mismatches.

Only after correctness passes should throughput, delivery latency, reconnect behavior, gaps and provider cost be benchmarked.

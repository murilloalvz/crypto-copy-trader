# Acquisition / corpus decision — 2026-09-09

## Revised decision

Do **not** pay for production-grade Yellowstone/gRPC before the bot's decoder semantics and opportunity intelligence show enough evidence to justify a live low-latency provider.

Current status:

- public `logsSubscribe -> getTransaction` at full Pump/PumpSwap volume: **REJECT for high-volume live acquisition**;
- Helius Free historical standard RPC: **ADOPT for decoder corpus and offline research now**;
- Helius Free Standard WebSockets: **ADOPT candidate for bounded live/shadow research**;
- paid Yellowstone/gRPC mainnet: **FREEZE / DEFER until live latency and full-coverage validation matter**;
- Carbon Pump.fun/PumpSwap decoders: **next semantic-parity experiment**;
- Carbon runtime/provider choice: **NOT YET EVALUATED**;
- V68: **still NOT_EVALUATED and frozen**.

## Why the previous live HTTP path was rejected

30-second mainnet run over `api.mainnet.solana.com`:

- notifications seen: 24,916;
- queued for hydration: 2,125;
- queue overflow: 14,509;
- hydrated: 39;
- hydrate errors: 61;
- remaining unhydrated at bounded drain timeout: 2,025;
- all observed hydration errors were HTTP 429 Too Many Requests;
- successful hydration median was ~37.6s;
- successful hydration p95 was ~57.3s;
- corpus validity: false.

Interpretation: one HTTP `getTransaction` per live market event cannot keep up with the full target-program event rate on the public endpoint. Increasing workers/retries would amplify rate-limit pressure.

This rejects that pattern for **high-volume live acquisition** only. It does **not** reject paced historical `getTransaction` for offline research.

## Zero-cost validation path

Helius currently documents a Free plan with:

- USD 0/month;
- 1,000,000 credits/month;
- 10 RPC requests/sec;
- Standard WebSockets on mainnet;
- 5 concurrent WebSocket connections;
- up to 1,000 subscriptions per connection.

Current documented credit costs:

- standard RPC call: 1 credit;
- `getSignaturesForAddress`: 1 credit;
- `getTransaction`: 1 credit;
- Standard WebSocket streaming: 2 credits per 0.1 MB.

Therefore decoder semantic parity does not require Yellowstone. A 250 Pump + 250 PumpSwap historical corpus costs roughly ~500 standard RPC credits plus a handful of signature-page calls, assuming no retries/missing rows.

Official research path now:

```text
Helius Free historical RPC
        |
        v
Pump / PumpSwap signatures
        |
        v
paced getTransaction (5 RPS target)
        |
        v
complete raw transaction + meta corpus
        |
        +-------------------+
        |                   |
        v                   v
our decoder            Carbon decoder
        |                   |
        +---------+---------+
                  v
           semantic parity
```

This is intentionally offline. Latency does not matter in this experiment; correctness does.

## What can be validated for free

### 1. Decoder correctness

Using complete historical transactions and metadata:

- venue recognition;
- mint;
- side;
- wallet;
- base/quote amounts;
- lifecycle/create events;
- duplicates/silent drops.

### 2. Market intelligence offline

Once the canonical decoder path is trustworthy, replay historical windows through candidate Market-First features and episode logic. Historical P&L remains discovery evidence, not causal proof.

### 3. Bounded prospective/shadow research

Helius Free Standard WebSockets can be used for mainnet `logsSubscribe`/other standard subscriptions. Any HTTP enrichment must be explicitly bounded below the Free-plan rate limit. This can support low-alert-rate shadow validation; it is not a claim of production full-market coverage.

## What still needs paid/trial streaming later

Only after correctness and economic promise are established do we need to benchmark:

- full live Pump/PumpSwap coverage under bursts;
- end-to-end delivery latency;
- reconnect/replay behavior;
- queue/backlog behavior at market peak;
- provider failover;
- production reliability.

At that point Yellowstone/gRPC becomes important because `SubscribeUpdateTransaction` carries full transaction + `TransactionStatusMeta` in the stream and avoids per-signature HTTP fan-out.

## Paid-provider candidates — deferred

Current documented shapes reviewed on 2026-09-09:

| Candidate | Relevant access | Commercial shape | Current decision |
|---|---|---|---|
| Helius | Standard WSS free; Enhanced WSS from Developer; mainnet gRPC from Business | Free / ~USD49 Developer / ~USD499 Business | **USE FREE NOW; DEFER PAID** |
| Alchemy | mainnet Yellowstone-compatible gRPC | ~USD75/TB PAYG, no fixed gRPC monthly minimum documented | **CHEAP PAYG CANDIDATE LATER** |
| ERPC | mainnet Geyser gRPC | 1-day trial; paid shared plans afterward | **TRIAL CANDIDATE LATER** |
| NoLimitNodes | Yellowstone according to current product pages | ~USD49/mo entry paid plan | **CHEAP FLAT-RATE CANDIDATE LATER; VERIFY** |
| QuickNode | mainnet Solana gRPC on higher plans | expensive relative to current stage | **DEFER** |

Provider pricing/claims are screening evidence only, not performance evidence.

## Promotion rule

Do not spend recurring money on streaming infrastructure until at least:

1. decoder semantic parity is established on a clean corpus;
2. Market-First candidate logic has reproducible offline evidence;
3. at least one bounded prospective/shadow experiment is worth scaling;
4. the expected latency/coverage benefit of paid streaming is measurable against a free baseline.

Only then run a provider bake-off and choose by measured latency, coverage, gaps, reconnect behavior, and actual bytes/month.

## Scientific constraints unchanged

- no SQLite/Radar/V68 changes merely to accommodate this corpus work;
- no real-money execution;
- no lookahead;
- systems PASS does not imply economic edge;
- historical P&L does not imply causal edge;
- Market-First and Social/Event-First remain independent research tracks;
- V68 remains `NOT_EVALUATED` until explicitly resumed under a valid protocol.

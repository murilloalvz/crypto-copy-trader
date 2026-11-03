# Existing Market Intelligence Sources — 2026-09-10

## Purpose

Apply the project rule:

```text
SEARCH -> UNDERSTAND -> BENCHMARK/VALIDATE -> ADOPT/ADAPT/REJECT -> BUILD only what remains
```

to **analysis/intelligence**, not only infrastructure.

The project must not assume that every useful market/risk feature should be rebuilt from
raw Solana data. Existing providers may supply valuable independent evidence, but their
scores and labels remain provider-native until prospectively validated.

## Decision summary

| Source | Current decision | Intended role | Why |
|---|---|---|---|
| Native Carbon + protocol facts + matched-unit flow | KEEP | Primary causal on-chain evidence | Exact event/pool/mint semantics under our own T0/missingness contracts |
| Jupiter Tokens V2 | PROBE / ADAPT AS EXTERNAL EVIDENCE | Organic activity, market stats, audit, metadata | Free/keyless path exists; exact-mint querying; useful provider-native organic/activity fields |
| DexScreener API | PROBE / ADAPT AS EXTERNAL EVIDENCE | Independent pair/liquidity/volume/txn/age cross-check | Free/no-key API; exact token-address pair lookup; high enough rate limits for research |
| Solana Tracker Data API | KEEP SELECTIVELY | Existing wallet/risk/discovery evidence | Already used by project; rich token risk/wallet analytics; preserve provider semantics |
| Birdeye Data API | DEFER PAID FEATURES | Holder history/profile, first buyers, tagged wallet concentration | Strong existing intelligence but key high-value endpoints are paid; benchmark only if free sources/native path leave a material gap |
| Custom new heuristic score | REJECT FOR NOW | — | Would duplicate provider/native evidence without prospective proof |

## 1. Native causal Market-First evidence

Carbon decoders and our protocol/matched-unit layers remain the primary evidence source
for facts that must be known exactly at T0:

- Pump/PumpSwap event identity;
- exact mint/pool identity when causally known;
- side and raw quote amount;
- event-native compatible quote reserves;
- local evidence availability;
- on-chain market time;
- protocol/lifecycle evidence;
- causal flow windows.

Native evidence is not automatically superior economically; it is superior in **causal
control and provenance**.

## 2. Jupiter Tokens V2

### Useful provider-native fields

Current Tokens V2 documentation exposes, depending on token/response availability:

- `organicScore` and `organicScoreLabel`;
- `holderCount`;
- liquidity / USD price / market cap / FDV;
- token audit metadata;
- `firstPool` and pool creation information;
- `stats5m`, `stats1h`, `stats6h`, `stats24h`;
- trading activity such as buy/sell counts and volume;
- organic-volume/activity metrics.

Jupiter describes organic score as its own attempt to distinguish organic activity from
wash/artificial activity. This is useful as an **independent feature**, not as ground
truth. Scores for very new tokens can be unstable and must never directly become
`TAKE/SKIP` or replace our own causal evidence.

### Access

The current Developer Platform supports keyless requests on `api.jup.ag` at 0.5 RPS and a
$0 Free API-key plan at 1 RPS. Search supports comma-separated queries up to 100 entries.

### Current implementation

`jupiter_token_intelligence_probe.py`:

- starts only from exact mints already present in ADAPTED native flow;
- rejects search results outside the exact requested mint set;
- stores the original provider payload and local request/receive clocks;
- marks post-shadow observations non-causal for the source shadow;
- reports missing-field coverage rather than imputing values;
- explicitly records that Jupiter's score is not ground truth.

## 3. DexScreener

### Useful provider-native fields

The token-address endpoint supplies pair-level evidence such as:

- exact base/quote token addresses;
- pair address / DEX identity;
- price USD/native;
- liquidity;
- transaction counts;
- volume;
- price change;
- pair creation timestamp;
- boost/attention metadata.

The API currently documents up to 30 comma-separated token addresses and a 300 requests/min
rate limit for the token endpoint.

### Interpretation

DexScreener is best used as an **independent market-data cross-check**, not as a source of
causal truth for a historical T0. In particular:

- its USD liquidity must not be silently equated to event-native raw reserve units;
- pair volume/transaction aggregates must not be merged into native flow without an
  explicit compatibility definition;
- boosts/paid promotion indicate attention spend, not organic demand or economic edge.

### Current implementation

`dexscreener_market_probe.py` stores only exact Solana pair matches for requested mints,
keeps raw provider payloads, timestamps the fetch locally, and reports pair/field coverage.

## 4. Solana Tracker

The project already uses Solana Tracker selectively for discovery, wallet PnL and token
risk evidence. The provider exposes useful concrete risk fields including mint/freeze
authority, bundler/insider/sniper/dev activity and liquidity context.

Policy remains:

- retain provider-native fields and score provenance;
- do not translate provider risk score directly into economic edge;
- do not let historical wallet PnL imply causal alpha;
- compare provider classifications to native/on-chain evidence when possible.

Raptor swap/quote infrastructure is also an existing execution candidate, but it must be
benchmarked against Jupiter/other routers if/when the project reaches executable quote
research. It is not part of the current signal gate.

## 5. Birdeye

Birdeye now exposes unusually relevant existing analytics for the exact problem this project
is trying to understand, including:

- holder-count history;
- holder distribution;
- holder profiles tagged as bundler/sniper/insider/dev;
- per-holder positions/PnL;
- token first buyers;
- token security and creation information;
- meme-token discovery and fee activity.

This is strategically important because it proves that several analyses we considered
building ourselves already exist as commercial primitives.

However, the current pricing/docs place important security/holder intelligence behind paid
plans. Therefore the project should **not reproduce all of Birdeye now**, but also should
not pay yet. Revisit only when a prospective experiment identifies a concrete missing
feature whose expected value exceeds the subscription cost and implementation burden.

## 6. Evidence hierarchy

For every external provider observation, preserve:

```text
provider
endpoint/version
exact mint/pool identity
requested_at / received_at when available
raw/provider-native field names
missingness
causal_for_episode_T0
```

Provider outputs must be classified as one of:

```text
DOCUMENTED FACT
EXTERNALLY OBSERVED DATA
PROVIDER-DERIVED METRIC/SCORE
VENDOR CLAIM
```

No provider-derived score is promoted into a bot decision rule merely because it sounds
useful.

## 7. Prospective validation plan

After native live acquisition/context correctness is stable:

1. capture external Jupiter + DexScreener observations **concurrently/prospectively** with
   future episodes, not after outcomes are known;
2. freeze raw provider features without threshold tuning;
3. compare overlap and disagreement with native Market-First features;
4. evaluate whether any external feature adds information out of sample;
5. only then consider an adapted feature or rule;
6. keep Birdeye paid analytics as a benchmark/buy-vs-build option if a specific gap remains.

Useful candidate questions, not assumptions:

- Does Jupiter organic activity add information beyond our own wallet/flow breadth?
- Does independent DexScreener liquidity materially improve execution-risk classification?
- Do provider audit fields catch hazards our native checks miss?
- Would first-buyer/holder-tag intelligence justify buying rather than building?

## Frozen rule

The goal is not to maximize the number of APIs or metrics. The goal is to minimize custom
work while retaining causal correctness and independent evidence.

**Use existing intelligence where it is strong; preserve its provenance; benchmark whether
it adds predictive or risk information; build only the missing differentiator.**
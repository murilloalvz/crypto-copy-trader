# X Social Tracker — feasibility v1

Research date: 2026-08-31.

## Official X API facts relevant to the project

Official documentation currently exposes:

- Recent Search over Posts from the last 7 days;
- Full-Archive Search for pay-per-use / Enterprise access;
- Filtered Stream for near-real-time Posts matching persistent rules;
- core query operators for keywords, hashtags, users and filters;
- pay-per-use pricing rather than a fixed subscription for self-serve access.

The Filtered Stream documentation reports approximately 6–7 seconds P99 delivery latency. For our research this is potentially useful because `observed_at` can represent the actual collector receipt time rather than pretending the post was known at `created_at`.

Official references:

- https://docs.x.com/x-api/posts/search/introduction
- https://docs.x.com/x-api/posts/filtered-stream/introduction
- https://docs.x.com/x-api/getting-started/pricing

## Current cost implication

The official pricing page currently lists Post reads at US$0.005 per unique resource, with same-resource deduplication within a 24-hour UTC window in normal operation. Current rates can change and must be checked again before enabling a collector.

Illustrative unique-Post read cost at that unit price:

| Unique Posts/day | Approx. cost/day | Approx. 30d cost |
| ---: | ---: | ---: |
| 100 | US$0.50 | US$15 |
| 1,000 | US$5 | US$150 |
| 10,000 | US$50 | US$1,500 |

Therefore a broad crypto firehose is a poor v1 design. The social sensor should maximize information gain per Post read.

## Recommended v1 collection strategy

Start narrow and preserve raw evidence:

1. curated accounts whose posts plausibly move or discover Solana opportunities;
2. token mint / contract identifiers when present;
3. token symbol only when collision risk is controlled;
4. launch/listing/announcement terms combined with specific Solana context;
5. selected accounts plus exclusion of repost noise where appropriate;
6. explicit query/rule version stored with every collection run.

Do not begin with a giant generic query for `crypto`, `solana` or `memecoin`. It is expensive, noisy and makes causal attribution worse.

## Architecture

```text
X API adapter
   ↓
raw Post snapshot
   ↓
created_at + observed_at
   ↓
token/entity resolution
   ↓
append-only SocialEvent snapshots
   ↓
causal 5m/15m/60m context
   ↓
join to Wave/wallet opportunity at decision time
```

The provider adapter must remain separate from `src/social_intelligence.py`. The existing causal feature layer should be able to consume X, another authorized social source or archived test fixtures without changing experiment definitions.

## Causal rule

`created_at` is not enough.

If a Post was created at 10:00 but our collector first received/discovered it at 10:07, a replay decision at 10:03 cannot use that Post. Eligibility is based on `observed_at <= decision_time`.

Engagement snapshots follow the same rule. A Post that had 20 likes when observed cannot retrospectively receive its 5,000-like count from two hours later.

## What to test before building a score

For every social event/context, measure future market paths rather than assigning arbitrary weights:

- +5m / +15m / +60m / +6h / +24h return;
- MFE/MAE;
- liquidity and executable slippage;
- time from Post creation to observation;
- time from observation to simulated execution;
- author-level repeatability;
- token/entity-resolution confidence;
- whether wallet evidence already existed before the social event;
- whether Wave evidence already existed before the social event.

Useful experiments include:

- social-only versus matched controls;
- social before wallet flow versus social after wallet flow;
- wallet flow with versus without social confirmation;
- Wave with versus without social confirmation;
- all three together versus each pair.

## Important anti-survivorship rule

Do not build the account list only from people remembered for calling famous pumps. Record why and when an account entered the monitored cohort, then evaluate all subsequent eligible calls/events, including failures and silence.

## Implementation status

- causal social event model: IMPLEMENTADO;
- causal snapshot selection: IMPLEMENTADO;
- 5m/15m/60m descriptive windows: IMPLEMENTADO;
- offline JSONL context CLI: IMPLEMENTADO;
- live X API collector: PLANEJADO;
- token/entity resolver: PLANEJADO;
- social event persistence in project SQLite: PLANEJADO;
- outcome join / causal replay: PLANEJADO;
- social trading score: intentionally NOT IMPLEMENTED until data supports one.

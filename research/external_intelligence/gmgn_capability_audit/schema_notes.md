# GMGN schema / causality notes

## Time model

GMGN API records commonly contain event timestamps such as trade `timestamp` or token
`created_timestamp`. The audited CLI documentation does not expose an API receipt timestamp.

Our wrapper must therefore persist:

- request_before_utc
- request_before_unix_ms
- response_after_utc
- response_after_unix_ms
- duration_ms
- raw response
- command / capability name

For scientific causality, use response_after as the conservative local availability time unless a
more precise locally measured arrival clock is available.

## Participant wallet data

### portfolio stats

Candidate fields:

- realized_profit
- winrate
- pnl_stat.token_num
- pnl_stat.avg_holding_period
- PnL bucket counts

These are dynamic aggregates. They are NOT safe for retrospective T0 use when queried later.

### portfolio profits

Provides period and all-time realized/unrealized profit/cost fields. Same causal restriction.

### portfolio activity

Individual rows contain activity timestamp and token identity, making them more auditable than
aggregate stats. Still preserve query observed_at and do not assume GMGN's classification/provenance
was historically identical.

## Deployer created-tokens

Top-level:

- last_create_timestamp
- inner_count
- open_count
- open_ratio
- creator_ath_info

Per launch:

- token_address
- create_timestamp
- is_open
- market_cap
- token_ath_mc
- pool_liquidity
- holders
- launchpad_platform
- bundler_rate

Important:

- total created = inner_count + open_count;
- tokens[] may be truncated;
- open_ratio and ATH are current-state values and can leak future if backfilled;
- for a fresh signal, a snapshot taken before/at decision time can become valid deployer-prior evidence.

## Smart Money / KOL

Raw event fields include:

- transaction_hash
- maker
- side
- base_address
- amount_usd
- token_amount
- price_usd
- timestamp
- maker_info tags/social metadata

Scientific representation should separate:

```text
trade event evidence
from
GMGN wallet classification evidence
```

The event can be checked on chain. The Smart Money/KOL classification is externally assigned and may
be mutable.

## Trenches

Useful raw categories:

- identity/timing: address, created_timestamp, open_timestamp, complete_timestamp
- market: market cap, liquidity, swaps, volume, holder_count
- structure/risk: top-holder concentration, rug ratio, insider/bundler/sniper metrics,
  creator balance/holding, wash-trading flags
- external participant counts: smart_degen_count, renowned_count

Only identity/event timestamps are naturally historical. Most other fields are snapshot state and
must be stored prospectively.

## Trending / hot

Ranking itself has no historical event timestamp in the audited schema. Therefore:

```text
rank observed at local_observed_at
```

is the causal fact. Never assign today's rank to an earlier launch.

## Survivorship controls

Never use:

```text
completed tokens only -> predictor quality
```

Always compare completed/migrated outcomes against an all-launch denominator captured from
new_creation / raw chain.

## Scores

Opaque or composed GMGN scores are hypothesis-mining aids only.

Prefer:

```text
raw component -> mechanism -> causal snapshot -> incremental test
```

over:

```text
external score -> selector
```

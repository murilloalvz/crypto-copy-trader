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


## Top100 holders / participant structure

`token holders --limit 100 --order-by amount_percentage` returns a current ranked holder snapshot.

Useful raw fields include:

- wallet `address` and token `account_address`;
- `balance` / `amount_cur`;
- `amount_percentage` (TOTAL-supply fraction, 0–1);
- buy/sell volumes and transaction counts;
- realized/unrealized/total profit fields;
- `start_holding_at`, `end_holding_at`, `last_active_timestamp`, `last_block`;
- `tags` and token-specific `maker_token_tags`;
- `native_transfer` funding metadata;
- transfer-in/out information.

The endpoint does not document a snapshot timestamp or historical `as_of`. Per-wallet timing fields do not
make the whole holder ranking historical. Persist local `request_before` / `response_after`.

Top-N concentration must clearly state its denominator:

```text
raw amount_percentage = share of total supply
```

Do not silently substitute the GMGN holder-analysis skill's tradeable-float rebasing.

Current top100 selection also has survivorship/current-balance selection risk: wallets that fully exited can
disappear from the holder snapshot.

## Smart-degen holder labels

`--tag smart_degen` filters using a GMGN platform classification described as historically high-performing
traders / smart money.

Known:

- wallet address is returned;
- current token share/PnL/flow data are returned;
- token-specific timing fields are returned;
- platform and token-specific tags may be returned.

Not established by current audited docs:

- label assignment algorithm;
- classification timestamp;
- whether a label existed at an arbitrary historical T0;
- whether labels are updated retroactively using later performance;
- historical label snapshots.

Therefore historical use is characterization only unless a point-in-time label snapshot has been stored.

## Wallet stats cutoff audit

Current `gmgn-cli portfolio stats` options:

- `--chain`;
- repeatable `--wallet`;
- `--period 7d|30d`;
- `--raw`.

No native `as_of`, `before`, `end_time` or historical-snapshot parameter is exposed.

Current `portfolio activity` options include token, pagination cursor, activity type and raw output, but no
server-side time cutoff. Each row does contain an event `timestamp`.

Therefore:

```text
today's 30d stats -> old signal T0
```

is lookahead-contaminated.

The only credible retrospective path in this audit is to page event history and independently rebuild metrics
from rows whose event timestamp is strictly before the target T0, with additional checks that the activity
archive is complete enough for the intended period.

## Top traders ranked by profit

`token traders --order-by profit --direction desc` returns the same rich wallet/token fields available to
holder/trader analysis, but the selection/ranking variable itself is an outcome.

Use it only for retrospective behavior research / hypothesis mining. Any pre-T0 characteristic discovered
from profitable traders must be defined without outcome information and tested on separate prospective data.

# GMGN External Intelligence Audit V0

Status: research-only, read-only, no selector changes, no private keys, no capital.

## Scope

This audit treats GMGN as external evidence / enrichment / benchmark / hypothesis source.
Raw chain and our causal capture remain primary scientific evidence.

Safe-use rule:

```text
GMGN dynamic field
-> query request_before
-> API response
-> response_after / local_observed_at
-> only then eligible as prospective evidence
```

Never backfill current GMGN aggregates into an earlier signal and call them causal.

## Current scientific gate

The current preregistered gate is NOT GMGN.

Branch:

`research/early-buyer-prior-quality-replication-v0`

The fresh 900s Participant Quality confirmation must be completed first on the scientific branch.
This audit branch stays isolated so external tooling cannot contaminate that capture or protocol.

## Highest-value capabilities

### 1. Deployer prior history — APPLY_NOW_SAFE acquisition candidate

Command:

```powershell
gmgn-cli portfolio created-tokens --chain sol --wallet <deployer> --order-by token_ath_mc --direction desc --raw
```

Raw useful components include prior launch count, graduation count/rate, token creation timestamps,
ATH market caps, prior launch status and launchpad. These must be snapshotted prospectively before
the current launch decision. Current ATH/open state is not safe to retroactively assign to an older T0.

### 2. Smart Money — TEST_AS_HYPOTHESIS

```powershell
gmgn-cli track smartmoney --chain sol --limit 100 --raw
```

Useful raw fields include transaction hash, maker wallet, side, token, amount, price and event timestamp.
The Smart Money label is GMGN-defined and may change over time, so the label itself is external/opaque
evidence. Any signal test must preserve both event_at and our local observed_at.

### 3. KOL — TEST_AS_HYPOTHESIS

```powershell
gmgn-cli track kol --chain sol --limit 100 --raw
```

Treat as a participant lead, never as BUY => BUY. Same timestamp/freshness requirement as Smart Money.

### 4. Trenches new_creation — BENCHMARK

```powershell
gmgn-cli market trenches --chain sol --type new_creation --launchpad-platform Pump.fun --limit 80 --raw
```

Use first for:

- GMGN creation-time vs chain T0;
- GMGN availability vs our observed_at;
- coverage overlap;
- missing launch analysis.

Dynamic structural fields are safe only as the snapshot observed at that request time.

### 5. Structural / token security — TEST_AS_HYPOTHESIS

```powershell
gmgn-cli token security --chain sol --address <token> --raw
```

Candidate dimensions include holder concentration, creator/dev exposure, bundler/insider/sniper-related
fields where the endpoint provides them. Do not activate vetoes without incremental testing.

## Explicitly not trusted as ground truth

- GMGN wallet-score;
- Smart Money / KOL labels;
- rug score;
- current ATH queried after the target signal;
- current PnL/winrate queried after the target signal;
- trending rank as historical alpha;
- completed-only launch samples.

Use raw components when possible.

## Safe API-key-only setup

For this audit, do NOT run `gmgn-cli config --apply`: the current CLI configuration flow writes a GMGN request-signing private key. We do not need that for the read-only endpoints selected here.

Use only an API key, for example in the current PowerShell session:

```powershell
$env:GMGN_API_KEY = "<set locally; do not paste or commit>"
gmgn-cli config --check
```

The selected sampler does not call holdings, swap, order submission, or follow-wallet. If any sampled capability asks for `GMGN_PRIVATE_KEY`, stop that capability.

## Timing sample

After the current fresh scientific capture has finished, run:

```powershell
powershell -ExecutionPolicy Bypass -File research\external_intelligence\gmgn_capability_audit\timing_sample.ps1
```

The script is read-only. It:

- checks GMGN CLI configuration;
- captures request-before and response-after timestamps;
- queries new Pump.fun launches, Smart Money, KOL and 5m trending;
- never logs an API key;
- never signs or submits a transaction.

Optional environment variables enable targeted wallet/deployer/token samples:

```powershell
$env:GMGN_SAMPLE_WALLET = "<public_wallet>"
$env:GMGN_SAMPLE_DEPLOYER = "<public_deployer>"
$env:GMGN_SAMPLE_TOKEN = "<public_token>"
```

If any command requires GMGN_PRIVATE_KEY, stop that capability and do not configure one.

`portfolio holdings` is explicitly excluded from this phase because current GMGN CLI documentation marks it as critical-auth/private-key gated.

## Scientific integration rule

Every future test is incremental:

```text
baseline signal
vs
baseline signal + one new external evidence family
```

No mega-score and no combined selector until individual/incremental value is established.


## Added capability audit — holder/trader/wallet temporal safety

### Top100 Holders — AUDIT_ONLY / FUTURE STRUCTURAL FEATURE

```powershell
gmgn-cli token holders --chain sol --address <token_address> --limit 100 --order-by amount_percentage --direction desc --raw
```

Raw holder rows are useful for:

- top1/top5/top10/top20 concentration;
- current holder distribution;
- creator/dev overlap through addresses/tags;
- repeated-wallet overlap across stored snapshots;
- funding-source / cluster hypotheses through `native_transfer`;
- prospective concentration persistence/decay.

Important semantics:

- raw `amount_percentage` is a fraction of **total token supply** (0–1), not tradeable float;
- the separate GMGN holder-analysis skill rebases percentages to tradeable float for its report, but this audit does not import that rating;
- the endpoint exposes per-wallet activity timestamps but no documented holder-list `as_of`, block cutoff, or historical snapshot;
- querying holders after the outcome is therefore retrospective structural evidence, not a T0 feature.

Classification remains `AUDIT_ONLY` until a prospective holder snapshot is actually observed before a decision cutoff.

### Smart Money Holders — AUDIT_ONLY pending label temporal safety

```powershell
gmgn-cli token holders --chain sol --address <token_address> --limit 100 --tag smart_degen --order-by amount_percentage --direction desc --raw
```

The CLI describes `smart_degen` as GMGN-tagged smart money / historically high-performing traders.
The exact classification algorithm, classification timestamp, historical label snapshot and retroactive-update
policy are not documented in the audited CLI/skill material.

Therefore:

```text
smart_degen at today's query
!=
proof that wallet was classified smart_degen at old T0
```

A prospectively stored `smart_degen` holder snapshot can later be tested as external participant evidence,
but the label itself remains external/opaque.

Forbidden shortcut:

```text
smart_degen holder -> BUY
```

### Wallet P&L Stats — TEST_AS_HYPOTHESIS with strict temporal reconstruction

```powershell
gmgn-cli portfolio stats --chain sol --wallet <wallet_address> --period 30d --raw
```

Current CLI exposes only `--period 7d|30d`. There is no documented `--as-of`, `--before`,
`--end-time` or historical-snapshot option.

Likewise, `portfolio activity` exposes token/type/cursor pagination but no server-side time cutoff.
Activity rows do include their own event `timestamp`, so a causal retrospective reconstruction candidate is:

```text
paginate wallet activity
-> keep only event.timestamp < target T0
-> recompute prior metrics ourselves
-> never use today's aggregate stats as if they existed at old T0
```

For a future live signal, a stats response can only be considered causal if its local `response_after`
precedes the decision cutoff.

### Top100 Traders by Profit — RETROSPECTIVE HYPOTHESIS MINING ONLY

```powershell
gmgn-cli token traders --chain sol --address <token_address> --limit 100 --order-by profit --direction desc --raw
```

This ranking selects wallets explicitly using realized/current outcome. It is therefore outcome-leaking by design
for launch-time prediction.

Safe use:

- study who captured large winners;
- inspect their entry/exit timing;
- find pre-T0 characteristics that could become new hypotheses;
- freeze those characteristics independently;
- validate them prospectively.

Unsafe use:

```text
top profitable traders
-> derive pattern
-> direct selector
```

Any derived signal must restart at discovery -> freeze -> fresh confirmation.

None of these four additions changes the currently frozen Participant Quality replication.


## Real read-only acquisition checkpoint — 2026-09-18

Sample directory observed locally:

`timing_samples/20260918-214527`

Initial token:

`5JGyhGrdY7hERN4Wkvnqu6wAv6EjW2QUFfkr4CU8pump`

Successful read-only capabilities and measured request durations from the first pass:

- Trenches new_creation: ~1244 ms
- Smart Money feed: ~1142 ms
- KOL feed: ~952 ms
- trending 5m: ~1010 ms
- token info: ~947 ms
- token security: ~992 ms
- Top100 holders: ~984 ms

The initial burst then hit an IP `RATE_LIMIT_EXCEEDED` on smart-degen holders.
This is operational evidence, not a scientific failure.

GMGN's current token-skill documentation assigns route weight 5 to both
`token holders` and `token traders`, versus weight 1 for token info/security.
The audit sampler was therefore changed to use pacing, one bounded cooldown-aware retry,
and resume/skip semantics rather than repeated requests.

After cooldown/resume:

- Top100 smart-degen holders: ~2037 ms
- Top100 traders by profit: ~1035 ms

The initial token-level capability sample is therefore complete.

Important:

- these are availability/request-duration measurements at local observation time;
- they do not prove predictive value;
- current holder/security/PnL snapshots cannot be backfilled to an old T0;
- the profit-ranked traders sample remains retrospective hypothesis-mining only;
- the next highest-information external capability is deployer prior history, using the creator
  address returned by the already-captured token-info snapshot.

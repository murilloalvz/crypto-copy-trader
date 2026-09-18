# GMGN real-sample analysis — 2026-09-18

## Scope

Source: local read-only bundle `timing_samples/20260918-214527`.

Audited token:

`5JGyhGrdY7hERN4Wkvnqu6wAv6EjW2QUFfkr4CU8pump`

Token T0:

`1789764125`

No private key, capital, selector change or frozen-protocol change was used.

This sample is an external-intelligence audit. Dynamic GMGN fields observed after token T0 are NOT backfilled as historical causal features.

## Decision

Next highest-information hypothesis family:

**DEPLOYER PRIOR QUALITY / DEPLOYER SPAM INTENSITY**

Classification:

- acquisition adapter: `APPLY_NOW_SAFE` when isolated/read-only;
- predictive feature family: `TEST_AS_HYPOTHESIS`;
- current late snapshot: discovery/schema evidence only, not validation.

## Deployer finding

Token Info mapped creator:

`49fAsUF3Nk8qbfpSrQND2sULKXanemwibYLGk5Jpn9bY`

At local observation time, Token Info reported:

- `stat.creator_created_count = 1247`.

Created Tokens independently reported:

- `inner_count = 1247`;
- `open_count = 0`;
- `open_ratio = 0`.

The aggregate count therefore cross-checks across two GMGN capabilities at this observation time.

Critical temporal caveat:

- Created Tokens request started ~4320s (~72m) after the audited token T0.
- `last_create_timestamp` is after T0, proving the creator kept launching after the audited token.
- Therefore the current aggregate 1247/0 cannot be assigned to T0.

The returned `tokens[]` contained 101 rows:

- 93 had immutable `create_timestamp < T0`;
- 1 was the audited token at T0;
- 7 were after T0.

Because the endpoint is capped and sorted by ATH, the returned rows are not a complete launch-history denominator. Still, among the returned rows alone:

- at least 9 launches were within the hour before T0;
- at least 92 launches were within the 24h before T0;
- the latest returned pre-T0 launch was only 117s earlier.

This is strong hypothesis-generation evidence for a deployer-spam / launch-frequency feature. Exact retrospective counts/cadence should be reconstructed from raw-chain creation events rather than inferred from the capped GMGN list.

### Retrospective ATH diagnostic only

Among the 93 returned pre-T0 rows:

- median current-observed ATH MC: ~$3.98k;
- 17 were >= $5k;
- 2 were >= $10k;
- maximum: ~$36.49k.

Do NOT use these figures as causal historical features. ATH was queried after T0 and can have changed after the target signal.

For future prospective snapshots, prior-best ATH can be evaluated only at the snapshot's local availability time and with the current token excluded.

## Holder finding

Top100 Holders returned only 4 rows in this late snapshot.

The largest row was:

- `addr_type = 2`;
- `exchange = pump`;
- `amount_percentage = 1`.

This is the Pump pool / curve account, not an ordinary wallet. Therefore naive Top1/TopN supply concentration from this response would be invalid for the audited stage.

The three non-pool wallets had zero current token balance by the late observation time. Current holder state therefore cannot reconstruct first-5s concentration.

Future holder experiments must:

1. snapshot prospectively;
2. exclude/segregate `addr_type=2` pool/exchange accounts;
3. state denominator explicitly (raw GMGN `amount_percentage` = total-supply share);
4. preserve exited wallets through our own event history instead of relying on current-holder survivorship.

No shared native funding source was observed among the three non-pool rows in this one late snapshot. Sample is far too small/late for an entity conclusion.

## Smart-degen holder finding

The prospective-style query mechanism works, but this late token query returned an empty list.

This does NOT prove no Smart Money participated early.

The label remains externally assigned and historical classification timing is not documented.

Classification remains:

`AUDIT_ONLY` until prospective point-in-time label snapshots are accumulated.

## Top traders finding

Profit-ranked Top100 Traders returned 4 rows.

This is outcome-selected by construction and remains:

`AUDIT_ONLY / RETROSPECTIVE HYPOTHESIS MINING`.

Do not derive a direct selector from profit-ranked winners.

## Smart Money feed timing

Real sample:

- 100 rows;
- 61 unique transactions;
- 35 unique makers;
- 22 unique tokens;
- latest event ~1.2s before request;
- median event age ~18.2s;
- oldest event age ~38.2s;
- 36 transaction hashes appeared in multiple rows/legs;
- maximum 3 rows for one transaction.

Implication:

GMGN Smart Money feed is operationally fresh enough to justify a later prospective hypothesis, but raw rows are not independent events. Any future feature must deduplicate transaction legs and preserve both event timestamp and local response-after availability.

The audited token was absent, but this feed was sampled ~63m after its T0; absence is not evidence about early participation.

## KOL feed timing

Real sample:

- 100 rows;
- 52 unique transactions;
- 22 unique makers;
- 22 unique tokens;
- latest event ~1.4s before request;
- median event age ~186s;
- oldest event age ~336s;
- 34 transaction hashes appeared in multiple rows/legs;
- maximum 4 rows for one transaction.

This is usable later as a participant lead, but lower priority than Deployer Prior Quality and requires the same deduplication / mutable-label safeguards.

## Trenches timing

`new_creation` returned 60 rows.

Creation-age distribution at request time:

- newest ~1.8s;
- median ~77.3s;
- oldest ~158.8s.

This supports keeping Trenches as a competitive launch timing/coverage benchmark. The audited token was already ~63m old at this query, so its absence is expected and says nothing about near-T0 GMGN coverage.

## Trending

The audited token was absent from the 5m trending snapshot taken ~63m after T0.

Trending has no historical ranking-event timestamp in this audit, so use only:

`rank observed at local_observed_at`

Classification remains `BENCHMARK`.

## Token Info / Security

Token Info is immediately useful for static/identity enrichment such as creator mapping and launchpad identity.

Dynamic token fields remain prospective-only.

Token Security exposed mint/freeze, burn/tax and structural fields, but this query was also ~63m after T0. Late structural state must not be backfilled into launch-time analysis.

Classification remains `TEST_AS_HYPOTHESIS` for future Structural Quality / Risk.

## Priorities after this bundle

1. **Deployer Prior Quality / Spam Intensity** — next.
2. Structural Quality — later incremental risk dimension.
3. Smart Money — later prospective participant hypothesis.
4. Trenches — synchronized competitive timing benchmark.
5. KOL — lower priority participant/social lead.
6. Holder snapshots — only after pool exclusion + point-in-time acquisition is solved.
7. Smart-degen holders — only after point-in-time label accumulation.
8. Profit-ranked traders — hypothesis mining only.

## Minimum causal Deployer experiment direction

Do not backfill this late GMGN snapshot into old captures.

Collect new research-plane snapshots only after a causal launch/signal candidate exists:

```text
token T0 / signal candidate
-> local request_before
-> token info (creator mapping)
-> local response_after
-> created-tokens creator snapshot
-> local response_after
-> immutable raw response
```

Candidate dimensions should remain separate initially:

- deployer created-total snapshot;
- deployer graduation count/rate snapshot;
- creator prior-best ATH as observed at snapshot, excluding current token;
- raw-chain prior-launch cadence (preferred source for strict launch frequency);
- time since previous launch from raw chain.

No threshold search. No single combined score.

Discovery must test incremental value beyond:

- Participant Quality;
- BUY acceleration;
- signed flow.

Only after discovery/robustness should one definition be frozen for fresh confirmation.

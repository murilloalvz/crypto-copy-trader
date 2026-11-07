# Crypto Copy Trader — Causal On-chain Token Hazard v37

Date: 2026-09-04  
Mode: PAPER / RESEARCH / READ ONLY

## Purpose

Validate a minimal causal token-hazard provider that does not depend on Solana Tracker credits and does not synthesize a proprietary risk score.

Provider identity:

- provider: `solana_rpc_mint_hazard_v1`
- purpose: `token_hazard_minimal_v1`

This is a NEW provider/version. It does not retroactively replace or reinterpret the v36 Solana Tracker result. The v36 live remains a provider failure caused by `HTTP 403: Insufficient credits for this request`.

## Frozen evidence

Core evidence comes from Solana RPC `getAccountInfo` with `encoding=jsonParsed` for the opportunity token mint:

- SPL Token program identity;
- classic Token vs Token-2022;
- decimals;
- raw supply;
- mint authority present/absent;
- freeze authority present/absent;
- Token-2022 extensions exposed by RPC;
- RPC context slot;
- terminal observation wall clock.

Auxiliary evidence comes from `getTokenLargestAccounts`:

- number of largest token accounts returned;
- raw sum of the first ten returned token accounts;
- top-10 token-account concentration as a percentage of the Mint raw supply;
- auxiliary RPC context slot.

### Nomenclature invariant

`getTokenLargestAccounts` returns token accounts, not unique beneficial owners. Therefore the metric is named exactly:

`top10_token_account_concentration_pct`

It MUST NOT be described as holder concentration, top holders, owner concentration, wallet concentration, insider concentration or bundler concentration.

When the metric is available, persisted quality flags explicitly include that it is token-account based and not holder based.

## Causal / failure semantics

- provider attempt `STARTED` is persisted before RPC I/O;
- attempts are at-most-once per run/episode/provider/purpose;
- one primary configured RPC endpoint is used by the hazard probe;
- each method receives one attempt only;
- no fallback/retry tail is used to borrow a later snapshot;
- `observed_at` is never earlier than episode T0;
- final attempts remain immutable;
- no artificial backfill;
- no later candle/quote substitutes for missing hazard evidence.

Core Mint RPC failure => `PROVIDER_ERROR`.

Missing Mint account => `UNAVAILABLE`.

Malformed/unsupported Mint state => `NORMALIZATION_ERROR`.

`getTokenLargestAccounts` is AUXILIARY. If it fails after valid Mint evidence was observed, the attempt remains `AVAILABLE` for core Mint evidence and the auxiliary error is persisted explicitly. This avoids deleting valid authority evidence merely because an optional concentration feature was unavailable.

Cross-slot inconsistencies are not hidden. If the top-10 account raw sum exceeds the Mint supply snapshot, concentration is withheld and the raw sum plus an explicit cross-slot/supply-mismatch quality flag remain persisted.

## What v37 explicitly does NOT infer

The provider does not synthesize:

- risk score;
- rug probability or `rugged` label;
- holder identity;
- dev ownership;
- sniper classification;
- bundler classification;
- insider classification;
- BUY/SELL decision.

Those concepts require separate evidence and validation.

## Live smoke

`unified_market_onchain_hazard_smoke_v37.py` retains the proven v34/v33 market path and attaches a bounded off-path provider queue only after first-time episode admission.

Default cohort:

- first 12 new episodes;
- 2 hazard workers;
- hazard RPC timeout 3 seconds;
- no Jupiter;
- no Solana Tracker;
- no signing;
- no execute;
- no transfer;
- no `decision_as_of` freeze;
- no official forward-outcome scheduling.

## Formal v37 provider gate

Provider classification is `PASS_CAUSAL_ONCHAIN_HAZARD_PROVIDER` only when:

1. `selected > 0`; zero is `INCONCLUSIVE_NO_SAMPLE`;
2. terminal coverage is 100%;
3. `CONFIG_MISSING = 0`;
4. hazard worker errors = 0;
5. reused attempts = 0 on the fresh run;
6. causal clock violations = 0;
7. at least one `AVAILABLE` hazard observation exists;
8. every `AVAILABLE` observation has complete core Mint evidence: token program, decimals, supply, mint-authority presence and freeze-authority presence are all known;
9. any persisted top-10 token-account concentration is within `[0,100]`;
10. any persisted concentration carries the explicit not-holder semantic flag.

Auxiliary concentration availability is intentionally NOT a PASS threshold. Its failure remains measurable and explicit.

## Same-run systems gate

The existing 11-condition v30/v34 latency gate is evaluated independently in the same run. v37 provider PASS does not waive systems latency, and systems latency PASS does not imply hazard predictive value or profitability.

## Scientific interpretation

A v37 PASS means only:

> the project can causally and auditably capture a minimal set of on-chain token hazard descriptors without paid Solana Tracker credits while preserving the proven acquisition path.

It does NOT mean:

- these features predict returns;
- an authority being present/absent is a validated trading threshold;
- concentration is causal edge;
- the strategy is profitable;
- funded executability passed;
- shadow/live trading is released.

Predictive use of these features must be tested only after the final `decision_as_of` protocol and executable forward outcomes are available.

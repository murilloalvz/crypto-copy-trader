# On-chain Minimal Token Hazard v37 — Protocol

Date: 2026-09-04
Mode: PAPER / RESEARCH / READ ONLY

## Motivation

The v36 Solana Tracker live smoke ended with 12/12 `PROVIDER_ERROR` because the account returned HTTP 403 `Insufficient credits for this request`. This is an external provider-credit blocker, not evidence that the causal hazard plumbing is broken.

The project should not require a paid proprietary risk score merely to establish the minimum causal token-hazard gate. Solana mint state exposes objective controls that are directly relevant to token risk and can be read from the configured RPC.

## Provider

- provider: `solana_rpc_mint_hazard_v1`
- purpose: `token_hazard_minimal_v1`
- RPC method: `getAccountInfo`
- encoding: `jsonParsed`
- commitment: `confirmed`
- retry policy for the probe: one client call attempt per endpoint path; existing SolanaClient fallback behavior remains explicit through PROVIDER_ERROR if all configured endpoints fail.

The attempt is persisted as STARTED before RPC I/O and is at-most-once per acquisition run + episode + provider + purpose.

## Causal fields

When the mint account is available and parsed as a mint, persist:

- provider observation time (`observed_at`), never before episode first trigger observation;
- RPC context slot;
- mint owner program;
- Token Program vs Token-2022 classification;
- decimals;
- raw supply;
- mint authority present/absent/unknown;
- freeze authority present/absent/unknown;
- Token-2022 extension names when exposed by the RPC parser;
- explicit data-quality flags.

## What this provider does NOT claim

It does not synthesize or imitate Solana Tracker's proprietary/aggregated fields:

- risk score;
- rugged classification;
- sniper percentage;
- bundler percentage;
- insider percentage;
- dev percentage;
- Jupiter verification.

Those may remain optional enrichment from a separate provider. Missing advanced enrichment must never erase an episode or be interpreted as safe.

## Scientific interpretation

`AVAILABLE` means only that the minimum on-chain mint-state hazard evidence was causally observed and persisted. It does not mean the token is safe.

A remaining mint authority is a directly observable capability to mint more units. A remaining freeze authority is a directly observable capability to freeze token accounts. Token-2022 may add additional control surfaces through extensions, so extension visibility is retained rather than flattened into a synthetic score.

## Future concentration metric

`getTokenLargestAccounts` can provide the 20 largest token accounts for a mint. This is not automatically equivalent to top holders because token accounts are not owner identities and liquidity/program accounts can be present. Therefore v37 does not label this result as `top10 holders` until account ownership and exclusions are causally resolved.

## Minimal provider gate

For a fresh live cohort:

1. selected episodes > 0; otherwise `INCONCLUSIVE_NO_SAMPLE`;
2. terminal coverage = 100%;
3. reused attempts = 0;
4. worker errors = 0;
5. causal clock violations = 0;
6. at least one `AVAILABLE` minimal hazard artifact;
7. missing mint / RPC / normalization failures remain explicit terminal evidence;
8. no proprietary risk field is fabricated;
9. the retained v34 unified market latency gates are evaluated independently in the same run.

This protocol changes the implementation/provider choice for the minimum hazard gate only. It does not change the frozen detector, episode T0, funded executable quote gate, decision_as_of ordering, forward outcome ordering, or release criteria for shadow/live money.

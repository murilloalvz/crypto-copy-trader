# Direct Funding Link v61 — causal integrity evidence protocol

Date: 2026-09-08
Mode: **PAPER / RESEARCH / READ ONLY**

## Research purpose

Participation concentration, repeated wallets and same-block buying are not sufficient evidence of insider activity. v61 introduces a stronger but still narrowly named primitive: a **direct on-chain transfer relationship between a token deployer and a participant that occurred before launch and was known by the research cutoff**.

The output is funding/link evidence. It is not a fraud verdict.

## Motivation

External Solana research on coordinated launch farming reduced false positives by restricting its high-confidence sample to same-block snipers that had a direct SOL-transfer link with the deployer before launch. That design motivates v61's semantics, but does not make the external result an internal project finding.

## Required reference

A launch reference contains:

- chain namespace/reference;
- token address/mint;
- deployer wallet;
- launch chain time;
- first observed launch/deployer clock;
- immutable reference key.

The launch/deployer identity itself must already be known by the requested `as_of` cutoff.

## Transfer semantics

A transfer observation contains:

- chain identity;
- source wallet;
- destination wallet;
- chain time;
- first observed time;
- asset kind (`native` or `token`);
- exact positive raw amount;
- optional token address for token transfers;
- optional transaction key, block number and event index.

Self-transfers are excluded from the direct-funding primitive.

## Causal eligibility

A deployer/participant transfer counts as pre-launch link evidence only when:

1. source and destination are exactly the deployer/participant pair;
2. transfer is on the same chain as the launch;
3. `transfer.chain_time < launch.chain_time`;
4. `transfer.observed_at <= as_of`;
5. launch/deployer identity was itself observed by `as_of`.

A transfer that happened historically before launch but is only discovered after the research decision is explicitly excluded from that earlier decision.

A post-launch transfer is not rewritten as pre-launch funding.

## Direction and asset type remain explicit

The following evidence classes are deliberately distinct:

- `DIRECT_NATIVE_DEPLOYER_TO_PARTICIPANT_PRELAUNCH`
- `DIRECT_TOKEN_DEPLOYER_TO_PARTICIPANT_PRELAUNCH`
- `DIRECT_PARTICIPANT_TO_DEPLOYER_PRELAUNCH`
- `DIRECT_PRELAUNCH_LINK`
- `NO_CAUSALLY_KNOWN_DIRECT_PRELAUNCH_LINK`

Native deployer-to-participant funding is not silently conflated with a participant paying the deployer or with a token transfer.

## What v61 proves

When the strongest class is present, v61 proves only that:

- the deployer directly transferred native chain currency to that participant before launch;
- that transfer was causally available by the research cutoff.

This is materially stronger provenance evidence than event-count concentration.

## What v61 does NOT prove

It does not prove:

- both addresses share an owner;
- insider intent;
- wash trading;
- manipulation;
- a sniper strategy;
- profitable extraction;
- that the participant's token trade was funded specifically by that transfer;
- that absence of a direct link means independence.

Multi-hop funding, exchange withdrawals, shared funders and account ownership remain unresolved.

## Future integration path

A future integrity study may join v61 with:

- launch/deployer identity;
- participant's first token entry;
- same-block / launch-delay evidence when block ordering is reliable;
- exit behavior;
- market-first opportunity episodes;
- outcome labels kept in a separate analysis layer.

Before any economic use, pre-register the participant universe, timing window, exact funding class and control group.

## Cross-chain use

v61 is chain-aware through the v59 identity contract. It can represent Solana native SOL links and EVM native ETH links without pretending the execution semantics are identical.

Token transfers remain distinguishable from native funding. Chain-specific parsers/adapters must preserve the native transfer and observation clocks before this evidence can be populated.

## Current implementation boundary

The repository currently does **not** have an approved generic live transfer/funding collector wired into the market-first pipeline. v61 is a pure evidence contract and analyzer only.

Do not mine legacy `raw_json` and assign present-day discovery time to historical transfers as though they had been known live.

## Boundary with v55

v61 cannot be injected into the already-running v55 experiment. It cannot rescue a v55 failure on the same sample.

## Promotion sequence

`transfer/deployer observability audit -> causal coverage -> descriptive integrity study -> one frozen hypothesis -> fresh prospective holdout -> incremental-value test`

No direct link is a live-trading authorization.
# Opportunity Wallet Convergence v60 — causal evidence protocol

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Research question

Conditional on a market-first opportunity episode already existing, does participation by wallets with pre-frozen evidence of profitable behavior add useful information about the episode's future economics?

This is deliberately different from copy trading.

`market detects first -> episode exists -> frozen-wallet participation becomes post-episode evidence`

A wallet cohort can never be an acquisition whitelist.

## Why convergence, not one Wallet Score

Public 2026 wallet data shows profitable memecoin traders use materially different execution styles: some trade thousands of tokens at high frequency, some place fewer/larger bets, and some rely on a small number of convex winners. The existing repository already models holding, frequency, scale-in, staged exits, re-entry and venue mix through `wallet_strategy_lab`.

v60 therefore preserves wallet identity and strategy diversity instead of collapsing all wallets into one opaque score.

## Cohort freeze rule

A wallet may count as v60 evidence only when its cohort membership was frozen strictly before the episode `as_of` clock.

A wallet that becomes profitable or is added to a leaderboard after the episode cannot be retroactively counted.

Cohort membership stores:

- wallet address;
- cohort key;
- freeze timestamp;
- optional strategy signature produced from pre-period behavior;
- evidence-version identifier.

No current/future PnL is read by the convergence feature builder.

## Initial public Solana study seeds

The following addresses are research seeds drawn from a public July 2026 KOL leaderboard and are **not copy-trading recommendations or an approved live cohort**:

- Cented — `CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o`
- Theo — `Bi4rd5FH5bYEN8scZ7wevxNZyNmKHdaBcvewdPFxYdLt`
- Cupsey — `2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f`
- Decu — `4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9`
- Pain — `J6TDXvarvpBdPXTaTU8eJbtso1PUCYKGkVtMKUUY8iEa`
- Kadenox — `B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC`
- Trunoest — `ardinRsN1mNYVeoJWTBsWeYeXvuR9UUDGMsCDKpb6AT`
- Kev — `BTf4A2exGK9BCVDNzy65b9dUzXgMqB4weVkvTMFQsadd`

Before any prospective use, the project must independently reconstruct each wallet's pre-period evidence and freeze the final cohort. A public leaderboard entry alone is insufficient.

## Causal clock

For an episode at `as_of`, a trade is eligible only if:

- it belongs to the same acquisition run and token;
- its chain time is inside the frozen lookback window and `<= as_of`;
- its `observed_at <= as_of`;
- its wallet belongs to a cohort frozen strictly before `as_of`.

An older transaction discovered after the decision is excluded.

## Descriptive evidence

v60 may report:

- eligible cohort size;
- cohort event count;
- cohort buy/sell event counts;
- unique cohort wallets;
- unique cohort buy/sell wallets;
- buy/sell wallet overlap;
- repeated cohort event share;
- share of known-wallet market events attributable to cohort members;
- first/last cohort buy offset inside the window;
- unique strategy-signature count when signature coverage is complete.

These are evidence fields, not a score.

## Independence caveat

Two distinct addresses are not automatically two independent traders.

`unique_strategy_signature_count` only measures observed behavioral diversity. It does not prove independence. Future funding/deployer/transfer graph work is required before claiming economic independence between wallets.

## Discovery windows

Future v60 discovery may use the already-natural market windows `30s`, `60s`, and `300s`. No return-optimized window may be selected after looking at outcomes. A later holdout must freeze exactly one hypothesis and its window before fresh acquisition.

## Required controls

If convergence is studied economically, compare against controls rather than merely reporting winner examples:

1. same-wallet ordinary/losing entries where available;
2. market episodes without frozen-cohort participation;
3. behaviorally comparable placebo wallets using `wallet_placebo_matching`;
4. strategy-signature diversity so one high-frequency archetype does not dominate by event count.

## Forbidden interpretations

v60 cannot conclude:

- a cohort wallet should be copied;
- a wallet is independent merely because the address differs;
- multiple buys are multiple confirmations if they come from one wallet;
- a profitable wallet today was known to be profitable in the past;
- convergence is bullish before a prospective economic holdout.

## Boundary with v55

v60 is not added to the currently running v55 candidate set. v55 remains frozen. Its result cannot be rescued by wallet convergence on the same sample.

## Promotion path

`descriptive convergence -> causal coverage audit -> matched discovery -> one frozen convergence hypothesis -> fresh prospective holdout -> executable/shadow economics`

No live-money path exists from v60 alone.
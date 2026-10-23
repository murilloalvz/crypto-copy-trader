# Pons v64 — Exact Causal Curve Progress Protocol

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Motivation

Flow60 on Solana attempted to proxy movement maturity from recent event count and failed prospectively. Pons v2 exposes a more direct structural lifecycle variable: the bonding curve's real quote reserve relative to its launch-specific graduation threshold.

The contract states that the curve reaches the graduation point when its real quote reserve reaches `graduationThreshold`; the sellable token floor and quote threshold represent the same launch point.

## Why external trade reconstruction is not authoritative

Pons v2 can execute internal buybacks during fee sweeps. A successful internal buyback keeps its quote amount in the curve's tradeable reserve while removing memecoin tokens from the curve.

Therefore this is NOT accepted as exact progress:

`sum(external buy net quote) - sum(external sell gross quote)`

unless every internal reserve-moving event is also proven complete.

v64 instead uses an exact same-block contract-state observation.

## Authoritative state inputs

For one coherent block/state reference collect:

- token address;
- `graduationThreshold`;
- `realQuoteReserve()`;
- `sellableTokens()`;
- `readyToGraduate()`;
- `graduated()`;
- block number;
- block/chain time;
- collector `observed_at`;
- provider identity.

Do not combine values read from different blocks into one v64 observation.

## Causal cutoff

A state observation can affect an `as_of` snapshot only when:

- `state.chain_time <= as_of`; and
- `state.observed_at <= as_of`.

A historical state fetched later cannot be backdated into an earlier decision.

## Progress definition

For an active/non-graduated curve:

`reserve_progress_pct = 100 * real_quote_reserve_raw / graduation_threshold_raw`

`remaining_quote_to_threshold_raw = max(threshold - reserve, 0)`

`remaining_quote_to_threshold_pct = 100 * remaining / threshold`

Do not clamp progress silently. Values above 100% are flagged for audit.

## Trading-state semantics

Pons closes trading once the sellable allocation is exhausted, even if automatic factory graduation has not completed yet.

Therefore:

- `graduated=False`, `ready_to_graduate=False` -> curve may be tradable;
- `graduated=False`, `ready_to_graduate=True` -> `CURVE_READY_TO_GRADUATE_TRADING_HALTED`;
- `graduated=True` -> curve reserves may already be drained and curve progress is no longer meaningful.

A post-graduation drained reserve must NOT be reported as 0% progress.

## Internal consistency

On an active non-graduated curve, `ready_to_graduate` must agree with `sellable_tokens_raw == 0` because that is the contract definition. Contradictory same-block reads fail closed.

The state threshold must equal the threshold frozen from the launch event/configuration. Mismatch fails closed.

## Code

- `src/pons_curve_state_progress_v64.py`
- `tests/test_pons_curve_state_progress_v64.py`

## What v64 proves

A green implementation proves only that the project can represent a causal, same-state measurement of Pons curve progress without using noisy event count as a maturity proxy and without being fooled by post-graduation reserve drainage.

It does NOT prove:

- early or late curve progress is profitable;
- graduation predicts positive returns;
- a particular percentage is a buy threshold;
- Solana Flow60 failure is rescued;
- Pons has a validated economic edge.

Any future economic hypothesis involving curve progress must be discovered on a dedicated sample and frozen before a separate untouched prospective holdout.

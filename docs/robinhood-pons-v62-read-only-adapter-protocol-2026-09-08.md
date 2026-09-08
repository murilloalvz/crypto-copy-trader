# Robinhood / Pons v62 — Read-Only Causal Adapter Protocol

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Purpose

Prepare Robinhood Chain / Pons v2 as the first non-Solana research adapter without changing the active Solana v55 acquisition, detector, economics, or holdout contract.

This milestone is a normalization and lifecycle-semantics milestone only. It does not collect a live economic sample and does not establish a Robinhood edge.

## Chain identity

- namespace: `eip155`
- Robinhood Chain mainnet chain id: `4663`
- native gas asset: ETH
- Pons v2 pre-graduation venue: one bonding-curve contract per launch
- Pons v2 post-graduation venue: Uniswap v4

The adapter consumes already-decoded provider/on-chain observations. It does not embed a provider credential, submit transactions, sign, or trade.

## Important protocol semantics frozen before any Robinhood study

### Launch-specific graduation threshold

Do NOT assume every Pons launch graduates at 4.2 ETH.

Native-quoted launches can use the native ETH threshold, while ERC-20 quote assets use their own raw threshold in the quote asset's decimals. The authoritative threshold belongs to the launch event/configuration and must be persisted per launch.

### Two-phase graduation

Pons v2 graduation is not one atomic market transition.

1. `launch_swept`: the curve is drained/halts trading.
2. `pool_graduated`: the Uniswap v4 pool is created and seeded.

There can be a seconds-to-minutes interval between these phases. During that interval the token must be represented as `SWEPT_NOT_TRADABLE`, not as curve-trading and not yet as graduated.

The generic v59 lifecycle adapter receives `graduated` only after completed `pool_graduated`. The intermediate swept state remains explicit in the Pons-specific v62 timeline.

### Causal availability

For a lifecycle event to affect an `as_of` snapshot, BOTH must hold:

- `event.chain_time <= as_of`
- `event.observed_at <= as_of`

Historical events discovered later cannot retroactively alter an earlier research decision.

### Identity

- use exact token contract address, never symbol alone;
- event identity includes chain namespace/reference + token + native transaction/log identity;
- EVM addresses are canonicalized lowercase;
- transaction hash + log/event index are retained.

## v62 code

- `src/robinhood_pons_adapter_v62.py`
- `tests/test_robinhood_pons_adapter_v62.py`

The adapter normalizes:

- Pons launch -> v59 `market_started` at `pons_v2_curve`;
- Pons curve BUY/SELL -> v59 unified trade;
- completed Pons pool graduation -> v59 `graduated` at `uniswap_v4`;
- Pons sweep -> Pons-specific `SWEPT_NOT_TRADABLE` lifecycle state only.

Raw quote/token amounts are retained in the Pons-specific trade object even when USD notional/price is unavailable. Missing USD economics remain missing.

## What v62 proves

If tests and CI pass, v62 proves only that the project can represent Pons launch/curve/graduation observations without silently imposing Solana semantics or collapsing the two graduation phases.

It does NOT prove:

- economic edge on Robinhood Chain;
- Pons graduation predicts positive returns;
- a quote asset is equivalent to ETH;
- the Solana detector thresholds transfer to Robinhood;
- route execution or fill quality;
- wallet profitability or copyability;
- live trading readiness.

## Future Robinhood research sequence

Only after the active Solana v55 result is closed:

1. provider/read-path validation;
2. systems/coverage-only Robinhood acquisition;
3. lifecycle dataset audit;
4. descriptive study of stage at entry / curve dynamics;
5. one pre-registered hypothesis;
6. separate untouched prospective holdout;
7. executable/shadow work only if economics survive.

No Solana threshold should be copied to Robinhood merely for convenience. Cross-chain replication means testing whether the economic concept generalizes, not forcing identical parameter values.

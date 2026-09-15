# Solana Launch Burst V4 — Freeze Status

Status: `FROZEN_PENDING_FUNDED_TAKER_PREFLIGHT`

This document freezes the current Solana Launch Burst prospective economic track at the maximum evidence obtained without funding the controlled taker fixture.

## Current state

- Systems/timing: **PASS / CLOSED**.
- Provider pricing: **CONFIRMED**.
- Provider transaction assembly capability: **CONFIRMED** using a diagnostic-only public funded control.
- Scientific hypothesis: **NOT REJECTED**.
- Prospective economic verdict: **INCONCLUSIVE**.
- Current blocker: the frozen controlled `JUPITER_TAKER_PUBLIC_KEY` has `0 USDC` and `0 SOL`, so the official funded-taker preflight fails closed before Jupiter assembly probes.

## Frozen hypothesis and contract

No changes are allowed while this status is active:

- stratum: `pump_launch`;
- primary window: `5s`;
- feature: `signed_flow_over_event_reserve`;
- selector: `>= 0.08`;
- confirmation: none;
- entry latency: `+2s`;
- notional: `US$25`;
- exit: `+60s`;
- frozen costs/slippage remain unchanged;
- BUY still requires an assembled candidate transaction;
- SELL remains route-only exact bought quantity;
- failed exit remains `-100%` under the frozen route-paper contract;
- no outcome-based retuning, rescue selector, alternate threshold, new feature, or adaptive top-up.

Frozen route contract hash:

`3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d`

Frozen funded-taker fixture hash:

`e7bde615886a9674a9f67cccca6be12aefa833e730a4076447ce60530d2e4ba8`

## Evidence that is already closed

The earlier V4 systems-only live established the timing path as valid under the observed live load. The first economic acquisition was not a signal failure: 57/57 admitted entries became `ROUTE_ONLY_UNEXPECTED` because the taker fixture could not satisfy transaction assembly.

Subsequent read-only diagnostics established:

1. the frozen taker is correctly identified by the fixture and has zero input balance and zero SOL;
2. Jupiter returns valid pricing for the frozen taker but cannot assemble the BUY because wallet state is insufficient;
3. an independently discovered public funded control produced `transaction_present=true` for both:
   - USDC -> wrapped SOL control; and
   - USDC -> the representative Burst token;
4. therefore Jupiter/provider assembly capability is confirmed independently of the unfunded controlled taker.

The public funded control is diagnostic-only and MUST NOT be treated as the official prospective taker or as economic evidence.

## Resume condition

Do not resume the 900s prospective economic live until all of the following are true **before acquisition starts**:

1. the same frozen controlled taker remains selected;
2. input balance is at least `25 USDC`;
3. operational SOL balance is at least `0.01 SOL`;
4. no adaptive post-signal top-up has occurred;
5. `benchmarks.launch_burst_prospective_route_live_v4.funded_taker_preflight` returns:

`PASS_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT`

and both read-only probes show assembled transactions for:

- known-liquid control; and
- representative Burst token.

Only after that PASS may the unchanged V4 economic live be repeated.

## Outcome routing after resume

- **Economic PASS:** hypothesis supported at the route-paper level; proceed to execution-realism validation, not retuning.
- **Economic FAIL:** close the frozen Solana Launch Burst hypothesis; no rescue tuning.
- **INCONCLUSIVE due support/coverage:** extend acquisition/sample only, without changing the frozen selector or contract.
- **SYSTEMS / provider fixture failure:** repair only the minimum operational blocker, preserving the frozen economic hypothesis and contract.

## Current decision

Until the funded-taker preflight passes, the Solana Launch Burst prospective economic track is intentionally paused. No additional diagnostics, tailfixes, selector work, new features, or economic live reruns are justified by the current evidence.

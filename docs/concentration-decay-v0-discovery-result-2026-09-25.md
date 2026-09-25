# H_ORGANICITY_CONCENTRATION_DECAY_V0 — Discovery Result — 2026-09-25

Status: ITERATE / ONE FRESH CONFIRMATION AUTHORIZED / NO LIVE MONEY

## Source

The hypothesis and its semantic threshold were frozen before the 2026-09-25 Launch Burst capture:

- feature: `mf_top_wallet_gross_share_delta_pct_points_late_minus_early`
- rule: `<= 0.0` percentage points
- meaning: top-wallet gross-flow concentration did not increase from the early 2.5s half to the late
  2.5s half of the frozen 5s decision window
- primary outcome: fixed +60s route-shadow net return
- threshold search: forbidden

The evaluated source capture was:

`launch_burst_prospective_route_live_v4-1790305374-3b6738bb33`

Causal reconstruction passed exact parity for all 311 complete episodes.

## Discovery population

- baseline admitted: 70
- feature available: 52
- feature coverage: 74.285714%
- candidate selected: 24
- signal frequency among feature-available baseline: 46.153846%

Route-usable:

- feature-available baseline: 34
- candidate: 19

## Economics

Feature-available baseline:

- mean net return: -27.303304%
- median net return: -27.315709%
- mean without best trade: -31.184430%
- p10: -97.609200%
- profit factor: 0.251605
- win rate: 17.647059%
- max drawdown: USD 233.278045

Candidate (`delta <= 0 pp`):

- mean net return: -20.604627%
- median net return: -25.198550%
- mean without best trade: -27.347876%
- p10: -93.624534%
- profit factor: 0.439755
- win rate: 26.315789%
- max drawdown: USD 107.282724

## Frozen decision

`ITERATE`

Reason:

`relative_separation_is_coherent_but_absolute_robust_profitability_not_yet_met`

Passed relative gates:

- minimum sample and frequency;
- candidate mean > baseline;
- candidate median > baseline;
- candidate profit factor > baseline;
- candidate mean-without-best > baseline;
- candidate p10 >= baseline.

Failed absolute KEEP gates:

- candidate mean > 0;
- candidate profit factor > 1;
- candidate mean-without-best > 0.

## Disposition

Exactly one fresh confirmation of the unchanged `<= 0 pp` rule is authorized.

No threshold retuning, subgroup rescue, feature combination, horizon substitution or same-sample
promotion is permitted.

If the fresh confirmation has sufficient support but does not meet every frozen absolute KEEP gate,
the selector candidate is closed as KILL. A second ITERATE is not authorized.

If fresh support is insufficient, the result is INCONCLUSIVE and no automatic extra capture is
authorized.

If every frozen KEEP gate passes on the fresh confirmation, the rule advances only to a
selection-edge candidate that still requires an independently preregistered replication before any
mature-edge or live-money claim.

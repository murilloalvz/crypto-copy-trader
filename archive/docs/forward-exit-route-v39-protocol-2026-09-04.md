# Forward Exit Route-Only Probe v39 — Protocol

Date: 2026-09-04

Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Prepare the +5m/+15m/+60m forward-exit observation path without weakening the frozen economic gate while funded entry remains blocked.

The key distinction is:

- **route-only forward observation**: Jupiter route/price evidence obtained without a taker; useful for research plumbing, never an official executable outcome;
- **official executable forward outcome**: requires an actually assemblable SELL path for a position/taker that can validly supply the token. This remains blocked until the position/execution preconditions exist.

v39 must never promote route-only evidence into official economic labels.

## Frozen lineage

The route-only SELL amount is taken from the exact `output_amount_raw` of the prior official executable BUY quote associated with the frozen decision.

A v39 probe is eligible only when the scheduled forward outcome is still `PENDING` and the prior entry lineage has:

1. Jupiter entry provider attempt `AVAILABLE`;
2. provider completion no later than the prior `decision_as_of`;
3. assembled transaction evidence on the entry attempt;
4. persisted executable BUY quote;
5. BUY quote observed no later than `decision_as_of`;
6. matching token mint;
7. persisted token decimals and positive raw token output amount.

No legacy paper position or synthetic amount may substitute this lineage.

## Target clock

The probe cannot start before the exact scheduled target:

`target_at = decision_as_of + horizon_seconds`

Frozen horizons remain:

- 300s;
- 900s;
- 3600s.

The route quote observation must satisfy:

`quote.observed_at >= target_at`

Target lateness is persisted and reported rather than hidden.

## Provider semantics

Provider: `jupiter_swap_v2_order`

Purpose per horizon:

`forward_exit_route_only_<horizon>s_v1`

The call uses:

- input mint = researched token;
- output mint = USDC;
- amount = exact raw token amount from prior BUY quote;
- `taker=None`;
- frozen/default slippage 100bps unless a future protocol explicitly changes it.

No signing, `/execute`, transfer or private key exists in this path.

## Fail-closed rule

Because v39 is intentionally route-only, a successful quote must remain:

`executable=False`

If Jupiter unexpectedly returns an assembled transaction without a taker, v39 classifies the observation as a normalization/protocol error instead of silently upgrading it.

## Storage separation

v39 may persist:

- provider attempt;
- causal SELL quote artifact;
- route/router/price-impact metadata;
- exact target lateness.

v39 MUST NOT call `complete_opportunity_forward_outcome(..., status="AVAILABLE")`.

The official forward-outcome store remains unchanged and retains the rule:

`AVAILABLE` requires an executable quote artifact.

Therefore:

`PASS_ROUTE_ONLY_FORWARD_OBSERVABILITY != PASS_OFFICIAL_EXECUTABLE_FORWARD_OUTCOME`

## Classifications

- `INCONCLUSIVE_NO_DUE_OFFICIAL_FORWARD_OUTCOMES`: no frozen/scheduled due sample exists.
- `PASS_ROUTE_ONLY_FORWARD_OBSERVABILITY`: at least one due outcome produced valid non-executable route evidence with no official-completion violation.
- `INCONCLUSIVE_NO_AVAILABLE_FORWARD_ROUTE`: due samples existed but none produced an AVAILABLE route artifact.
- `FAIL_ROUTE_ONLY_EXECUTABILITY_SEMANTICS`: route-only evidence was incorrectly executable.
- `FAIL_FORWARD_ROUTE_PLUMBING`: runner/internal semantics failed or route-only path attempted to complete official outcomes.

## What v39 does NOT prove

A route-only PASS does not prove:

- the wallet owns the token;
- a SELL transaction can be assembled for the eventual position;
- a transaction would land;
- fill price;
- profitability;
- economic edge;
- shadow/live readiness.

## Promotion order retained

When funding/position preconditions become available:

1. funded executable BUY gate;
2. freeze official `decision_as_of`;
3. schedule exact +5/+15/+60 outcomes;
4. collect official executable SELL evidence without route-only substitution;
5. evaluate quote-to-quote economics;
6. later landing/fill evidence as a separate stronger layer.

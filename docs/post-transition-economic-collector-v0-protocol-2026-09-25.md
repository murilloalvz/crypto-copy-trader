# Post-Transition Economic Collector V0 Protocol — 2026-09-25

Status:

`IMPLEMENTED / CONTRACT FROZEN FOR IMPLEMENTATION / FRESH ECONOMIC DISCOVERY BLOCKED`

## Purpose

Add the first economic-evaluation layer after
`PASS_POST_TRANSITION_PROSPECTIVE_LINEAGE_READINESS_V1` without opening a fresh
economic sample before the full outcome/censoring protocol is frozen.

This layer does not change the Market-First selector. The Post-Transition cohort
remains all complete, lineage-eligible transition+30s snapshots with no selector
predicates. `structural_reacceleration_candidate` remains diagnostic only.

## Frozen entry / route contract

- decision: PumpSwap transition observed_at + 30 seconds;
- paper entry target: decision + 2 seconds;
- maximum quote age: 15 seconds;
- maximum quote wait: 5 seconds;
- entry requires an assembled transaction / executable BUY quote;
- notional: US$25;
- provider price impact must be present and <= 2 percentage points;
- entry fee: 20 bps;
- exit fee: 20 bps;
- entry adverse slippage: 100 bps;
- exit adverse slippage: 100 bps;
- route-path SELL marks are route-only and must use the exact entry output
  quantity.

Entry-provider missingness is coverage/missingness, not a synthetic zero-return
trade. After a usable entry, a standardized fixed-horizon exit that cannot be
routed retains the frozen -100% unexitable semantics.

## Standardized outcomes

`FIXED_60` remains the PRIMARY standardized label.

`FIXED_300` remains EXPLORATORY and may never replace `FIXED_60` based on the
observed result.

## Market Path

The collector records every observed post-entry SELL route mark, including
non-routeable marks and their reason. Routeable marks expose gross return, net
return, provider price impact, liquidity and causal clocks.

Derived outcomes include:

- MFE;
- MAE;
- time to MFE;
- time to MAE;
- observed-grid time above +10%, +20%, +50%, +100%, +200%;
- observed-grid time below -10%, -20%;
- routeability share/path;
- provider price impact path.

"Time above/below" is the sum of each routeable quote's declared
`resolution_seconds`. Missing periods are not interpolated.

MFE/MAE are descriptive outcomes only. MFE is never a simulated exit.

## Independent TP policies

The implementation supports three independent causal policies:

- `TP50`: first routeable observed mark with net return >= +50%;
- `TP100`: first routeable observed mark with net return >= +100%;
- `TP200`: first routeable observed mark with net return >= +200%.

A crossing at a non-routeable mark does not count. A later routeable crossing
may count. The policies are reported separately; there is no best-TP-per-trade
oracle.

## Dynamic exits

The following interfaces are deliberately `NOT_ARMED`:

- `DECELERATION_EXIT`;
- `PROFIT_PROTECTION_EXIT`;
- `HYBRID_HUMAN_EXIT`.

The already-existing `human_assisted_exit_v0` policy is retrospective-only and
is not silently promoted into this prospective line.

Future dynamic policies may consume only causal state available at each update,
including price, peak/giveback, buy/sell/event rates, signed flow, unique
participants, concentration/delta, routeability, impact and liquidity.

## Censoring / maximum horizon blocker

No semantically compatible Post-Transition maximum horizon was already frozen
for these new TP/dynamic outcomes.

Therefore this implementation does NOT invent one.

The contract records:

`maximum_horizon_seconds = null`

and:

`fresh_economic_discovery_authorized = false`

Fresh economic discovery must remain fail-closed until a maximum
horizon/censoring policy is explicitly frozen before the sample is opened.

This is an intentional scientific blocker, not a systems failure.

## Provider preflight

`provider_preflight.py` performs one read-only Jupiter `USDC -> WSOL` route
probe using the frozen US$25 notional and 100 bps slippage. It uses no
Post-Transition cohort token, submits no transaction, writes no economic
outcome and leaves fresh discovery blocked.

Passing this preflight proves provider route availability/normalization only.
It is not economic evidence.

## Edge claims

This implementation proves no Signal Edge, Human-Assisted Edge or Autonomous
Edge. It only makes the next fresh collection auditable once the unresolved
censoring horizon is frozen.

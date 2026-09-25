# Post-Transition Economic Collector V0 Protocol — 2026-09-25

Status:

`IMPLEMENTED / ROUTE-ONLY CONTRACT FROZEN / TRANSPORT HEALTH HARDENED / FRESH OUTCOMES NOT YET OPENED`

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
- entry uses a route-only BUY quote; no assembled transaction or funded wallet is required during research;
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

## Censoring / maximum horizon

The maximum economic observation horizon is now frozen **before any fresh Post-Transition economic outcome**:

`maximum_horizon_seconds = 300`

Policy status:

`FROZEN_300S_RIGHT_CENSORING`

Semantics:

- the censoring clock starts from the usable entry quote's `observed_at`;
- Market Path, MFE/MAE and TP50/TP100/TP200 consume only causal route marks with offset <= 300s;
- no missing interval is interpolated;
- no TP crossing after +300s counts for that episode;
- a TP not reached by +300s is `NOT_REACHED`, not a fabricated exit;
- dynamic policies that remain open at +300s are `CENSORED_STILL_OPEN` once prospectively armed;
- there is **no forced time exit at +300s**;
- `FIXED_300` remains a separate standardized benchmark and may use its already-frozen 5s quote-wait grace, so the first valid routeable quote in [300s, 305s] can close the benchmark;
- that 300-305s benchmark grace is excluded from Market Path, MFE/MAE and TP outcomes and therefore cannot leak into the 300s economic path.

Rationale: 300s was already pre-declared as the exploratory fixed benchmark before fresh economic outcomes. Reusing that existing time scale avoids introducing a new post-result horizon and provides a finite censoring boundary for TP/path analysis.

Fresh economic discovery is authorized only under this frozen 300s censoring contract. `fresh_economic_outcomes_opened` remains false until an actual prospective run begins.

## Provider preflight

`provider_preflight.py` performs one read-only Jupiter `USDC -> WSOL` route
probe using the frozen US$25 notional and 100 bps slippage. It uses no
Post-Transition cohort token, submits no transaction, writes no economic
outcome and leaves fresh discovery blocked.

Passing provider preflight proves provider route availability/normalization only.
It is not economic evidence.

## Edge claims

This implementation proves no Signal Edge, Human-Assisted Edge or Autonomous
Edge. It only makes the next fresh collection auditable once the unresolved
censoring horizon is frozen.


## Route-only paper-entry amendment — before fresh outcomes

Before any fresh Post-Transition economic outcome was opened, the research entry gate was intentionally changed from assembled/funded-wallet entry to `ROUTE_ONLY_PAPER`.

Frozen semantics now:

- `require_assembled_transaction=false`;
- Jupiter BUY quote uses `taker=None`;
- no wallet balance, ATA, signature or transaction submission is required for research;
- exact quoted output quantity remains required and is reused for route-only SELL path observations;
- +2s entry latency, US$25 notional, 100 bps entry/exit slippage, 20 bps fees, <=2pp provider impact, +60 primary, +300 exploratory, TP50/100/200, 300s censoring and 5s route grid remain unchanged;
- funded-wallet/assembly validation is deferred to future shadow/real execution work and does not block signal-edge research;
- this amendment occurred while `fresh_economic_outcomes_opened=false`; no observed result motivated it.


## Transport-health amendment — first attempt void before outcomes

The first route-only fresh attempt aborted after approximately 48 seconds because
the selected public Solana WebSocket stalled and hit a keepalive ping timeout.
That artifact contained zero immutable decision snapshots, zero episodes and
`fresh_economic_outcomes_opened=false`. It therefore does not constitute an
economic sample and is classified as `VOID_PRE_OUTCOME_TRANSPORT_ABORT`.

Before any replacement attempt, the following systems-only policy is frozen:

- 10-second dual-stream traffic-health preflight before the admission clock starts;
- at least 20 raw Pump notifications and 20 raw PumpSwap notifications are
  required during that preflight;
- client WebSocket keepalive ping is disabled (`ping_interval=None`);
- the live stream has a 15-second raw-message idle watchdog;
- no admission-window extension is allowed;
- no reconnect is used to splice a started economic sample;
- transport abort before the first economic provider call is VOID and permits a
  replacement attempt;
- transport failure after economic outcomes open is FAIL and does not authorize
  automatic rerun.

These transport changes do not modify selector, entry timing, notional, fees,
slippage, impact limits, standardized horizons, TP levels, censoring, route
cadence or dynamic-exit status.

Current contract hash:
`67671f812f695c2b5bd957279181bfa603cb9b4e802c969169c7e03fe4ab9a6b`.

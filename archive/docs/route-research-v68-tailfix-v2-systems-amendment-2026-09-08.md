# Route Research v68 — Tailfix v2 Systems Amendment — 2026-09-08

## Scope

This amendment changes only the systems implementation used by the already pre-registered v68 prospective holdout acquisition path.

It does **not** change the economic hypothesis, detector, feature, bins, favorable direction, primary horizon, support requirements, provider pacing, route notional/slippage, A/B cohort semantics, feature builder, or PASS/FAIL/INCONCLUSIVE evaluator.

## Why the amendment exists

The first v68 acquisition attempt stopped before any economic verdict because the frozen systems path failed the unchanged 11-gate profile on PumpSwap causal pipeline latency.

Observed failed acquisition systems evidence included PumpSwap p95 above the frozen 5s threshold. Forward economic collection therefore did not start and the v68 economic hypothesis remained NOT EVALUATED.

Subsequent systems-only diagnosis identified two infrastructure bottlenecks:

1. unnecessary cross-source stateful commit serialization for disjoint tokens; and
2. PumpSwap hedged RPC batch-slot retention after decision availability, which amplified same-pool single-flight waits into global sequence head-of-line blocking.

## Tailfix v1

Tailfix v1 separates Pump and PumpSwap stateful commit lanes while preserving shared per-token serialization across sources.

Invariant protections:
- same-token cross-source overlap remains forbidden;
- multi-token work locks tokens in deterministic order;
- unclassified synchronous stages fail closed;
- detector, replay, as-of, reservation FIFO and episode semantics are unchanged.

## Tailfix v2

Tailfix v2 keeps the v1 commit lanes and changes only the ownership of hedged PumpSwap RPC transports.

The winning/deadline decision releases the v41 batch slot immediately. Already-running losing transports drain in one resolver-owned executor bounded by the existing `max_concurrent_resolutions` ceiling. Queued losing transports are cancelled.

Invariant protections:
- no hidden RPC oversubscription;
- per-pool single-flight unchanged;
- hydration budget unchanged;
- explicit unresolved behavior unchanged;
- provider pacing unchanged;
- economics unchanged.

## Validation

Accepted systems-only validation:

- classification: `PASS_TAILFIX_V2_UNCHANGED_11_GATE`
- V43 systems gate: **11/11 PASS**
- radar coverage: **96.2%**
- true backlog: **3.807%**
- Pump p95: **1866.9 ms**
- PumpSwap causal pipeline p95: **3408.0 ms**
- drops: **0**
- worker errors: **0**
- hydration budget skips: **0**
- reservation superset violations: **0**

Tailfix v2 transport diagnostics:
- transport workers: 18
- max active transports: 18
- transport limit violations: 0
- decisions released: 106
- decision release p95: 721.1 ms

The same run produced `PASS_V54_DEMAND_ONLY_RESOLUTION_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE` because exact v50 clock attribution was incomplete at the frozen deadline. This does not invalidate the systems PASS; the guard explicitly preserves the 11/11 systems result independently and forbids causal-clock inference from an incomplete trace.

A previous Tailfix v2 systems-only run also produced 11/11 with PumpSwap p95 3479.2 ms. Its final v54 classification was diagnostic-missing only because the composed resolver had not registered inherited v41/v52/v53 `last_instance` aliases. That instrumentation compatibility issue was fixed without changing scheduling behavior.

## Frozen v68 economics remain unchanged

The following remain exactly as pre-registered:

- feature: `flow60_buy_share_pct`
- LOW <= 57.1429
- MID >57.1429 and <=65.7143
- HIGH >65.7143
- favorable: LOW
- opposite: HIGH
- primary horizon: 900s
- minimum available support in each subcohort: LOW >=5 and HIGH >=5
- same frozen nine-condition primary PASS gate
- MID and 300s/3600s diagnostic only
- no retry/backfill to improve economics
- failed/inconclusive economics cannot be rescued on the same sample

## Prospective execution rule

A fresh v68 acquisition using Tailfix v2 must use untouched `-A` and `-B` run keys. Prior interrupted/failed-acquisition v68 keys must not be pooled or reused.

The integration wrapper is:

`route_research_prospective_flow60_buy_share_holdout_v68_tailfix_v2.py`

It temporarily substitutes the validated Tailfix v2 systems implementation at v68's existing v54 seam, runs the unchanged v68 module, and restores globals afterward.

This is an infrastructure amendment following a pre-economic systems abort, not a new economic hypothesis and not a retuning of v68.

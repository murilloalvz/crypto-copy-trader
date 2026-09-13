# Launch Burst Research Protocol V0

## Status

Independent research track. This protocol does not modify Market-First/V68 and does not combine with Social/Event-First.

Launch Burst V0 remains **feature-only and outcome-blind**. It can characterize causally observable launch structure, but it cannot emit an automatic trade decision or support an economic-edge claim.

## Objective

Test whether causally observable launch/liquidity-activation structure contains short-horizon predictive information without selecting candidates or thresholds from future returns.

## Live venue contract and strata

The live Market-First pipeline persists lifecycle and trade venues as `pump` and `pumpswap`. Launch Burst uses those canonical stored values directly; it does not introduce aliases.

The following strata are evaluated independently:

1. `pump_launch` — lifecycle venue `pump`.
2. `pumpswap_liquidity_launch` — lifecycle venue `pumpswap`.

No pooled headline result is allowed until each stratum has independent evidence.

## Frozen causal clocks

For each token + venue stratum:

- `chain_t0 = lifecycle.market_started_at`.
- `observed_t0 = lifecycle.observed_at`.
- Default V0 feature window = 30 seconds.
- `decision_as_of = observed_t0 + 30s` on the local observation clock.
- `chain_window_end = chain_t0 + 30s` on the chain clock.

The clock domains are never subtracted from one another.

A trade can enter the V0 snapshot only when:

- its token matches the lifecycle token;
- its venue exactly matches the lifecycle venue;
- `trade.observed_at <= decision_as_of`;
- `chain_t0 <= trade.chain_time <= chain_window_end`.

Venue equality is mandatory. A token that graduates from Pump to PumpSwap inside the same 30-second chain window cannot leak PumpSwap trades into the Pump snapshot or vice versa.

The first causally observed lifecycle row for a token + venue is the immutable candidate anchor. Later lifecycle evidence never rewrites a candidate snapshot. A later-observed row that claims an earlier `market_started_at` is retained as audit evidence.

## V0 durable-store features

The canonical market observation store supports:

- event count;
- buy/sell count and count buy share;
- unique wallet count and wallet identity coverage;
- unique transaction count and transaction identity coverage;
- known buy/sell notional and known-notional buy share only when actually present;
- notional coverage;
- price coverage;
- first/last price and within-window return only when price coverage is complete;
- first trade delay inside the chain clock;
- first trade delay inside the local observation clock;
- explicit data-quality flags.

The current Carbon market-trade adapter deliberately writes `notional_usd=None` and `price_usd=None`. Current live acquisitions therefore support count/wallet/transaction structure in the durable market-observation store before they support USD price/notional structure. Coverage tools must report this absence rather than infer a conversion.

No liquidity amount, holder concentration, bonding-curve progress, market cap, route quality, social score or other field is invented when the canonical evidence does not support it.

## Matched-unit microstructure evidence

The current ingestion path already produces causal `MatchedUnitFlowObservation` evidence before converting it into `MarketTradeObservation`.

Matched-unit evidence can contain:

- raw quote amount;
- raw quote reserve in the same quote asset/unit;
- quote-asset identity;
- market-surface identity;
- venue;
- side;
- independent chain and local observation clocks.

The reusable `matched_unit_flow` contract can derive dimensionless same-unit features such as signed flow over reserve and gross turnover over reserve without manufacturing a USD conversion.

However, these matched-unit fields are **not currently persisted in the market-observation SQLite tables**. Launch Burst therefore treats them as available from processed/raw evidence replay, not as durable-store fields.

The outcome-blind matched-unit coverage audit reports only whether this evidence exists and can be adapted causally. It does not expose raw quote amounts, reserve magnitudes, flow/reserve ratios, returns or profitability.

### Pump

Pump matched-unit adaptation uses fields carried directly by the decoded Pump trade event and does not require external identity enrichment.

### PumpSwap

PumpSwap matched-unit adaptation requires exact pool identity causally available by the event's local receive time.

Bootstrap, create-pool and dynamic account-decoder identities remain ordered by their real `observed_wall_ns`. A dynamic identity discovered after processing an earlier PumpSwap trade may support later trades, but it **must never retroactively backfill the earlier trade**.

## Run eligibility and selection

Launch Burst does not infer acquisition completion from filesystem modification time, row recency or the presence of market observations.

The authoritative run registry is `market_activity_discovery_runs_v0`, whose states are:

- `OPEN`;
- `CLOSED`;
- `INTERRUPTED`.

Automatic selection is allowed only when:

1. the registry row exists;
2. the registry state is exactly `CLOSED`;
3. the run has at least one persisted lifecycle observation.

`OPEN`, `INTERRUPTED`, orphan observation runs, and `CLOSED` runs without lifecycle evidence are not eligible.

The readiness orchestrator selects the newest eligible `CLOSED` acquisition and then requires **exactly one** matching Market-First live `report.json` with:

- the same `acquisition_run_key`;
- `run.status = CLOSED`;
- `valid_live_discovery = true`.

Zero matching reports fail closed. Multiple valid matching reports also fail closed because the evidence source would be ambiguous.

## Censoring

A lifecycle anchor is right-censored when the available evidence cannot establish observation coverage through `decision_as_of`.

There are two intentionally different levels of evidence:

### DB-only replay

`launch_burst_replay_v0` uses the largest persisted `observed_at` visible in the acquisition. This is conservative: a late quiet launch can be marked censored even when the collector actually remained active but no later persisted event occurred.

The DB-only replay must not upgrade that uncertainty by assumption.

### Processed-evidence/live-report audit

`launch_burst_matched_unit_coverage_v0` uses the acquisition's `ended_wall_ns` from a valid live report. An anchor has a complete 30-second local feature window when the acquisition itself demonstrably remained active through `observed_t0 + 30s`; another trade is not required merely to prove collector duration.

A processed chunk with no `carbon-canonical` artifact is accepted only when its `chunk-report.json` explicitly proves `status = NO_TARGET_EVENTS`. Unexpected missing canonical evidence is an integrity failure.

## Outcome-blind durable-store coverage audit

Before any economic outcome protocol is frozen, `launch_burst_coverage_audit_v0` measures only:

- anchor/sample counts;
- right-censoring;
- per-stratum sample counts;
- event-count availability;
- first-trade delay availability;
- wallet identity coverage;
- transaction identity coverage;
- notional coverage;
- price coverage;
- data-quality flag prevalence.

It must not report:

- future outcome values;
- within-window return values;
- notional magnitudes;
- buy-share magnitudes;
- profitability-ranked candidates.

Its purpose is to determine what the durable acquisition can measure, not what would have made money.

## Outcome-blind matched-unit coverage audit

`launch_burst_matched_unit_coverage_v0` reuses the processed artifacts created by the live pipeline rather than performing new RPC acquisition or running a second decoder implementation.

It consumes the live report and its declared processed evidence, including plain or gzip forms of:

- `carbon-canonical`;
- `target-manifest`;
- `pool-account-output` when present;
- authoritative bootstrap identity evidence.

It preserves exact `first_received_wall_ns` ordering and the frozen discovery admission window.

It reports only:

- processed/evidence integrity counts;
- matched-unit adaptation status counts;
- Pump vs PumpSwap adaptation coverage;
- number of complete launch anchors;
- number of launches with matched-unit evidence;
- distributions of matched-unit event counts;
- distributions of surface counts;
- distributions of quote-asset identity counts.

It never reports quote-amount magnitudes, reserve magnitudes, dimensionless flow values, returns or future outcomes.

## Source capability boundary

`launch_burst_source_capabilities_v0` is the machine-readable declaration of what the current stack can support.

Current state:

- feature-only research: ready;
- lifecycle/count/side: durable and usable;
- wallet/transaction identity: conditionally durable and coverage-audited;
- USD price/notional: not inferred by the current market-trade adapter;
- native matched-unit quote amount/reserve: recoverable from processed/raw evidence but not durable in the market-observation store;
- dimensionless flow/reserve features: computable from matched-unit evidence but not yet admitted into an economic hypothesis;
- causal executable-quote selection primitive: present;
- proven official executable Launch Burst outcome collector: absent;
- economic outcome readiness: false.

A quote-selection contract is not evidence that an outcome collector exists.

## Readiness orchestration

`launch_burst_readiness_v0` is the outcome-blind orchestration gate.

It performs, in order:

1. authoritative newest-`CLOSED` Launch Burst run selection;
2. unique valid live-report resolution;
3. durable-store Launch Burst coverage audit;
4. matched-unit processed-evidence coverage audit;
5. source-capability/blocker audit.

Its possible classifications are:

- `NEEDS_MORE_OR_BETTER_LAUNCH_SAMPLE`;
- `CORE_FEATURES_READY_MATCHED_UNIT_NOT_READY`;
- `FEATURE_RESEARCH_READY_ECONOMIC_OUTCOME_BLOCKED`;
- `READY_FOR_FROZEN_OUTCOME_PROTOCOL`.

At the current source-capability state, `economic_outcome_ready=false`; therefore the last classification cannot be reached merely because feature coverage is strong.

The orchestrator does not load economic outcomes, future returns or candidate thresholds.

## Outcome protocol remains unfrozen

`LAUNCH_BURST_OUTCOME_PREREG_V0.md` remains `UNFROZEN_COVERAGE_ONLY`.

The following are not yet frozen:

- outcome horizons;
- executable observation contract;
- target observation lateness;
- unavailable/provider-error treatment;
- entry-price convention;
- fees/slippage/priority-fee model;
- exit convention;
- primary/secondary endpoints;
- sample requirements;
- success/failure/inconclusive criteria;
- multiplicity policy.

Market-First +300/+900/+3600 outcomes are not silently reused because they belong to a different decision problem and episode contract.

## No threshold fitting in V0

V0 emits every complete supported launch anchor. It does not define:

- BUY/SELL thresholds;
- minimum event count for profitability;
- minimum buy share;
- wallet breadth threshold;
- matched-unit flow/reserve threshold;
- return target;
- stop loss;
- take profit.

Those values must not be selected by looking at future or prospective outcome returns.

## Outcome progression

1. Run outcome-blind readiness on eligible closed acquisitions.
2. Measure sample size, censoring, durable-field coverage and matched-unit evidence coverage by stratum only.
3. Decide whether missing feature families require new causal enrichment before economic testing.
4. Freeze a short-horizon executable outcome protocol using operational/research objectives, not the horizon that maximizes historical P&L.
5. Commit that frozen protocol before the first retrospective economic-outcome analysis.
6. Use retrospective outcomes only for hypothesis generation and feature prioritization.
7. Freeze one or more candidate Burst hypotheses.
8. Validate them on a fresh prospective cohort.
9. Only prospective replication can support an edge claim.

## Convergence rule

Market-First, Launch Burst and Social/Event-First remain independent research tracks. Cross-track convergence is a new hypothesis and can only be tested after the component tracks have their own evidence.

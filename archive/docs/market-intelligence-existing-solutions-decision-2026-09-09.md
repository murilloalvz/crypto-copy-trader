# Market Intelligence Existing-Solutions Decision — 2026-09-09

## Status

**Decision:** COMPOSE EXISTING CAUSAL FACTS FIRST; BUILD ONLY THE MISSING MARKET-FIRST LAYER.

This decision is intentionally independent from Social/Event-First and from any convergence hypothesis.
It does not validate economic edge, authorize live trading, revive V68, or introduce a trading score.

## Existing-solutions-first inventory

### KEEP / COMPOSE

- `src/market_protocol_facts.py`
  - exact-mint and dual-clock protocol facts;
  - explicit Pump/PumpSwap lifecycle state;
  - explicit migration evidence;
  - provenance and missingness;
  - does not infer migration from PumpSwap activity alone.
- `src/opportunity_snapshot_core.py`
  - causal flow windows: 10/30/60/300s;
  - buy/sell counts and wallet breadth;
  - USD notional imbalance when coverage is complete;
  - price response/return when price coverage is complete;
  - repeated-wallet share only when identity coverage is complete;
  - observation lag;
  - causal execution quote/liquidity/impact surface.
- `src/market_opportunity_episode_store.py`
  - causal episode identity/persistence;
  - first-persisted trigger remains canonical;
  - late/replayed evidence is audited instead of retroactively reshaping enrollment.
- `src/market_signal_kernel.py`
  - production-validated in-memory detector state; no reason to rebuild it for intelligence features.

### ADAPT / REUSE AS RESEARCH EVIDENCE

- `src/pons_curve_state_progress_v64.py`
- `src/pons_launch_quality_evidence_v67.py`
- existing V47/V55/V56/V58/V63 research modules.

These modules may contain useful feature definitions or historical evidence, but old thresholds and economic
conclusions are not automatically promoted into the new Market-First plane.

### BUILD

- one score-free `MarketIntelligenceBaselineV0` composition surface;
- explicit protocol-state + flow/microstructure + execution evidence at the same T0;
- matched-unit liquidity-normalized flow only after the adapter carries dimensionally compatible raw flow and reserve units;
- Mayhem-mode causal fact (`true` / `false` / `unknown`) once its chain field is present at the adapter boundary;
- later: regime/earliness experiment harness and MarketEpisode research snapshots.

### DEFER

- Opportunity Ranker;
- confidence/calibration;
- Social/Event composition;
- convergence;
- Hawkes processes;
- ML ranking;
- wallet labels as hot-path authority;
- paid data-provider dependency;
- V68;
- live-money execution.

## External protocol evidence

### Pump.fun bonding curve

Pump.fun documents the launch bonding curve as a constant-product AMM driven by virtual reserves. Buys and sells
move reserves and therefore price. Pump.fun also documents automatic, irreversible graduation to PumpSwap once the
graduation condition is reached.

Source: https://pump.fun/docs/bonding-curve

**Decision:** ADOPT protocol mechanics as documented facts, but use explicit on-chain completion/migration evidence
in our causal state rather than reconstructing a migration claim from a reserve threshold or from PumpSwap activity.

### Pump.fun Mayhem Mode

Pump.fun documents Mayhem Mode as an optional per-token mode in which an automated agent can place randomized
trades during a token's first 24 hours. The public Pump `create_v2` documentation exposes `is_mayhem_mode` as a
creation argument.

Sources:
- https://pump.fun/docs/mayhem-mode
- https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/COIN_CREATION.md

**Decision:** ADOPT `is_mayhem_mode` as a protocol fact when causally available. Never treat it as inferred from
flow. Until adapter coverage exists, represent the fact as unknown. Flow generated in a Mayhem-enabled market must
not be silently described as purely organic participant demand.

## External microstructure evidence

Order-flow imbalance and price response are established market-microstructure quantities. Cont, Kukanov and Stoikov
showed a robust short-horizon relation between order-flow imbalance and price changes, with impact related to market
depth. Later empirical work also studies market impact conditional on signed order-flow imbalance.

Sources:
- https://arxiv.org/abs/1011.6402
- https://arxiv.org/abs/2004.08290

**Decision:** ADAPT the concepts, not the order-book formulas. Pump/PumpSwap are AMMs, so our baseline exposes
signed flow/imbalance, price response, reserve/liquidity state and executable impact separately. No claim is made
that an order-book OFI coefficient transfers directly to an AMM.

## Regime / earliness methods

Mature online-stream libraries such as River already provide drift/change detectors, including Page-Hinkley and
ADWIN families. River remains actively maintained in 2026.

Source: https://github.com/online-ml/river

**Decision:** BENCHMARK mature detectors before implementing a custom regime detector. Initial candidates:
1. simple rate/EWMA baseline;
2. Page-Hinkley;
3. ADWIN.

Do not select thresholds or a winner using the prospective evaluation set. Hawkes models remain deferred until a
simpler detector demonstrably leaves a research gap.

## Dimensional integrity decision

Current generic flow observations carry `notional_usd`; protocol reserve observations carry raw token/quote units.
A value such as `USD flow / raw reserve integer` has no stable economic unit and MUST NOT be labeled
"liquidity-normalized flow".

Therefore `MarketIntelligenceBaselineV0` explicitly reports this feature as unavailable. A future adapter may expose
matched-unit quote flow and quote reserve (with mint/decimals/provenance), after which a dimensionally valid ratio can
be researched.

## Baseline contract

`MarketIntelligenceBaselineV0` is:
- Market-First only;
- immutable and versioned;
- exact-token / exact-as-of;
- causal;
- descriptive;
- score-free;
- confidence-free;
- recommendation-free;
- explicit about missingness;
- explicit about protocol provenance.

It composes:

```text
MarketProtocolFactsV0
        +
OpportunitySnapshotCoreV1
        ↓
MarketIntelligenceBaselineV0
        ↓
research / episode replay later
```

## Promotion gates

Before any ranking layer:
1. focused unit tests PASS;
2. full suite PASS after production-module changes;
3. historical/replay serialization is deterministic;
4. no future evidence changes a previously frozen T0 snapshot;
5. Mayhem-mode coverage is measured rather than assumed;
6. matched-unit liquidity feature is either valid or explicitly missing;
7. regime detectors are compared prospectively or on a discovery/holdout split;
8. outcomes remain separate from feature construction.

## Frozen non-conclusions

This work does **not** show that:
- high buy imbalance predicts profit;
- high activity is organic;
- a PumpSwap pool proves canonical migration;
- a curve near graduation is automatically attractive;
- any regime detector creates economic edge;
- a Market-First signal should be traded.

Those are separate hypotheses requiring outcome evidence.

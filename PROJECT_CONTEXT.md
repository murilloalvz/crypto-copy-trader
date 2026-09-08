# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado permanece em `docs/`.

## Estado canônico

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch relevante: `feat/exit-engine-v1`
- Modo: **PAPER / RESEARCH / READ ONLY**
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**
- Fluxo: `market -> radar -> causal episode -> enrichment -> research decision -> forward outcomes -> economic validation -> shadow`
- Detector permanece congelado.

## Status atual

- Unified Market Latency v42: **FORMAL PASS 11/11**
- v44 provider-paced route-only path: **PASS 11/11**
- v46 dual prospective discovery: **COMPLETE**
- v47 causal feature discovery: **COMPLETE**
- v53 opportunistic prefetch: systems-only PASS standalone, later unstable in v48-B
- v54 demand-only resolver admission: **LIVE SYSTEMS PASS 11/11 / accepted acquisition profile**
- v48-v54 prospective Flow60 holdout: **COMPLETE / FAIL ECONOMIC HYPOTHESIS**
- Flow60 hypothesis: **REJECTED PROSPECTIVELY; DO NOT RETUNE OR REUSE**
- v55 Causal Early-Opportunity Discovery: **IMPLEMENTED / PROTOCOL PRE-REGISTERED / FRESH LIVE RUN STARTED BY USER / RESULT PENDING**
- v55 candidate-selection bridge: **PRE-REGISTERED BEFORE RESULT REVIEW / DETERMINISTIC RANKING IMPLEMENTED**
- v56 Exceptional Trade Pre-Entry: **CAUSAL RESEARCH SCAFFOLD IMPLEMENTED / CI GREEN / NO ECONOMIC STUDY YET**
- v57 Market-First Social Evidence: **CAUSAL EVIDENCE BRIDGE IMPLEMENTED / TESTS GREEN / NO LIVE SOCIAL PROVIDER OR ECONOMIC TEST**
- participation-structure research boundary: **DOCUMENTED; NOT A MANIPULATION DETECTOR**
- market-first exit research: **LEGACY WAVE ENGINE AUDITED / CURRENT LINEAGE GAP DOCUMENTED / NO EXIT TUNING**
- profitable economic edge: **NOT ESTABLISHED**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- official executable outcomes/shadow/live: **NOT RELEASED**

## Frozen systems gate

ALL must pass:
1. no worker errors
2. drops 0
3. reference asset episodes 0
4. radar coverage >=95%
5. true backlog <=5%
6. Pump p95 <=5s
7. PumpSwap causal pipeline p95 <=5s
8. hydration budget skips 0
9. bundles nonempty
10. replay/audit valid
11. reservation superset violations 0

Do not relax the 5s threshold.

## v54 accepted systems profile

Fresh systems-only run:
`route-research-systems-stability-20260907-54`

- PumpSwap received 3887
- Pump received 2020
- radar coverage 98.1%
- true backlog 1.913%
- Pump p95 1906.1ms
- PumpSwap p95 1625.9ms
- systems 11/11
- zero worker errors / drops / hydration-budget skips / reservation-superset violations
- speculative resolver tasks scheduled 0
- skipped speculative candidate pools 3890
- no forward collector

The v50 exact causal trace was incomplete at the frozen deadline; do not infer an exact dominant causal clock from that run. Systems PASS is independent of trace completeness.

## v48 prospective Flow60 result — CLOSED

Result doc:
`docs/route-research-v48-prospective-flow60-result-2026-09-07.md`

Base:
`route-research-prospective-holdout-20260907-48v54`

Validity:
- A=40 decisions
- B=40 decisions
- rows=80
- lineage violations=0
- missing decisions/episodes/hazard/entry quotes=0
- official decision mutations=0
- causal holdout audit PASS
- primary support adequate

Frozen primary test:
- feature `flow60_event_count`
- LOW <=25 / MID 26..47 / HIGH >47
- primary horizon 900s
- primary contrast LOW vs HIGH

900s:
- A LOW n=9 median=-18.472% PF=0.561
- A HIGH n=11 median=-36.705% PF=0.549
- B LOW n=10 median=-9.805% PF=0.027
- B HIGH n=5 median=+6.962% PF=0.256
- ALL LOW n=19 median=-10.770% PF=0.303 mean_without_best=-32.040%
- ALL HIGH n=16 median=-11.315% PF=0.486

Primary gate:
- support_ok=True
- same_direction_ok=False
- low_positive_median_both=False
- low_pf_gt_one_both=False
- aggregate_low_pf_gt_one=False
- aggregate_low_mean_without_best_positive=False
- classification=`FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

Interpretation: Flow60 alone did not replicate as a robust stage/maturity proxy. Do not rescue with new bins, MID, 300s/3600s, favorable subcohort selection, or another feature from the same holdout presented as validation.

Detector-population baseline at 900s across the 80 rows:
- available=64
- positive share=42.19%
- mean=-12.53%
- median=-9.82%
- PF=0.633
- mean_without_best=-20.27%
- best=+475.17%

Current economic problem: **selection**. Preserve access to rare explosive moves while rejecting a large fraction of poor detector episodes.

## v55 Causal Early-Opportunity Discovery — ACTIVE EXPERIMENT

Protocol:
`docs/route-research-v55-causal-early-opportunity-discovery-protocol-2026-09-07.md`

Purpose:
Study simple dynamics observable by `research_decision_as_of` among episodes already detected by the frozen radar.

Fresh acquisition:
- v46 A/B semantics unchanged
- v54 systems profile
- cap 40 / minimum 30 decisions per subcohort
- pacing 650/1000/250ms
- route-only US$25 / 100bps
- horizons 300/900/3600

Closed candidate feature set:
- flow10_event_count
- flow10_vs_60_event_rate_ratio
- flow30_vs_300_event_rate_ratio
- flow10_buy_share_pct
- flow60_buy_share_pct
- flow10_unique_buy_wallet_count
- flow30_unique_buy_wallet_count
- flow60_unique_buy_wallet_count
- flow30_wallet_direction_balance
- flow60_wallet_direction_balance
- flow30_repeated_wallet_event_share_pct
- flow60_repeated_wallet_event_share_pct

`flow60_event_count` itself is explicitly excluded from v55 candidate mining because it already failed prospectively.

Primary discovery horizon: 900s.

Candidate shortlist requires:
- clean causal dataset
- >=80% feature coverage independently in A and B
- inherited minimum group support
- same-direction descriptive median contrast in A and B

Candidate status is discovery-only. No candidate becomes a trading rule without a separate, newly pre-registered future holdout.

Forbidden in v55:
- label-optimized thresholds
- arbitrary feature combinations
- logistic/RF/XGBoost/grid search
- dropping losers
- favorable subcohort selection
- reusing v55 A/B as future holdout
- injecting v56/v57 evidence into the already-running experiment

## v55 candidate selection -> future holdout bridge — PRE-REGISTERED BEFORE RESULTS

Protocol:
`docs/route-research-v55-candidate-selection-to-holdout-protocol-2026-09-07.md`

Code:
- `src/route_research_v55_candidate_selection.py`
- `route_research_v55_candidate_selection.py`
- `tests/test_route_research_v55_candidate_selection.py`

If multiple 900s candidates survive the frozen v55 eligibility rules, rank them deterministically by:

1. `min(abs(delta_median_A), abs(delta_median_B))`, descending;
2. split-balance ratio `min(abs(A),abs(B))/max(abs(A),abs(B))`, descending;
3. `abs(delta_median_ALL)`, descending;
4. minimum A/B feature coverage, descending;
5. feature name lexicographically ascending.

Only rank #1 may be carried forward.

For numeric v55 features the effect is `median(HIGH)-median(LOW)`:
- positive same-direction delta -> HIGH is discovery-favorable;
- negative same-direction delta -> LOW is discovery-favorable.

The selected discovery cutpoints and favorable direction must be frozen before any new holdout data are collected.

Future validation uses the conservative v48-style 900s PASS template generalized to FAVORABLE vs OPPOSITE extreme: same direction A/B/ALL, favorable median >0 A/B, favorable PF >1 A/B, aggregate favorable PF >1 and aggregate favorable mean_without_best >0. MID/300s/3600s cannot rescue primary failure.

If no v55 candidate survives, do not relax rules to manufacture one.

## v56 Exceptional Trade Intelligence — strict pre-entry scaffold

Protocol:
`docs/exceptional-trade-v56-causal-preentry-snapshot-protocol-2026-09-07.md`

Code:
- `src/exceptional_trade_preentry_v56.py`
- `exceptional_trade_preentry_snapshot_v56.py`
- `tests/test_exceptional_trade_preentry_v56.py`

Purpose:
Prepare a future causal study of what was observable immediately before entries made by trades/wallets that are later classified as exceptional.

Causal cutoffs are strict:
- `event.chain_time < entry_chain_time`
- `event.observed_at < entry_observed_at`

Same-second activity is excluded conservatively because an arbitrary external entry has no canonical sub-second order in the persisted store. A trade that happened earlier on-chain but was only discovered after the reference entry is also excluded.

Frozen descriptive pre-entry windows:
- 10s
- 30s
- 60s
- 300s

Participation structure is computed only with adequate/complete identity coverage where required. Outcome/P&L labels are deliberately absent from the feature builder.

The exceptional outcome definition is intentionally **not registered yet**. A future comparison study must pre-register the target universe, outcome label, controls/placebos, dependence rules, sample support, feature set and statistic before labels are joined.

v56 proves only causal snapshot semantics. It does not prove exceptional trades are predictable or copyable.

## v57 Market-First Social Evidence — scaffold only

Protocol:
`docs/opportunity-social-v57-market-first-causal-evidence-protocol-2026-09-07.md`

Code:
- `src/opportunity_social_evidence_v57.py`
- `tests/test_opportunity_social_evidence_v57.py`

Existing social core already preserves `created_at` and `observed_at`, anchors window membership on first collector observation and allows only engagement snapshots known by `as_of`.

v57 adds a market-first envelope with:
- exact `token_mint` join only; no symbol-only episode linkage
- current social window 300s
- baseline 3600s
- event count / unique authors / acceleration / author diversity / original share / known engagement
- explicit `NO_CAUSAL_EVENTS` missingness
- zero prior baseline => acceleration remains `None`, never infinity/bullish

The repository still has no approved live social provider in this protocol. Existing `social_ingest.py` imports already-observed JSONL only.

v57 is not part of v55 and cannot be used to rescue or reinterpret its outcome.

## Participation-structure research boundary

Design:
`docs/participation-structure-research-design-2026-09-07.md`

Existing `src/market_integrity.py` is aggregate observational evidence and explicitly cannot establish self-trading, counterparty graphs, order-level sequence or funding relationships.

Transaction-level wallet metrics such as breadth, repetition, top-wallet event share, buy/sell overlap and acceleration may be studied as **participation structure**.

Do not call these metrics wash trading, sybil activity, insider coordination, organic demand or manipulation without a separately validated semantic study and stronger evidence.

## Market-first exit research boundary

Design:
`docs/market-first-exit-research-gap-2026-09-07.md`

The existing `exit_engine_v1` is a useful legacy Wave laboratory tied to `wave_signals`, `WAVE_STRATEGY_VERSION` and GeckoTerminal/candle observation. Its metrics already include MFE, MAE, MFE captured, winner dependence and paired policy evaluation.

It is **not** the authoritative exit path for current market-first route-research decisions. Silently converting v55 episodes into Wave signals would conflate entry semantics, clocks, provider evidence and lineage.

Do not tune a new TP/SL/trailing parameter now. A future market-first exit study first needs a route-compatible path-observation contract with explicit `observed_at`, route SELL semantics, provider missingness and MFE/MAE/peak-giveback geometry. That work should start only after entry-selection evidence warrants the extra provider/runtime budget.

## Scientific invariants

- discovery != validation
- systems PASS != economic edge
- wallet is post-episode evidence, not whitelist
- no backfill / retroactive enrollment
- missingness remains explicit
- first persisted trigger remains canonical
- no blind worker tuning
- route availability != assemblable transaction != landed transaction != fill
- route-only return != realized P&L
- no live money without robust forward evidence
- no hidden RPC oversubscription
- failed prospective hypotheses are closed, not retuned
- v48-v54 sample is burned for validation
- v55 is discovery only; any future hypothesis must be frozen before new untouched data
- v55 feature contract cannot change while its live run is in progress
- v55 candidate selection rule was registered before result review and cannot be changed to favor a result
- only v55 rank #1 may advance to one fresh holdout; rank #2 cannot rescue its failure
- v56 outcome labels remain separate from pre-entry feature construction
- v56 same-second target activity is excluded
- participation concentration/repetition != manipulation proof
- social `created_at` != causal availability; collector `observed_at` is authoritative
- v57 exact mint linkage only
- old Wave exit results do not validate market-first exit behavior
- no second live economic acquisition while v55 is active

## Immediate next action

The user has already started the fresh v55 base:
`route-research-early-opportunity-discovery-20260907-55`

Do not start another economic/live acquisition or modify the v55 contract while it is running.

When v55 completes:
1. inspect the full A+B output and systems/lineage gates;
2. apply the pre-registered candidate ranking without discretion;
3. if there is a rank #1, freeze its feature definition, value-only cutpoints and favorable direction;
4. register one separate fresh 900s holdout before collecting validation data;
5. if no candidate survives, do not loosen v55 rules.

v56/v57/exit-boundary work is preparatory scaffolding only and must not influence the running v55 result.

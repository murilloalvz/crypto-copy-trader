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
- v55 Causal Early-Opportunity Discovery: **IMPLEMENTED / PROTOCOL PRE-REGISTERED / FRESH RUN PENDING**
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

## v55 Causal Early-Opportunity Discovery

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

## Immediate next action

First require CI green on the current branch after removal of the obsolete v53 wiring test and addition of v55 tests.

After CI is green, run one fresh v55 discovery base. Recommended key:
`route-research-early-opportunity-discovery-20260907-55`

Command:
`python route_research_early_opportunity_discovery_v55.py --run-key route-research-early-opportunity-discovery-20260907-55`

Do not run any other concurrent economic experiment. When v55 completes, review the full output before choosing at most one future holdout hypothesis.

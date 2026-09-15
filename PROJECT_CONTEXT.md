# Crypto Copy Trader / Opportunity Intelligence Engine — Current Context

Este arquivo resume apenas o **estado operacional e científico atual**. Histórico detalhado, protocolos antigos e resultados completos permanecem em `docs/`, artifacts e Git.

Precedência de evidência:

`código + resultados mais recentes > decisões científicas recentes > PROJECT_CONTEXT.md > handoffs antigos > ideias antigas`

## CURRENT STATE

Objetivo de longo prazo:

`information/narrative -> token -> early activity -> Burst -> capital quality -> structural quality -> executability -> signal -> entry/exit -> positive net EV`

Regra de produto e pesquisa: **cada camada só entra se provar valor incremental**. Não construir mega-score, feature creep ou automação de execução antes de existir evidência prospectiva.

Modo atual: **NO-CAPITAL / PAPER / SHADOW / READ-ONLY RESEARCH**.

Prioridade ativa:

1. **Robinhood/Pons systems + acquisition**, enquanto Solana está bloqueada apenas por execution-fixture funding.
2. **Solana Launch Burst V4** permanece congelada até funded-taker preflight válido.
3. Social/Event, Narrative Revival, Convergence, wallet/deployer scores e exit optimization continuam congelados.

## CURRENT SYSTEMS STATUS

### Solana

- Launch Burst V4 systems/timing: **PASS / CLOSED**.
- V4 systems live: 84/84 selected before entry-ready/deadline, zero missed deadlines, max queue depth 1.
- Jupiter pricing/route availability: **CONFIRMED**.
- Jupiter candidate transaction assembly capability: **CONFIRMED** via diagnostic-only public funded control for both liquid control and representative Burst token.
- Frozen controlled taker: unfunded (`0 USDC`, `0 SOL`).
- Official funded-taker preflight: **FAIL-CLOSED BY DESIGN** until balances are present.
- Solana active systems blocker: **execution fixture funding only**.

Freeze status document:

`docs/launch-burst-v4-solana-freeze-status.md`

### Robinhood / Pons

Active branch:

`research/robinhood-launch-burst-v0`

Robinhood V0 already contains:

- Pons V2 factory discovery;
- RPC executed-event acquisition;
- direct BUY/SELL quote math;
- pinned-block state reads;
- protocol capability / fee / tax detection;
- Nitro Sequencer raw capture;
- bootstrap classification;
- coordinated RPC + Sequencer runner;
- reconciliation plumbing.

Authoritative 180s coordinated-shadow attempt:

- requested duration: 180s;
- parent lifetime: ~1.73s;
- child start skew: ~11.89ms;
- `rpc_return_code = 0`;
- `feed_return_code = 0`;
- RPC report: `FAIL_ROBINHOOD_LAUNCH_BURST_PREFLIGHT_V0`;
- parent classification: `FAIL_COORDINATED_SHADOW_ARTIFACTS`;
- bootstrap not opened;
- latency claim not opened;
- execution reconciliation not opened;
- economic outcomes not opened;
- selector remains unfrozen.

Interpretation: **SYSTEMS FAILURE BEFORE SCIENTIFIC ACQUISITION**, not evidence against Robinhood/Pons or Burst.

Confirmed observability bug: the Sequencer capture CLI printed `FAIL_CAPTURE_PREFLIGHT` on an exception after creating a run directory but did not persist `report.json`; the coordinated parent therefore masked the real feed cause as an artifact failure.

Minimal repair applied:

- persist CLI preflight failure report into the run directory when exactly one new capture run directory belongs to that invocation;
- fail closed if artifact ownership is ambiguous;
- add unit coverage;
- compile/test capture + coordinated paths in Robinhood Sequencer CI.

The repair is **observability-only**. It does not alter feed parsing, RPC acquisition, event semantics, ordering, selector, economics or reconciliation rules.

Current repair HEAD at time of consolidation:

`ffc6228a9353d73e31a043482fbdc8e2a24b35ea`

CI status must be checked from GitHub before treating that HEAD as validated.

## CURRENT SCIENTIFIC STATUS

### Solana Launch Burst

Frozen hypothesis:

- stratum: `pump_launch`;
- primary window: `5s`;
- feature: `signed_flow_over_event_reserve`;
- selector: `>= 0.08`;
- confirmation: none.

Scientific state: **NOT REJECTED**.

The first V4 economic acquisition does **not** evaluate the hypothesis because entry assembly coverage was 0/57 due the unfunded taker fixture. Do not reinterpret it as a signal failure.

A separate future `NO-CAPITAL / SHADOW / QUOTE-PAPER BURST-0` surface is allowed only as a fresh protocol. It must never be presented as validation of the frozen V4 assembled-transaction contract.

### Robinhood / Pons

Scientific state: **NOT YET EVALUATED**.

No Robinhood selector is frozen. No Solana threshold/window/feature semantics may be imported.

The active scientific prerequisite is causal observability:

`Sequencer intent -> canonical tx identity -> RPC confirmation -> Pons Launch/CurveBuy/CurveSell -> intent-to-execution timing`

Semantics are frozen:

- Sequencer Feed = **INTENT EVIDENCE ONLY**;
- RPC logs / canonical chain data = **EXECUTION EVIDENCE**;
- Feed observation without RPC confirmation = **UNKNOWN**, never inferred failed execution;
- initial Sequencer sequence `0` = **BOOTSTRAP ONLY**, never a latency boundary.

Only after acquisition + reconciliation are healthy may Robinhood Burst-0 begin.

## CURRENT ECONOMIC STATUS

### Solana

`ECONOMIC = INCONCLUSIVE`

Reason: the frozen V4 Route-Paper contract requires an assembled candidate BUY transaction, while the controlled taker is unfunded.

This is an **execution-fixture blocker**, not evidence of positive or negative expectancy.

### Robinhood

`ECONOMIC = NOT OPENED`

No selector, economic hypothesis, trade return or realized PnL claim is currently authorized.

## ACTIVE EXPERIMENT

### Robinhood coordinated shadow — current gate

Question:

> Can RPC execution evidence and Nitro Sequencer intent evidence be acquired together with causal artifacts reliable enough for later reconciliation?

Current authoritative run failed before that question was answered.

Immediate task:

1. read the RPC child `report.json` and both child stdout/stderr from the existing 180s run;
2. recover the exact RPC and feed preflight causes;
3. repair only the minimum operational blocker;
4. repeat the **same coordinated gate**, preferably short (e.g. 60s) once the blocker is known;
5. do not open Burst-0 until coordinated acquisition and causal reconciliation are valid.

Artifacts from the authoritative failed run:

`C:\robinhood-shadow-v0\robinhood_sequencer_coordinated_shadow_v0-1789442344-67f7e01d8a`

## FROZEN CONTRACTS

### Solana Route-Paper V4

Do not change:

- `pump_launch`;
- 5s primary window;
- `signed_flow_over_event_reserve >= 0.08`;
- no confirmation window;
- +2s entry latency;
- US$25 notional;
- frozen fees/slippage;
- +60s exit;
- BUY requires assembled candidate transaction;
- SELL is route-only exact bought quantity;
- failed exit = -100%;
- no adaptive post-signal funding/top-up;
- no outcome-driven rescue or retuning.

Route contract hash:

`3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d`

Funded-taker fixture hash:

`e7bde615886a9674a9f67cccca6be12aefa833e730a4076447ce60530d2e4ba8`

Solana resume condition before acquisition:

- same frozen controlled taker;
- >=25 USDC;
- >=0.01 SOL operational balance;
- no adaptive top-up;
- `PASS_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT`;
- assembled read-only probes for liquid control and representative Burst token.

### Robinhood

No economic selector or primary feature is frozen yet.

Do not import from Solana:

- `.08`;
- primary 5s choice;
- Solana selector;
- Solana economic contract;
- cross-chain threshold sharing.

## CLOSED HYPOTHESES / HISTORICAL DECISIONS THAT STILL MATTER

- Solana V48 `flow60_event_count` prospective holdout: **FAIL / CLOSED**.
- Solana V68 Flow60 buy-share economic verdict: **NOT EVALUATED** because systems aborted before valid forward economic collection.
- Historical V9 Solana systems: **PASS 11/11**, PumpSwap p95 ~3.151s, Pump p95 ~1.478s. This motivated preserving useful systems work but no longer defines the active scientific gate.
- Market-First and Social/Event-First remain independent research tracks; convergence is a future hypothesis only after both are independently supported.

## KNOWN BLOCKERS

### Solana

Only active blocker for frozen V4 economic continuation:

`CONTROLLED TAKER FUNDING`

Do not spend capital merely to discover whether Burst has first-move residual. Funding is classified separately as execution-fixture funding.

### Robinhood

Current blocker:

`EXACT RPC + FEED PREFLIGHT CAUSES FROM FAILED COORDINATED RUN`

Known secondary systems fact:

- Robinhood public RPC is rate-limited and is explicitly not recommended for production/latency-sensitive use.
- Do not treat public-provider throttling as a scientific failure.
- Provider upgrade is allowed only when evidence shows the public endpoint is the blocker; do not redesign parser/strategy preemptively.

Current Pons protocol verification:

- current official V2 factory matches `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`;
- current `TokenLaunched`, `CurveBuy` and `CurveSell` event shapes match the repository decoder signatures.

Therefore do not change factory/event semantics without new evidence.

## NEXT GATE

### Robinhood

Current route:

`recover exact preflight causes -> minimum systems repair -> repeat same coordinated gate -> causal reconciliation`

Outcome routing:

- **PASS_COORDINATED_SHADOW_ACQUISITION_V0** -> open causal Feed->RPC reconciliation.
- **PASS_COORDINATED_SHADOW_ACQUISITION_V0_NO_LIVE_CANDIDATES** -> increase acquisition duration only.
- **SYSTEMS FAIL** -> repair only the observed operational blocker, then repeat the same gate.
- **INCONCLUSIVE coverage** -> extend acquisition only; no feature/selector changes.

After healthy reconciliation:

### Robinhood Burst-0 — NO CAPITAL

Question:

> After the causal moment at which an opportunity can actually be observed, does meaningful residual movement remain in the bonding curve?

Start with base rate only, no selector.

Desired forward horizons when viable:

`15s / 30s / 60s / 120s / 300s`

Measure:

- forward return;
- MFE;
- MAE;
- time-to-MFE;
- time-to-failure;
- missingness;
- right-tail / top-1 / top-3 dependence.

Do not call quote-paper evidence a fill or realized PnL.

## ROADMAP

1. Robinhood acquisition health.
2. Robinhood causal Sequencer->RPC reconciliation.
3. Robinhood Burst-0 base-rate residual move, no capital and no selector.
4. Only if Burst-0 justifies: Burst-1 with a small number of grounded momentum/acceleration and capital-quality families.
5. Only if Burst-1 produces a prospectively supported candidate: Burst-2 structural risk/veto layer.
6. Fresh validation.
7. Quote/route paper.
8. Execution realism.
9. Continuous shadow.
10. Small capital only after prior gates survive.

Potential future layers, explicitly **not active now**:

- Social / Attention Lead;
- Narrative Revival;
- cross-track convergence;
- wallet independence / common funding / deployer history as structural risk;
- TP/SL or exit optimization.

## CAPITAL RULE

Preferred sequence:

`NO-CAPITAL OBSERVABILITY -> PROSPECTIVE SCIENTIFIC EVIDENCE -> FROZEN SELECTOR -> FRESH VALIDATION -> QUOTE/ROUTE PAPER -> EXECUTION REALISM -> SHADOW -> SMALL CAPITAL`

Never use trading capital simply to discover whether the basic phenomenon exists.

## INTERPRETATION DISCIPLINE

Always separate:

### SYSTEMS
Did acquisition / pipeline / reconciliation work?

### SCIENTIFIC EVIDENCE
Was the phenomenon measured causally without lookahead, survivorship or contamination?

### ECONOMIC EDGE
Is there future movement that may be capturable after costs and execution constraints?

Never infer:

- Systems PASS = edge;
- MFE = realized profit;
- Sequencer intent = execution;
- route/quote paper = landed fill;
- many trades = real capital commitment;
- distinct wallets = independent traders.

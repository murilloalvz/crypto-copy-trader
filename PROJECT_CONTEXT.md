# Crypto Copy Trader / Opportunity Intelligence Engine — Current Context

Precedência:

`código + resultados mais recentes > decisões científicas recentes > PROJECT_CONTEXT.md > handoffs antigos > ideias antigas`

## CURRENT STATE

Objetivo:

`information/narrative -> token -> early activity -> Burst -> capital quality -> structural quality -> executability -> signal -> entry/exit -> positive net EV`

Regra: cada camada só entra se provar valor incremental. Modo atual: **NO-CAPITAL / PAPER / SHADOW / READ-ONLY RESEARCH**.

Prioridade:
1. Robinhood/Pons systems + acquisition + causal reconciliation.
2. Solana Launch Burst V4 congelada por execution-fixture funding.
3. Social/Event, Narrative Revival, Convergence, wallet/deployer scores e exit optimization congelados.

## ACTIVE TRACK

### Robinhood / Pons

Branch:

`research/robinhood-launch-burst-v0`

HEAD após hardening de provider/feed transport:

`bc805f7be0b236ae2f769a59469bdae343d6dfa2`

CI relevante nesse HEAD: Robinhood Sequencer Shadow + Sequencer Transport **PASS**.

Próximo gate: provider-access preflight atualizado -> coordinated shadow curto (60s) somente se provider access passar.

## CURRENT SYSTEMS STATUS

### Solana

- Launch Burst V4 systems/timing: **PASS / CLOSED**.
- Jupiter pricing/route: **CONFIRMED**.
- Candidate transaction assembly capability: **CONFIRMED** via diagnostic-only public funded control.
- Frozen controlled taker: `0 USDC`, `0 SOL`.
- Official funded-taker preflight: fail-closed até funding.
- Status: `FROZEN_PENDING_FUNDED_TAKER_PREFLIGHT`.

Freeze status:

`docs/launch-burst-v4-solana-freeze-status.md`

### Robinhood / Pons

Authoritative failed coordinated run:

`C:\robinhood-shadow-v0\robinhood_sequencer_coordinated_shadow_v0-1789442344-67f7e01d8a`

Requested: 180s. Actual parent lifetime: ~1.73s.

Recovered exact causes:

- RPC child: `eth_chainId -> HTTP 403 Forbidden` before factory discovery.
- Feed child: old capture also failed preflight before raw frames; original CLI masked the cause by not persisting `report.json`.
- Provider A/B probe later showed:
  - baseline RPC -> `403`;
  - identified RPC (`User-Agent` explicit) -> `200`, chain id `4663`;
  - WebSocket endpoint upgrades successfully, but Robinhood currently omits optional Nitro response metadata headers (`arbitrum-feed-server-version`, `arbitrum-chain-id`).

Interpretation: the old 180s result was **SYSTEMS FAILURE / PROVIDER-ACCESS + CLIENT-COMPATIBILITY**, not Pons/parser/scientific failure.

Hardening now applied:

- CLI preflight failures persist their artifact fail-closed.
- Parent surfaces child errors/factory/transport facts.
- Bootstrap parse/block-resolution errors cannot become false `NO_LIVE_CANDIDATES`.
- anchor/reorg failure has specific systems classification.
- causal-coverage HOLD = INCONCLUSIVE, not PASS.
- explicit RPC readiness barrier before Feed starts.
- RPC requested duration starts after preflight.
- strict single-call JSON-RPC id/result validation.
- public Robinhood RPC requests use explicit identified `User-Agent`.
- Feed WebSocket request uses explicit identified `User-Agent`.
- Nitro response `feed-server-version` / `chain-id` headers are optional metadata: if present they are validated fail-closed; if absent they remain `null` and are never inferred.
- chain identity remains independently verified through RPC before Feed acquisition.
- ambiguous `PONS_CURVE_OTHER_INTENT` is not promoted to semantic execution.
- causal lead candidate requires post-anchor eligibility + semantic RPC match + nonnegative observation delta.

## CURRENT SCIENTIFIC STATUS

### Solana Launch Burst

Frozen hypothesis:
- stratum `pump_launch`;
- primary 5s;
- `signed_flow_over_event_reserve >= 0.08`;
- no confirmation.

Scientific state: **NOT REJECTED**.
Economic state: **INCONCLUSIVE** because the frozen execution fixture is unfunded.

No rescue/retuning.

### Robinhood / Pons

Scientific state: **NOT YET EVALUATED**.

Semantics:
- Sequencer Feed = **INTENT EVIDENCE ONLY**;
- RPC logs/canonical chain data = **EXECUTION EVIDENCE**;
- Feed without RPC confirmation = **UNKNOWN**;
- initial sequence `0` = **BOOTSTRAP ONLY**, never latency boundary.

No Robinhood selector is frozen. Do not import Solana `.08`, 5s primary choice or economic contract.

## CURRENT ECONOMIC STATUS

### Solana

`ECONOMIC = INCONCLUSIVE`

Reason: frozen Route-Paper V4 requires assembled candidate BUY transaction, controlled taker is unfunded.

### Robinhood

`ECONOMIC = NOT OPENED`

No selector, return claim, realized PnL or execution edge is authorized.

## ACTIVE EXPERIMENT

### Robinhood provider/access -> coordinated acquisition

Immediate question:

> Can the public Robinhood RPC + Nitro Feed be accessed with a causally valid client and then acquired together without provider/client artifacts contaminating the gate?

Current order:
1. fast provider-access preflight;
2. only if PASS, coordinated shadow 60s with RPC readiness barrier;
3. if coordinated PASS, causal Feed->RPC reconciliation;
4. only after reconciliation health, Robinhood Burst-0 no-capital.

## FROZEN CONTRACTS

### Solana Route-Paper V4

Do not change:
- `pump_launch`;
- 5s;
- `signed_flow_over_event_reserve >= 0.08`;
- no confirmation;
- +2s entry latency;
- US$25 notional;
- frozen costs;
- +60s exit;
- BUY requires assembled candidate transaction;
- SELL route-only exact bought quantity;
- failed exit = -100%;
- no adaptive top-up.

Route contract hash:
`3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d`

Funded fixture hash:
`e7bde615886a9674a9f67cccca6be12aefa833e730a4076447ce60530d2e4ba8`

Resume requires same controlled taker, >=25 USDC, >=0.01 SOL and `PASS_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT`.

### Robinhood

No economic selector/primary feature frozen.

## CLOSED HYPOTHESES / DECISIONS

- Solana V48 `flow60_event_count`: **FAIL / CLOSED**.
- Solana V68 economic: **NOT EVALUATED** due systems abort.
- Market-First and Social/Event-First remain independent.

## KNOWN BLOCKERS

### Solana

`CONTROLLED TAKER FUNDING` only.

### Robinhood

No protocol/parser blocker is currently established.

Public endpoint facts:
- public RPC is rate-limited / non-production;
- A/B evidence shows explicit client identification is required for reliable public RPC access in current environment;
- Feed upgrades but may omit optional Nitro metadata response headers.

Do not treat provider throttling/access policy as scientific failure.

Pons protocol remains verified:
- V2 factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`;
- current `TokenLaunched`, `CurveBuy`, `CurveSell` shapes match decoder signatures.

## NEXT GATE

### Robinhood

`provider-access PASS -> coordinated 60s -> causal reconciliation`

Routing:
- provider PASS -> coordinated short gate.
- provider 401/403 -> provider/access systems blocker only.
- provider 429 -> INCONCLUSIVE rate-limit; acquisition/provider adjustment only.
- coordinated PASS -> reconciliation.
- coordinated NO_LIVE_CANDIDATES -> extend duration only.
- coordinated SYSTEMS FAIL -> repair exact operational blocker only.
- bootstrap coverage HOLD -> INCONCLUSIVE; extend acquisition only.

### Robinhood Burst-0 — only after healthy reconciliation

Question:

> After causal observation, does meaningful residual movement remain in the bonding curve?

Base rate only, no selector.

Forward horizons when viable:
`15s / 30s / 60s / 120s / 300s`

Measure:
- return;
- MFE;
- MAE;
- time-to-MFE;
- time-to-failure;
- missingness;
- top-1/top-3/right-tail dependence.

Quote-paper != fill != realized PnL.

## ROADMAP

1. Robinhood provider/access health.
2. Coordinated RPC + Feed acquisition.
3. Causal Sequencer->RPC reconciliation.
4. Robinhood Burst-0 no-capital base rate.
5. Burst-1 only if residual move exists prospectively.
6. Burst-2 structural risk/veto only if Burst-1 justifies.
7. Fresh validation -> quote/route paper -> execution realism -> continuous shadow -> small capital.

## CAPITAL RULE

`NO-CAPITAL OBSERVABILITY -> PROSPECTIVE SCIENTIFIC EVIDENCE -> FROZEN SELECTOR -> FRESH VALIDATION -> QUOTE/ROUTE PAPER -> EXECUTION REALISM -> SHADOW -> SMALL CAPITAL`

## INTERPRETATION DISCIPLINE

Always separate:

### SYSTEMS
Did acquisition / pipeline / reconciliation work?

### SCIENTIFIC EVIDENCE
Was the phenomenon measured causally without lookahead/survivorship/contamination?

### ECONOMIC EDGE
Is there future movement potentially capturable after costs/execution constraints?

Never infer Systems PASS = edge, MFE = realized profit, Sequencer intent = execution, or quote/route paper = landed fill.

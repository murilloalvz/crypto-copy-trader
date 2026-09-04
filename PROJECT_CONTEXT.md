# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado permanece em `docs/`; aqui ficam estado canônico, invariantes, gates e a próxima ordem de trabalho.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo canônico:
  `market data -> unified radar -> detector -> opportunity episode -> flow/wallet/context -> execution/hazard -> decision_as_of -> executable forward outcomes -> economic evaluation`.

Status canônico:

- Pump native acquisition: PASS.
- PumpSwap native acquisition + causal pool resolution: PASS.
- Unified radar -> causal opportunity episode: PASS.
- Replay / continuation hardening: PASS / auditável.
- **Unified Market Latency v34/v37: FORMAL PASS 11/11.**
- **Jupiter route availability: PASS 12/12.**
- **Funded executable assembly: BLOCKED_BY_FUNDING.**
- v35 taker readiness: `SOL=0`, `USDC=0`, déficit USDC `25`, `INSUFFICIENT_USDC_AND_SOL`.
- Solana Tracker hazard v36: **FAIL / BLOCKED_BY_PROVIDER_CREDITS** — 12/12 `HTTP 403: Insufficient credits for this request`.
- **Solana RPC on-chain hazard v37: FORMAL PROVIDER PASS 12/12**, no mesmo live em que latency também passou 11/11.
- Wallet market-first history v38: **CODE/CI READY**; strict pre-T0 loader e bundle guard implementados. Amostra econômica oficial ainda não existe por causa do funded executable blocker.
- `decision_as_of`: mecanismo/readiness CODE/CI READY; **nenhum freeze oficial enquanto funded executability estiver bloqueada**.
- Forward outcomes +5m/+15m/+60m: schema/schedule CODE/CI READY; coleta econômica oficial ainda bloqueada.
- Economic edge/profitability: **não estabelecido**.
- Shadow/live money: **não liberado**.
- **Não iniciar coleta de 12h ainda.**

Bloqueios externos não são strategy failure:
- funding pode esperar;
- créditos do Solana Tracker não serão comprados apenas para fabricar PASS;
- o provider on-chain v37 já substitui a dependência de Solana Tracker para o hazard mínimo;
- implementação paralela não muda a ordem dos gates econômicos finais.

## North star

```text
market changes state
-> causal radar
-> opportunity episode T0
-> flow / microstructure
-> executable entry / liquidity
-> token hazard descriptors
-> wallets actually present + only strict pre-T0 resolved history
-> freeze final decision_as_of
-> executable forward outcomes
-> out-of-sample economic evaluation
```

Objetivo científico: testar se informação realmente disponível no momento da decisão produz resultados forward líquidos favoráveis fora da amostra, sem survivorship, lookahead, retroactive enrollment, artificial backfill ou redefinição de labels depois de ver outcomes.

## Princípios congelados

- Histórico exploratório de P&L não é prova causal de edge.
- Detector/estratégia/coorte ficam congelados durante validação de infraestrutura e providers.
- Separar signal quality, observability, executability, economic replay e systems latency.
- No-sample não significa strategy failure.
- Wallet é evidência pós-episódio, nunca acquisition whitelist.
- Missing/failure de provider permanece explícito.
- Nunca substituir missing por candle/quote/snapshot posterior.
- Primeiro trigger-to-episode **persistido** permanece canônico.
- Late-earlier não retrocede T0 e não abre episódio retroativo concorrente.
- PASS de systems latency não significa profitability PASS.
- Não aumentar workers por tentativa; primeiro localizar o relógio dominante.
- Nenhum live money sem forward evidence robusta + gate explícito.
- Features de hazard/wallet permanecem descritivas até demonstrarem valor incremental out-of-sample.
- Não criar threshold porque uma feature “parece boa” ou porque um resultado histórico favorece um corte.
- Reordenar implementação por blocker externo não muda a precedência da validação final.

## Detector congelado

`src/market_opportunity_radar.py`

Version: `market_opportunity_radar_v1_1_tx_aware`.

- fast window 30s;
- baseline 300s;
- >=6 fast events;
- >=4 known unique wallets;
- established: >=3 baseline events e >=3x acceleration;
- fresh causal token age <=120s;
- com transaction identity coverage=100%: >=4 unique fast tx;
- direction é descritiva.

**Nenhum threshold foi ajustado por P&L ou pelos smokes live.**

## Systems latency — formal gate congelado

ALL:

1. no traceback/worker errors;
2. drops 0;
3. `reference_asset_episodes=0`;
4. coverage >=95%;
5. true total deadline backlog <=5% de received;
6. Pump radar p95 <=5s;
7. PumpSwap causal pipeline p95 <=5s;
8. hydration budget skips 0;
9. bundles não sistematicamente vazios;
10. replay/collision counters auditáveis, sem corruption não explicada;
11. `reservation_superset_violations=0`.

### v34 canonical live

- received 4892;
- processed 4814;
- coverage 98.4%;
- true backlog 1.594%;
- Pump p95 2.053s;
- PumpSwap p95 1.712s;
- errors/drops/ref/budget/superset violations = 0;
- demoted pending jobs 83;
- demoted finalizer acks pending 0.

Resultado: **PASS 11/11**.

v34 semantics permanecem congeladas:
- proof-based late continuation demotion;
- apenas pending continuation-only provado sai do stateful dependency graph;
- payload demovido continua audit-visible pelo finalizer normal;
- ambiguity / late-earlier / different-window continua strict FIFO;
- ready/running nunca é demovido.

### v37 retained latency live — 2026-09-04

Run:
`unified-market-onchain-hazard-smoke-20260904-37`

- elapsed 120.2s;
- received PumpSwap 3061 + Pump 2720 = **5781**;
- processed PumpSwap 3061 + Pump 2710 = **5771**;
- coverage **99.8%**;
- true backlog `10/5781 = 0.173%`;
- Pump radar p95 **1.397s**;
- PumpSwap pipeline p95 **1.695s**;
- drops 0;
- worker errors 0;
- reference asset episodes 0;
- hydration budget skips 0;
- reservation superset violations 0;
- bundles non-empty / replay auditable;
- v34 demoted pending jobs 80;
- demoted finalizer acks pending 0.

Resultado: **UNIFIED MARKET LATENCY v37 = PASS 11/11**.

Não mexer em scheduler/workers/SQLite/hydration sem nova evidência.

## Jupiter executable entry

Provider:
- `jupiter_swap_v2_order`;
- purpose `entry_executable_buy_v1`;
- first 12 new episodes;
- input USDC;
- frozen notional US$25;
- slippage 100bps;
- taker public address only;
- STARTED antes de I/O;
- terminal immutable;
- sem private key, signing ou execute.

Persisted v34 diagnostic:
- attempts 12;
- `route_id` 12/12;
- AVAILABLE 0;
- UNAVAILABLE 12;
- assembled transaction 0;
- provider reason 12/12 `code=1 / Insufficient funds`.

Classificação:
- **route availability = PASS 12/12**;
- **funded executable assembly = BLOCKED_BY_FUNDING**.

Final executable quote PASS continua exigindo na mesma fresh run:
- latency 11/11 PASS;
- selected>0;
- terminal coverage100%;
- CONFIG_MISSING0;
- worker errors0;
- reused attempts0;
- >=1 AVAILABLE com assembled transaction persistida;
- clocks causais válidos;
- nenhum synthetic/backfill.

## v35 taker readiness

`jupiter_taker_readiness_v35.py` é READ ONLY:
- `getBalance` SOL;
- `getTokenAccountsByOwner` USDC;
- sem Jupiter order/sign/execute/transfer.

Taker observado:
`DEoSVsCUAdszfYaxWwJrz3MfftByPNvNMe4aUu5BDgij`

- SOL 0;
- USDC 0;
- required USDC 25;
- deficit 25;
- project readiness min SOL 0.01;
- `INSUFFICIENT_USDC_AND_SOL`.

Não gastar nova coorte funded até esse preflight ficar READY. READY sozinho ainda não é executable quote PASS.

## Hazard v36 — Solana Tracker continua falha histórica explícita

Provider:
- `solana_tracker_token_info`;
- purpose `token_hazard_v1`.

Live v36:
- selected12;
- terminal coverage100%;
- AVAILABLE0;
- PROVIDER_ERROR12;
- reused0;
- worker errors0;
- causal violations0.

Persisted diagnostic provou 12/12:
`SolanaTrackerAuthenticationError: HTTP 403: Insufficient credits for this request`.

Classificação:
- plumbing/terminal observability: funcionou;
- provider availability: FAIL;
- root cause: **BLOCKED_BY_PROVIDER_CREDITS**.

Não alterar endpoint/retries/workers para mascarar esse resultado e não promover v36 retroativamente para PASS.

## v37 — minimal causal on-chain hazard — LIVE PASS

Arquivos:
- `src/opportunity_onchain_hazard.py`;
- `unified_market_onchain_hazard_smoke_v37.py`;
- `tests/test_opportunity_onchain_hazard.py`;
- `tests/test_unified_market_onchain_hazard_smoke_v37.py`;
- `docs/onchain-hazard-v37-protocol-2026-09-04.md`.

Provider:
- `solana_rpc_mint_hazard_v1`;
- purpose `token_hazard_minimal_v1`.

Core via `getAccountInfo(jsonParsed)`:
- SPL Token / Token-2022;
- decimals;
- raw supply;
- mint authority presence;
- freeze authority presence;
- Token-2022 extensions quando expostas;
- Mint context slot.

Auxiliary via `getTokenLargestAccounts`:
- `top10_token_account_concentration_pct`;
- count/raw sum/context slot quando disponível.

Nomenclature invariant:
- largest token accounts != unique holders/owners;
- nunca chamar essa métrica de holder concentration.

Live v37:
- selected12;
- AVAILABLE12;
- terminal coverage100%;
- core complete12;
- core incomplete0;
- worker errors0;
- reused0;
- causal violations0;
- concentration range/semantic violations0;
- concentration available0;
- largest-accounts auxiliary errors12.

Classificação: **PASS_CAUSAL_ONCHAIN_HAZARD_PROVIDER**.

A falha auxiliar 12/12 não apaga o Mint core válido e não será “corrigida” com dado sintético. Investigar separadamente apenas se/quanto essa feature auxiliar justificar dependência operacional.

Hazard terminal latency v37 p95 ~7.91s é aceitável porque a fila é off-path; não colocar hazard no hot path do detector apenas para reduzir esse número.

## Wallet market-first history v38 — strict pre-T0 — CODE/CI READY

Arquivos:
- `src/opportunity_wallet_intelligence.py`;
- `src/opportunity_wallet_market_history.py`;
- `src/opportunity_episode_enrichment.py`;
- `wallet_market_history_diagnostic_v38.py`;
- `tests/test_opportunity_wallet_market_history.py`;
- `tests/test_opportunity_wallet_history_enrichment_guard.py`;
- `docs/market-first-wallet-history-v38-protocol-2026-09-04.md`.

### Separação semântica obrigatória

**Wallet-owned historical outcome** e **market-first wallet/opportunity association** são famílias diferentes.

Um outcome +5/+15/+60 de uma oportunidade onde a wallet apareceu:
- NÃO é PnL realizado da wallet;
- NÃO prova que a wallet entrou no nosso quote;
- NÃO prova que ela saiu naquele horizonte;
- NÃO prova landing/fill nosso.

Por isso o novo label é:
`executable_quote_return_pct`

e fica separado de:
`realized_return_pct`.

### Fonte oficial permitida

Uma associação só existe quando a lineage anterior contém:
1. market-first episode com `decision_as_of` congelado;
2. Jupiter entry attempt AVAILABLE;
3. `assembled_transaction_present=True`;
4. executable BUY quote válido e observado dentro do prior decision clock;
5. exact forward outcome no horizonte predeclared;
6. status AVAILABLE;
7. executable SELL quote válido;
8. outcome + exit quote estritamente conhecidos antes do T0 atual;
9. wallet atual realmente presente no prior opportunity decision window de 30s.

O loader **não lê** legacy Discovery/Copyability, Solana Tracker leaderboard PnL, old wallet-forward research ou resultados exploratórios v2/v3.

### Strict pre-T0 rule

Para current T0:
`current_episode.first_trigger_observed_at`

Obrigatório:
- prior `decision_as_of < current_t0`;
- prior `outcome_observed_at < current_t0`;
- prior exit quote `observed_at < current_t0`.

Igualdade é excluída por ambiguidade de ordering em timestamps de segundo.

`history_cutoff` pode ser mais conservador que T0, nunca posterior.

O próprio enrichment bundle repete essa validação e rejeita injeção manual post-T0 mesmo que alguém tente pular o loader.

### Horizon rule

Horizon aceito: 300 / 900 / 3600 segundos.

- uma snapshot usa um único horizon predeclared;
- não existe fallback automático entre horizontes;
- não escolher o melhor historical label retroativamente;
- não promover 15m só porque resultados exploratórios antigos eram mais fortes.

### Missingness

Se não existir lineage oficial:
`no_valid_market_first_history_sample`

é o estado correto, não loss e não strategy failure.

Como funded executable assembly ainda está bloqueado, **a expectativa atual é zero official market-first wallet associations**. O diagnóstico local v38 deve portanto ser inconclusivo até existirem decisões/outcomes oficiais anteriores.

CI do protocolo v38: compile + unit tests PASS em 2026-09-04.

## Risk bundle / decision readiness

`src/opportunity_episode_enrichment.py`:
- providers de hazard versionados ficam semanticamente separados;
- token-account concentration nunca vira Solana Tracker holder metric;
- hazard observado depois de bundle `as_of` não é backfilled;
- market-first wallet history precisa ser strict pre-T0, mesmo que o bundle seja montado depois.

`src/opportunity_decision_readiness.py`:
- aceita Solana Tracker e on-chain RPC hazard como providers distintos;
- on-chain AVAILABLE incompleto falha fechado;
- hazard terminal missing/error pode permanecer explicit missingness;
- executable entry continua hard prerequisite da coorte econômica;
- `Insufficient funds` => `BLOCKED_BY_FUNDING`;
- não congela `decision_as_of` automaticamente.

## Forward outcomes +5/+15/+60 — infra READY

`src/opportunity_forward_outcome_store.py`

- só agenda após `decision_as_of` congelado;
- horizons 300/900/3600s;
- target = decision + horizon;
- PENDING idempotente;
- observation não pode preceder target;
- AVAILABLE exige executable quote artifact key;
- UNAVAILABLE/PROVIDER_ERROR explícitos;
- terminal immutable;
- sem later candle/artificial backfill.

Ainda falta o collector econômico oficial apoiado no funded executable gate; não iniciar coorte antes disso.

## Ordem de trabalho atual

Enquanto funding continua externo:
1. v37 hazard fica congelado como PASS; não ajustar por outcome;
2. rodar apenas o diagnóstico SQLite v38 para confirmar estado explícito de no official history sample;
3. preparar o collector de forward executable SELL quotes +5/+15/+60 sem iniciar coorte oficial;
4. manter decision readiness/bundle pronto, sem freeze oficial;
5. investigar `getTokenLargestAccounts` auxiliar somente se houver benefício claro, sem transformar isso em blocker.

Quando funding puder ser usado:
1. v35 preflight READY;
2. fresh integrated funded executable quote gate PASS;
3. on-chain minimal hazard já validado;
4. freeze final `decision_as_of`;
5. executable forward outcomes +5/+15/+60;
6. histórico market-first começa a nascer naturalmente para episódios futuros;
7. short true economic E2E smoke;
8. provider/clock/cost/dedup/reconnect audit;
9. hydration/rate/backpressure policy;
10. freeze runnable protocol;
11. primeira coleta 12h;
12. somente depois ablation/time-split para medir edge e valor incremental de wallet/hazard/flow.

## Shadow / live

- systems acquisition/latency: **PASS**;
- Jupiter route: **PASS**;
- funded executable entry: **BLOCKED_BY_FUNDING**;
- Solana Tracker hazard: **BLOCKED_BY_PROVIDER_CREDITS**;
- on-chain hazard v37: **PASS**;
- market-first wallet history v38: **CODE/CI READY; official sample not yet available**;
- decision_as_of: official freeze pending;
- executable forward outcomes: official collection pending;
- economic edge: **NOT ESTABLISHED**;
- shadow/live money: **NOT RELEASED**.

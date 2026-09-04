# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado permanece em `docs/`; aqui ficam estado canônico, invariantes, gates e próxima ordem de trabalho.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo canônico:
  `market data -> unified radar -> detector -> opportunity episode -> flow/wallet/context -> execution/hazard -> decision_as_of -> executable forward outcomes -> economic evaluation`.

Status canônico:

- Pump native acquisition: **PASS**.
- PumpSwap native acquisition + causal pool resolution: **PASS**.
- Unified radar -> causal opportunity episode: **PASS**.
- Replay / continuation hardening: **PASS / auditável**.
- **Unified Market Latency v34/v37: FORMAL PASS 11/11.**
- **Jupiter route availability: PASS 12/12.**
- **Funded executable BUY assembly: BLOCKED_BY_FUNDING.**
- v35 taker readiness: `SOL=0`, `USDC=0`, déficit USDC `25`, `INSUFFICIENT_USDC_AND_SOL`.
- Solana Tracker hazard v36: **FAIL / BLOCKED_BY_PROVIDER_CREDITS** — 12/12 `HTTP 403: Insufficient credits for this request`.
- **Solana RPC on-chain hazard v37: FORMAL PROVIDER PASS 12/12**, no mesmo live em que latency também passou 11/11.
- Wallet market-first history v38: **strict causal lineage PASS / official history sample INCONCLUSIVE**, pois não existem decisões/outcomes econômicos oficiais anteriores.
- Forward route-only v39: **CODE/CI READY**; pesquisa causal de rota SELL sem taker, explicitamente incapaz de completar outcome econômico oficial.
- `decision_as_of`: mecanismo/readiness CODE/CI READY; **nenhum freeze oficial enquanto funded executable BUY estiver bloqueado**.
- Official forward outcomes +5m/+15m/+60m: schema/schedule CODE/CI READY; coleta executável oficial ainda bloqueada.
- Economic edge/profitability: **NOT ESTABLISHED**.
- Shadow/live money: **NOT RELEASED**.
- **Não iniciar coleta de 12h ainda.**

Bloqueios externos não são strategy failure:
- funding pode esperar;
- créditos do Solana Tracker não serão comprados apenas para fabricar PASS;
- o provider on-chain v37 já remove a dependência de Solana Tracker para hazard mínimo;
- implementação paralela não muda a precedência dos gates econômicos finais.

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
- Não criar threshold porque uma feature “parece boa” ou porque um histórico favorece um corte.
- Reordenar implementação por blocker externo não muda a precedência da validação final.
- Route availability != assemblable transaction != landed transaction != fill.
- Um outcome de oportunidade onde uma wallet apareceu **não é P&L realizado da wallet**.

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

Run: `unified-market-onchain-hazard-smoke-20260904-37`

- elapsed 120.2s;
- received PumpSwap 3061 + Pump 2720 = **5781**;
- processed PumpSwap 3061 + Pump 2710 = **5771**;
- coverage **99.8%**;
- true backlog `10/5781 = 0.173%`;
- Pump radar p95 **1.397s**;
- PumpSwap pipeline p95 **1.695s**;
- drops / worker errors / reference assets / budget skips / superset violations = 0;
- v34 demoted pending jobs 80;
- demoted finalizer acks pending 0.

Resultado: **UNIFIED MARKET LATENCY v37 = PASS 11/11**.

Não mexer em scheduler/workers/SQLite/hydration sem nova evidência.

## Jupiter executable BUY entry

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
- route_id 12/12;
- AVAILABLE 0;
- UNAVAILABLE 12;
- assembled transaction 0;
- provider reason 12/12 `code=1 / Insufficient funds`.

Classificação:
- **route availability = PASS 12/12**;
- **funded executable assembly = BLOCKED_BY_FUNDING**.

Final executable BUY PASS continua exigindo numa fresh run:
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
- getBalance SOL;
- getTokenAccountsByOwner USDC;
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

Provider `solana_tracker_token_info`, purpose `token_hazard_v1`.

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
- plumbing/terminal observability funcionou;
- provider availability FAIL;
- root cause **BLOCKED_BY_PROVIDER_CREDITS**.

Não promover v36 retroativamente para PASS.

## v37 — minimal causal on-chain hazard — LIVE PASS

Provider `solana_rpc_mint_hazard_v1`, purpose `token_hazard_minimal_v1`.

Core:
- SPL Token / Token-2022;
- decimals;
- raw supply;
- mint authority presence;
- freeze authority presence;
- Token-2022 extensions quando expostas;
- Mint context slot.

Auxiliary `getTokenLargestAccounts`:
- `top10_token_account_concentration_pct` quando disponível;
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

A falha auxiliar não apaga o Mint core válido e não será “corrigida” com dado sintético. Hazard é off-path.

## Wallet market-first history v38 — strict pre-T0

Arquivos principais:
- `src/opportunity_wallet_intelligence.py`;
- `src/opportunity_wallet_market_history.py`;
- `src/opportunity_episode_enrichment.py`;
- `wallet_market_history_diagnostic_v38.py`;
- `docs/market-first-wallet-history-v38-protocol-2026-09-04.md`;
- `docs/wallet-history-v38-diagnostic-2026-09-04.md`.

### Semântica

Wallet-owned historical outcome e market-first wallet/opportunity association são famílias diferentes.

O label da associação é:
`executable_quote_return_pct`

Ele NÃO é `realized_return_pct` da wallet.

### Lineage permitida

Uma associação só pode existir quando o prior episode tem:
1. market-first `decision_as_of` congelado;
2. Jupiter entry attempt AVAILABLE;
3. assembled transaction evidence;
4. executable BUY quote dentro do prior decision clock;
5. exact predeclared forward outcome;
6. executable SELL quote válido;
7. outcome e SELL quote estritamente conhecidos antes do current T0;
8. current wallet realmente presente no prior opportunity decision window de 30s.

Legacy Discovery/Copyability, leaderboard PnL, old wallet-forward research e exploratórios v2/v3 são ignorados.

Strict rule:
- prior decision < current T0;
- prior outcome observed_at < current T0;
- prior SELL quote observed_at < current T0;
- igualdade é excluída por ambiguidade em clock de segundos.

### Live persisted diagnostic v38

Run inspecionada: `unified-market-onchain-hazard-smoke-20260904-37`

- episodes=12;
- participant wallet observations=194;
- candidate prior official episodes=0;
- eligible labeled prior episodes=0;
- matching prior episodes=0;
- associations=0;
- `no_prior_official_market_first_decisions`: 12/12;
- `no_valid_market_first_history_sample`: 12/12.

Classificação:
**INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE**.

Interpretação: comportamento causal correto. O sistema preferiu zero histórico a reutilizar labels contaminados. Isso não é strategy failure nem evidência de edge.

## Forward outcomes +5/+15/+60 — official store

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

## v39 — causal forward SELL route-only — CODE/CI READY

Arquivos:
- `src/jupiter_forward_exit_route.py`;
- `src/opportunity_forward_due.py`;
- `forward_exit_route_probe_v39.py`;
- `tests/test_jupiter_forward_exit_route.py`;
- `tests/test_opportunity_forward_due.py`;
- `tests/test_forward_exit_route_probe_v39.py`;
- `docs/forward-exit-route-v39-protocol-2026-09-04.md`.

Objetivo: preparar observabilidade causal do lado SELL sem inventar uma posição que a wallet paper não possui.

Regra central:
- SELL route-only usa o exact `output_amount_raw` do prior executable BUY quote como sizing;
- roda somente quando um official scheduled outcome já está due;
- `target_at = decision_as_of + horizon`;
- quote observed_at precisa ser >= target;
- target lateness fica explícito;
- input token -> USDC;
- `taker=None`;
- no signing / no execute / no private key.

**Route-only nunca completa official forward outcome.**

Uma route-only quote válida precisa permanecer:
`executable=False`.

Se Jupiter inesperadamente retornar assembled transaction sem taker, v39 falha fechado com normalization/protocol error.

Classificações:
- `INCONCLUSIVE_NO_DUE_OFFICIAL_FORWARD_OUTCOMES`;
- `PASS_ROUTE_ONLY_FORWARD_OBSERVABILITY`;
- `INCONCLUSIVE_NO_AVAILABLE_FORWARD_ROUTE`;
- `FAIL_ROUTE_ONLY_EXECUTABILITY_SEMANTICS`;
- `FAIL_FORWARD_ROUTE_PLUMBING`.

PASS v39 prova apenas route-only observability. NÃO prova:
- token balance para SELL;
- assemblable official SELL;
- landing/fill;
- profitability;
- economic edge.

Motivo estrutural: um executable SELL assembly para um taker real exige que a posição/token supply do taker seja compatível. Como o current BUY é somente assembly research e não é executado, não podemos fingir que a wallet recebeu o token.

CI v39: compile + unit tests **PASS** em 2026-09-04.

## Risk bundle / decision readiness

`src/opportunity_episode_enrichment.py`:
- providers de hazard versionados ficam separados;
- token-account concentration nunca vira holder metric;
- hazard post-as_of não é backfilled;
- market-first wallet history precisa ser strict pre-T0 mesmo se bundle for montado depois.

`src/opportunity_decision_readiness.py`:
- on-chain hazard AVAILABLE incompleto falha fechado;
- hazard terminal missing/error permanece explicit missingness;
- executable BUY entry é hard prerequisite da coorte econômica;
- Insufficient funds => BLOCKED_BY_FUNDING;
- não congela `decision_as_of` automaticamente.

## Ordem de trabalho atual

Enquanto funding continua externo:
1. v34/v37 systems latency ficam congelados como PASS;
2. v37 hazard fica congelado como PASS;
3. v38 strict wallet-history lineage fica congelado; no-sample atual é esperado;
4. v39 route-only SELL plumbing fica CODE/CI READY e não deve ser promovido a official outcome;
5. manter official decision/outcome collectors preparados sem iniciar coorte;
6. investigar `getTokenLargestAccounts` apenas se houver benefício incremental claro;
7. não criar novos thresholds/score antes de labels forward oficiais.

Quando funding puder ser usado:
1. v35 preflight READY;
2. fresh integrated funded executable BUY gate PASS;
3. on-chain minimal hazard já validado;
4. freeze final `decision_as_of`;
5. schedule exact +5/+15/+60 outcomes;
6. coletar official executable SELL evidence sem substituir por route-only;
7. histórico market-first começa a nascer naturalmente para episódios futuros;
8. short true economic E2E smoke;
9. provider/clock/cost/dedup/reconnect audit;
10. hydration/rate/backpressure policy;
11. freeze runnable protocol;
12. primeira coleta 12h;
13. depois ablation/time-split para medir edge e valor incremental de wallet/hazard/flow.

## Shadow / live

- systems acquisition/latency: **PASS**;
- Jupiter route: **PASS**;
- funded executable BUY: **BLOCKED_BY_FUNDING**;
- Solana Tracker hazard: **BLOCKED_BY_PROVIDER_CREDITS**;
- on-chain hazard v37: **PASS**;
- market-first wallet history v38: **LINEAGE CORRECT / OFFICIAL SAMPLE INCONCLUSIVE**;
- forward route-only v39: **CODE/CI READY**;
- decision_as_of: official freeze pending;
- official executable forward outcomes: pending;
- economic edge: **NOT ESTABLISHED**;
- shadow/live money: **NOT RELEASED**.

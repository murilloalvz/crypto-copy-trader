# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado permanece em `docs/`; aqui ficam estado canônico, invariantes, gates e a próxima ordem de trabalho.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo canônico:
  `market data -> unified radar -> detector -> opportunity episode -> flow/wallet/context -> execution/hazard -> decision_as_of -> executable forward outcomes`.

Gates / status:

- Pump native acquisition: PASS.
- PumpSwap native acquisition + causal pool resolution: PASS.
- Unified radar -> causal opportunity episode: PASS.
- Replay/continuation hardening: PASS / auditável.
- **Unified Market Latency v34: FORMAL PASS 11/11.**
- Live v36 reteve o mesmo path e também passou os 11 gates de latency.
- **Jupiter route availability: PASS 12/12** no live v34.
- **Funded executable assembly: BLOCKED_BY_FUNDING** — provider retornou `Insufficient funds` 12/12.
- v35 taker readiness: `SOL=0`, `USDC=0`, déficit de USDC `25`, classificação `INSUFFICIENT_USDC_AND_SOL`.
- Solana Tracker hazard v36: **FAIL / BLOCKED_BY_PROVIDER_CREDITS** — 12/12 `HTTP 403: Insufficient credits for this request`.
- Novo provider hazard on-chain v37 (`solana_rpc_mint_hazard_v1`): **CODE/CI READY; live pendente**.
- `decision_as_of`: mecanismo/readiness CODE/CI READY; **nenhum freeze oficial enquanto funded executability estiver bloqueada**.
- Forward outcomes +5m/+15m/+60m: schema/schedule CODE/CI READY; coleta econômica oficial ainda bloqueada.
- Historical wallet intelligence: agregador causal CODE READY; labels exploratórios antigos **não podem ser promovidos a evidência oficial**. Histórico econômico oficial depende de prior executable forward outcomes já observados antes do novo `as_of`.
- Economic edge/profitability: **não estabelecido**.
- Shadow/live money: **não liberado**.
- **Não iniciar coleta de 12h ainda.**

Bloqueios externos não devem ser reinterpretados como strategy failure:
- funding da wallet é opcional agora e pode esperar;
- créditos do Solana Tracker não serão comprados apenas para fabricar PASS;
- implementação independente pode avançar, mas a ordem da validação final permanece congelada.

## North star

```text
market changes state
-> causal radar
-> opportunity episode
-> flow / microstructure
-> liquidity / executable entry
-> token hazard / manipulation descriptors
-> wallets actually present + only pre-T0 resolved history
-> freeze final decision_as_of
-> executable forward outcomes
-> economic evaluation
```

Objetivo científico: testar se informação realmente disponível no momento da decisão produz resultados forward líquidos favoráveis fora da amostra, sem survivorship, lookahead, retroactive enrollment ou artificial backfill.

## Princípios congelados

- Histórico exploratório de P&L não é prova causal de edge.
- Detector/estratégia/coorte ficam congelados durante validação de infraestrutura e providers.
- Separar signal quality, observability, executability, economic replay e systems latency.
- No-sample não significa strategy failure.
- Wallet é evidência pós-episódio, nunca acquisition whitelist.
- Missing/failure de provider permanece explícito.
- Nunca substituir missing provider por candle/quote/snapshot posterior.
- Primeiro trigger-to-episode **persistido** permanece canônico.
- Late-earlier não retrocede T0 e não abre episódio retroativo concorrente.
- PASS de systems latency não significa profitability PASS.
- Não aumentar workers por tentativa; primeiro localizar o relógio dominante.
- Nenhum live money sem forward evidence robusta + gate explícito.
- Reordenar implementação por causa de um blocker externo não muda a precedência dos gates finais.
- Features de hazard permanecem descritivas até haver evidência forward de utilidade preditiva. Não criar threshold de entrada porque uma feature “parece arriscada”.

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

## Systems latency — baseline congelado

Formal gate, ALL:

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

### v34 canonical live PASS

- received 4892;
- processed 4814;
- coverage 98.4%;
- true backlog 1.594%;
- Pump p95 2.053s;
- PumpSwap pipeline p95 1.712s;
- errors/drops/ref/budget/superset violations = 0;
- `demoted_pending_jobs=83`;
- `demoted_finalizer_acks_pending=0`.

Resultado: **FORMAL PASS 11/11**.

v34 semantics:
- proof-based late continuation demotion;
- apenas pending continuation-only provado pode sair do stateful dependency graph;
- payload demovido ainda passa pelo normal finalizer para audit/hits/metrics;
- ambiguous/late-earlier/different-window continua strict FIFO;
- ready/running nunca é demovido.

### v36 retained latency live

Mesmo com fila hazard off-path:
- total received 6906;
- processed 6887;
- coverage 99.7%;
- true backlog ~0.275%;
- Pump p95 1.808s;
- PumpSwap p95 2.729s;
- drops/errors/ref/budget/superset violations = 0;
- v34 demotion exercitada 119 vezes, ack pending 0.

Resultado de latency dessa run: **PASS 11/11**.

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

`jupiter_taker_readiness_v35.py`

READ ONLY:
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

## Hazard v36 — Solana Tracker permanece falha histórica explícita

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

Classificação correta:
- plumbing/terminal observability: funcionou;
- provider availability: FAIL;
- root cause: **BLOCKED_BY_PROVIDER_CREDITS**.

Não alterar endpoint/retries/workers para mascarar esse resultado e não promover v36 retroativamente para PASS.

## v37 — minimal causal on-chain hazard — CODE/CI READY

Arquivos principais:
- `src/opportunity_onchain_hazard.py`;
- `tests/test_opportunity_onchain_hazard.py`;
- `unified_market_onchain_hazard_smoke_v37.py`;
- `tests/test_unified_market_onchain_hazard_smoke_v37.py`;
- `docs/onchain-hazard-v37-protocol-2026-09-04.md`;
- integração versionada em `src/opportunity_episode_enrichment.py` e `src/opportunity_decision_readiness.py`.

Provider:
- `solana_rpc_mint_hazard_v1`;
- purpose `token_hazard_minimal_v1`.

Core via Solana RPC `getAccountInfo(jsonParsed)`:
- SPL Token program;
- classic Token vs Token-2022;
- decimals;
- raw supply;
- mint authority present/absent;
- freeze authority present/absent;
- Token-2022 extensions expostas pelo RPC;
- Mint context slot.

Auxiliary via `getTokenLargestAccounts`:
- count returned;
- top-10 raw token-account sum;
- `top10_token_account_concentration_pct`;
- auxiliary context slot.

### Nomenclature invariants

`getTokenLargestAccounts` fornece **token accounts**, não unique owners.

Portanto:
- `top10_token_account_concentration_pct` é permitido;
- “top10 holders”, “holder concentration”, “owner concentration” NÃO são equivalentes e não podem ser usados para essa métrica;
- quando a concentração existe, quality flags deixam essa semântica explícita.

### Failure / causal semantics

- at-most-once por run/episode/provider/purpose;
- STARTED antes do RPC;
- uma primary endpoint / uma tentativa por método no probe v37;
- sem retry/fallback tail para buscar snapshot posterior;
- Mint RPC failure => PROVIDER_ERROR;
- missing Mint => UNAVAILABLE;
- malformed/unsupported Mint => NORMALIZATION_ERROR;
- largest-accounts failure é AUXILIARY: core Mint válido continua AVAILABLE, com erro auxiliar explícito;
- cross-slot concentração >100% não é corrigida artificialmente: métrica fica missing e raw sums/flags permanecem auditáveis;
- nenhum risk score/rug/dev/sniper/bundler/insider label é sintetizado.

### Frozen v37 provider gate

PASS somente quando:
1. selected>0 (`0 => INCONCLUSIVE_NO_SAMPLE`);
2. terminal coverage100%;
3. CONFIG_MISSING0;
4. hazard worker errors0;
5. reused0 fresh run;
6. causal clock violations0;
7. >=1 AVAILABLE;
8. todo AVAILABLE tem core Mint completo (program, decimals, supply, mint/freeze authority observability);
9. concentração, se presente, fica em [0,100];
10. concentração, se presente, carrega flag explícita de que NÃO é holder concentration.

Concentration availability não é threshold de PASS.

Mesmo run ainda precisa ser avaliada separadamente pelos 11 gates de systems latency.

**Live v37 ainda pendente.**

## Risk bundle / decision readiness

`src/opportunity_episode_enrichment.py` aceita providers versionados sem fundi-los semanticamente:
- campos Solana Tracker permanecem provider-native;
- campos RPC on-chain permanecem separados;
- concentração de token accounts nunca é copiada para `top10_pct` do Solana Tracker;
- hazard observado após bundle `as_of` é excluído em vez de backfilled.

`src/opportunity_decision_readiness.py`:
- aceita o provider Solana Tracker e o provider RPC v37 como identidades distintas;
- on-chain AVAILABLE incompleto falha fechado;
- hazard terminal unavailable/error pode permanecer como missingness explícita;
- executable entry continua hard prerequisite para coorte econômica oficial;
- `Insufficient funds` => `BLOCKED_BY_FUNDING`;
- não congela `decision_as_of` sozinho.

## Wallet historical intelligence

`src/opportunity_wallet_intelligence.py` já impõe:
- wallets vêm da oportunidade atual, nunca whitelist de aquisição;
- current participation precisa estar observada <= `as_of`;
- current episode é excluído do próprio histórico;
- historical outcome só entra se `outcome_observed_at <= as_of`;
- unresolved/future labels permanecem missing;
- sem BUY/SELL recommendation ou wallet score dentro dessa camada.

Regra adicional congelada:
- os resultados wallet-first exploratórios antigos não são labels oficiais para a tese market-first atual;
- historical wallet outcomes oficiais só devem ser derivados de episódios anteriores com lineage executável e outcome já observado causalmente antes do novo `as_of`.

Até existir essa lineage econômica oficial, **no valid history sample** é melhor que artificial backfill.

## Forward outcomes +5/+15/+60 — infra READY

`src/opportunity_forward_outcome_store.py`

- só agenda após `decision_as_of` congelado;
- horizons 300/900/3600s;
- target exato = decision + horizon;
- PENDING idempotente;
- observation não pode preceder target;
- AVAILABLE exige executable quote artifact key;
- UNAVAILABLE/PROVIDER_ERROR explícitos;
- terminal immutable;
- sem later candle/artificial backfill.

Não iniciar coorte econômica oficial antes do funded executable gate.

## Ordem de trabalho atual

Enquanto funding continua externo:
1. live v37 causal on-chain hazard mantendo v34 latency path;
2. se v37 PASS, congelar provider semantics; não ajustar hazard por outcomes;
3. continuar preparando historical wallet lineage apenas com official prior executable outcomes quando existirem;
4. manter decision bundle/readiness preparado, mas sem freeze oficial;
5. manter forward outcome collector/schema preparado, sem iniciar coorte.

Quando funding puder ser usado:
1. v35 preflight READY;
2. fresh integrated funded executable quote gate;
3. minimal hazard/risk gate já validado;
4. historical wallet pre-T0 evidence quando aplicável;
5. freeze final `decision_as_of`;
6. executable forward outcomes +5/+15/+60;
7. short true economic E2E smoke;
8. provider/clock/cost/dedup/reconnect audit;
9. hydration/rate/backpressure policy;
10. freeze runnable protocol;
11. primeira coleta 12h.

## Shadow / live

- systems acquisition/latency: PASS;
- Jupiter route: PASS;
- funded executable entry: BLOCKED_BY_FUNDING;
- Solana Tracker hazard: BLOCKED_BY_PROVIDER_CREDITS;
- on-chain hazard v37: CODE/CI READY, live pending;
- decision_as_of: official freeze pending;
- executable forward outcomes: official collection pending;
- economic edge: NOT ESTABLISHED;
- shadow/live money: **NOT RELEASED**.

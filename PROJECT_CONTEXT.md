# Crypto Copy Trader — Project Context

Este arquivo registra o estado técnico consolidado do projeto. Ideias discutidas fora do código devem ser tratadas como hipóteses até serem confirmadas no repositório e por testes reproduzíveis.

## Estado operacional

- Branch ativa: `feat/exit-engine-v1`.
- Modo de mercado: **PAPER / RESEARCH / READ ONLY**. Nenhum fluxo habilitado assina ou envia transações reais.
- Persistência: SQLite via `DATABASE_PATH` (padrão `data/copytrader.db`).
- Estratégia Wave ativa: `wave_v3_volume_integrity`, com entrada **CONGELADA** durante a formação de evidência forward.
- Solana Tracker Data API: bloqueada por `403 Insufficient credits`; não gastar novas chamadas até reset/restauração.
- GeckoTerminal: preços/candles/settlement histórico com pacing e budget adaptativo.
- Solana RPC público: Wallet Forward Watch.
- Jupiter Swap V2 `GET /order`: integração read-only implementada; não existe `/execute`, assinatura ou envio de transação no fluxo liberado.
- Rede escolar apresentou TLS/certificado raiz não confiável para Jupiter; usar internet doméstica/hotspot para coletas reais.
- A primeira coleta longa Wallet + Jupiter com BUYs reais foi concluída em 2026-09-01: `wallet-forward-1788217626-543a9b6b`, runtime legacy v1, 21 ações forward, 13 BUYs e 65/65 quotes proxy bem-sucedidas.
- O evento real `Wallet BUY -> detector RPC -> Jupiter -> persistência -> replay causal descritivo` passou de **AGUARDANDO AMOSTRA** para **VALIDADO OPERACIONALMENTE EM PROXY MODE**. Isso não valida fill, edge ou copyability.
- Última suíte de código confirmada após o novo Sample Quality audit: **394 testes aprovados, zero falhas**, com `compileall` aprovado, no commit `a731844`.

## Regra central de validação

```text
IMPLEMENTADO
-> TESTADO
-> VALIDADO OPERACIONALMENTE
-> EVIDÊNCIA ECONÔMICA
-> SHADOW
-> LIVE CANARY
```

Código funcionando não prova edge. Backtest positivo não libera live. Nenhuma política/wallet/estratégia é chamada de vencedora sem cobertura, missingness, custos, outliers, causalidade, independência da amostra e validação forward adequados.

## Arquitetura atual

### Wave / paper

- `radar.py`: token discovery, Wave Radar e persistência paper.
- `src/wave_radar.py`: integridade, Wave Score, barreiras e cautions.
- `src/wave_paper.py`: sinais versionados, cooldown e checkpoints 5m/15m/60m.
- `src/wave_funnel.py`: cobertura e attrition por discovery.
- `evaluate.py` + `src/wave_metrics.py`: cobertura, retorno, PF, drawdown, Wilson, missingness, outliers e slippage.
- `backtest_concurrent.py` / `simulate_bankroll.py`: capital concorrente e stress.

### Exit Engine

- `src/exit_engine.py`: coorte forward e políticas pareadas.
- Políticas v1 congeladas: fixed15, fixed60, SL -10%, TP +20%, trailing 10%.
- `src/exit_metrics.py` + `evaluate_exits.py`: avaliação pareada.
- Políticas dinâmicas usam apenas candles realmente observados; não existe reconstrução retroativa do caminho.

### Wallet Strategy Intelligence

- `src/onchain_wallet_research.py`: sequência on-chain observada por wallet.
- `src/wallet_exit_sizing.py`: sizing descritivo de saídas a partir de deltas de swap.
- `src/wallet_strategy_lab.py`: fingerprints de holding/exit/reentry/frequência/sizing/DEX.
- `src/wallet_strategy_compare.py`: comparação multi-wallet.
- `src/wallet_strategy_readiness.py`: evidence readiness e fila de pesquisa.
- Fingerprint não é PnL, Copyability Score ou recomendação de cópia.

### Wallet Forward runtime

- `src/wallet_forward_observations.py` / `src/wallet_forward_collector.py`: ações forward com `chain_time` e `observed_at`.
- `wallet_watch_forward.py`: coletor RPC.
- Runtime v1 legacy: `wallet_forward_runtime_v1_unversioned`.
- Runtime v2: `wallet_forward_runtime_v2_causal_boundary`, adicionou fronteira causal depois do bootstrap para bloquear late-hydrated pre-start transactions.
- Runtime atual para novas coletas: **`wallet_forward_runtime_v3_rotating_poll_order`**.
- v3 gira a ordem de polling da coorte a cada ciclo para não dar sistematicamente à primeira wallet a menor latência.
- Polling continua não sendo streaming; rotação reduz viés de ordem, não elimina a latência RPC.
- `wallet_forward_integrity.py`: audita causalidade sem apagar/reclassificar evidência.
- `wallet_forward_exposure.py`: mede right-censoring e quanto follow-up cada BUY realmente recebeu.
- `wallet_forward_run_admin.py`: recuperação explícita de run ACTIVE órfã, com confirmação de que os processos pararam.
- Manifests finalizados são imutáveis: `ACTIVE -> COMPLETED/ABORTED`; não existe reclassificação posterior silenciosa.
- Nova run é bloqueada quando outra manifest está ACTIVE no mesmo banco, evitando coortes sobrepostas acidentalmente.

### Causal Quote / Jupiter / Replay

- `src/jupiter_swap_v2.py`: cliente read-only para `/swap/v2/order`.
- `src/causal_quotes.py` + `src/causal_quote_store.py`: quotes causais BUY/SELL e metadados de rota.
- `src/wallet_quote_watch.py`: agenda quotes após BUY forward e persiste sucesso **e falha**.
- Delays padrão `0/15/30/60/120s` são delays **após `wallet_observed_at`**, não após `chain_time`.
- `src/wallet_quote_completeness.py`: reconstrói o denominador esperado `BUY causal × delays`, mantendo probes nunca iniciados como missing.
- `src/wallet_causal_replay.py`: replay sem lookahead usando somente quotes disponíveis depois de detecção + delay.
- `wallet_forward_checkpoint.py`: checkpoint run-scoped, BUY-only para viabilidade de entrada e quotes ligados ao evento exato.
- `src/wallet_quote_drift.py`: drift de preço entre delays do **mesmo BUY**.
- `src/wallet_entry_latency.py` + `wallet_forward_sample_quality.py`: mede `chain_time -> observed_at -> quote_observed_at`, tornando explícita a latência end-to-end real.
- `src/wallet_forward_dependence.py`: mede repetição/concentração da amostra e produz drift token-clustered para não tratar BUYs repetidos nos mesmos poucos tokens como oportunidades independentes.
- Jupiter provider metadata prospectiva agora inclui router, `priceImpact`, `slippageBps` e `swapUsdValue` quando disponível.
- Quote-only é proxy causal de preço/rota; transação montada é apenas candidata; nenhum dos dois prova landing/fill.

### Multi-wallet convergence

- `src/wallet_forward_convergence.py` + `wallet_forward_convergence.py`: convergência causal de BUYs da mesma run.
- Regra exploratória padrão: janela 300s, threshold >=2 wallets BUY únicas, cooldown 1800s/token.
- Usa `observed_at`; backfill posterior não confirma retrospectivamente o passado.
- Convergência é feature de pesquisa, não edge e não sinal de compra.

### Rejection Intelligence

- `src/rejection_intelligence.py`: sidecar observacional para rejeições Wave.
- `rejection_lab.py`: seleção/auditoria/settlement explícito.
- Toda nova discovery bem-sucedida salva snapshots causais de rejeições sem alterar pass/fail.
- Follow-up padrão: até 12 rejeições data-valid por run; prioriza single-barrier near misses; 5m/15m/60m.
- Cooldown de 6h por mint reduz pseudo-amostra e chamadas repetidas.
- Missingness permanece visível; erros temporários ficam pending e permanentes failed.
- `+20%` e `-25%` são cortes descritivos, não TP/SL/gates.

### Market Integrity v1

- `src/market_integrity.py`: features observacionais a partir de snapshots causais agregados.
- `market_integrity_lab.py`: inspeção local accepted/rejected, sem rede.
- Opportunity Context pode anexar Market Integrity disponível até `as_of`.
- Não existe manipulation score nem `wash_trading_detected`.
- Snapshot agregado não permite provar self-trading/wash trading; anti-manipulação séria exige microestrutura, participantes e/ou grafo de funding.

### Wallet Confirmation + Placebo

- `src/wallet_confirmation_placebo.py`: confirmação causal e target x placebo.
- `src/wallet_placebo_matching.py`: matching pré-período sem outcomes/PnL.
- `src/wallet_confirmation_study.py`: registry imutável de estudos prospectivos.
- `src/wallet_confirmation_wave_study.py`: materializa confirmações usando somente wallet observations disponíveis até a oportunidade Wave.
- Target/placebos precisam ser wallet-disjoint e escolhidos com dados pré-período.
- Comparação mantém pending/failed/missing no denominador.
- Universo atual ainda é insuficiente para congelar um estudo econômico sério de Wallet Confirmation.

### Social / Opportunity Intelligence

- Fundação de Social Intelligence e persistência existe.
- Opportunity Intelligence combina Wave/Wallet/Social/Market Integrity causalmente sem score final de trading.
- Coletor X real ainda é **PLANEJADO**.
- Social será avaliado por valor incremental; nunca `tweet -> buy`.

### Shadow / live readiness

- `src/shadow_execution_store.py`: auditoria/persistência de shadow, sem private key/signing/submission.
- `docs/live-readiness-gates-v1.md`: gates até live canary.
- Execução real `quote -> route -> tx -> assinatura -> envio -> confirmação -> reconciliação` ainda não está fechada/liberada.

## Wave v3 — checkpoint 2026-08-31

59 sinais registrados = 19 históricos + 40 forward.

| Horizonte | Cobertura | WR | Média | Mediana | PF | Diagnóstico |
|---|---:|---:|---:|---:|---:|---|
| 5m | 57/59 = 96,6% | 33,3% | -0,44% | -1,60% | 0,84 | sem edge observado a 1% slippage/lado |
| 15m | 53/59 = 89,8% | 45,3% | +2,08% | -1,15% | 1,49 | média sem maior winner = -0,16%; outlier/missingness |
| 60m | 46/59 = 78,0% | 45,7% | +5,28% | -0,14% | 1,54 | 22% failures dominam a inferência |

`wave_v3_volume_integrity` permanece **EM TESTE**. Pode acabar sendo mais útil como sensor de oportunidade/contexto do que como compra automática, mas isso ainda não altera a estratégia.

## Exit Engine — checkpoint 2026-08-31

25 sinais possuíam as cinco políticas fechadas.

- fixed15: média -1,94%, mediana -1,68%, PF 0,67.
- fixed60: média -4,45%, mediana -1,26%, PF 0,65.
- SL10: média -18,88%, mediana -4,23%, PF 0,10.
- TP20: média +4,17%, mediana -1,35%, PF 2,29, média sem melhor +3,49%.
- trailing10: média -17,80%, mediana -4,68%, PF 0,10.

`take_profit_20_v1` = **PROMISSOR / EM TESTE**, não vencedor.

## Wallet Strategy Intelligence — hipóteses congeladas

### 7mPti

`7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`

- histórico local: 94 swaps / 36 tokens / 306,3d.
- fingerprint `one_day|mixed_exit|occasional_reentry|moderate`.
- first exit mediano 18,5h; roundtrip 72,2%; multi-sell 42,3%; reentry 19,2%.
- **DESCRIPTIVE_READY**.
- H1: com >=10 novos roundtrips forward, first exit >6h, multi-sell >=25%, reentry <40%.

### Gf9X

`Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`

- 71 swaps / 36 tokens / 21,2d.
- fingerprint `ultra_short|single_exit_dominant|rare_reentry|moderate`.
- first exit histórico 5,3min; **EVIDENCE_GAPS**.
- H2: após >=10 novos roundtrips adequados, first exit <15m, multi-sell <=25%, reentry <15%.

### 3tc4

`3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`

- 93 swaps / 5 tokens / 0,2d.
- fingerprint `ultra_short|staged_exit_dominant|frequent_reentry|high_frequency`.
- first exit histórico 1,2min; **EVIDENCE_GAPS**.
- H3 só é avaliada após >=10 tokens e >=10 complete-like: first exit <15m, multi-sell >=40%, reentry >=40%, first tranche <=75%.

Nenhum arquétipo multi-wallet está confirmado.

## Wallet Forward + Jupiter — primeiro checkpoint real 2026-09-01

Documento detalhado: `docs/wallet-forward-checkpoint-2026-09-01.md`.

Run: `wallet-forward-1788217626-543a9b6b`.

- runtime legacy v1; quote mode proxy; coorte 7mPti/Gf9X/3tc4.
- ações 21; BUY/SELL 13/8; wallets ativas 2; tokens 3.
- `CAUSAL_BOUNDARY_CLEAN`.
- source lag p50/p95/max 37s/43s/43s; 100% <=60s e 0% <=30s.
- quotes esperadas/tentadas/sucesso: 65/65/65; falhas 0; missing 0.
- transações candidatas montadas: 0; proxy quotes: 65.
- readiness: `CAUSAL_REPLAY_SAMPLE_READY`, exclusivamente como gate de dados.
- 7mPti: 0 ações.
- Gf9X: 1 BUY.
- 3tc4: 20 ações, 12 BUYs/8 SELLs, mas só 2 tokens.
- convergências multi-wallet: 0.

Censoring:

- 15m de follow-up: 13/13 BUYs.
- 1h: 4/13.
- 6h: 0/13.
- 24h: 0/13.

Logo H1 não recebeu teste válido e H2/H3 continuam com amostra insuficiente.

Drift event-level no conjunto:

- +15s: mediana +9,62%, p95 +108,36%.
- +30s: mediana -19,76%, p95 +38,48%.
- +60s: mediana -37,64%, p95 +1,81%.
- +120s: mediana -80,58%, p95 +0,24%.

Em 3tc4, 12 BUYs vieram de apenas 2 tokens; portanto o `n=12` não deve ser tratado como 12 oportunidades econômicas independentes. O novo Sample Quality audit mede concentração/repetição e também drift token-clustered.

Importante: `+0/+15/...` são delays após detecção. Com source lag já em 31–43s, o end-to-end `chain_time -> quote_observed_at` é materialmente maior. A nova auditoria passa a reportar isso diretamente.

Status:

- `Wallet action -> detection -> Jupiter proxy -> persistence -> causal replay path`: **VALIDADO OPERACIONALMENTE**.
- assembled candidate / landing / fill / slippage real: **NÃO VALIDADO**.
- copyability econômica: **EM TESTE**.
- live: **BLOQUEADO**.

## Pesquisa externa incorporada como priors

Documentos principais:

- `docs/memecoin-market-research-priors-2026-08-31.md`;
- `docs/external-evidence-reuse-map-v1.md`;
- `docs/rejection-intelligence-v1.md`;
- `docs/market-integrity-v1.md`;
- `docs/wallet-confirmation-placebo-v1.md`;
- `docs/wallet-placebo-matching-v1.md`;
- `docs/wallet-forward-convergence-v1.md`;
- `docs/wallet-forward-runtime-v2.md`;
- `docs/wallet-forward-runtime-v3.md`;
- `docs/wallet-forward-checkpoint-2026-09-01.md`.

Priors atuais:

- wallets lucrativas podem usar arquétipos muito diferentes;
- PnL alto não significa copyability;
- volume público simples pode não possuir edge isolado;
- memecoins apresentam heavy tails e dependência de poucos winners;
- latência/liquidez/rota fazem parte da estratégia;
- volume aparente pode conter manipulação;
- smart-wallet confirmation precisa de placebo/controle;
- rejeitados precisam de follow-up para medir false negatives;
- evidência de regimes/mercados diferentes não deve ser misturada automaticamente;
- event rows repetidos no mesmo token não devem inflar artificialmente a confiança.

Nenhum threshold externo é copiado diretamente para produção.

## Live readiness

Live permanece **BLOQUEADO**.

```text
causal data
-> hipótese congelada
-> replay com custos
-> robustness / missingness / outliers / dependência
-> shadow forward
-> execution engine + risk controls
-> live canary pequeno e separado
-> comparar live x shadow
-> escalar somente depois
```

Controles mínimos: limite por trade, exposição total, concorrência, perda diária, kill switch, idempotência, stale-quote protection e reconciliação on-chain.

## Limitações conhecidas

- Tracker credits bloqueiam nova discovery Wave/leaderboard.
- GeckoTerminal possui missingness, distant candles e rate limit.
- RPC polling não é streaming; a primeira run real teve source lag de 31–43s.
- Delays Jupiter são relativos à detecção, não ao source chain time.
- Jupiter quote-only não é fill.
- Runtime legacy não possuía provider metadata nova; 0/65 metadata é esperado, sem backfill inventado.
- Runs curtas sofrem right-censoring para hipóteses de holding longo.
- Muitos BUY events podem vir dos mesmos poucos tokens; event-level n não equivale a amostra independente.
- candles 1m não resolvem ordem intraminuto de TP/SL/trailing.
- fingerprints podem refletir inventário preexistente/cobertura parcial.
- realized PnL pode esconder perdas não realizadas.
- market snapshots agregados não provam wash trading.
- Rejection Intelligence é prospectivo; não existe backfill causal honesto de rejeições antigas.
- Wallet Confirmation placebo ainda não possui target/placebos prospectivos congelados nem amostra econômica suficiente.

## Próximas prioridades

1. Rodar o novo `wallet_forward_sample_quality.py` no checkpoint de 2026-09-01 para medir end-to-end chain→quote e dependência/token-clustered drift.
2. Usar runtime v3 com polling rotativo e provider metadata na próxima coleta operacional.
3. Projetar **intake window + follow-up tail** para Wallet Strategy Intelligence, para que todo BUY matriculado possa receber 15m/1h/6h/24h de acompanhamento sem confundir fim da run com hold longo.
4. Manter H1/H2/H3 congeladas; não retunar por causa desta pequena run.
5. Fazer causal replay/cost stress somente com quotes event-scoped e sempre reportar proxy vs assembled candidate separadamente.
   A primeira infraestrutura econômica v1 agora está disponível em `src/wallet_economic_replay.py`
   e `wallet_causal_economic_replay.py`; ela permanece diagnóstica, usa lotes por evento por falta
   de quantidades e não cria PnL sem SELL/quote causal.
6. Quando Tracker voltar, continuar Wave v3 congelada + Rejection Intelligence prospectivo.
7. Ampliar Wallet Strategy Intelligence e formar target/placebos usando somente pré-período.
8. Quando houver universo suficiente, pré-registrar Wallet Confirmation antes de outcomes.
9. Avançar anti-manipulação para microestrutura/grafo apenas quando houver dados que suportem isso.
10. Promover a primeira candidata para shadow somente com critério pré-declarado; execução real/risk controls vêm depois do gate de evidência.

### SELL causal quote capture v1 (implementado/testado)

- `ForwardTradeEvent` e `schedule_trade_quotes` agora suportam BUY e SELL; `ForwardBuyEvent` permanece alias compatível.
- Observações forward aceitam `run_key` nullable e índice `(run_key,id)`; linhas históricas não são backfilled.
- SELL candidates usam rota real TOKEN→USDC e só podem usar `output_amount_raw` de uma BUY quote anterior como quantidade hipotética; não inferem inventário da wallet.
- Quotes/attempts permanecem event-scoped e idempotentes; replay usa mapa por `observation_key` quando fornecido.
- Run concluída classifica BUY sem SELL como `RIGHT_CENSORED`; run ativa permanece `OPEN`.
- Ainda não há evidência econômica SELL real; a captura prospectiva precisa ser validada em nova run após revisão.

## Regra para handoffs

Todo handoff deve informar:

- branch/commit atual;
- status real: implementado/testado/validado/em teste/hipótese/planejado;
- dados e coorte exatos;
- critérios congelados;
- riscos de leakage/missingness/censoring/dependência;
- próximo teste e critério de sucesso;
- nunca chamar política/estratégia de vencedora sem evidência suficiente.

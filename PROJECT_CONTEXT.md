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
- Jupiter Swap V2 `GET /order`: integração read-only implementada e smoke real concluído fora da rede escolar.
- Rede escolar apresentou TLS/certificado raiz não confiável para Jupiter; não usar para coletas longas.

## Regra central de validação

```text
IMPLEMENTADO
-> TESTADO
-> VALIDADO OPERACIONALMENTE
-> EVIDÊNCIA ECONÔMICA
-> SHADOW
-> LIVE CANARY
```

Código funcionando não prova edge. Backtest positivo não libera live. Nenhuma política é chamada de vencedora sem cobertura, missingness, custos, outliers, causalidade e validação forward adequados.

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

- `src/wallet_strategy_lab.py`: fingerprints de holding/exit/reentry/frequência/sizing/DEX.
- `src/wallet_strategy_compare.py`: comparação multi-wallet.
- `src/wallet_strategy_readiness.py`: evidence readiness e fila de pesquisa.
- `src/wallet_forward_observations.py` / `src/wallet_forward_collector.py`: ações forward com `chain_time` e `observed_at`.
- `wallet_watch_forward.py`: coletor RPC.
- Wallet Intelligence não altera a Wave atual.

### Causal Quote / Jupiter / Replay

- `src/jupiter_swap_v2.py`: cliente read-only para `/swap/v2/order`; não implementa `/execute`.
- `src/causal_quotes.py` + `src/causal_quote_store.py`: quotes causais BUY/SELL e metadados de rota.
- `src/wallet_quote_watch.py`: agenda quotes +0/+15/+30/+60/+120s após BUY forward e persiste sucesso **e falha**.
- `src/wallet_causal_replay.py`: replay sem lookahead, usando apenas quotes disponíveis depois de detecção + delay.
- `wallet_forward_experiment.py`: orquestra Wallet Watch + Quote Watch.
- `wallet_forward_checkpoint.py`: checkpoint run-scoped, BUY-only para entry feasibility e quotes ligados ao evento que os originou.
- Quote-only é proxy causal de preço/rota; transação montada também não prova landing/fill.

### Rejection Intelligence

- `src/rejection_intelligence.py`: sidecar observacional para rejeições da Wave.
- `rejection_lab.py`: seleção/auditoria/settlement explícito.
- Toda nova discovery bem-sucedida salva snapshots causais de rejeições sem alterar pass/fail.
- Follow-up padrão: até 12 rejeições data-valid por run; prioriza single-barrier near misses; horizontes 5m/15m/60m.
- Cooldown de 6h por mint reduz repetição artificial da mesma rejeição.
- Missingness permanece visível; erros temporários ficam pending e permanentes failed.
- Relatório separa outcomes totais e outcomes de barreira única.
- `+20%` e `-25%` são cortes descritivos, não TP/SL/gates.

### Market Integrity v1

- `src/market_integrity.py`: features observacionais de integridade a partir de snapshots causais agregados.
- `market_integrity_lab.py`: inspeção local de sinais aceitos e rejeições; não precisa de rede.
- `opportunity_context.py` agora pode anexar o snapshot causal de Market Integrity disponível até `as_of`.
- Features: buy pressure, imbalance, shape/aceleração de volume, transações por holder e campos de concentração/risco.
- `existing_gate_flags` apenas reapresenta thresholds que já pertencem à Wave; nenhum novo filtro foi criado.
- Não existe manipulation score nem `wash_trading_detected`.
- Limites explícitos: snapshot agregado não mostra self-trading, grafo de contrapartes, sequência order-level nem relações de funding.
- Próxima geração anti-manipulação exige dados de microestrutura/participantes antes de qualquer gate novo.

### Wallet Confirmation + Placebo v1

- `src/wallet_confirmation_placebo.py`: núcleo causal para eventos de confirmação e target x placebo.
- Regra primária do primeiro estudo: janela 300s, >=2 BUY wallets únicas; parâmetro de pesquisa, não filtro Wave.
- `src/wallet_placebo_matching.py` + `wallet_placebo_match.py`: matching pré-período sem PnL/outcomes e sem Match Score ponderado; expõe bucket similarity, atividade, token breadth, holding, DEX, coverage e warnings.
- `src/wallet_confirmation_study.py`: registry imutável para pré-registrar cutoff, start/end, Wave strategy version, target, placebos, policy, horizons e matching version antes do período de outcome.
- `src/wallet_confirmation_wave_study.py`: materializa confirmações para oportunidades Wave elegíveis usando somente wallet observations com `observed_at <= detected_at`; eventos já congelados não são reescritos por backfill posterior.
- `wallet_confirmation_study.py`: CLI de register/show/activate/materialize/evaluate/close para estudos prospectivos.
- Target/placebos precisam ser wallet-disjoint e, por padrão, do mesmo tamanho.
- Target/placebos devem ser escolhidos com dados pré-período e avaliados no mesmo universo/relógio de oportunidades.
- Comparação mantém pending/failed/missing no denominador e reporta target menos mediana dos placebos.
- Labels são apenas `NO_COMPARABLE_OUTCOMES`, `DESCRIPTIVE_LOW_COVERAGE` e `DESCRIPTIVE_PLACEBO_COMPARISON`; não existe `edge_proven`.
- As três wallets atuais do Forward Watch são uma coorte de observabilidade/arquéti​pos, não uma cesta econômica já validada.
- Universo local atual ainda é insuficiente para congelar um placebo study economicamente sério; infraestrutura pronta não significa evidência pronta.

### Social / Opportunity Intelligence

- Fundação de Social Intelligence e persistência de eventos existe.
- Opportunity Intelligence combina Wave/Wallet/Social/Market Integrity causalmente sem score final de trading.
- Coletor X real ainda é **PLANEJADO**.
- Social será avaliado por valor incremental; nunca `tweet -> buy`.

### Shadow / live readiness

- `src/shadow_execution_store.py`: persistência/auditoria de runs shadow, sem private key/signing/submission.
- `docs/live-readiness-gates-v1.md`: gates de processo até live canary.
- Execução real `quote -> route -> tx -> assinatura -> envio -> confirmação -> reconciliação` ainda não está fechada/liberada.

## Wave v3 — checkpoint 2026-08-31

59 sinais registrados = 19 históricos + 40 forward.

| Horizonte | Cobertura | WR | Média | Mediana | PF | Diagnóstico |
|---|---:|---:|---:|---:|---:|---|
| 5m | 57/59 = 96,6% | 33,3% | -0,44% | -1,60% | 0,84 | sem edge observado a 1% slippage/lado |
| 15m | 53/59 = 89,8% | 45,3% | +2,08% | -1,15% | 1,49 | média sem maior winner = -0,16%; outlier/missingness |
| 60m | 46/59 = 78,0% | 45,7% | +5,28% | -0,14% | 1,54 | 22% failures dominam a inferência |

Conclusão: `wave_v3_volume_integrity` permanece **EM TESTE**. Hipótese atual: pode ser mais útil como sensor de oportunidade/contexto do que como compra automática, mas isso ainda não altera a estratégia.

## Exit Engine — checkpoint 2026-08-31

25 sinais possuíam as cinco políticas fechadas.

- fixed15: média -1,94%, mediana -1,68%, PF 0,67.
- fixed60: média -4,45%, mediana -1,26%, PF 0,65.
- SL10: média -18,88%, mediana -4,23%, PF 0,10.
- TP20: média +4,17%, mediana -1,35%, PF 2,29, média sem melhor +3,49%.
- trailing10: média -17,80%, mediana -4,68%, PF 0,10.

`take_profit_20_v1` = **PROMISSOR / EM TESTE**, não vencedor. Cobertura desigual e amostra pequena impedem promoção. SL/trailing observados em candle não equivalem a stop garantido de -10%.

## Wallet Strategy Intelligence — evidência atual

### 7mPti

`7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`

- 94 swaps / 36 tokens / 306,3d.
- fingerprint `one_day|mixed_exit|occasional_reentry|moderate`.
- first exit mediano 18,5h; roundtrip 72,2%; multi-sell 42,3%; reentry 19,2%.
- 21 ciclos complete-like; **DESCRIPTIVE_READY**.
- H1 forward congelada: com >=10 novos roundtrips, first exit >6h, multi-sell >=25%, reentry <40%.

### Gf9X

`Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`

- 71 swaps / 36 tokens / 21,2d.
- fingerprint `ultra_short|single_exit_dominant|rare_reentry|moderate`.
- first exit 5,3min; roundtrip 36,1%; sequência incompleta; **EVIDENCE_GAPS**.
- H2: após amostra forward adequada, first exit <15m, multi-sell <=25%, reentry <15%.

### 3tc4

`3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`

- 93 swaps / 5 tokens / 0,2d.
- fingerprint `ultra_short|staged_exit_dominant|frequent_reentry|high_frequency`.
- first exit 1,2min; amostra de tokens/janela estreita; **EVIDENCE_GAPS**.
- H3 só é avaliada após >=10 tokens e >=10 complete-like.

Nenhum arquétipo multi-wallet está confirmado. Fingerprint não prova edge nem copyability.

## Wallet Forward + Jupiter

Coorte inicial: 7mPti, Gf9X, 3tc4.

Smoke real Jupiter:

- API key aceita;
- SOL -> USDC retornou rota;
- resposta parseada;
- sem `taker`, nenhuma transação montada;
- nenhuma ordem enviada.

Smoke integrado ~3min:

- run `wallet-forward-1788212954-67ee16b5`;
- 3 wallets, polling 30s, 6 ciclos;
- zero falhas de sync/bootstrap;
- zero ações forward porque as wallets não operaram;
- run `COMPLETED`; checkpoint retornou `SEM AMOSTRA` corretamente.

Status:

- orquestração/manifest/bootstrap/RPC/checkpoint: **VALIDADO OPERACIONALMENTE em smoke curto**;
- evento real `Wallet BUY -> detector -> Jupiter -> persistência -> causal replay`: **AGUARDANDO AMOSTRA**;
- coleta de 6h em internet estável: liberada tecnicamente e pendente.

Comando preferido:

```powershell
python wallet_forward_experiment.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 6 `
  --interval-seconds 30 `
  --with-jupiter-quotes
```

Depois:

```powershell
python wallet_forward_checkpoint.py
python evaluate_wallet_forward.py
python evaluate_wallet_quotes.py
```

## Pesquisa externa incorporada como priors

Documentos principais:

- `docs/memecoin-market-research-priors-2026-08-31.md`;
- `docs/external-evidence-reuse-map-v1.md`;
- `docs/rejection-intelligence-v1.md`;
- `docs/market-integrity-v1.md`;
- `docs/wallet-confirmation-placebo-v1.md`;
- `docs/wallet-placebo-matching-v1.md`.

Priors atuais:

- wallets lucrativas podem usar arquétipos muito diferentes;
- PnL alto não significa copyability;
- volume público simples pode não possuir edge isolado;
- memecoins apresentam heavy tails e dependência de poucos winners;
- latência/liquidez/rota fazem parte da estratégia;
- volume aparente pode conter manipulação;
- smart-wallet confirmation precisa de placebo/controle;
- estudar rejeitados ajuda a medir false negatives;
- evidência de regimes/mercados diferentes não deve ser misturada automaticamente.

Nenhum threshold externo é copiado diretamente para produção.

## Live readiness

Live permanece **BLOQUEADO**.

```text
causal data
-> hipótese congelada
-> replay com custos
-> robustness / missingness / outliers
-> shadow forward
-> execution engine + risk controls
-> live canary pequeno e separado
-> comparar live x shadow
-> escalar somente depois
```

Controles mínimos: limite por trade, exposição total, concorrência, perda diária, kill switch, idempotência, stale-quote protection e reconciliação on-chain.

Não é necessário terminar Wave + Wallet + Social para o primeiro canary; basta uma única estratégia atravessar todo o funil sem retuning pós-hoc.

## Limitações conhecidas

- Tracker credits bloqueiam nova discovery Wave/leaderboard.
- GeckoTerminal possui missingness, distant candles e rate limit.
- RPC polling não é streaming; ultra-fast wallets podem não ser copiáveis.
- Jupiter quote-only não é fill.
- candles 1m não resolvem ordem intraminuto de TP/SL/trailing.
- fingerprints podem refletir inventário preexistente/cobertura parcial.
- realized PnL pode esconder perdas não realizadas.
- market snapshots agregados não provam wash trading.
- Rejection Intelligence é prospectivo; não existe backfill causal honesto de rejeições antigas.
- Wallet Confirmation placebo ainda não possui target/placebos prospectivos congelados nem amostra econômica.
- O registry/runner de placebo está implementado para prevenir retuning; ele não resolve a falta atual de universo de wallets comparáveis.

## Próximas prioridades

1. Rodar/auditar as 6h Wallet + Jupiter em internet estável.
2. Fazer causal replay com latência/custos nos BUYs realmente observados.
3. Usar `market_integrity_lab.py` para caracterizar accepted/rejected snapshots existentes sem criar novos gates.
4. Quando Tracker voltar, continuar Wave v3 congelada + Rejection Intelligence prospectivo.
5. Ampliar Wallet Strategy Intelligence e formar target/placebos usando somente pré-período.
6. Quando houver universo suficiente, pré-registrar o primeiro `wave_opportunity_v1` no registry e só então iniciar outcomes.
7. Avançar anti-manipulação para microestrutura/grafo apenas quando houver dados que suportem isso.
8. Promover a primeira candidata para shadow somente com critério pré-declarado.
9. Construir execução real/risk controls depois de uma candidata passar o gate de evidência.

## Regra para handoffs

Todo handoff deve informar:

- branch/commit atual;
- status real: implementado/testado/validado/em teste/hipótese/planejado;
- dados e coorte exatos;
- critérios congelados;
- riscos de leakage/missingness;
- próximo teste e critério de sucesso;
- nunca chamar política/estratégia de vencedora sem evidência suficiente.

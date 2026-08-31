# Crypto Copy Trader — Project Context

Este arquivo registra o estado técnico consolidado do projeto. Ideias discutidas fora do código devem ser tratadas como hipóteses até serem confirmadas no repositório e por testes reproduzíveis.

## Estado operacional

- Branch de trabalho: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY** em relação ao mercado. O projeto não possui fluxo habilitado que assine ou envie transações reais.
- Persistência: SQLite, `DATABASE_PATH` (padrão `data/copytrader.db`).
- Estratégia Wave ativa: `wave_v3_volume_integrity`, com entrada **CONGELADA** enquanto a evidência forward é formada.
- Solana Tracker Data API: atualmente bloqueada por `403 Insufficient credits`; não gastar novas chamadas até reset/restauração de créditos.
- GeckoTerminal: usado para preços/candles e settlement histórico com pacing/adaptação de rate limit.
- Solana RPC público: usado no Wallet Forward Watch.
- Jupiter Swap V2 `GET /order`: integração read-only validada em smoke real fora da rede escolar.
- Rede escolar apresentou TLS/certificado raiz não confiável para Jupiter; não usar para coletas longas.

## Princípio de validação

O projeto separa explicitamente:

```text
implementado -> testado -> validado operacionalmente -> evidência econômica -> shadow -> live canary
```

Código funcionando não prova edge. Backtest positivo não libera live. Qualquer estratégia candidata precisa atravessar dados causalmente válidos, custos/slippage, missingness/outliers, forward/shadow e controles de execução antes de capital real.

## Arquitetura principal

### Wave / paper

- `radar.py`: discovery de tokens, Wave Radar e persistência paper.
- `src/wave_radar.py`: política, integridade, Wave Score, barreiras e cautions.
- `src/wave_paper.py`: sinais versionados, cooldown e checkpoints 5m/15m/60m.
- `src/wave_funnel.py`: cobertura e attrition por discovery.
- `evaluate.py` + `src/wave_metrics.py`: cobertura, retorno, PF, drawdown, Wilson, missingness, outliers e slippage.
- `backtest_concurrent.py` / `simulate_bankroll.py`: capital concorrente e stress.

### Exit Engine

- `src/exit_engine.py`: políticas forward pareadas e trajetória observada.
- `src/exit_metrics.py` + `evaluate_exits.py`: avaliação das políticas.
- Políticas v1 congeladas: fixed 15m, fixed 60m, SL -10%, TP +20%, trailing 10%.
- Gatilhos dinâmicos usam apenas candles realmente observados; não há backfill retrospectivo do caminho.

### Wallet Intelligence / Strategy Lab

- `src/wallet_strategy_lab.py`: fingerprint descritivo de holding/exit/reentry/frequência/sizing/DEX.
- `src/wallet_strategy_compare.py`: comparação entre fingerprints com evidence readiness.
- `src/wallet_strategy_readiness.py`: fila de evidência e bloqueadores.
- `src/wallet_forward_observations.py` / `src/wallet_forward_collector.py`: observações forward com `chain_time` e `observed_at` reais.
- `wallet_watch_forward.py`: observador RPC.
- Wallet Intelligence não controla a Wave atual.

### Causal Quote / Jupiter / Replay

- `src/jupiter_swap_v2.py`: cliente read-only para Jupiter Swap V2 `/order`; não implementa `/execute`.
- `src/causal_quotes.py` + `src/causal_quote_store.py`: quote causal com lado BUY/SELL e metadados de rota.
- `src/wallet_quote_watch.py`: após um BUY forward, agenda quotes em +0/+15/+30/+60/+120s e persiste sucesso **e falha**.
- `src/wallet_causal_replay.py`: reprocessa decisões apenas com informação disponível após detecção + delay.
- `wallet_forward_experiment.py`: orquestra Wallet Watch + Quote Watch sob um único run manifest.
- `wallet_forward_checkpoint.py`: relatório run-scoped; replay de entrada é BUY-only e cada quote é ligado ao evento exato que o originou.
- Quote-only é proxy causal de preço/rota, não fill. Transação candidata montada também não prova landing/fill.

### Shadow / live readiness

- `src/shadow_execution_store.py`: auditoria de runs e decisões shadow, sem private key, assinatura ou submission.
- `docs/live-readiness-gates-v1.md`: gates de processo antes de live.
- Execução real `quote -> route -> tx -> assinatura -> envio -> confirmação -> reconciliação` ainda não está liberada/fechada.

### Rejection Intelligence

- `src/rejection_intelligence.py`: sidecar observacional para tokens rejeitados pela Wave.
- `rejection_lab.py`: auditoria/settlement explícito.
- Toda nova discovery bem-sucedida registra snapshots de rejeições sem alterar pass/fail.
- Amostra de follow-up padrão: até 12 rejeições data-valid por run, priorizando single-barrier near misses; horizontes 5m/15m/60m.
- Erros temporários de preço permanecem pending; permanentes ficam failed; missingness é visível.
- Relatório inclui distribuição total e outcomes isolados de rejeições com uma única barreira.
- `+20%` e `-25%` são cortes descritivos, não novos gates.
- Rejeições antigas sem snapshot causal completo não são reconstruídas com estado futuro.

Tabelas adicionais:

- `wallet_forward_observations`;
- `wallet_forward_runs`;
- `causal_quote_observations`;
- `causal_quote_attempts`;
- `shadow_runs` / `shadow_decisions` (schema da camada shadow);
- `wave_rejection_decisions`;
- `wave_rejection_followups`.

## Estado da Wave v3 — checkpoint 2026-08-31

Total registrado: 59 sinais = 19 históricos + 40 forward.

### 5 minutos

- cobertura 57/59 = 96,6%;
- WR 33,3%;
- média/mediana -0,44% / -1,60%;
- PF 0,84;
- média sem maior vencedor -1,05%;
- a 1% de slippage por lado, o edge observado não é positivo.

### 15 minutos

- cobertura 53/59 = 89,8%;
- WR 45,3%;
- média/mediana +2,08% / -1,15%;
- PF 1,49;
- melhor +118,40%, pior -97,93%;
- média sem maior vencedor -0,16%;
- missingness e dependência de outlier impedem promoção.

### 60 minutos

- cobertura 46/59 = 78,0%;
- WR 45,7%;
- média/mediana +5,28% / -0,14%;
- PF 1,54;
- média sem maior vencedor +2,88%;
- 22% de falhas de preço dominam a incerteza.

Conclusão: `wave_v3_volume_integrity` permanece **EM TESTE**. Pode ser mais útil como detector de oportunidade/contexto do que como regra final de compra, mas isso é hipótese e não alteração da estratégia.

## Exit Engine — checkpoint 2026-08-31

25 sinais possuíam todas as políticas fechadas no checkpoint.

- fixed15: média -1,94%, mediana -1,68%, PF 0,67;
- fixed60: média -4,45%, mediana -1,26%, PF 0,65;
- SL10: média -18,88%, mediana -4,23%, PF 0,10;
- TP20: média +4,17%, mediana -1,35%, PF 2,29, média sem melhor +3,49%;
- trailing10: média -17,80%, mediana -4,68%, PF 0,10.

`take_profit_20_v1` é **PROMISSOR / EM TESTE**, não vencedor. Cobertura desigual e amostra pequena impedem seleção. SL/trailing sob observação por candle não representam stop garantido de -10%.

## Wallet Strategy Intelligence — evidência atual

### `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`

- 94 swaps / 36 tokens / 306,3 dias;
- fingerprint: `one_day|mixed_exit|occasional_reentry|moderate`;
- intensidade em dia ativo: mediana 1 swap/dia;
- first exit mediano 18,5h;
- roundtrip observado 72,2%;
- multi-sell 42,3%; reentry 19,2%;
- 21 ciclos complete-like; evidence-ready descritivamente.

Hipótese forward congelada H1, a verificar com >=10 novos roundtrips: first exit >6h, multi-sell >=25%, reentry <40%.

### `Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`

- 71 swaps / 36 tokens / 21,2 dias;
- fingerprint: `ultra_short|single_exit_dominant|rare_reentry|moderate`;
- first exit mediano 5,3min;
- roundtrip 36,1%; sequência incompleta;
- evidence-ready: NÃO.

H2, somente após amostra forward adequada: first exit <15m, multi-sell <=25%, reentry <15%.

### `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`

- 93 swaps / 5 tokens / 0,2 dia;
- fingerprint: `ultra_short|staged_exit_dominant|frequent_reentry|high_frequency`;
- first exit mediano 1,2min;
- amostra de tokens/janela muito estreita;
- evidence-ready: NÃO.

H3 só pode ser avaliada após >=10 tokens e >=10 complete-like.

Nenhum arquétipo multi-wallet está confirmado e nenhuma dessas fingerprints prova edge.

## Wallet Forward + Jupiter

Coorte inicial:

- 7mPti;
- Gf9X;
- 3tc4.

Jupiter smoke real fora da rede escolar:

- API key aceita;
- SOL -> USDC retornou rota `metis`;
- resposta parseada;
- sem `taker`, nenhuma transação foi montada;
- nenhuma ordem foi enviada.

Smoke integrado de ~3 minutos:

- run `wallet-forward-1788212954-67ee16b5`;
- 3 wallets;
- polling 30s;
- 6 ciclos;
- zero falhas de sync/bootstrap;
- zero ações forward porque as wallets não operaram na janela;
- run finalizada `COMPLETED`;
- checkpoint corretamente retornou `SEM AMOSTRA`.

Classificação:

- orquestração/manifest/bootstrap/RPC/checkpoint: **VALIDADO OPERACIONALMENTE em smoke curto**;
- evento real `Wallet BUY -> detector -> Jupiter -> persistência -> causal replay`: **AGUARDANDO AMOSTRA**;
- coleta de 6h em internet estável: liberada tecnicamente e ainda pendente de resultado.

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

## Pesquisa externa de mercado

Documentos:

- `docs/memecoin-market-research-priors-2026-08-31.md`;
- `docs/external-evidence-reuse-map-v1.md`;
- `docs/rejection-intelligence-v1.md`.

Princípios incorporados como priors, não como estratégia:

- traders lucrativos podem pertencer a arquétipos muito diferentes;
- wallet lucrativa pode ser incopiável por vantagem de timing/creator/sniper;
- volume público simples pode não conter edge suficiente isoladamente;
- memecoins têm heavy tails e dependência extrema de poucos winners;
- liquidez/rota/latência fazem parte da estratégia;
- volume aparente pode conter wash trading/manipulação;
- presença simultânea de smart wallets exige placebo/controle antes de inferência causal;
- estudar rejeitados reduz busca cega e mede false negatives;
- evidência pre-graduation não deve ser misturada automaticamente com mercado pós-graduação.

Fontes externas são usadas para gerar hipóteses e desenhos experimentais. Nenhum threshold externo é copiado diretamente para produção.

## Social / Opportunity Intelligence

- Fundação de Social Intelligence e persistência de eventos existe.
- Opportunity Intelligence combina contexto Wave/Wallet/Social causalmente sem score final de trading.
- Coletor X real ainda é PLANEJADO.
- Social deve ser testado por valor incremental, nunca como `tweet -> buy`.

## Live readiness

Live permanece **BLOQUEADO**.

Sequência congelada de alto nível:

```text
causal data
-> hipótese/estratégia congelada
-> replay com custos
-> robustness/missingness/outliers
-> shadow forward
-> execution engine real + risk controls
-> live canary pequeno em wallet separada
-> comparação live x shadow
-> escala somente depois
```

Controles mínimos antes de live incluem limite por trade, exposição total, concorrência, perda diária, kill switch, idempotência, stale-quote protection e reconciliação on-chain.

Não é necessário terminar Wave + Wallet + Social para liberar o primeiro canary; basta **uma** estratégia atravessar todo o funil sem mudança pós-hoc de critérios.

## Limitações e riscos conhecidos

- Solana Tracker credits atualmente bloqueiam nova discovery Wave/leaderboard.
- GeckoTerminal continua sujeito a cobertura incompleta, distant candles, rate limit e missingness.
- RPC polling não é streaming; wallets ultra-fast podem ser pouco copiáveis.
- Quote Jupiter é melhor proxy que candle, mas quote-only não é fill.
- 1m candles não resolvem ordem intraminuto de TP/SL/trailing.
- Wallet fingerprints podem refletir inventário preexistente ou cobertura incompleta.
- Realized PnL de wallets pode esconder perdas não realizadas.
- Memecoin market data é vulnerável a manipulação e seleção de sobreviventes.
- Rejection Intelligence começa prospectivamente; não há backfill causal honesto dos snapshots antigos.

## Próximas prioridades

1. Rodar e auditar a coleta Wallet + Jupiter de 6h em internet estável.
2. Fazer causal replay com latência/custos nos BUYs realmente observados.
3. Continuar Wallet Strategy Intelligence e decidir se alguma hipótese merece shadow.
4. Quando o Tracker voltar, continuar Wave v3 congelada e formar Rejection Intelligence prospectivo em paralelo.
5. Auditar false negatives por barreira sem retunar a própria amostra.
6. Pesquisar/implementar controles anti-manipulação apenas como features observacionais antes de qualquer gate novo.
7. Promover a primeira estratégia para shadow somente com critério pré-declarado.
8. Construir execução real/risk controls apenas depois de uma candidata passar o gate de evidência.

## Regra para handoffs

Ao transferir trabalho entre Copiloto/Work, informar:

- branch/commit atual;
- status real: implementado/testado/validado/em teste/hipótese/planejado;
- dados e coorte exatos;
- critérios congelados;
- riscos de leakage/missingness;
- próximo teste e critério de sucesso;
- nunca chamar uma política/estratégia de vencedora sem evidência suficiente.

# Crypto Copy Trader — Project Context

Este arquivo registra o estado técnico consolidado do projeto. Ideias discutidas fora do código
devem ser tratadas como hipóteses até serem confirmadas no repositório e por testes reproduzíveis.

## Estado atual

- Modo operacional: **PAPER/READ ONLY**. Não existem ordens, assinaturas ou movimentações reais.
- Branch de trabalho: `feat/wave-integrity-audit`.
- A árvore local é igual à árvore de `origin/feat/wave-integrity-audit`, embora o histórico local
  esteja 6 commits à frente e 6 atrás por commits equivalentes com hashes diferentes.
- Persistência local em SQLite, configurada por `DATABASE_PATH` (padrão `data/copytrader.db`).
- Fonte do Wave Radar: Solana Tracker Token Search.
- Fonte dos checkpoints históricos: GeckoTerminal, com rastreio do pool de entrada e saída.
- A estratégia ativa para novos sinais é `wave_v3_volume_integrity`.
- O monitor híbrido permite discovery e atualização de checkpoints em frequências distintas.
- Última suíte completa conhecida: 139 testes aprovados. Deve ser executada novamente após qualquer
  alteração funcional.

## Arquitetura atual

Fluxo principal:

1. `discover.py`: discovery e ranking de wallets públicas.
2. `radar.py`: busca tokens, aplica política do Wave Radar, exibe ranking e registra sinais paper.
3. `src/wave_radar.py`: integridade, barreiras, componentes do Wave Score e elegibilidade.
4. `src/wave_paper.py`: versionamento, cooldown, persistência e checkpoints 5m/15m/60m.
5. `monitor.py`: agenda discovery e atualização de preços.
6. `evaluate.py` + `src/wave_metrics.py`: cobertura, estatísticas, custos, coortes, outliers e falhas.
7. `simulate_bankroll.py`: simulação sequencial de banca.
8. `backtest_concurrent.py` + `src/wave_bankroll.py`: capital limitado, posições concorrentes,
   reinvestimento, exposição e stress de custo.
9. `app.py`: interface Streamlit.

Tabelas relevantes:

- `wallets`, `transactions`, `paper_trades`;
- `token_pool_cache`, `price_cache`;
- `wave_signals`, `wave_signal_checks`.

## Estratégias existentes

### `wave_v1_baseline`

- **IMPLEMENTADO / HISTÓRICO**.
- Apenas 2 sinais; amostra inconclusiva.
- Preservada como benchmark, não recebe novos sinais.

### `wave_v2_momentum`

- **IMPLEMENTADO / HISTÓRICO**.
- 65 sinais registrados.
- Resultado 5m observado: n=64, win rate 82,8%, média +5,18%, mediana +5,11%, PF 6,61.
- Limitação crítica: 35/65 snapshots tinham janelas `5m/1h/24h` inconsistentes.
- Não recebe novos sinais; resultados servem apenas como evidência exploratória.

### `wave_v3_volume_integrity`

- **IMPLEMENTADO / EM TESTE**.
- Estratégia de momentum atual com exigência `volume_5m <= volume_1h <= volume_24h`.
- Mantém filtros de risco, liquidez, aceleração, concentração, authorities e desequilíbrio.
- Cooldown de 360 minutos por mint evita repetição artificial do mesmo token.
- Parâmetros de entrada devem permanecer congelados durante a formação da amostra.

## Funcionalidades implementadas

- Monitoramento de wallets Solana e parsing de swaps suportados.
- Ledger paper FIFO e métricas de wallets.
- Discovery, Candidate Score, Copyability Score e watchlist de wallets.
- Detecção de convergência de wallets em código, ainda não usada como estratégia ativa do Wave Radar.
- Wave Radar com barreiras explícitas e score reproduzível.
- Integridade obrigatória das janelas cumulativas de volume.
- Sinais paper versionados com snapshots de entrada.
- Checkpoints 5m, 15m e 60m com slippage configurado nos dois lados.
- Rastreio e auditoria do pool usado para precificação.
- Avaliação com cobertura, Wilson 95%, PF, drawdown, outliers, stress de resultados ausentes,
  stress de slippage e coortes pré-fixadas.
- Backtests sequencial e concorrente com reinvestimento e capital bloqueado.
- Stress adicional de custos no backtest concorrente.
- Monitor híbrido reiniciável; dados concluídos persistem mesmo após interrupção.

## Experimentos ativos

### Formação da amostra v3

- **EM TESTE**.
- Backup reproduzido: `copytrader-backup-8h.db`, SQLite `integrity_check: ok`.
- Estado reproduzido do backup: 12 sinais v3; 34 checkpoints concluídos; 0 pendentes; 2 falhos.
- Integridade: 12/12 snapshots legíveis; 0 janelas de volume inconsistentes.

Resultados v3 reproduzidos:

| Horizonte | Cobertura | Win rate | Média | Mediana | PF | Observação |
|---|---:|---:|---:|---:|---:|---|
| 5m | 12/12 | 33,3% | +0,86% | -1,30% | 1,28 | Média vira -2,10% sem o melhor trade |
| 15m | 12/12 | 50,0% | +11,98% | +2,30% | 7,67 | Maior vencedor responde por 71,6% do lucro bruto |
| 60m | 10/12 | 70,0% | +15,52% | +4,34% | 3,19 | 2 falhas; melhor +113,34%, pior -66,93% |

- Conclusão: amostra ainda inconclusiva (<30). 5m está fraco e dependente de outlier; 15m e 60m
  são hipóteses promissoras, ainda sem evidência suficiente para live.
- Experimento atual no computador do usuário: monitor de 4 horas, discovery a cada 15 minutos,
  atualização de preços a cada 5 minutos, até 50 tokens por busca. Os filtros v3 permanecem iguais.

Comando do experimento acelerado:

```powershell
python monitor.py --hours 4 --price-interval-minutes 5 --discovery-interval-minutes 15 --tokens 50 --top 10
```

## Decisões consolidadas

- Permanecer PAPER/READ ONLY até autorização explícita e validações adicionais.
- Não misturar resultados de estratégias diferentes como uma única amostra.
- Não alterar filtros preditivos com menos de 30 observações; 100 observações ainda não são garantia.
- Manter v1 e v2 como benchmarks históricos; v3 é a única entrada ativa.
- Aumentar cobertura do discovery sem afrouxar as barreiras de qualidade.
- Usar cooldown por mint para evitar duplicação de sinais correlacionados.
- Preservar sinais rejeitados e motivos para futura análise contrafactual.
- Construir saída dinâmica sem reescrever entradas ou checkpoints históricos.
- Wallet Intelligence e Social/Event Intelligence devem começar em shadow, coletando evidência sem
  controlar capital ou alterar a entrada v3.
- Confluências futuras devem começar como features de ranking; só viram filtros após validação.
- Não fazer merge na `main` até consolidar a branch avançada, resolver a divergência de histórico e
  executar a suíte completa.

## Limitações e problemas conhecidos

- Amostra v3 pequena e concentrada em poucos vencedores.
- Checkpoints fixos não reconstruem o caminho intraperíodo necessário para TP, SL e trailing reais.
- Atualização em 5 minutos pode perder gatilhos e gaps entre observações.
- GeckoTerminal pode falhar ou não oferecer candle suficientemente próximo, especialmente em 60m.
- Retornos paper não possuem quotes executáveis históricos completos, impacto de mercado observado,
  prioridade de transação ou todas as fees por sinal.
- Resultados de 60m têm risco de survivorship bias quando há falhas de preço.
- Aumentar frequência de discovery melhora cobertura, mas não cria observações independentes nem
  substitui diversidade de dias e regimes de mercado.
- A branch local e remota têm árvores iguais, mas históricos divergentes; evitar push forçado.

## Funcionalidades planejadas relevantes

### Exit Engine v1

- **PLANEJADO / PRÓXIMA IMPLEMENTAÇÃO**.
- Posições paper persistentes e seguras a reinício.
- Registro de máximo, mínimo, MFE, MAE e duração.
- Políticas paralelas: saída fixa, stop, take-profit, trailing e time stop.
- Motivo de saída, preço, slippage, fees disponíveis e versão da política.
- Comparação contra checkpoints fixos sem otimizar parâmetros nos mesmos resultados usados para medir.

### Execução e validação

- **PLANEJADO**: quotes executáveis, rota/pool, latência, fees, slippage e falhas de execução.
- **PLANEJADO**: shadow execution com decisões completas registradas, sem assinatura/transação.
- **PLANEJADO**: backtest concorrente exclusivo da v3 após amostra suficiente.
- **PLANEJADO**: micro-live com wallet exclusiva, limites rígidos e kill switch, somente após evidência.

### Estratégias e confirmações futuras

- **HIPÓTESE**: Wallet Intelligence como confirmação e futura estratégia independente.
- **HIPÓTESE**: Social/Event Intelligence como confirmação e futura estratégia independente.
- **HIPÓTESE**: cruzar momentum, wallets e eventos; inicialmente como ranking, não filtro obrigatório.

## Próxima prioridade

1. Deixar o experimento v3 atual terminar e preservar o banco.
2. Implementar `exit-engine-v1` incrementalmente em branch própria, sem alterar a entrada v3.
3. Continuar a coleta v3 até pelo menos 30 sinais e depois até 100, em horários/regimes diversos.
4. Avaliar v3 por cobertura, mediana, PF, drawdown, custos e dependência de outliers.
5. Rodar backtest concorrente v3 e só então decidir a política de saída candidata a shadow.

## Handoff para outros chats

- **Estado atual:** v3 ativa em paper, 12 sinais reproduzidos no backup de 8h; novo teste acelerado de
  4 horas em execução.
- **O que está implementado:** radar, integridade de volume, paper checkpoints, avaliação estatística,
  backtests de banca e monitor híbrido.
- **O que está em teste:** estabilidade e expectativa da `wave_v3_volume_integrity`.
- **O que continua incerto:** edge líquido da v3, melhor horizonte e efeito real de uma saída dinâmica.
- **Próxima prioridade:** Exit Engine v1 enquanto a amostra v3 cresce.
- **Pergunta para o Copiloto:** quais políticas de saída pré-registradas oferecem maior informação com
  o menor número de parâmetros, evitando overfitting na amostra pequena?

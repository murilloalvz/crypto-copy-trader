# Crypto Copy Trader — Project Context

Este arquivo registra o estado técnico consolidado do projeto. Ideias discutidas fora do código
devem ser tratadas como hipóteses até serem confirmadas no repositório e por testes reproduzíveis.

## Estado atual

- Modo operacional: **PAPER/READ ONLY**. Não existem ordens, assinaturas ou movimentações reais.
- Branch de trabalho: `feat/exit-engine-v1`.
- Persistência local em SQLite, configurada por `DATABASE_PATH` (padrão `data/copytrader.db`).
- Fonte do Wave Radar: Solana Tracker Token Search.
- Fonte dos checkpoints históricos: GeckoTerminal, com rastreio do pool de entrada e saída.
- A estratégia ativa para novos sinais é `wave_v3_volume_integrity`.
- O monitor híbrido atualiza checkpoints fixos e posições do exit engine na mesma frequência.
- Última suíte completa conhecida nesta branch: 150 testes aprovados.

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
10. `src/exit_engine.py`: coorte forward, políticas pareadas e trajetória observada.
11. `src/exit_metrics.py` + `evaluate_exits.py`: avaliação multi-métrica das saídas.
12. `src/wave_funnel.py`: auditoria de cobertura e redução do universo por rodada.

Tabelas relevantes:

- `wallets`, `transactions`, `paper_trades`;
- `token_pool_cache`, `price_cache`;
- `wave_signals`, `wave_signal_checks`.
- `exit_experiments`, `exit_policies`, `exit_positions`, `exit_price_observations`;
- `wave_discovery_runs`, `wave_discovery_candidates`.

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
- Exit Engine v1 forward-only com fronteira por timestamp e ID do último sinal existente.
- Cinco políticas pareadas por nova entrada v3: 15m, 60m, SL -10%, TP +20% e trailing 10%.
- Máximo, mínimo, MFE, MAE, trajetória observada, motivo e execução de saída persistidos.
- Funil por discovery com limite solicitado, retorno da fonte, validade, barreiras,
  candidatos, duplicados/cooldown, rejeições de persistência e sinais criados.

## Experimentos ativos

### Exit Engine v1

- **IMPLEMENTADO / EM TESTE FORWARD**.
- Engine `exit_engine_v1`; políticas pré-registradas:
  - `fixed_15m_v1`: 900 segundos;
  - `fixed_60m_v1`: 3.600 segundos;
  - `stop_loss_10_v1`: -10%, fallback em 60m;
  - `take_profit_20_v1`: +20%, fallback em 60m;
  - `trailing_stop_10_v1`: 10% abaixo do maior preço observado, fallback em 60m.
- A fronteira real é criada na primeira execução desta versão no banco operacional. Ela registra
  `activated_at` e `start_after_signal_id`; os 19 sinais anteriores não entram na coorte.
- Cada novo sinal recebe todas as políticas; não há seleção por token nem política vencedora.
- Benchmarks fixos usam o candle de seu target exato. Políticas dinâmicas usam apenas o último candle
  de minuto concluído observado durante cada ciclo, sem backfill do caminho perdido.
- O intervalo esperado fica salvo. Padrão operacional pré-registrado para a primeira coorte:
  60s. Cada preço por sinal é compartilhado pelas cinco políticas.
- O cliente GeckoTerminal impõe 2,1s entre requisições. O monitor estima a carga dinâmica por
  ciclo e alerta a partir de 80% da capacidade teórica.
- No backup com 19 sinais v3, o pico reproduzido foi 7 sinais em uma janela de 60m: estimativa de
  14,7s por ciclo, 420 consultas dinâmicas/h e 24,5% da capacidade teórica. Rate limit público,
  benchmarks vencidos e resolução inicial de pool ainda precisam de validação operacional.

### Formação da amostra v3

- **EM TESTE**.
- Banco mais recente reproduzido: `copytrader(1).db`, SQLite `integrity_check: ok`.
- Estado reproduzido: 19 sinais v3; 54 checkpoints concluídos; 1 pendente; 2 falhos.
- Integridade: 19/19 snapshots legíveis; 0 janelas de volume inconsistentes.

Resultados v3 reproduzidos:

| Horizonte | Cobertura | Win rate | Média | Mediana | PF | Observação |
|---|---:|---:|---:|---:|---:|---|
| 5m | 19/19 | 42,1% | +1,69% | -0,02% | 1,79 | Média vira -0,07% sem o melhor trade |
| 15m | 19/19 | 63,2% | +9,31% | +4,13% | 8,64 | Média sem o melhor trade permanece +3,25% |
| 60m | 16/19 | 75,0% | +23,03% | +10,08% | 5,52 | 2 falhas e 1 pendente; melhor +113,34%, pior -66,93% |

- Conclusão: amostra ainda inconclusiva (<30). 5m continua frágil e dependente de outlier; 15m e
  60m ganharam suporte, mas ainda não constituem evidência suficiente para live.
- O experimento acelerado de 4 horas acrescentou 7 sinais v3: discovery a cada 15 minutos,
  atualização de preços a cada 5 minutos, até 50 tokens por busca. Os filtros v3 permaneceram iguais.

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
- Atualização em 1 minuto ainda pode perder gatilhos e gaps intraminuto; os dados originais são
  preservados para futura subamostragem comparativa em 5m.
- Em gap, SL/TP/trailing usam o primeiro preço observado e podem executar melhor ou pior que o
  limiar; nenhum preenchimento artificial no threshold é criado.
- Candles de um minuto não revelam a ordem intraminuto entre máximos, mínimos e cruzamentos.
- GeckoTerminal pode falhar ou não oferecer candle suficientemente próximo, especialmente em 60m.
- Retornos paper não possuem quotes executáveis históricos completos, impacto de mercado observado,
  prioridade de transação ou todas as fees por sinal.
- Resultados de 60m têm risco de survivorship bias quando há falhas de preço.
- Aumentar frequência de discovery melhora cobertura, mas não cria observações independentes nem
  substitui diversidade de dias e regimes de mercado.
- A branch local e remota têm árvores iguais, mas históricos divergentes; evitar push forçado.

## Funcionalidades planejadas relevantes

### Exit Engine v1

- **IMPLEMENTADO / EM TESTE**.
- Próximo passo é formar exclusivamente a coorte forward e avaliar cobertura pareada.
- Parâmetros e entrada v3 permanecem congelados; não houve grid search nem escolha de vencedora.

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

1. Ativar a nova branch no banco operacional e anotar a fronteira impressa pelo monitor.
2. Continuar a coleta v3 e a coorte forward sem alterar entradas ou parâmetros de saída.
3. Inspecionar o funil por várias rodadas antes de decidir qualquer ampliação do discovery.
4. Aos 30 sinais forward, avaliar cobertura pareada, mediana, PF, MFE/MAE, duração, drawdown e outliers.
5. Só depois escolher candidatas para shadow execution com quotes executáveis.

## Handoff para outros chats

- **Estado atual:** v3 ativa em paper, 19 sinais reproduzidos; o teste acelerado de 4 horas acrescentou
  7 sinais com integridade completa.
- **O que está implementado:** infraestrutura exit-engine-v1, cinco políticas pareadas, fronteira
  forward, persistência de trajetória, relatório de saídas e funil auditável.
- **O que está em teste:** estabilidade da v3 e efeito forward das políticas de saída.
- **O que continua incerto:** edge líquido da v3, robustez com n>=30, melhor horizonte e efeito real
  de uma saída dinâmica.
- **Próxima prioridade:** coletar a nova coorte e conferir cobertura/qualidade do funil.
- **Pergunta para o Copiloto:** qual regra de decisão prévia usar quando a coorte pareada atingir 30,
  sem reduzir a comparação a uma única métrica?

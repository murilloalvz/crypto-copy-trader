# Pré-registro — POS-RUNNER-V0 — RASCUNHO — 2026-10-15

Status: **RASCUNHO — NÃO CONGELADO.** Falta (1) o OK do operador no relatório do Passo 0 (calibração com os 5 exemplos do professor) e (2) o hash da config final. Só depois disso este arquivo vira `PRE-REGISTRADO`, é commitado e **só então** o backtest da Parte A pode baixar dado de resultado. Nenhum backtest foi rodado. Nenhum dado de resultado de universo sem viés foi lido.

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`. Modelo seguido: `docs/templates/batch-preregistration-template-v1.md` (aqui K = 1 hipótese com uma grade de 6 variantes).

Código: branch `signals-mvp`, pasta `signals_mvp/pos_runner/` (detector causal, simulador, custos, gráficos, Passo 0). Config: `signals_mvp/pos_runner/pos_runner_v0.yaml` — hash atual `<preencher no congelamento>`.

## 0. O que é e o que não é

- Hipótese **nova**. Não é resgate da "Post-Transition Pullback/Reacceleration V0" (`PT-V0`, CLOSED/BURNED): aquela olhava janelas de 10 s logo depois da transição para o PumpSwap; esta olha horas/dias depois de um runner de MC >= 300k, em 3 launchpads.
- Estratégia (anotações do operador): runner forte → pullback de ~80–90% → consolidação acima do nível da bonding curve com wicks no suporte → rompimento da caixa = entrada → saída no último topo.
- Os 5 exemplos do professor (BIKE TYSON, SOLCAT, ALLINU, ZILLIONS, FLAME) foram usados SÓ para calibrar (Passo 0). Ficam **fora de todas as métricas** (são vencedores escolhidos depois).

## 1. Coleta que julga a hipótese (Parte A — backtest histórico sem viés)

- **Universo**: toda graduação bem-sucedida, na Solana, dos launchpads abaixo, dentro de janelas de calendário sorteadas com seed fixa (`20261015`). Nunca uma lista de "tokens conhecidos".

  | Launchpad | Instrução de migração (conferida on-chain nos exemplos) | Pool de destino |
  |---|---|---|
  | pump.fun | `MigrateV2` (pump.fun) → `CreatePool` (PumpSwap) — BIKE TYSON, SOLCAT | PumpSwap (cotado em SOL) |
  | Raydium LaunchLab | `MigrateToCpswap` (LaunchLab) → `InitializeWithPermission` (Raydium CPMM), assinante `RAYpQbFNq9i3mu6cKpTKKRwwHFDeK5AuZz8xvxUrCgw` — ALLINU (cotado em DKNG), ZILLIONS (cotado em ZEC) | Raydium CPMM (ou AMM v4 via `MigrateToAmm`) |
  | Meteora DBC | `MigrationDammV2` (DBC) → `InitializePoolWithDynamicConfig` (DAMM v2) — FLAME (cotado em EMBER) | Meteora DAMM v2 (ou v1) |

- **Enumeração**: método de âncora sem Helius COPIADO do H2 (`benchmarks/sig_fast_v0/h2_enumeration_no_helius_v0.py`, branch `research/rust-signal-plane-live-shadow-v0`, commit `da37ce6`) para `signals_mvp/pos_runner/solana_rpc.py`: busca binária do slot no fim da janela, assinatura âncora, `getSignaturesForAddress` da conta de migração de cada launchpad paginando para trás até o início da janela, `getTransaction` confirma a instrução. RPC: `POS_RUNNER_RPC_URLS` (QuickNode do operador) ou o RPC público oficial (o `publicnode` apaga blocos com mais de ~2 dias e é recusado automaticamente).
- **Preço**: OHLCV do GeckoTerminal do **pool de graduação**, pedido **em token de cotação** (`currency=token`) e convertido para USD com uma série de referência da cotação (SOL/USDC Orca; ZEC/USDC; etc.). Motivo: no exemplo ZILLIONS o USD do próprio GeckoTerminal ficou travado num valor errado por 24 h. O USD do GeckoTerminal fica só como conferência. Candle sem cotação/USD no instante fica de fora (nunca inventado). Buracos de download são conferidos contra a série de 1h (`missing_windows`) e rebaixados.
- **Estágios**: (1) 1h de cada pool, de graduação até graduação + `<horizonte, proposta: 14 dias>`, para achar quem chegou a MC >= 300k; (2) só esses recebem 5m e 4h do mesmo período. Limite da API pública: ~30 req/min e 180 dias de histórico. Checkpoint e retomada em disco.
- **Período**: janela grátis de 180 dias contada da data do congelamento `D`. Discovery = primeiros ~4 meses; **embargo de 1 semana**; holdout SELADO = últimos ~2 meses, terminando pelo menos 10 dias antes de `D` (para os trades do holdout terem candles de saída). Cada token pertence ao período da sua **graduação**. Datas exatas `<preencher em D>`.
  - Atenção: o começo da janela grátis anda 1 dia por dia. Depois do congelamento o download do discovery precisa começar logo.
- **Selagem**: a lista de pools do holdout e o hash dela são commitados ANTES de qualquer cálculo do discovery. O código do discovery recusa carregar um pool do holdout.
- **Tamanho (parada por contagem, sem olhar retorno)**: janelas sorteadas são processadas na ordem do sorteio até que o MENOR número de setups primários entre os 3 timeframes chegue a 60 no discovery (ou acabem as janelas). Reportar quantos runners e quantos setups.
- **Código e travas** (`signals_mvp/pos_runner/parte_a/`, pronto e testado com universo sintético; NÃO rodado):
  `python -m signals_mvp.pos_runner.parte_a.cli plano --congelamento <D>` → `selar-holdout` → `discovery` → `escolher` → `holdout` → `relatorio`.
  O código recusa rodar se este arquivo não estiver `PRE-REGISTRADO` com o hash da config, se a selagem do holdout não estiver commitada ou com hash diferente, ou se a config/plano mudarem no meio da coleta (checkpoint SQLite guarda os hashes). O discovery recusa qualquer pool do holdout selado; o holdout nunca passa das janelas seladas e só abre se o discovery produziu candidato.
- **Datas de exemplo** (congelamento em 2026-10-17, horizonte de 14 dias): discovery = graduações de 2026-04-23 a 2026-07-27 (95 dias), embargo 2026-07-27 a 2026-08-03, holdout = 2026-08-03 a 2026-09-23 (51 dias). Fica menor que "4 + 2 meses" porque cada token precisa de 14 dias de observação mais até 9 dias para o trade sair dentro dos 180 dias da API. Janelas de 30 min.
- **Cobertura da enumeração (limitação declarada)**: pump.fun pela autoridade de migração do H2; LaunchLab pelo migrador `RAYpQbFN…` (53 de 60 transações amostradas são `MigrateToCpswap`; `MigrateToAmm` não apareceu); DBC pela config de DAMM v2 `A8gMrEPJ…` (amostra de 2026-10-15: 78 migrações `MigrationDammV2` lidas a partir do keeper `GZjYfGy…` e da própria config, todas com `A8gMrEPJ…` na conta 25; a amostra é parcialmente circular e outra config não apareceu) — migração da DBC para DAMM v1 não coberta. O relatório reporta as contas usadas.
- **Linha de base**: K = 5 runners por setup, sorteio com seed derivada do setup.
- **Holdout**: processa as janelas seladas na ordem até 30 setups primários no timeframe escolhido; veredito com no mínimo 20 trades fechados.
- **Gates de sistema antes de qualquer número econômico**:
  1. a enumeração acha a graduação de cada um dos 5 exemplos rodando numa janela que a contém (os 3 launchpads);
  2. >= 95% das graduações enumeradas têm candles de 1h baixados, ou motivo explícito de falta;
  3. holdout selado (hash commitado) antes do discovery;
  4. testes de causalidade do detector passando (prefixo/futuro não muda decisão passada);
  5. nenhuma série de estágio 2 com buraco contra o 1h depois do reparo (senão o pool sai, com motivo).
  Falha de sistema = SEM VEREDITO; não gasta tentativa.

## 2. Hipótese (K = 1)

### POS-RUNNER-V0 — rompimento da consolidação pós-runner

- Família: `padrão de preço pós-runner (horas/dias)`.
- Tipo: entrada (alpha).
- Origem: nova.
- Regra congelada: detector `signals_mvp/pos_runner/detector.py` + parâmetros `pos_runner_v0.yaml` (hash `<preencher>`), calibrados SÓ no Passo 0 com os 5 exemplos. Decisão em t usa só candles fechados até t (teste de prefixo). Entrada no open do candle seguinte ao sinal.
- Grade (única variação permitida): timeframe {5m, 1h, 4h} × saída {A, B} = **6 variantes**. Escolhe 1 no discovery pelo EV líquido; empate → 1h e saída A. Runner fixo em >= 300k (500k só diagnóstico).
- Primário: só o PRIMEIRO setup elegível por token e timeframe. Setups seguintes, fora da janela de idade ou "absurdos" = diagnóstico.
- Saídas: A = 100% no alvo (0,95 × pico), stop na mínima da última wick −3%, exaustão (power candle verde com +50%), stop de tempo 48 candles. B = 50% no alvo, resto com stop na entrada + trailing 25% da máxima, mesmas exaustão/tempo. Mesmo candle tocando stop e alvo = stop primeiro.
- Custos (`signals_mvp/pos_runner/costs.py`): fee do PumpSwap pela faixa de MC em SOL (tabela oficial); terminal 1%/perna; rede 0,0003 SOL/perna (0,2% de 0,15 SOL); slippage AMM para 0,15 SOL; ATA = 0. Fee de pool Raydium CPMM / Meteora DAMM v2: **não confirmada** — usa 1,0%/perna até a Parte A medir a fee real de cada pool on-chain.
- Linha de base pareada: para cada setup primário (token, tf, idade na entrada), K = 5 outros runners do mesmo período (sorteio com seed), cada um entrando na MESMA idade, no mesmo tf, com o MESMO colchete percentual (stop −x%, alvo +y% do setup), mesmo stop de tempo e mesmos custos. "Runner" = MC >= 300k já atingida antes daquela idade. Edge = EV do setup − EV médio da base.
- Métricas (discovery, por variante): nº de setups, taxa de acerto (alvo antes do stop), R múltiplo médio/mediano, EV líquido por trade (%), profit factor, pior sequência de perdas, tempo médio no trade, por nº de wicks (1, 2, 3+), por launchpad, por faixa de pico (300k–1M, 1–5M, >5M), e a linha de base.
- **Critério de candidato (discovery)**: na variante escolhida, EV líquido > 0, PF > 1, edge sobre a base > 0 e >= 30 trades.
- **Confirmação (holdout selado, variante congelada)**: EV líquido > 0 e PF > 1, com >= `<proposta: 20>` trades (abaixo disso = INCONCLUSIVE).
- Sensibilidade: custo 2× (todas as parcelas) reportado sempre.
- Controles: linha de base pareada; resultados reportados com cobertura (todas as graduações enumeradas, não só as que deram trade).
- O que um PASS **não** prova: execução real (o candle é proxy, não cotação executável — Gate 0/2), fill e latência, slippage fora do modelo, fee real dos pools não-PumpSwap, comportamento futuro do mercado. Um PASS aqui = `PASS (aguarda replicação)`; a replicação prevista é o paper ao vivo da Parte B com a mesma regra congelada, e depois o Gate 2.

## 3. Multiplicidade e próximos passos

- 1 hipótese, 6 variantes (grade) julgadas no mesmo discovery; só 1 vai para o holdout.
- PASS no holdout → `PASS (aguarda replicação)` → replicação sozinha (paper ao vivo, regra congelada, pré-registro próprio).
- FAIL/KILL → fecha. Ideia derivada = hipótese nova.
- Pergunta ao operador: o POS-RUNNER ocupa o "caminho 2" reservado da regra de parada do programa (1 discovery + 1 confirmação)?

## 3.1 Parte B (bot ao vivo) rodando antes do congelamento

O handoff pede a Parte B em paralelo. Ela roda com a config em RASCUNHO (os alertas mostram `(rascunho)` e o hash) e
grava paper A/B + base pareada em `pos_runner.csv`. Regras: (a) os parâmetros finais saem SÓ do Passo 0 (5 exemplos);
mudar qualquer parâmetro depois de olhar resultado do paper ao vivo conta como ajuste em dado de resultado e é
proibido (§4); (b) linhas com `versao_config` diferente do hash congelado não entram em nenhuma avaliação; (c) o paper
ao vivo com a regra congelada só vira "replicação" com pré-registro próprio (§3).

## 4. Proibido depois de ver dado de resultado

Mudar qualquer parâmetro da config, a grade, o critério, o período, a linha de base ou o custo; incluir/remover tokens; olhar só um subgrupo; trocar a variante depois do holdout.

## 5. Pendências antes de congelar (todas do Passo 0)

- OK do operador nos gráficos dos 5 exemplos (o detector "vê" o que ele vê?).
- Parâmetros finais (proposta no relatório do Passo 0) e o hash.
- Leitura de "tokens de 2–7 dias em fase 2": idade do token desde a graduação (leitura do handoff) ou tempo na fase 2?
- Horizonte de observação por token (proposta: 14 dias depois da graduação) e mínimo de trades no holdout (proposta: 20).
- Datas exatas dos períodos (dependem do dia do congelamento).

## 6. Atualização do registro

Linha `POS-RUNNER-V0` em `docs/research-hypothesis-registry-v1-2026-10-04.md` com status `RASCUNHO` agora; `PRE-REGISTRADA` no commit do congelamento; resultado no mesmo commit que o registrar.

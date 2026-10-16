# Pré-registro — POS-RUNNER-V0 — RASCUNHO — 2026-10-15 (revisado em 2026-10-16 com as decisões do operador)

Status: **RASCUNHO PRONTO PARA CONGELAR — NÃO CONGELADO.** As regras abaixo são as do operador (decisões de 2026-10-16 sobre o relatório do Passo 0); os pontos que ele não respondeu seguem a opção mais conservadora (§5). Falta só a **confirmação do operador** (§7). Com ela, este arquivo vira `PRE-REGISTRADO` com o hash da config, é commitado e **só então** o backtest da Parte A pode baixar dado de resultado. Nenhum backtest foi rodado. Nenhum dado de resultado de universo sem viés foi lido.

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`. Modelo seguido: `docs/templates/batch-preregistration-template-v1.md` (aqui K = 1 hipótese com uma grade de 6 variantes).

Código: branch `signals-mvp`, pasta `signals_mvp/pos_runner/` (detector causal, simulador, custos, gráficos, Passo 0). Config: `signals_mvp/pos_runner/pos_runner_v0.yaml` — **hash candidato `2a8bef99a917`** (vira o hash congelado com a confirmação; qualquer mudança depois disso é hipótese nova).

## 0. O que é e o que não é

- Hipótese **nova**. Não é resgate da "Post-Transition Pullback/Reacceleration V0" (`PT-V0`, CLOSED/BURNED): aquela olhava janelas de 10 s logo depois da transição para o PumpSwap; esta olha horas/dias depois de um runner de MC >= 300k, em 3 launchpads.
- Estratégia (operador): runner forte → queda de 80–90% → zona de consolidação acima da bonding curve, com testes de suporte → rompimento da zona = entrada → saída perto do último topo.
- Os 5 exemplos do professor (BIKE TYSON, SOLCAT, ALLINU, ZILLIONS, FLAME) calibram só a **detecção das fases** (Passo 0). Os parâmetros de entrada vêm das regras do operador, não de "acertar" os exemplos. Ficam **fora de todas as métricas** (são vencedores escolhidos depois).
- Passo 0: v1 (2026-10-15, proposta com varredura) em `signals_mvp/pos_runner/passo0_relatorio/`; **v2 (2026-10-16, regras do operador, sem varredura e sem resultado de trade)** em `signals_mvp/pos_runner/passo0_relatorio_v2/`. Na v2 o detector vê a fase 2 dos 5 exemplos em pelo menos um timeframe (o SOLCAT aparece como fase 2 com zona madura antes de a onda morrer); 26 das 43 ondas que chegaram à fase 2 morreram por queda > 90%; 1 entrada dos exemplos seria primária (FLAME 5m, 15/09 06:20, idade 3,9 dias).

## 1. Coleta que julga a hipótese (Parte A — backtest histórico sem viés)

- **Universo**: toda graduação bem-sucedida, na Solana, dos launchpads abaixo, dentro de janelas de calendário sorteadas com seed fixa (`20261015`). Nunca uma lista de "tokens conhecidos".

  | Launchpad | Instrução de migração (conferida on-chain nos exemplos) | Pool de destino |
  |---|---|---|
  | pump.fun | `MigrateV2` (pump.fun) → `CreatePool` (PumpSwap) — BIKE TYSON, SOLCAT | PumpSwap (cotado em SOL) |
  | Raydium LaunchLab | `MigrateToCpswap` (LaunchLab) → `InitializeWithPermission` (Raydium CPMM), assinante `RAYpQbFNq9i3mu6cKpTKKRwwHFDeK5AuZz8xvxUrCgw` — ALLINU (cotado em DKNG), ZILLIONS (cotado em ZEC) | Raydium CPMM (ou AMM v4 via `MigrateToAmm`) |
  | Meteora DBC | `MigrationDammV2` (DBC) → `InitializePoolWithDynamicConfig` (DAMM v2) — FLAME (cotado em EMBER) | Meteora DAMM v2 (ou v1) |

- **Enumeração**: método de âncora sem Helius COPIADO do H2 (`benchmarks/sig_fast_v0/h2_enumeration_no_helius_v0.py`, branch `research/rust-signal-plane-live-shadow-v0`, commit `da37ce6`) para `signals_mvp/pos_runner/solana_rpc.py`: busca binária do slot no fim da janela, assinatura âncora, `getSignaturesForAddress` da conta de migração de cada launchpad paginando para trás até o início da janela, `getTransaction` confirma a instrução. RPC: `POS_RUNNER_RPC_URLS` (do operador) ou o RPC público oficial (o `publicnode` apaga blocos com mais de ~2 dias e é recusado automaticamente).
- **Criação do token (idade)**: transação bem-sucedida mais antiga do mint, paginando `getSignaturesForAddress(mint)` para trás a partir da assinatura da migração (`lineage.creation_time`; bateu ao segundo com o Passo 0 nos 5 exemplos). Só para runners. Teto de 100 páginas (100 mil assinaturas; o SOLCAT teve ~10 mil): acima disso a criação é **desconhecida** — o token não tem idade, nenhum setup dele é primário e ele fica fora da linha de base; a contagem sai no relatório (`runners_sem_criacao`). Falha de RPC para a coleta (retoma do checkpoint), nunca vira "sem criação".
- **Preço**: OHLCV do GeckoTerminal do **pool de graduação**, pedido **em token de cotação** (`currency=token`) e convertido para USD com uma série de referência da cotação (SOL/USDC Orca; ZEC/USDC; etc.). Motivo: no exemplo ZILLIONS o USD do próprio GeckoTerminal ficou travado num valor errado por 24 h. Candle sem cotação/USD no instante fica de fora (nunca inventado). Buracos de download são conferidos contra a série de 1h (`missing_windows`) e rebaixados. A conversão usa a cotação/USD do **fechamento** de cada candle (limitação medida no Passo 0 v2: com cotação exótica que sobe junto com o token, a máxima do 1h/4h distorce — FLAME/EMBER: mesmo topo em EMBER, 3,3M no 5m e 5,7M no 1h; por isso o relatório corta por tipo de cotação).
- **Estágios**: (1) 1h de cada pool, de graduação até graduação + 14 dias, para achar quem chegou a MC >= 300k (runner) e buscar a criação dos runners; (2) só esses recebem 5m e 4h do mesmo período. Limite da API pública: ~30 req/min e 180 dias de histórico. Checkpoint e retomada em disco.
- **Período**: janela grátis de 180 dias contada da data do congelamento `D`. Discovery = primeiro trecho; **embargo de 1 semana**; holdout SELADO = último terço do trecho usável, terminando antes de `D` o bastante para os trades do holdout terem candles de saída. Cada token pertence ao período da sua **graduação**. Datas exatas no plano (`plano --congelamento D`, commitado junto). Exemplo com `D` = 2026-10-17: discovery = graduações de 2026-04-23 a 2026-07-27 (95 dias, 4.560 janelas de 30 min), embargo até 2026-08-03, holdout = 2026-08-03 a 2026-09-23 (51 dias, 2.448 janelas).
  - Atenção: o começo da janela grátis anda 1 dia por dia. Depois do congelamento o download do discovery precisa começar logo.
- **Selagem**: a lista de pools do holdout e o hash dela são commitados ANTES de qualquer cálculo do discovery. O código do discovery recusa carregar um pool do holdout.
- **Tamanho (parada por contagem, sem olhar retorno)**: janelas sorteadas são processadas na ordem do sorteio até que o MENOR número de setups primários entre os 3 timeframes chegue a **60** no discovery (ou acabem as janelas). No holdout: até **40** setups primários no timeframe escolhido (folga para chegar aos 30 trades fechados do veredito), nunca além das janelas seladas. Reportar quantos runners e quantos setups.
- **Código e travas** (`signals_mvp/pos_runner/parte_a/`, pronto e testado com universo sintético; NÃO rodado):
  `python -m signals_mvp.pos_runner.parte_a.cli plano --congelamento <D>` → `selar-holdout` → `discovery` → `escolher` → `holdout` → `relatorio`.
  O código recusa rodar se este arquivo não estiver `PRE-REGISTRADO` com o hash da config, se a selagem do holdout não estiver commitada ou com hash diferente, ou se a config/plano mudarem no meio da coleta (checkpoint SQLite guarda os hashes). O discovery recusa qualquer pool do holdout selado; o holdout nunca passa das janelas seladas e só abre se o discovery produziu candidato.
- **Cobertura da enumeração (limitação declarada)**: pump.fun pela autoridade de migração do H2; LaunchLab pelo migrador `RAYpQbFN…` (53 de 60 transações amostradas são `MigrateToCpswap`; `MigrateToAmm` não apareceu); DBC pela config de DAMM v2 `A8gMrEPJ…` (amostra de 2026-10-15: 78 migrações `MigrationDammV2` lidas a partir do keeper `GZjYfGy…` e da própria config, todas com `A8gMrEPJ…` na conta 25; a amostra é parcialmente circular e outra config não apareceu) — migração da DBC para DAMM v1 não coberta. O relatório reporta as contas usadas.
- **Gates de sistema antes de qualquer número econômico**:
  1. a enumeração acha a graduação de cada um dos 5 exemplos rodando numa janela que a contém (os 3 launchpads);
  2. >= 95% das graduações enumeradas têm candles de 1h baixados, ou motivo explícito de falta;
  3. holdout selado (hash commitado) antes do discovery;
  4. testes de causalidade do detector passando (prefixo/futuro não muda decisão passada);
  5. nenhuma série de estágio 2 com buraco contra o 1h depois do reparo (senão o pool sai, com motivo).
  Falha de sistema = SEM VEREDITO; não gasta tentativa.

## 2. Hipótese (K = 1)

### POS-RUNNER-V0 — rompimento da zona de consolidação pós-runner

- Família: `padrão de preço pós-runner (horas/dias)`. Tipo: entrada (alpha). Origem: nova.
- Regra congelada: detector `signals_mvp/pos_runner/detector.py` + parâmetros `pos_runner_v0.yaml` (hash `2a8bef99a917`). Decisão no candle t usa só candles fechados até t (teste de prefixo). Entrada no **open do candle seguinte** ao sinal. Medidas: pico, queda, suporte e resistência pelos **extremos** dos candles (máxima/mínima); rompimento, recuperação e invalidação pelo **fechamento**.
- **Fase 1 — runner**: pico (máxima) da onda >= **300k** de MC (300–500k já vale). "Quanto maior, melhor" é **atributo**, não filtro: faixas 300–500k, 500k–1M, 1–5M, >5M; todos os resultados são reportados por faixa. Nova máxima acima do pico = nova onda.
- **Fase 2 — queda e zona**: a queda a partir do pico (mínima desde o pico) chega a **>= 80%** → a zona começa. Queda **> 90% = moeda morta**: a onda sai (uma nova onda só começa no candle seguinte). Suporte **S >= 0,75 × L_bc** (L_bc = MC no 1º candle de 1h depois da graduação; abaixo disso a onda sai). "Fase 2 normalmente acima de 100k" = **atributo** (S >= 100k sim/não) e corte de análise, não filtro. "Outros fatores" não codificáveis: só atributo, sem exceção manual.
- **Zona**: S = mínima da zona. O **1º repique** (1º fechamento que recupera, ver testes) fixa o fundo; **R = máxima das tentativas de subida depois do fundo, incluindo o 1º repique**. Comprar o 1º repique é impossível por construção (ele forma R e não há teste antes dele).
- **Teste de suporte** (substitui a "wick"): episódio de 1 ou muitos candles em que, estando o preço dentro da zona (depois de uma recuperação), a mínima desce a **<= S × 1,10** e depois o preço **recupera**: fecha **>= min((S + R)/2, S × 1,25)** (e acima de S × 1,10). Sem limite de candles; martelo de 1 candle é caso particular; episódios distintos são separados por uma recuperação completa. Registra-se o nº de testes (1, 2, 3+). **Invalidação**: fechamento abaixo da mínima do último teste − 2% = setup morto (a zona recomeça). **Stop** = mínima do último teste − 3%.
- **Fase 3 — entrada**: zona **madura** até o candle anterior (>= 12 candles do timeframe desde o fundo **e** >= 1 teste completo) e **fechamento do candle acima de R**. **Sem exigência de volume** (o rompimento costuma ser lento; volume = atributo). **Veto**: candle "absurdo" que cobre >= 50% da distância R → P_peak ((máxima − R)/(P_peak − R) >= 0,5). Power candle saudável no rompimento (amplitude >= 3 × ATR(20)) = atributo.
- **Idade**: **2–7 dias de existência do token (desde a criação)** no momento da entrada (fim do candle do sinal) — filtro do sinal primário nos 3 timeframes; fora disso, só diagnóstico. Sem data de criação = sem idade = não primário.
- **Primário**: só o PRIMEIRO setup elegível (dentro da janela de idade) por token e timeframe. Uma decisão (entrada ou absurdo) por zona; depois dela a zona recomeça; setups seguintes, fora da idade ou absurdos = diagnóstico (registrados).
- **Grade** (única variação permitida): timeframe {5m, 1h, 4h} × saída {A, B} = **6 variantes**. Escolhe 1 no discovery pelo EV líquido; empate → 1h e saída A.
- **Saídas** (comuns): alvo = **0,95 × P_peak**; **exaustão** = power candle (amplitude >= 3 × ATR(20), de qualquer cor) cuja máxima chega a **>= 0,85 × P_peak** → sai no open seguinte (o alvo, ordem limitada, vale antes dentro do candle); **stop de tempo = 48 candles** do timeframe; mesmo candle tocando stop e alvo = stop primeiro (`ambiguo`). **A** = 100% no alvo. **B** = 50% no alvo, stop do resto na entrada e resto em trailing de 25% da máxima (a partir do candle seguinte ao alvo). Registra-se a **máxima atingida antes da saída em % do caminho entrada → P_peak**.
- **Custos** (`signals_mvp/pos_runner/costs.py`): fee do PumpSwap pela faixa de MC em SOL (tabela oficial); terminal 1%/perna; rede 0,0003 SOL/perna (0,2% de 0,15 SOL); slippage AMM para 0,15 SOL; ATA = 0. Fee de pool Raydium CPMM / Meteora DAMM v2: **não confirmada** — usa 1,0%/perna.
- **Linha de base pareada**: para cada setup primário (token, tf, **idade desde a criação** na entrada), K = 5 outros runners do mesmo período com criação conhecida (sorteio com seed derivada do setup), cada um entrando na MESMA idade, no mesmo tf, com o MESMO colchete percentual (stop −x%, alvo +y% e o pico equivalente da exaustão), mesmo stop de tempo e mesmos custos. "Runner" = MC >= 300k já atingida antes daquela idade. Edge = EV do setup − EV médio da base.
- **Métricas** (discovery, por variante): nº de setups, taxa de acerto, taxa de alvo antes do stop, R múltiplo médio/mediano, EV líquido por trade (%), mediana, profit factor, pior sequência de perdas, tempo médio no trade, máxima atingida em % do caminho até o pico (quartis, % que chegou à metade e ao topo), linha de base e custo 2×. **Resultado completo por faixa de pico.** Cortes (atributos, nenhum muda a escolha): nº de testes (1, 2, 3+), launchpad, tipo de cotação (SOL/estável × outra), S >= 100k (sim/não), R/S (<= 3 × > 3), volume do rompimento (>= 2× × < 2× a média da zona) e power candle no rompimento (sim/não).
- **Critério de candidato (discovery)**: na variante escolhida, EV líquido > 0, PF > 1, edge sobre a base > 0 e >= 30 trades.
- **Confirmação (holdout selado, variante congelada)**: EV líquido > 0 e PF > 1, com **>= 30 trades fechados** (abaixo disso = INCONCLUSIVE).
- Sensibilidade: custo 2× (todas as parcelas) reportado sempre.
- Controles: linha de base pareada; resultados reportados com cobertura (todas as graduações enumeradas, não só as que deram trade).
- O que um PASS **não** prova: execução real (o candle é proxy, não cotação executável — Gate 0/2), fill e latência, slippage fora do modelo, fee real dos pools não-PumpSwap, comportamento futuro do mercado. Um PASS aqui = `PASS (aguarda replicação)`; a replicação prevista é o paper ao vivo da Parte B com a mesma regra congelada (pré-registro próprio), e depois o Gate 2.

## 3. Multiplicidade e próximos passos

- 1 hipótese, 6 variantes (grade) julgadas no mesmo discovery; só 1 vai para o holdout. Os cortes da §2 são descritivos e pré-listados aqui (nenhum outro).
- O POS-RUNNER ocupa o **caminho 2** da regra de parada do programa (1 discovery + 1 confirmação; escolha conservadora, §5).
- PASS no holdout → `PASS (aguarda replicação)` → replicação sozinha (paper ao vivo, regra congelada, pré-registro próprio).
- FAIL/KILL → fecha. Ideia derivada = hipótese nova.

## 3.1 Parte B (bot ao vivo) rodando antes do congelamento

O handoff pede a Parte B em paralelo. Ela roda com a config em RASCUNHO (os alertas mostram `(rascunho)` e o hash) e
grava paper A/B + base pareada em `pos_runner.csv`. Regras: (a) os parâmetros finais saem SÓ das regras do operador e
da calibração da detecção (Passo 0); mudar qualquer parâmetro depois de olhar resultado do paper ao vivo conta como
ajuste em dado de resultado e é proibido (§4); (b) linhas com `versao_config` diferente do hash congelado não entram em
nenhuma avaliação; (c) o paper ao vivo com a regra congelada só vira "replicação" com pré-registro próprio (§3).
Mecânica que garante isso no código: uma decisão só vira sinal de uma `versao_config` se aconteceu depois do 1º ciclo
dela (refazer o detector com candles congelados nunca cria sinal retroativo); paper aberto de outra versão vira
`descontinuado`; a idade sai da data de criação on-chain (pool sem ela não entra no radar).

## 4. Proibido depois de ver dado de resultado

Mudar qualquer parâmetro da config, a grade, o critério, o período, a linha de base, os cortes ou o custo; incluir/remover tokens; olhar só um subgrupo; trocar a variante depois do holdout.

## 5. Decisões do operador (2026-10-16) e as escolhas conservadoras do item 8

Decisões do operador aplicadas sem interpretação: §2 inteiro (runner >= 300k com faixas; queda [80%, 90%]; S >= 0,75 × L_bc; S >= 100k só atributo; R inclui o 1º repique e o 1º repique nunca é comprado; teste de suporte; invalidação −2% e stop −3%; zona madura 12 candles + 1 teste; fechamento acima de R sem volume; veto de 50%; idade 2–7 dias desde a criação; exaustão 0,85 × P_peak; saídas A/B; stop de tempo 48; máxima em % do caminho). Exemplos: só calibram a detecção, fora de todas as métricas; o operador não sabe qual setup o professor usou em cada gráfico.

O item 8 da mensagem do operador chegou cortado ("Pendência do relatório sem resposta do operador: escolher a opção mais…"). Leitura adotada: **escolher a opção mais conservadora** em cada ponto sem resposta. As escolhas:

| ponto sem resposta | escolha | por que é a conservadora |
|---|---|---|
| Medir pico/queda/zona pelos corpos (proposta da v1) ou pelos pavios | **Extremos** (máxima/mínima) para pico, queda, S e R; **fechamento** para rompimento, recuperação e invalidação (o fechamento já é regra do operador nesses três) | o preço negociou nos extremos (sem escolha arbitrária de corpo); mais ondas morrem por queda > 90% e o rompimento precisa superar a maior máxima. No Passo 0 v2, 7 ondas do timeframe principal morrem pelos extremos e sobreviveriam pelos corpos |
| Horizonte de observação (proposta: 14 dias depois da graduação) | **14 dias** | não muda nenhum setup primário (a idade máxima é 7 dias desde a criação, que é anterior à graduação); só amplia o diagnóstico |
| Mínimo de trades no holdout (proposta: 20) | **30 trades fechados** (parada do holdout em 40 setups) | mais exigente: menos chance de PASS por ruído; igual ao mínimo do discovery |
| O POS-RUNNER ocupa o "caminho 2" da regra de parada? | **Sim** | conta como tentativa: 1 discovery + 1 confirmação; não abre espaço para mais tentativas fora da regra |
| R/S <= 3 e volume >= 2× (handoff original) | **atributos** com cortes de análise em 3 e 2× | o operador disse que os parâmetros de entrada vêm da lista dele, e nenhum dos dois está nela; não inventar filtro que ele não pediu |
| Medida do candle "absurdo" | (máxima − R)/(P_peak − R) >= 0,5 | veta pelo menos tanto quanto qualquer outra leitura (num pool contínuo a mínima do candle de rompimento fica abaixo de R) |
| Data de criação desconhecida | token sem idade → nenhum setup primário, fora da base, contado no relatório | falta de dado nunca vira "dentro da janela" |
| Janela de idade nos 3 timeframes | vale nos 3 (5m incluso) | a regra do operador não distingue timeframe |
| Exaustão × alvo no mesmo candle | o alvo (ordem limitada a 0,95 × P_peak) vale dentro do candle; a exaustão sai no open seguinte | a exaustão só é conhecida no fechamento do candle |
| Parte B: 👀 WATCHLIST | só quando a zona fica madura (S, R e testes existem) | não alerta zona que ainda não é setup |
| Parte B: alertas | só do 1º setup primário de cada token/timeframe (`so_primario: true`); todo o resto vai só para o paper/CSV | menos alerta fora da regra |
| Parte B: comando para pôr token no radar à mão | **não** | "sem exceção manual" |

## 6. Atualização do registro

Linha `POS-RUNNER-V0` em `docs/research-hypothesis-registry-v1-2026-10-04.md` com status `RASCUNHO` agora; `PRE-REGISTRADA` no commit do congelamento; resultado no mesmo commit que o registrar.

## 7. Falta para congelar (só a confirmação do operador)

1. Confirmar a leitura do item 8 (opção mais conservadora) e as escolhas da §5 — em especial a medida pelos **extremos**.
2. Conferir no Passo 0 v2 se o detector "vê" as fases que o professor mostrou.
3. Dizer o dia do congelamento `D` (as datas dos períodos saem do plano gerado nesse dia).

Com o OK, no mesmo commit: a linha de status deste arquivo passa a PRE-REGISTRADO com o hash `2a8bef99a917`, a linha do registro vira `PRE-REGISTRADA` e entra o plano da Parte A (`plano --congelamento D`); depois `selar-holdout` (commit) e só então o discovery. A trava do código lê só a linha de status (a primeira que começa com "Status:").

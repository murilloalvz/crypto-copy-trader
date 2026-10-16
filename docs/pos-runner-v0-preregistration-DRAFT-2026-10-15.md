# Pré-registro — POS-RUNNER-V0 — 2026-10-15 (revisado em 2026-10-16 com as decisões do operador; congelado em 2026-10-16)

Status: **PRE-REGISTRADO** (congelado em 2026-10-16, confirmação do operador sobre o Passo 0 v2 e a config `2a8bef99a917`). A partir daqui nenhuma regra, grade, período, linha de base, corte ou custo muda (§4); uma mudança é hipótese nova. Ainda NENHUM dado de resultado de universo sem viés foi lido neste commit — o backtest da Parte A começa depois dele.

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`. Modelo seguido: `docs/templates/batch-preregistration-template-v1.md` (aqui K = 1 hipótese com uma grade de 6 variantes).

Código: branch `signals-mvp`, pasta `signals_mvp/pos_runner/` (detector causal, simulador, custos, gráficos, Passo 0). Config: `signals_mvp/pos_runner/pos_runner_v0.yaml` — **hash congelado `2a8bef99a917`**. Regra congelada = este hash **+** o código em `detector.py`/`simulate.py`/`costs.py`/`params.py` no commit `dbbcea1` (SHA256 abaixo); qualquer mudança em qualquer um dos dois depois deste commit é hipótese nova.

| arquivo | SHA256 (commit `dbbcea1`) |
|---|---|
| `signals_mvp/pos_runner/detector.py` | `df995c39db3db0297c6423ecdb35e23ee382414440f0e536d63e3e0d2b200496` |
| `signals_mvp/pos_runner/simulate.py` | `5d7144f32488e8d7f9e0a621ebd8194de7fa6b400e8947dbf19cf019b9732693` |
| `signals_mvp/pos_runner/costs.py` | `c42e8cb83c466ba2b7cdc415f3168794a5a4ffb0ea60654e87d0005edcc362b9` |
| `signals_mvp/pos_runner/params.py` | `b42c4f51b2a12e39fe13b91c81a91ed77bb3d40f6d53b86488932e3f97dcd3f6` |
| `signals_mvp/pos_runner/pos_runner_v0.yaml` | `e04c1c3ae7afeb3c9a8b43d0a95a3c758ff2996755821c1fa729c3dc32934361` |

**Decisão do operador sobre o L_bc (§7, pendência 3):** a confirmação cobriu a config `2a8bef99a917` como está; L_bc não é parâmetro do YAML (é calculado do dado: MC no open do 1º candle de 1h do pool de graduação), e a alternativa on-chain não foi pedida. Fica a definição atual — a limitação do STREAM continua registrada em §1 como fato medido, não como filtro a mudar.

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
- **L_bc** (nível em que a curva terminou) = MC no open do 1º candle de 1h do pool de graduação (Parte A e B). Limitação medida no teste de fumaça de 2026-10-16: quando a curva é comprada inteira na criação e o 1º negócio no pool sai muito acima dela, L_bc fica alto (STREAM, pump.fun, criado e migrado no mesmo segundo em 14/10: 1º open ~362k, mínima do mesmo candle ~52k) e a regra S >= 0,75 × L_bc fica mais dura para esse token; nos 5 exemplos e nos outros tokens do teste L_bc deu 28–51k. Alternativa não adotada (decisão do operador no congelamento, §7): reservas iniciais do pool na própria transação de migração.
- **Estágios**: (1) 1h de cada pool, de graduação até graduação + 14 dias, para achar quem chegou a MC >= 300k (runner) e buscar a criação dos runners; (2) só esses recebem 5m e 4h do mesmo período. Limite da API pública: ~30 req/min e 180 dias de histórico. Checkpoint e retomada em disco.
- **Período**: janela grátis de 180 dias contada da data do congelamento `D` = **2026-10-16**. Discovery = primeiro trecho; **embargo de 1 semana**; holdout SELADO = último terço do trecho usável, terminando antes de `D` o bastante para os trades do holdout terem candles de saída. Cada token pertence ao período da sua **graduação**. Plano gerado e commitado junto (`docs/pos-runner-v0/plano_parte_a.json`, versão `8a2387a3e185`): discovery = graduações de 2026-04-22 a 2026-07-26 (95 dias, 4.560 janelas de 30 min, ordem `bba2e0f3d591cf50`), embargo até 2026-08-02, holdout = 2026-08-02 a 2026-09-22 (51 dias, 2.448 janelas, ordem `32edc0024c93b521`).
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
- **Zona**: S = mínima da zona. O **1º repique** (1º fechamento que recupera, ver testes) fixa o fundo; **R = máxima das tentativas de subida depois do fundo, incluindo o 1º repique** (se o próprio candle do fundo já fecha recuperado — martelo —, a máxima dele entra em R). Comprar o 1º repique é impossível por construção (ele forma R e não há teste antes dele).
- **Teste de suporte** (substitui a "wick"): episódio de 1 ou muitos candles em que, estando o preço dentro da zona (depois de uma recuperação), a mínima desce a **<= S × 1,10** e depois o preço **recupera**: fecha **>= min((S + R)/2, S × 1,25)** (e acima de S × 1,10). Sem limite de candles; martelo de 1 candle é caso particular; episódios distintos são separados por uma recuperação completa. Registra-se o nº de testes (1, 2, 3+). **Invalidação**: fechamento abaixo da mínima do último teste − 2% = setup morto (a zona recomeça). **Stop** = mínima do último teste − 3%.
- **Fase 3 — entrada**: zona **madura** até o candle anterior (>= 12 candles do timeframe desde o fundo, contando o candle do fundo, **e** >= 1 teste completo) e **fechamento do candle acima de R**. Candle cuja mínima mata a onda (queda > 90% ou fundo < 0,75 × L_bc) nunca é entrada: a onda morre nele. **Sem exigência de volume** (o rompimento costuma ser lento; volume = atributo). **Veto**: candle "absurdo" que cobre >= 50% da distância R → P_peak ((máxima − R)/(P_peak − R) >= 0,5). Power candle saudável no rompimento (amplitude >= 3 × ATR(20)) = atributo.
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

## 3.1 Parte B (bot ao vivo)

A Parte B rodou em paralelo com a config em RASCUNHO antes deste commit (os alertas mostravam `(rascunho)` e o hash);
daqui em diante os alertas mostram `(pré-registrada)` (`config_status` lê este arquivo) — a config é a mesma, só o
rótulo muda. Grava paper A/B + base pareada em `pos_runner.csv`. Regras: (a) os parâmetros não mudam mais (§4); (b)
linhas com `versao_config` diferente do hash congelado não entram em nenhuma avaliação; (c) o paper ao vivo com a
regra congelada só vira "replicação" com pré-registro próprio (§3) — o paper gravado antes deste commit (rascunho)
nunca é usado como se fosse essa replicação. Mecânica que garante isso no código: uma decisão só vira sinal de uma
`versao_config` se aconteceu depois do início da execução contínua dela (refazer o detector com candles congelados
nunca cria sinal retroativo; voltar a uma versão recomeça a contagem); paper aberto de outra versão vira
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
| "12 candles desde o fundo" | conta o candle do fundo; a entrada mais cedo possível é o 13º candle | leitura literal; nenhuma entrada antes de 12 candles completos de zona |
| Candle de rompimento cuja mínima passa de 90% de queda (ou fica abaixo de 0,75 × L_bc) | **não é entrada**: a onda morre nele | "acima de 90% = moeda morta, fora" vale mesmo que o candle feche acima de R |
| Candle do fundo que já fecha recuperado (martelo) | a máxima dele entra em R | R inclui o 1º repique; R mais alto = rompimento mais exigente |
| Rompimento vetado (absurdo) | não gasta o "1º setup" do token/timeframe | o setup vetado não é elegível; o próximo elegível é o primário |
| Parte A: candle sem cotação/USD no fechamento | a série **para** nesse candle (como a Parte B, que espera); nunca vira candle inventado; contado (`sem_usd_cortados`) | sem dado não se cria preço |
| Janela de idade nos 3 timeframes | vale nos 3 (5m incluso) | a regra do operador não distingue timeframe |
| Exaustão × alvo no mesmo candle | o alvo (ordem limitada a 0,95 × P_peak) vale dentro do candle; a exaustão sai no open seguinte | a exaustão só é conhecida no fechamento do candle |
| Parte B: 👀 WATCHLIST | só quando a zona fica madura (S, R e testes existem) | não alerta zona que ainda não é setup |
| Parte B: alertas | só do 1º setup primário de cada token/timeframe (`so_primario: true`); todo o resto vai só para o paper/CSV | menos alerta fora da regra |
| Parte B: comando para pôr token no radar à mão | **não** | "sem exceção manual" |

## 6. Atualização do registro

Linha `POS-RUNNER-V0` em `docs/research-hypothesis-registry-v1-2026-10-04.md`: `PRE-REGISTRADA` neste commit; resultado entra no mesmo commit que o registrar (discovery/holdout).

## 7. Congelamento

Confirmado pelo operador em 2026-10-16: Passo 0 v2 (o detector vê as fases dos 5 exemplos) e a config `2a8bef99a917` como está. `D` (dia do congelamento, usado no plano da Parte A) = **2026-10-16**.

Deste commit em diante: nenhuma mudança de parâmetro, grade, critério, período, linha de base, corte ou custo (§4). Próximos passos, na ordem, cada um com seu próprio commit:

1. (este commit) status → `PRE-REGISTRADO`, registro → `PRE-REGISTRADA`, plano da Parte A (`plano --congelamento 2026-10-16`).
2. `selar-holdout` → commit da selagem (lista + hash), ANTES de qualquer cálculo do discovery.
3. `baixar-bruto --periodo discovery` (ordem cronológica, §8.1) → `discovery` → `escolher` → commit da escolha → `holdout` (só se o discovery der candidato) → `relatorio`.

## 8. Decisões OPERACIONAIS de 2026-10-16 (infraestrutura — nenhuma muda a hipótese, a grade, o período, a linha de
## base, os cortes ou o custo; §2 e §4 continuam intocados)

Calibrado antes de rodar em escala: ~181 chamadas de RPC por janela (3 launchpads), ~108 s/janela no teto padrão de
100/min do cliente (o próprio teto, não o QuickNode do operador, é o limitador real nesse padrão). Selar as 400
janelas do holdout sozinho custaria ~12 h nesse teto.

### 8.1 Ordem de download (limite móvel de ~180 dias do GeckoTerminal)

O discovery começa em 2026-04-22, perto do limite de ~180 dias do OHLCV grátis do GeckoTerminal — limite que anda 1
dia por dia. Uma janela antiga que só fosse baixada tarde na ordem SORTEADA (a que decide o resultado) corre o risco
de sair do alcance antes de ser baixada, numa coleta de muitas horas/dias. Correção operacional: `baixar-bruto`
(`signals_mvp/pos_runner/parte_a/pipeline.py:prefetch_period`) baixa o bruto (enumeração on-chain + candles de
estágio 1/2) com a janela mais ANTIGA do calendário primeiro — nunca pela ordem sorteada — grava com checkpoint
(retomável) e não roda o detector nem decide a parada por contagem. A parada por contagem continua, sem exceção, na
ordem sorteada pré-registrada (`discovery`/`holdout`); depois de um `baixar-bruto` completo, ela não faz NENHUMA
chamada de rede nova (lê só o que já está em cache/checkpoint). Janela sorteada cuja data já estiver fora do alcance
grátis (HTTP 401 do GeckoTerminal) vira status explícito **`fora_do_alcance_gratis`** (com a data), nunca
`sem_dados` genérico nem pulo em silêncio — contado no relatório e nos estágios 1/2 (`pipeline.py:_fetch_history`).
Holdout (2026-08-02 a 2026-09-22) não corre esse risco (45–75 dias de idade hoje, bem dentro dos 180); a prioridade
cronológica é para o discovery.

### 8.2 Exemplos no holdout

Conferido: `EXCLUDED` (os 5 exemplos do professor) já era aplicado em `enumerate_windows` ANTES do `if period !=
"holdout"`, ou seja, para discovery E holdout igualmente — não precisou de correção. Travado com teste
(`test_examples_are_excluded_from_both_discovery_and_holdout`).

### 8.3 Créditos e ritmo do RPC

Ritmo-teto do RPC configurável por `POS_RUNNER_RPC_PER_MIN` (padrão 100, igual a antes — só infra, nunca regra); o
limitador é adaptativo (cai pela metade a cada 429, sobe aos poucos) e só é seguro subir o teto num RPC DEDICADO
(QuickNode do operador), nunca no público compartilhado. Cada comando da Parte A loga e acumula (`rpc_calls_total`,
`gt_calls_total` na Store) as chamadas de RPC e GeckoTerminal daquela execução. **Limitação desta sessão**: não há
acesso programático ao painel/API de cota da QuickNode — não dá para calcular o % real do plano gratuito mensal
consumido sem o operador informar o limite do plano ou checar o painel. Reportarei os totais acumulados medidos a
cada marco; se o operador disser o limite mensal, calculo o % e paro com checkpoint em 90%, como pedido.

## 9. Addendum de RELATÓRIO de 2026-10-16 — tabela de trades + gestão de banca (SUBSTITUI o item 1, "simulação de
## banca", da mensagem original do operador; pré-registrado ANTES de qualquer cálculo do discovery)

Nova entrega do relatório (nenhuma mudança de hipótese, grade, período, linha de base, corte, custo ou escolha da
variante — §2 e §4 continuam intocados; a escolha da variante em `metrics.choose_variant` continua vindo só do
custo FIXO de 0,15 SOL do handoff): para CADA ajuste da grade (tf 5m/1h/4h × saída A/B), uma **tabela de trades**
(CSV sempre; XLSX com uma aba por ajuste/período + aba `resumo`, se `openpyxl` estiver instalado) — uma linha por
entrada primária FECHADA que o bot faria pelas regras congeladas, em ordem cronológica real:

`data_entrada, token, contrato, launchpad, tf, saida, mc_entrada, mc_saida, motivo_saida (TP/stop/exaustão/tempo),
tempo_no_trade_h, lucro_bruto_%, taxas_%, lucro_liquido_%, tamanho_posicao_usd, resultado_usd, banca_depois_usd`.

**Gestão de banca** (separada por ajuste, nunca preço médio): banca inicial US$100; posição = 5% da banca NO
MOMENTO da entrada; no máximo 3 posições abertas ao mesmo tempo (a 4ª entrada marcada `"pulado: limite"`); stop
diário (banca cai ≥10% desde o início do dia UTC OU 3 perdas seguidas) pausa o resto do dia
(`"pulado: stop diário"`); stop semanal (banca cai ≥20% desde o início da semana ISO/UTC) pausa o resto da semana
(`"pulado: stop semanal"`); taxas e slippage **recalculados pelo tamanho real da posição** (o `CostModel` do
handoff é calibrado a 0,15 SOL fixo — aqui o mesmo evento/caminho de preço é resimulado com um `CostModel` do
tamanho real em SOL daquele instante; o evento, o detector e a decisão de ENTRADA são os mesmos, só o custo muda
com o tamanho).

**Resumo no topo** (uma linha por ajuste): nº de trades, % que deu lucro, lucro líquido médio %, banca final US$,
maior queda da banca US$ e %.

**Limitação documentada**: só trades com status `fechado` entram nesta tabela ilustrativa e na contagem de
posições abertas; `cancelado` (abriu fora do plano, nunca uma posição real) e `em_aberto` (sem desfecho até o fim
da janela de dados) ficam fora — não afeta a métrica oficial (`variant_table`/`choose_variant`/`candidate`/
`holdout_verdict`), que já trata esses status separadamente. `token` vem de um lookup (cacheado, só leitura) no
GeckoTerminal (`networks/solana/pools/{pool}`); falha ou indisponibilidade vira `sem dado` (nunca trava o
relatório, nunca filtro).

Feito no discovery e, se houver candidato, no holdout (abas/arquivos separados por período). Os 5 exemplos do
professor ficam fora (mesma exclusão de sempre). Implementação: `signals_mvp/pos_runner/parte_a/bankroll.py`
(`simulate_bankroll`, `write_bankroll_reports`), chamado por `report.write_report` (comando `relatorio`).
A Parte B ao vivo (`live.py`) grava a mesma tabela com os sinais reais e envia o resumo diário no Telegram
(decisão registrada aqui; implementação na branch `signals-mvp` junto do paper A/B existente).

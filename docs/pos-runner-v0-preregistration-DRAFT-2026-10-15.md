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
professor ficam fora (mesma exclusão de sempre). A gestão de banca em si (`BankrollLedger`/`BankrollState`) vive em
`signals_mvp/pos_runner/bankroll.py`, sem depender do `Context` da Parte A, e é compartilhada pelas duas partes:
Parte A (`parte_a/bankroll.py`: `simulate_bankroll`/`write_bankroll_reports`, chamado por `report.write_report`,
comando `relatorio`) e Parte B ao vivo (`live.py`: `PosRunnerLive._update_bankroll`, chamado assim que um sinal
real fecha; grava `pos_runner_banca.csv`, estado persistido em `pr_bankroll_state` por `(tf, variante,
versao_config)`; resumo diário por ajuste enviado no Telegram no mesmo horário do resumo diário do bot v0).

## 10. EMENDA de 2026-10-16 — grade ampliada para 24 combinações (ANTES de qualquer cálculo do discovery; nenhum foi
## feito neste repositório até este commit)

Pedido do operador, verbatim: "ampliar a grade antes de ver dado". Motivo documentado: a grade de 6 variantes do §2
(tf × saída) deixava de fora duas dimensões que o operador quer comparar — a medida da queda/zona (extremos vs.
fechamentos, já discutida como leitura conservadora em §5) e a janela de idade (2–7 dias vs. uma janela mais larga,
1–10 dias) — e o operador prefere decidir isso agora, ampliando a grade, do que depois de ver qualquer resultado
(o que seria `p-hacking` e está proibido por §4). **Nenhum cálculo de discovery/holdout foi feito antes desta
emenda**: o `selar-holdout` já rodado só enumera janelas on-chain (RPC), nunca chama o detector nem lê resultado de
trade — por isso a seleção de janelas não depende da regra e o holdout selado **continua válido** sem precisar
refazer a selagem.

**Config**: novo hash `0de2333a7f63` (era `2a8bef99a917`). O campo novo (`Params.queda_medida`, default
`"extremos"`, validado contra `{"extremos", "fechamentos"}`) é o único campo de parâmetro que mudou — o hash muda
automaticamente porque `Params.version` cobre `self.as_dict()` inteiro; nenhum outro valor de `pos_runner_v0.yaml`
foi tocado. Regra congelada a partir de agora = este hash **+** o código em `detector.py`/`simulate.py`/`costs.py`/
`params.py`/`pos_runner/parte_a/{pipeline,baseline,metrics,report,bankroll}.py`/`pos_runner/live.py` no commit desta
emenda; qualquer mudança depois dele é hipótese nova. A linha de `Status:` no topo deste arquivo não muda (continua
`**PRE-REGISTRADO**`) — esta emenda é uma versão do MESMO pré-registro, não uma hipótese nova, porque é uma
ampliação da grade decidida antes de qualquer dado de resultado, exatamente o caso previsto para emenda (ao
contrário de retune depois do dado, que §4 proíbe).

### 10.1 Grade (24 combinações)

`tf {5m, 1h, 4h} × saída {A, B} × medida da queda {extremos, fechamentos} × idade {2–7 dias, 1–10 dias}` = 3 × 2 × 2
× 2 = **24 combinações**. Tudo o mais em §2 continua congelado como está (zona, teste de suporte, invalidação,
exaustão, custos, linha de base pareada, veto de candle absurdo, etc.) — a medida da queda só troca extremos por
fechamentos no pico/queda/S/R (rompimento, recuperação e invalidação já eram pelo fechamento nos dois casos, §5); a
idade só troca a janela do filtro de sinal primário (§2, "2–7 dias" → também "1–10 dias"), sem tocar a regra de
detecção.

- **Mecânica (implementação, não muda regra)**: a medida da queda é uma dimensão NOVA do detector (`Params` com
  `queda_medida` diferente) — precisa rodar o detector de novo, mas sobre os MESMOS candles já baixados (nenhuma
  chamada de rede nova; `tf_variant()` guarda o resultado sob um rótulo pseudo-tf, ex. `"1h_fecham"`, na MESMA coluna
  `tf` das tabelas `setups`/`trades`, sem mudar o schema nem a regra de parada por contagem, que só olha tf reais).
  A idade NÃO precisa de nenhuma nova execução do detector: "primário" por janela de idade é reclassificado depois
  da coleta, direto do atributo `idade_dias` já gravado em cada setup, repetindo a MESMA regra do detector ("1º
  setup elegível por token/tf vence"), só filtrando por outra janela (`primary_under_window`).
- **Escolha no discovery**: maior EV líquido entre as combinações com **>= 30 trades**; empate → **1h, A, extremos,
  2–7 dias** (a combinação primária original). Combinação sem 30 trades nunca é escolhida, mesmo com EV alto.
- **Holdout**: só a combinação escolhida decide o veredito (EV líquido > 0, PF > 1, **>= 30 trades fechados**;
  abaixo disso = INCONCLUSIVE, igual a antes). As outras 23 são medidas no mesmo holdout só para comparação/relatório,
  nunca para o veredito. **Multiplicidade registrada**: 24 comparações no mesmo discovery (era 6); o relatório e o
  registro (§6/§10.4) citam esse número.
- **Regra de parada por contagem**: aplica-se à combinação primária original (1h, A, extremos, 2–7 dias) — é ela
  quem decide quando o discovery/holdout para de coletar (§7/§8). As outras 23 combinações usam exatamente as MESMAS
  janelas de calendário sorteadas (nenhuma janela extra é sorteada ou baixada por elas).
- **Confirmado (correção de implementação, não de regra — sem novo hash)**: (a) a medida "fechamentos" roda nos 3
  timeframes reais (5m, 1h, 4h), não só 1h — `detect_and_trade` (`pipeline.py`) itera `QUEDA_MEDIDAS` dentro do loop
  por tf real; travado por `test_runner_without_creation_date_has_no_primary_setup`, que já conta
  `setups_primarios` nos 6 rótulos (`5m`, `1h`, `4h`, `5m_fecham`, `1h_fecham`, `4h_fecham`). (b) "1º setup por
  token" é recalculado SEPARADAMENTE para cada faixa de idade — `primary_under_window` nunca herda o resultado de
  uma janela para a outra (cada chamada começa um `done` novo e só olha o `idade_dias` já gravado); uma entrada no
  dia 1,5 (fora de 2–7, dentro de 1–10) pode virar a primária sob 1–10 enquanto a entrada do dia 3 do MESMO
  pool/tf, que era a primária sob 2–7, nunca é herdada como primária sob 1–10 (vira reentrada sob essa janela).
  Caso coberto pelo teste novo `test_primary_under_window_is_recomputed_independently_per_idade_faixa`
  (`tests/test_pos_runner_parte_a.py`).

### 10.2 Tabela de trades (substitui a estrutura do §9 — mesmo conteúdo por linha, agora por combinação)

Uma aba/CSV por combinação (24, nomeadas `{periodo}_{tf}_{medida}_{idade}_{saida}`), com o resumo no topo (uma linha
por combinação: nº de trades, % com lucro, lucro líquido médio %, banca final US$, maior queda US$ e %) — mesma
estrutura e mesmas colunas do §9, só que 24 vezes em vez de 6. Mais **2 abas de DIAGNÓSTICO** que nunca contam para
o veredito nem para a escolha da combinação:

- `{periodo}_diag_fora_de_qualquer_janela_de_idade`: entradas cuja idade desde a criação é desconhecida, < 1 dia ou
  > 10 dias (fora das duas janelas testadas nas duas direções) — mostra o que a ampliação da janela (1–10) ainda
  deixa de fora.
- `{periodo}_diag_reentradas_apos_1o_setup`: setups do mesmo token/tf com `n_entrada` > 1, ou seja, zonas que
  reabriram depois do 1º setup elegível (o detector só deixa o 1º virar "primário"; esta aba só documenta quantas
  reentradas existiram, sem gerar trade nem contar para nenhuma métrica oficial).

A gestão de banca de cada combinação é independente (banca US$100 própria, nunca preço médio entre combinações).

### 10.3 Parte B ao vivo

Alertas (👀/🟢/🟡/📊) e paper A/B com gestão de banca real continuam só da combinação PRIMÁRIA (1h, A, extremos,
2–7 dias) — nenhuma mudança de comportamento visível ao operador. As outras 23 combinações: só a dimensão "medida da
queda" precisa rodar ao vivo (a dimensão "idade" é reclassificação pós-hoc, não existe em tempo real) — o detector
`fechamentos` roda em paralelo sobre os MESMOS candles do mesmo pool/tf, grava o sinal (entrada/fechamento, sem base
pareada) só para `pos_runner_detalhe.csv` (nunca entra em `pos_runner.csv`, contrato estável — filtrado por
`storage._pos_runner_rows`), nunca manda alerta Telegram, nunca toca a banca de US$100 da Parte B. Serve só para
comparar depois com o paper da Parte A sobre o mesmo dado real.

### 10.1b EMENDA de 2026-10-16 — 3 atributos secundários (sem mudar regra primária nem a grade de 24)

A pedido do operador, ANTES de qualquer cálculo do discovery: 3 atributos secundários gravados em todo setup, só
descritivos (nunca filtro, nunca mudam a escolha/veredito/parada por contagem; **sem novo hash de config** — nenhum
campo de `Params` mudou, só novos campos no dicionário que o detector já emite). Relatório: estratificação completa
(`CUTS`) por cada atributo, sem filtrar, igual aos cortes já existentes (`por_testes`, `por_launchpad`, etc.) — inclui
automaticamente a combinação escolhida (holdout) e todas as 24 do discovery, porque `_cut_lines`/`CUTS` já são
genéricos.

1. **Hora da entrada em BRT (UTC−3, sem horário de verão)**, faixa **8h–14h vs. resto** (`metrics._hora_brt`, a
   partir de `entry_ts` — o open do candle seguinte ao sinal, já gravado em `trade_info`). Corte novo `por_hora_brt`.
2. **Origem/launchpad** (pump.fun / Raydium LaunchLab / Meteora DBC) — **já existia** como corte `por_launchpad`
   (`r[12]` = `graduations.launchpad`); nenhuma mudança de código, só confirmação.
3. **Razão volume do candle do último teste de suporte / média de volume dos candles da zona madura**
   (`detector.py`: `teste_vol_ratio` no dicionário de dados da ENTRADA — numerador = volume do candle que fixou a
   mínima do último teste completo, `z.cur["low_vol"]`/`z.tests[-1]["low_vol"]`, novo campo só de leitura, nunca usado
   em nenhuma decisão; denominador = o MESMO `mean_vol` da zona já usado pelo `vol_ratio` do candle de rompimento —
   só troca o candle do numerador). Corte novo `por_vol_teste` (mesmo limiar 2× do `por_volume` existente, só para
   comparar com a mesma régua).

**Holders/authority/liquidez** (pedido do operador, registrado para o futuro): só como colunas descritivas no
**forward/ao vivo** (`live.py`, se/quando uma fonte de dado for escolhida), **nunca no backtest** (Parte A) — nada
implementado nesta emenda (nenhuma fonte/API foi especificada); é só uma restrição registrada de antemão para
quando essa fonte existir, para não entrar por engano no cálculo do backtest.

Testado: `test_primary_under_window_is_recomputed_independently_per_idade_faixa` (já existente) e
`test_report_has_the_bands_the_cuts_and_the_sampled_trades` (estendido com `por_hora_brt`/`por_vol_teste`); suíte
offline completa 276/276.

### 10.4 Registro

Linha `POS-RUNNER-V0` em `docs/research-hypothesis-registry-v1-2026-10-04.md` atualizada no mesmo commit desta
emenda: emenda registrada, grade 6 → 24, multiplicidade 24, hash novo `0de2333a7f63`, holdout selado permanece
válido.

## 11. Correção de qualidade de dado na enumeração (2026-10-16) — selo re-emitido, NENHUMA regra mudou

Achado durante `baixar-bruto` do discovery: a trava de vazamento (holdout dentro do discovery) pegou 1 "pool" com
o mint nativo do SOL — nunca um pool real. Raiz confirmada via `getTransaction` real: uma transação pode chamar o
MESMO programa do launchpad em mais de uma instrução de nível 1 (ex.: comprar e migrar no mesmo envio, ou
criar+testar+migrar); `_launchpad_instruction` pegava "a 1ª instrução que casa o `programId`", não necessariamente
a de migração, e lia mint/pool do layout de contas ERRADO. Corrigido em `enumerate.py`/`lineage.py`: casa a
instrução pelo NOME logado (`top_level_instruction_names`), nunca só pelo `programId`; filtro defensivo adicional
rejeita (`nao_resolvida`, nunca "pool morto") qualquer mint/pool que bata com endereço nativo/de sistema conhecido.
Fixtures reais das 2 transações que causaram os achados (`rpc_tx_migrate_dbc_bundled.json`,
`rpc_tx_migrate_pumpfun_bundled_buy.json`); os 3 exemplos clássicos continuam resolvendo exatamente o mesmo
pool/mint de antes (regressão zero).

**Varredura e reprocessamento** (holdout, as únicas 28366 graduações já enumeradas; discovery só tinha 4 linhas,
sem suspeitas): 45 entradas suspeitas (pool/mint == endereço nativo/de sistema, ou pool==mint) — 44 em pump.fun,
1 em meteora_dbc. Reprocessadas com o parser corrigido via `getTransaction` real (1 chamada por entrada,
`Store.reprocess_graduation`, nunca edição direta do SQLite): 34 corrigidas (pool/mint reais); 11 eram
duplicatas — a mesma migração real já estava corretamente gravada sob OUTRA assinatura (mesmo mint, pool, grad_ts
próximo; causa exata da assinatura duplicada não aprofundada, registrada como limitação) — removidas, sem perda de
dado (a linha correta permanece). 0 removidas como genuinamente "não resolvida" (todas as 45 encontraram a
instrução certa com o fix).

**Selo re-emitido com transparência total** (`docs/pos-runner-v0/holdout_selado.json`, histórico git preserva a
versão anterior): hash antigo `f17dda7e1f719967dc9cfd59211d3277` (28362 pools, incluindo o lixo) → hash novo
`e6edb9723d10e3554c6a7c89ffe20bae` (28351 pools, só reais). Confirmado ANTES do re-selo: `stage1`/`stage2`/`setups`/
`trades` com 0 linhas (nada dependente de `ctx.params`/do detector foi calculado ainda) — a correção é só
qualidade de enumeração, nunca retune de regra. `versao_plano`/janelas (400) inalterados.

**Nada de regra/grade/período/baseline/corte/custo mudou** — só a qualidade do dado de enumeração (correção de
bug de parsing + filtro defensivo, ambos documentados e testados). Commits da correção, do filtro e do re-selo
citam este parágrafo.

## 12. Segunda rodada da correção (2026-10-17) — posição do pool do pump.fun + 2 checagens "falhar fechado"

Validação positiva (60 amostras) achou 5% de divergência, acima do limite de 1% combinado com o operador — parei,
reportei (`DECISÃO NECESSÁRIA`), e segui com a opção aprovada. Causa: a instrução LEGADA `Migrate` (sem V2,
27/25 contas) tem o pool numa posição DIFERENTE de `MigrateV2` (29 contas) — índice fixo 10 lia um endereço que
nem existe on-chain (confirmado via `getAccountInfo`). Fix: `LaunchpadSpec.pool_after_program` (só pump.fun —
raydium_launchlab/meteora_dbc validaram 0/20 na mesma amostra) acha o pool pela posição RELATIVA ao programa da
AMM de destino (`accounts.index(pool_after_program) + 1`), nunca um índice fixo.

Duas checagens "falhar fechado" novas, independentes do layout de contas, pedidas pelo operador: (1) mint precisa
aparecer em `postTokenBalances`/`preTokenBalances` da própria tx (sem RPC nova); (2) pool precisa EXISTIR
on-chain, verificado em lote (`getMultipleAccounts`, lotes de 5 — limite do plano `discover` da QuickNode,
medido em produção) dentro de `enumerate_window`; falha de rede nesta checagem sobe como erro (nunca aceita sem
verificar). Quem não passa vira `nao_resolvida` (fora, contado, nunca pool morto).

Varredura em escala (holdout, pump.fun — os 10077 pools já enumerados, em lotes de 5, ~2016 chamadas): 1102
(10,9%) não existiam on-chain. Reprocessados via `getTransaction` real + o parser corrigido +
`Store.reprocess_graduation`: 100 corrigidos (pool/mint reais); 1002 eram duplicatas — a mesma migração real já
estava correta sob OUTRA assinatura (mesmo padrão do achado anterior: migrações com sniper bot geram uma tx
`Migrate` legada E uma `MigrateV2`/outra para o mesmo evento) — removidos sem perda de dado. 0 genuinamente
`nao_resolvida`, 0 erros.

**Re-selo** (2ª vez, mesma transparência): hash anterior `e6edb9723d10e3554c6a7c89ffe20bae` (28351 pools) → hash
novo `3f648e9548002cef355f78c107cacef8` (27349 pools). Confirmado ANTES: `stage1`/`stage2`/`setups`/`trades` com 0
linhas. **Nova validação positiva, amostra DIFERENTE (seed distinta, 60 entradas estratificadas por launchpad)**:
0% de divergência. `versao_plano`/janelas (400) inalterados; nenhuma regra/grade/limiar mudou.

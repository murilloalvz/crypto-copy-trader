# Handoff — POS-RUNNER-V0 (estratégia pós-runner) — 2026-10-16 (rev. 2: regras do operador aplicadas)

Branch `signals-mvp` (espelho em `claude/pensive-wright-62usq8`, PR #6). Modo PAPER / READ ONLY: nenhuma chave, nenhuma
assinatura, nenhuma ordem. Kernel Rust, branch do H2, `benchmarks/sig_fast_v0/` e `artifacts/sig_fast_h2_*` intocados
(a enumeração de migrações por âncora foi COPIADA para `signals_mvp/pos_runner/solana_rpc.py`, com a origem citada).

## 1. Onde está cada entrega

| entrega | estado |
|---|---|
| Passo 0 | v1 (15/10, proposta com varredura) em `signals_mvp/pos_runner/passo0_relatorio/`. **v2 (16/10)**: o que o detector vê nos 5 exemplos com as suas regras — `signals_mvp/pos_runner/passo0_relatorio_v2/relatorio_passo0_v2.md` (+ gráficos, `fases.json`, hashes; mesmos candles do v1, reprodutível sem rede). Sem varredura e sem resultado de trade |
| Pré-registro | rascunho **revisado com as suas decisões e pronto para congelar** — `docs/pos-runner-v0-preregistration-DRAFT-2026-10-15.md`; config candidata `2a8bef99a917`; linha do registro atualizada (continua `RASCUNHO`) |
| Parte A — backtest sem viés | código atualizado às regras (idade desde a criação, base pareada pela mesma idade, cortes por faixa/testes/cotação…), testado com universo sintético, **NÃO executado**. A trava continua fechada até o pré-registro virar `PRE-REGISTRADO` com o hash |
| Parte B — sinal ao vivo no bot | ligada com as regras novas (config em rascunho); passo a passo no `signals_mvp/README.md` |

## 2. O que preciso de você (para congelar)

1. **Item 8 chegou cortado** ("Pendência do relatório sem resposta do operador: escolher a opção mais…") — igual nas duas
   vezes em que a mensagem chegou. Li como **"a opção mais conservadora"**. Confirma? O que essa leitura decidiu está na
   tabela da §5 do rascunho (medida pelos extremos, holdout com ≥ 30 trades, caminho 2 da regra de parada, R/S e volume
   só como atributo, sem comando manual de radar…).
2. **Medida da queda pelos extremos** (máxima/mínima) — a escolha conservadora. Nos exemplos, 7 ondas do timeframe
   principal morrem pelos extremos (queda > 90%) e sobreviveriam pelos corpos (Passo 0 v2, §2). Confirma os extremos?
3. **Passo 0 v2**: o detector vê as fases que o professor mostrou? Resumo: fase 2 detectada nos 5 exemplos em pelo
   menos um timeframe; o SOLCAT aparece com zona madura (👀) nas duas ondas antes de morrer; 26 das 43 ondas que chegaram
   à fase 2 morreram por queda > 90%; 1 entrada dos exemplos seria primária (FLAME 5m, 15/09 06:20, idade 3,9 dias) — as
   outras ficaram fora de 2–7 dias desde a criação (BIKE sempre com mais de 8 dias; nos outros, as primeiras entradas
   vieram com menos de 2 dias e as de ondas posteriores com mais de 7) ou vieram depois da primária no mesmo timeframe.
4. **L_bc (limitação nova, medida no teste de fumaça)**: L_bc = open do 1º candle de 1h do pool de graduação. O STREAM
   (pump.fun) foi criado e migrado no mesmo segundo (14/10 19:18:29Z, pela busca on-chain do teste) e o 1º negócio no
   PumpSwap saiu a ~362k de MC, enquanto a curva terminou a ~52k (a mínima do mesmo candle); L_bc ficou ~7× alto e a
   regra S ≥ 0,75 × L_bc ficaria mais dura para esse token (nos 5 exemplos e nos outros 3 tokens do teste, L_bc deu
   28–51k, coerente). Alternativa mais exata: ler L_bc on-chain nas reservas do
   pool na própria transação de migração (mais código, sobretudo para DAMM v2). **Mantive a definição atual**. Quer a
   troca antes do congelamento?
5. O dia do congelamento `D` (as datas dos períodos saem do plano gerado nesse dia; ex.: D = 17/10 → discovery de 23/04
   a 27/07, holdout de 03/08 a 23/09).

## 3. O que mudou com as suas decisões

- **Detector** (`pos_runner/detector.py`, o mesmo no Passo 0, na Parte A e no bot): zona da fase 2 aberta quando a queda
  chega a 80%; moeda morta acima de 90%; fundo ≥ 0,75 × L_bc; R = máxima das subidas depois do fundo **incluindo o 1º
  repique** (que nunca é comprado: ele forma R e não há teste antes dele); **teste de suporte** de 1 ou muitos candles
  (mínima ≤ S × 1,10 e depois fechamento ≥ min((S+R)/2, S × 1,25)); setup morto se fechar abaixo do último teste −2%;
  stop no último teste −3%; zona madura = 12 candles + 1 teste; entrada = fechamento acima de R, sem volume; veto de
  candle absurdo (≥ 50% de R → pico); **idade de 2–7 dias desde a criação** do token.
- **Atributos** (nenhum é filtro): faixa do pico (300–500k, 500k–1M, 1–5M, >5M), S ≥ 100k, nº de testes, R/S, volume
  do rompimento, power candle, idade desde a graduação, máxima atingida antes da saída em % do caminho até o pico.
- **Saídas**: alvo 0,95 × pico (A: 100%; B: 50% + stop do resto na entrada + trailing de 25%); exaustão = power candle
  com máxima ≥ 0,85 × pico; stop de tempo 48 candles.
- **Criação do token**: transação bem-sucedida mais antiga do mint, paginando para trás a partir da migração (bateu ao
  segundo com o Passo 0 nos 5 exemplos). Parte A: só para runners; Parte B: na thread de linhagem, antes de o token
  entrar no radar. Sem criação = sem idade = nunca primário.
- **Parte A**: base pareada pela mesma idade desde a criação; resultado completo por faixa de pico; cortes por testes,
  launchpad, tipo de cotação, S ≥ 100k, R/S, volume e power candle; holdout com ≥ 30 trades fechados (parada em 40
  setups); contagem dos runners sem data de criação no relatório.
- **Parte B**: alertas com zona/testes/idade desde a criação; um sinal só conta para uma `versao_config` se foi decidido
  depois do 1º ciclo dela (refazer o detector a partir dos candles congelados nunca cria sinal retroativo); paper aberto
  de outra versão vira `descontinuado`; tokens já no radar sem data de criação voltam para a fila até a thread buscá-la.

## 4. Como a Parte B funciona (resumo; detalhe no README)

- Mesmo detector, simulador, custos e conversão para USD do backtest. Candle consumido só **fechado** (+90 s para o
  GeckoTerminal indexar) e **congelado** no SQLite: reiniciar o bot refaz exatamente o mesmo estado.
- Um token só entra no radar depois da **prova on-chain** de que o pool nasceu da migração de um dos 3 launchpads, para
  aquele mint, e da **data de criação** do token (RPC público ou o seu em `POS_RUNNER_RPC_URLS`, numa thread própria).
- Chamadas ao GeckoTerminal saem de uma fatia reservada do orçamento do v0 (`chamadas_por_ciclo`, padrão 3).
- Alertas: 👀 (zona madura), 🟢 (entrada + mini-gráfico + Axiom), ⚪ (candle absurdo: não entrar), 🔴 (setup morto ou
  onda descartada), 🟡 (saída sugerida, como resposta ao 🟢), 📊 (resultado do paper com custos e base pareada).
- Paper A/B de **toda** entrada (custo 1× e 2×) e base pareada. CSVs `dados\pos_runner.csv` (colunas do handoff:
  `idade_h` agora em horas desde a criação, `n_wicks` = nº de testes) e `dados\pos_runner_detalhe.csv` (+ faixa do
  pico, S ≥ 100k, R/S, idade desde a graduação, máxima em % do caminho até o pico).
- **Regra científica**: com a config em rascunho, o paper ao vivo é só operacional; mudar parâmetro depois de olhar
  resultado dele = ajuste em dado de resultado (proibido); linhas de outra `versao_config` ficam fora de qualquer
  avaliação (§3.1 do rascunho).

## 5. Verificações feitas

- **250 testes offline** (`python -m unittest discover -s signals_mvp/tests -t .`) em Python 3.13 e 3.10 (o mínimo do
  README; sem matplotlib o teste do gráfico é pulado) e `compileall` em 3.11.
- Detector: entrada de livro (com a zona e o teste esperados), mesmas decisões em todo prefixo da série (sem lookahead),
  moeda morta > 90%, fundo abaixo de 0,75 × L_bc, sem exigência de volume, maturidade, precisa de teste, 1º repique
  nunca comprado, teste de vários candles, descida sem recuperação, invalidação, veto de absurdo, idade desde a criação
  (dentro, jovem demais, desconhecida).
- Parte A (universo sintético): parada por contagem e retomada idempotente, base pareada pela idade desde a criação,
  resultado por faixa e os cortes, token sem data de criação nunca primário e fora da base, trava do pré-registro.
- Parte B: fluxo completo (descoberta → linhagem → criação → 👀 → 🟢 → paper → 🟡 → 📊 → CSV), busca da criação (ok,
  teto de páginas, falha de RPC), pool antigo sem criação volta para a fila, troca de versão sem sinal retroativo, além
  dos testes anteriores (candle em andamento nunca consumido, reinício sem alerta repetido, orçamento, 429, erro de um
  pool sem travar os outros, multi-timeframe com cotação em SOL, integração com o engine).
- Passo 0 v2 rodado duas vezes a partir do instantâneo: mesmo texto (fora a data) e `fases.json` idêntico.

## 6. Bugs achados e corrigidos

- **Revisão independente do diff** (outro agente, só leitura, verificando cada achado com script) — 4 confirmados e 1
  reforço, todos corrigidos com teste que falha sem a correção:
  1. R não incluía a máxima do candle do fundo quando ele mesmo já fechava recuperado (martelo) — contrariava "R inclui
     o 1º repique";
  2. um candle de rompimento cuja mínima passava de 90% de queda gerava ENTRADA e "moeda morta" no mesmo candle —
     agora a morte da onda vence (sem entrada);
  3. Parte A: candle sem cotação/USD era trocado por um candle plano inventado (esconderia quedas reais) — agora a
     série para ali, como na Parte B, e o corte é contado (vinha do commit 7261491);
  4. Parte B: trocar de versão da config e voltar (V → V' → V) adotava como sinal de V o que foi decidido com V' rodando —
     agora o início da versão recomeça a cada troca;
  5. a trava aceitava variações do termo ("PRE-REGISTRADO?", "PRE-REGISTRADOS") — agora só `**PRE-REGISTRADO**` exato.
  O Passo 0 v2 foi regenerado com o detector corrigido: muda R onde o fundo foi martelo e 1 entrada do BIKE no 5m; o resumo
  (43 ondas, 26 mortas, 1 entrada primária no FLAME) não muda.
- **Trava do pré-registro** (achado pelo teste nesta rodada): o rascunho novo cita a linha de status final e o hash
  candidato, e a trava antiga procurava o padrão em qualquer lugar do texto — teria aberto. Agora só a linha de status
  (a 1ª que começa com "Status:") conta, num único helper (`params.is_preregistered`) usado pela Parte A e pelo bot.
- (rodada anterior) Config do v0 com o endereço errado do USDT; carga de candles que podia não terminar; linhagem de
  pool quente; URL de RPC fora dos logs.

## 7. Teste de fumaça contra as APIs reais (somente leitura, sem Telegram)

Com o código desta rodada (config `2a8bef99a917`), 2026-10-16 05:18–05:36 UTC, GeckoTerminal público + RPC público da
Solana, 6 ciclos com `chamadas_por_ciclo: 4` e no máximo 4 pools:

- **Descoberta**: 18 candidatos reais das listas do GeckoTerminal, todos pools do PumpSwap com MC ≥ 300k (a linhagem
  decide se são pools de graduação).
- **Linhagem + data de criação (RPC)**: 3 aceitos e postos no radar, todos pump.fun, com a criação on-chain — STREAM
  (criado e migrado no mesmo segundo, 14/10 19:18:29Z), FTR (criado 15/10 01:59, migrado 02:08) e DOPE (criado 11/10
  13:28, migrado 13:33); 3 recusados com motivo explícito (DGAI, PULT e um 2º pool "FTR": nenhuma migração do pump.fun
  criou esses pools em ±10 min da criação); 12 ainda na fila quando o teste acabou — o gargalo é o RPC público
  (266 chamadas em 6 ciclos).
- **Candles**: STREAM e DOPE carregados nos 3 timeframes (DOPE: 1.344 de 5m, 112 de 1h, 28 de 4h); FTR com o 1h e o
  resto ainda na fila do orçamento. 17 chamadas ao GeckoTerminal, 0 erro, 0 *rate limit*.
- **Detector**: os 3 em fase 1 (runner, sem zona ainda) → nenhum alerta, como esperado. L_bc: DOPE 45k, FTR 46k e STREAM
  362k (o caso do §2, item 4).
- Rodada anterior (15–16/10, regras antigas): VEIL, DOPE, STREAM e CLAUDIA verificados e carregados; mesmo padrão de
  recusas.

Não testado contra o serviço real: Telegram (o cliente é o do v0, com `sendPhoto`) e Windows.

## 8. Limitações declaradas

- Candle não mostra a ordem dos preços dentro dele (stop e alvo no mesmo candle = stop). Entrada do paper = open do candle
  seguinte ao sinal; o clique real chega depois do alerta (pesa mais no 5m).
- Conversão para USD pela cotação do **fechamento** do candle: com cotação exótica que sobe junto com o token, a máxima
  do 1h/4h distorce (FLAME/EMBER: mesmo topo em EMBER, 3,3M no 5m e 5,7M no 1h). A Parte A corta por tipo de cotação.
- L_bc pelo 1º open de 1h (ver §2, item 4).
- Data de criação: até 100 mil assinaturas do mint antes da migração; acima disso o token fica sem idade (contado).
- Fee dos pools Raydium CPMM e Meteora DAMM v2 não confirmada (1% conservador por perna); supply atual (queima posterior
  distorce o passado).
- Cobertura da enumeração da DBC: só a config de DAMM v2 `A8gMrEPJ…`; a LaunchLab só por `MigrateToCpswap`.
- O RPC público é lento e limita `getTransaction`/`getSignaturesForAddress`; neste ambiente (IP de saída compartilhado)
  ele recusou bastante. Um RPC gratuito seu deixa a entrada no radar muito mais rápida.
- Windows real e Telegram real não testados nesta sessão (o cliente do Telegram é o mesmo do v0, com `sendPhoto`).

## 9. Congelamento (2026-10-16)

Confirmado pelo operador: Passo 0 v2 e a config `2a8bef99a917`. Pré-registro passou a `PRE-REGISTRADO`
(`D` = 2026-10-16; commit `dbbcea1` fixa o código da regra, SHA256 no documento), registro `PRE-REGISTRADA`, plano
gerado (`docs/pos-runner-v0/plano_parte_a.json`, versão `8a2387a3e185`): discovery 2026-04-22 a 2026-07-26 (4.560
janelas), embargo até 2026-08-02, holdout 2026-08-02 a 2026-09-22 (2.448 janelas). L_bc fica na definição atual (1º
open de 1h): a confirmação cobriu a config como está e L_bc não é parâmetro do YAML.

Daqui em diante nenhuma regra muda (§4 do pré-registro). Próximos passos, cada um com seu commit:

1. `selar-holdout` → commit da selagem (lista + hash) ANTES de qualquer cálculo do discovery.
2. `discovery` → `escolher` → commit da escolha → `holdout` (só se o discovery der candidato) → `relatorio`.

RPC: a Parte A usa `POS_RUNNER_RPC_URLS`, vazia neste ambiente; defino para o próprio processo da coleta com o
endpoint QuickNode de `H2_BACKFILL_RPC_URLS` (presente neste ambiente, grátis), em vez do RPC público (lento e mais
recusado, medido no teste de fumaça da Parte B).

## 10. Decisões operacionais e addendum de relatório (2026-10-16, pós-congelamento)

Três pontos de operação antes de rodar (infraestrutura, nenhuma regra mudou; detalhe completo no pré-registro
§8): (1) `baixar-bruto` baixa o bruto do discovery em ordem cronológica (mais antiga primeiro) para nunca perder
dado por causa do limite móvel de ~180 dias do GeckoTerminal; a ordem sorteada que decide a parada por contagem
não muda; (2) confirmado que a exclusão dos 5 exemplos já valia em discovery E holdout; (3) créditos de
RPC/GeckoTerminal acumulados e logados por execução; ritmo do RPC pago configurável
(`POS_RUNNER_RPC_PER_MIN`, só para o endpoint dedicado). Selagem do holdout relançada com ritmo maior no QuickNode
dedicado (antes limitada pelo teto autoimposto de 100/min, não pelo provedor).

**Addendum de relatório** (§9 do pré-registro; substitui o item 1, "simulação de banca", da mensagem original do
operador): tabela de trades (CSV + XLSX) por ajuste da grade (tf×saída), com simulação de banca de US$100 (posição
5%, até 3 abertas, stop diário/semanal) — custo recalculado pelo tamanho real da posição; a escolha da variante
continua vindo só do custo fixo de 0,15 SOL. A gestão de banca em si (`BankrollLedger`/`BankrollState`) vive em
`pos_runner/bankroll.py`, sem depender do `Context` da Parte A, e é compartilhada pelas duas partes:

- Parte A: `relatorio` chama `parte_a/bankroll.py` automaticamente, que roda o ledger em lote sobre todo o período
  e grava CSV + XLSX.
- Parte B ao vivo: `live.py` avança o MESMO ledger um sinal real por vez, assim que ele fecha
  (`PosRunnerLive._update_bankroll`), grava `pos_runner_banca.csv` (mesmas colunas) e persiste o estado no banco
  (`pr_bankroll_state`, chave `(tf, variante, versao_config)` — trocar de config começa banca nova, igual ao resto
  do paper). O resumo diário por ajuste sai no Telegram no mesmo horário do resumo diário do bot v0
  (`engine.maybe_send_daily_summary` chama `PosRunnerLive.daily_bankroll_summary()`).
- Conversão US$→SOL (posição real) precisa de uma cotação SOL/USD já cacheada; sem ela a linha fica explícita
  (`"sem dado: sol/usd"`), nunca um custo inventado.

## 11. Status em 2026-10-16 ~15h UTC (handoff para quem assumir a sessão)

**Pronto e commitado** (branch `signals-mvp` = `claude/pensive-wright-62usq8`, PR #6):
- Congelamento do pré-registro (commit `dbbcea1`), plano da Parte A, 3 decisões operacionais de §8 (prefetch
  cronológico, confirmação dos exemplos, créditos/ritmo do RPC) e o addendum de relatório completo (§9: Parte A
  `bankroll.py` + Parte B `live.py` com resumo diário no Telegram) — commits `28b310a`, `b6f9102`, `77eebe7`,
  `a0c35f9`, `5808a98`. 261 testes offline passando.

**Em andamento agora** (processo em segundo plano, PID 490, fora do controle de versão):
`selar-holdout --janelas 400`, checkpoint em `signals_mvp/dados/pos_runner_parte_a/parte_a.sqlite` (gitignored).
Estava em ~239/400 janelas, 0 erro, usando um endpoint QuickNode NOVO (o antigo bateu o limite diário às
~14h40 UTC; trocado com o operador). Ritmo `POS_RUNNER_RPC_PER_MIN=150` (conservador, endpoint novo sem
histórico de limite conhecido).

**Ainda NÃO existe nenhuma tabela de trades/banca real** (a pergunta "terminou a tabela?" — resposta: não, e não
pode terminar antes do discovery rodar): `write_bankroll_reports` só gera algo para um período com graduações
enumeradas, e por enquanto SÓ o holdout está sendo selado (zero linhas em `graduations` para `discovery`, zero em
`trades`). A tabela real só existe depois de: selar o holdout (em andamento) → commitar a selagem → `baixar-bruto
--periodo discovery` (4.560 janelas, o maior passo — download cronológico do bruto para não perder dado no limite
de ~180 dias do GeckoTerminal) → `discovery` (parada por contagem, ≥60 setups/tf) → `escolher` → (se candidato)
`holdout` → `relatorio` (que já chama `write_bankroll_reports` automaticamente).

**Próximos passos exatos, na ordem, cada um com seu commit** (comandos em
`signals_mvp/pos_runner/parte_a/cli.py`):
1. Esperar `selar-holdout` chegar a 400/400 → commitar `docs/pos-runner-v0/holdout_selado.json` ANTES de qualquer
   `discovery`.
2. `baixar-bruto --periodo discovery` (sem commit — só grava bruto em cache/checkpoint).
3. `discovery` → `escolher` → commitar `docs/pos-runner-v0/escolha_discovery.json`.
4. Se `candidato: true`: `holdout` → commitar `docs/pos-runner-v0/resultado_holdout.json`.
5. `relatorio` → gera `docs/pos-runner-v0/relatorio_parte_a.md` + `docs/pos-runner-v0/trades/*.csv` +
   `trades_parte_a.xlsx` (a tabela de banca) + 5 gráficos de trades sorteados. Esse conjunto é a entrega final.

**Only-mentioned-once risco conhecido**: um endpoint QuickNode agressivo (600/min) esgota TODAS as 8 tentativas de
`getTransaction`/`getSlot` e trava o progresso sem travar o processo (fica "dormindo" em retry); se isso se
repetir, `curl`/`requests.post` direto no endpoint com `getSlot` mostra na hora se é limite diário (HTTP 429,
`-32003 "daily request limit reached"`) — não é só questão de baixar o `POS_RUNNER_RPC_PER_MIN`.

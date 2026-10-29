# Bot de sinais de memecoins — v0 (PAPER / somente leitura)

O bot **não executa nada**. Ele olha as redes **Solana, BSC e Robinhood Chain**, corta o lixo, calcula um score
transparente, **manda o alerta no Telegram** e grava o que aconteceu depois de **cada token avaliado** (enviado ou
não) — para você decidir em segundos e, com o tempo, medir com dados se o score separa bons de ruins.
Você opera **manualmente no simulador** (Axiom para Solana; GMGN para BSC e Robinhood).

```
descoberta → segurança (corta) → métricas → score → sinal → acompanhamento (+5/+15/+60 min) → log
```

**Regras fixas deste projeto:** nenhuma chave privada, nenhuma assinatura/envio de transação, nenhum segredo no git
(`.env` fica fora), nada de gerar volume, wash trading, pump coordenado ou deploy de token. O Telegram só obedece o
seu `TELEGRAM_CHAT_ID`.

> **Isto é um instrumento de coleta e treino, não uma prova de edge.** Os pesos do score são um ponto de partida
> **não validado**. Qualquer afirmação de que o score "funciona" exige o rito do repositório: pré-registro da
> hipótese, validação em período não visto e resultado líquido de custos (ver `docs/research-hypothesis-registry-v1-2026-10-04.md`
> e [Disciplina dos dados](#disciplina-dos-dados-e-recalibração)). Nada aqui mexe nas linhas de pesquisa existentes.

---

## Passo a passo no Windows (≈ 15 minutos)

1. **Instale o Python 3.10 ou mais novo** em <https://www.python.org/downloads/>. Na primeira tela do instalador,
   marque **"Add python.exe to PATH"**. (Evite a versão da Microsoft Store.)
2. **Traga a pasta do projeto** para o PC (`git clone` do repositório e `git checkout signals-mvp`, ou baixe o ZIP
   da branch). O bot vive em `signals_mvp\`.
3. **Instale as dependências** (só `requests` e `PyYAML`): dê dois cliques em `signals_mvp\instalar.bat`
   — ou, num `cmd` aberto na pasta que contém `signals_mvp`:
   ```
   py -3 -m pip install -r signals_mvp\requirements.txt
   ```
   O `instalar.bat` também cria o arquivo `signals_mvp\.env` a partir do `.env.example`.
4. **Crie o bot no Telegram:** abra o **@BotFather**, mande `/newbot`, escolha nome e usuário. Ele devolve um
   **token** parecido com `123456789:AAH...`. Depois **abra o seu bot no Telegram e mande `/start`** (sem isso ele
   não consegue escrever para você).
5. **Pegue o seu chat id:** mande qualquer mensagem para o **@userinfobot**; ele responde com o seu `Id` (um número).
6. **Preencha o `.env`** (`signals_mvp\.env`, abre no Bloco de Notas):
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAH...seu_token
   TELEGRAM_CHAT_ID=seu_numero
   ```
7. **Teste tudo** com dois cliques em `signals_mvp\testar.bat` (ou os três comandos abaixo, um de cada vez):
   ```
   py -3 -m signals_mvp selfcheck        # testes + simulação com dados falsos, sem rede
   py -3 -m signals_mvp teste-rede       # APIs reais (GeckoTerminal, GoPlus, Telegram getMe), só leitura
   py -3 -m signals_mvp teste-telegram   # manda UMA mensagem de teste para o seu Telegram
   ```
   Se a mensagem de teste chegou, token e chat id estão certos.
8. **Edite o `meta.txt`** com o meta do dia (veja [Meta do dia](#meta-do-dia-metatxt)) e dê uma olhada no
   `config.yaml` (tudo comentado).
9. **Ligar (1 comando):** dois cliques em **`signals_mvp\iniciar.bat`**
   (ou `py -3 -m signals_mvp iniciar`). A janela mostra uma linha curta por ciclo; o detalhe vai para
   `signals_mvp\logs\signals_mvp.log` (o supervisor tem o seu em `logs\supervisor.log`).
10. **Parar (1 comando):** **`signals_mvp\parar.bat`** (ou `py -3 -m signals_mvp parar`, ou `Ctrl+C` na janela do bot).
    Ele grava os CSVs e sai com segurança.

**Reinício automático:** `iniciar` sobe um *supervisor* que reinicia o bot se ele cair. **Stall guard:** se passar
`ciclo.stall_guard_s` (300 s) sem ciclo, o supervisor registra `STALL` no log, mata o processo travado e sobe outro
(e avisa no Telegram). Para ligar sozinho quando o Windows iniciar, crie uma tarefa no *Agendador de Tarefas*
apontando para o `iniciar.bat`.

**Onde ficam os CSVs:** `signals_mvp\dados\` — `sinais.csv`, `descartados.csv`, `trades_operador.csv` (e
`sinais_detalhe.csv`, com todos os campos internos). O estado vive em `dados\estado.sqlite`; se você apagar um CSV,
`py -3 -m signals_mvp exportar` recria. **Se o CSV estiver aberto no Excel o Windows trava o arquivo:** o bot avisa
no log e regrava no ciclo seguinte (nada se perde) — prefira abrir uma *cópia*.

---

## O que chega no Telegram

```
🟢 82/100 | BSC | $TICKER | MC 85k | 4 min | novo
Narrativa: IA (match meta)
Vol m5: 12k (3,4x) | Compra/venda: 68/32 ($8k/$4k) | Liq: 40k
Top10: 22% | Segurança: ok | Alertas: nenhum
Plano: TP1 +60% (vende 50%) | SL −30% | tempo 15 min
Lat: 52 s (evento→alerta)
<contrato do token, toque para copiar>
[GMGN] [DexScreener]
[✅ entrei] [⏭ passei]
```

- **Bolinha:** 🟢 a partir de `score.verde_min` (75), 🟡 abaixo (mas acima do mínimo de alerta, 60).
- **`Vol m5: 12k (3,4x)`:** volume dos últimos 5 min e a **aceleração** = ritmo do m5 ÷ ritmo médio da última hora
  (ou da vida do pool, se tiver menos de 1 h). Em pool com menos de 5 min não há base de comparação: fica `s/d`.
- **`Compra/venda: 68/32`:** nº de transações de compra/venda no m5. O `($8k/$4k)` é o **valor** em USD, calculado
  das últimas ~300 trades do pool; com `*` quer dizer janela parcial (pool muito movimentado).
- **`Segurança`:** `ok` só quando os itens obrigatórios foram **verificados**. `parcial ⚠` = parte verificada.
  **`SEM DADO ⚠` = não deu para verificar — nunca é tratado como ok** (veja a política abaixo). `ok (GT)` = mint/freeze
  da Solana verificados só pelo GeckoTerminal.
- **`Lat`:** latência **evento → alerta**: da criação do pool (carimbo da chain) até o alerta sair. Também vai no CSV
  (`latencia_s`) e no resumo diário.
- **Botões:** `entrei` registra a posição padrão (`plano.posicao_usd`); `passei` registra que você passou.

**Comandos** (todos gravam em `trades_operador.csv`):

| comando | efeito |
|---|---|
| `/entrei <contrato> <valor> [chain]` | registra entrada (valor em USD; `100` ou `100,5`) |
| `/sai <contrato> <valor> [chain]` | registra saída (USD recebido) |
| `/passei <contrato> [chain]` | registra que passou |
| `/status` | estado do bot (config, ciclos, latência) |
| `/resumo` | resumo de hoje |

`[chain]` (`solana`, `bsc`, `robinhood`) só é necessário se o contrato não for de um sinal recente e for ambíguo
(um `0x…` pode ser BSC ou Robinhood). Um contrato que veio de um sinal descobre a chain sozinho e liga a linha ao sinal
(`sinal_relacionado` = `data|etiqueta` do `sinais.csv`).

**Resumo diário** (às `resumo_diario.hora_local`, hora do PC): por **etiqueta e chain** — enviados × não enviados ×
cortados; resultado líquido (média e mediana) e **% que bateu TP1 antes do SL**, **separando enviados de não enviados**
(é essa comparação que diz se o score separa bons de ruins) — e a latência p50/p95.

---

## POS-RUNNER ao vivo (estratégia pós-runner) — Parte B

Além do v0, o mesmo bot acompanha a hipótese **POS-RUNNER-V0**: token que **já correu** (runner com pico de MC ≥ 300k),
**caiu 80–90%** a partir do pico, formou uma **zona** com o fundo acima de 0,75 × o nível da curva (`L_bc`, a MC da
graduação), teve pelo menos um **teste de suporte** (desceu até perto do fundo e recuperou) e **fecha acima da
resistência** da zona. Ele roda nos timeframes **5m, 1h e 4h**, nos 3 launchpads da Solana (pump.fun, Raydium
LaunchLab, Meteora DBC), com **o mesmo detector, simulador e custos do backtest** (Parte A). PAPER: o bot só avisa e
simula; quem decide e opera é você, no simulador do Axiom.

> **Congelada em 2026-10-16.** As regras do padrão estão em `pos_runner/pos_runner_v0.yaml`
> (`PRE-REGISTRADO`, `docs/pos-runner-v0-preregistration-DRAFT-2026-10-15.md`); mudar qualquer parâmetro agora é
> hipótese nova. Os alertas mostram `config <hash> (pré-registrada)`. Paper ao vivo **não é validação**: a hipótese só
> pode virar edge pelo backtest sem viés com holdout selado (Parte A) e o rito do registro de hipóteses.

**Passo a passo mínimo (depois dos passos 1–6 do início deste README: Python, `.env` com
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`, bot criado no @BotFather, `/start` mandado)**

1. Rode de novo o `instalar.bat` (instala o `matplotlib`, usado no mini-gráfico; sem ele o alerta sai só em texto).
2. (Opcional, recomendado) Ponha um RPC gratuito seu (Helius/QuickNode) em `POS_RUNNER_RPC_URLS=` no `.env`
   (`signals_mvp\.env`, uma URL completa por linha ou separadas por vírgula). Sem ele o bot usa o RPC público da
   Solana, que é lento: a conferência on-chain de cada token novo leva minutos. Com QuickNode, um dia de uso errado
   pode bater o **limite diário do plano** — o bot percebe (HTTP 429 com `"daily request limit reached"`), pausa
   só aquele endpoint por 1h e continua no RPC público sozinho; ele volta a tentar a QuickNode depois, sem precisar
   reiniciar nada.
3. **Teste a entrega antes de ligar pra valer** — manda 1 alerta de ENTRADA de mentira (com mini-gráfico) e 1 resumo
   de banca de mentira pro seu Telegram:
   ```
   py -3 -m signals_mvp teste-pos-runner
   ```
   Se os dois chegaram no celular (claramente marcados "TESTE"/"mentira"), token, chat id e o mini-gráfico estão
   certos.
4. Confira no `config.yaml` a seção `pos_runner:` — vem **ligada** (`ligado: true`). Para desligar, troque para
   `false` e salve (o bot recarrega sozinho). Os outros itens dizem **quais tokens** acompanhar (`max_pools`, `fontes`,
   `idade_max_dias`) e **quais alertas** mandar; as regras do padrão ficam no arquivo `parametros` (mudar esse arquivo
   exige reiniciar o bot).
5. **Ligar (1 comando):** `signals_mvp\iniciar.bat` (ou `py -3 -m signals_mvp iniciar`). O console mostra
   `POS-RUNNER ligado | config <hash> (rascunho)` e, ao longo do dia, `POS-RUNNER: acompanhando $TICKER`.
   `/status` no Telegram mostra quantos tokens estão no radar.
6. **Parar (1 comando):** `signals_mvp\parar.bat` (ou `py -3 -m signals_mvp parar`, ou `Ctrl+C` na janela do bot).

**Como os tokens entram no radar:** a cada 3 min o bot lê uma lista do GeckoTerminal (em rodízio: *trending* e os
pools de maior volume 24h do PumpSwap, Meteora DAMM v2 e Raydium) e também olha os pools novos que o v0 já busca.
Entra quem é **pool de graduação** (a DEX certa), tem **MC ≥ 300k** agora e **até 14 dias** de vida. Antes de
acompanhar, o bot confere **on-chain** (RPC) que o pool nasceu da **migração** de um dos 3 launchpads, para aquele
token e aquele pool, e busca a **data de criação** do token (a idade dos sinais conta dela) — sem essas duas provas o
token não entra. No máximo `max_pools` (15) ao mesmo tempo; o resto espera na fila (maior MC primeiro). Cada token é
acompanhado até 14 dias depois da graduação (`idade_max_dias`); como só a idade de 2–7 dias desde a criação gera sinal
primário, baixar para 7 libera vagas do radar mais cedo.

**O que chega no Telegram**

| alerta | quando |
|---|---|
| `👀 WATCHLIST POS-RUNNER [tf]` | a zona da fase 2 ficou **madura**: ≥ 12 candles desde o fundo e ≥ 1 **teste de suporte**. Mostra pico (e a faixa: 300–500k, 500k–1M, 1–5M, >5M), queda %, `L_bc`, `S`, `R`, nº de testes, idade desde a criação e o nível que **mata** o setup |
| `🟢 ENTRADA POS-RUNNER [tf]` | **fechamento acima de `R`** (sem exigência de volume). Mostra MC de entrada (o paper entra no **open do próximo candle**), stop (3% abaixo da mínima do último teste), alvo (95% do pico), R:R, nº de testes, volume do rompimento e **power candle** (só atributos), S ≥ 100k, idade, botão do Axiom e o **mini-gráfico** com S, R, testes e pico |
| `⚪ NÃO ENTRAR [tf]` | o rompimento veio num candle **absurdo** (sozinho cobriu ≥ 50% do caminho de `R` até o pico) |
| `🔴 INVALIDADO [tf]` | fechou abaixo da mínima do último teste −2% (setup morto), a queda passou de 90% (moeda morta) ou o fundo ficou abaixo de 0,75 × `L_bc` (só para tokens que tiveram 👀) |
| `🟡 SAÍDA SUGERIDA [tf]` | o paper saiu (ou vai sair no próximo candle): **stop**, **alvo**, **trailing** (saída B), **exaustão** (power candle perto do último topo: máxima ≥ 85% do pico) ou **stop de tempo** (48 candles). Vem como **resposta** ao 🟢 |
| `📊 POS-RUNNER [tf]` | resultado do paper (A e B, já com custos) e a **linha de base pareada** |

Com `so_primario: true` (padrão), o 👀/🟢 só sai para o **1º setup** de cada token em cada timeframe com **idade de
2 a 7 dias desde a criação**; reentradas e setups fora da idade viram só paper (aparecem no CSV). Os 🟡 chegam no **fechamento do candle** (o bot trabalha com candles fechados):
se você entrar, coloque **stop e alvo no próprio Axiom**.

**Saídas do paper:** **A** = vende tudo no alvo (95% do pico); **B** = vende metade no alvo, o stop do resto vai para
a entrada e o resto segue com *trailing* de 25% da máxima. As duas têm o mesmo stop, a saída por exaustão e o stop de
tempo. **Todo** sinal de entrada vira paper A e B (custo normal e custo 2×), e cada um ganha uma **linha de base
pareada**: até 5 outros tokens do radar que já eram runners na mesma idade (desde a criação), "comprados" na mesma
idade com o mesmo stop/alvo em %. É isso que mostra se o padrão agrega algo além de "comprar token que já correu".

**Troca de versão das regras:** reiniciar o bot com outro `pos_runner_v0.yaml` muda o hash (`versao_config`). O paper
aberto da versão anterior vira `descontinuado`, e nenhuma decisão anterior ao 1º ciclo da versão nova vira sinal dela
(o detector refaz o estado a partir dos candles congelados, sem sinal retroativo; voltar para uma versão antiga também
recomeça a contagem dela).

**Seus trades:** `/entrei <contrato> <valor>` e `/sai <contrato> <valor>` funcionam igual ao v0 e gravam em
`trades_operador.csv`; quando o contrato é de um sinal POS-RUNNER, `sinal_relacionado` fica `data|pos_runner_<tf>`.

**CSVs:** `dados\pos_runner.csv` — **uma entrada por linha**, colunas fixas do handoff:
`data,token,contrato,launchpad,tf,idade_h,P_peak,L_bc,queda_pct,S,R,n_wicks,entrada_mc,stop_mc,tp_mc,rr,power_candle,resultado_A,resultado_B,tempo_trade_h,motivo_saida,versao_config`
(`resultado_*` = % líquido de custos; vazio enquanto o trade está aberto; `motivo_saida` = `A=…; B=…`,
`em_aberto`, `cancelado` ou `descontinuado`; `idade_h` = horas desde a **criação** do token; `n_wicks` = nº de
**testes de suporte**; `versao_config` = hash do `pos_runner_v0.yaml`). `dados\pos_runner_detalhe.csv` traz o resto:
resultado bruto e com custo 2×, R múltiplo, base pareada e edge sobre ela, se o alerta saiu e com que atraso, faixa do
pico, S ≥ 100k, R/S, idade desde a graduação e a máxima atingida antes da saída em % do caminho até o pico.
Os mini-gráficos ficam em `dados\pos_runner\graficos\`.

**Gestão de banca** (addendum de relatório, 2026-10-16): `dados\pos_runner_banca.csv` — uma linha por entrada real
fechada de cada ajuste (tf × saída), simulando uma banca de US$100 por ajuste (posição 5%, até 3 abertas, stop
diário −10%/3 perdas, stop semanal −20%; sinais bloqueados pela gestão aparecem como `pulado: limite/stop
diário/stop semanal`). É a MESMA tabela que a Parte A gera no backtest (`docs/pos-runner-v0/trades/`), só que com
os sinais reais. Resumo diário por ajuste sai no Telegram no mesmo horário do resumo diário do bot v0
(`resumo_diario.hora_local`).

**Limitações (leia):**
- candle não mostra a ordem dos preços dentro dele: stop e alvo no mesmo candle contam como **stop**;
- o bot só usa candle **fechado** e espera 90 s para o GeckoTerminal indexar as últimas trades; o paper entra no
  open seguinte ao sinal, e o seu clique real chega depois do alerta (no 5m isso pesa mais);
- MC em USD = preço no token de cotação × cotação/USD do fechamento horário anterior (SOL via Orca SOL/USDC) ×
  supply **atual** (queima posterior distorce um pouco o passado); com cotação **exótica** que sobe junto com o token
  (ex.: FLAME/EMBER) a máxima do 1h/4h pode distorcer (medido no Passo 0 v2);
- a data de criação vem da transação mais antiga do token (até 100 mil transações antes da migração); acima disso o
  token fica sem idade e não entra no radar;
- o radar só pega tokens **enquanto** estão com MC ≥ 300k: um runner que aconteceu com o bot desligado não entra
  depois; as chamadas ao GeckoTerminal são divididas com o v0 (`chamadas_por_ciclo`), então com muitos tokens em
  fase 2 o 5m pode atrasar um ciclo;
- custos: fee do PumpSwap por faixa de MC; Raydium CPMM e Meteora DAMM v2 com fee **ainda não confirmada** (usa 1%
  conservador), terminal 1%/perna, rede 0,0003 SOL, slippage estimado para 0,15 SOL.

---

## POS-RUNNER-V1/V2 ("regras do professor") e análise condicional

Estratégia separada (congelada, hash próprio por versão) rodando em paralelo ao v0/V0 acima — comandos,
alertas e CSVs completos em `docs/pos-runner-v1/` (`INTERPRETACOES.md`, `PROTOCOLO_VALIDACAO.md`). Só o
que é novo nesta revisão (trajetória pós-entrada + linha de base pareada, PAPER/leitura, zero chamada
nova de API — usa só candles já em cache):

- `SEM_EVIDENCIA=1` no `.env` desliga essa medição por completo (a V1/V2 continuam normais);
- `/analise [v1|v2]` no Telegram roda a análise condicional pré-registrada
  (`docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md`) — com menos de 30 sinais fechados distintos só
  responde "amostra insuficiente (n/30)";
- **o plano pré-registrado não pode ser editado depois que a 1ª análise rodar** — o bot trava o hash do
  arquivo (`meta.plano_analise_hash`) e recusa rodar de novo se o texto mudar; uma interpretação nova
  precisa de uma seção/versão nova, nunca reescrever a que já foi julgada.

**PATCH 2026-10-27 (diagnóstico McRib/ヤギ, hashes V1/V2 intactos — ver `INTERPRETACOES.md` #13/#13b):**

- candle suspeito (OHLC incoerente, divergência DexPaprika confirmada, ou salto isolado vs. o pico/os
  candles vizinhos) nunca dispara um gatilho de entrada, e nunca decide TP1/EXIT até confirmar (pelo
  DexPaprika ou pelo candle seguinte) — `pos_runner/qualidade_candle.py`;
- ao fill real da entrada, o bot responde ao alerta original com "✅ ENTRADA CONFIRMADA" (fill/stop/risco
  reais); risco real < 3% grava a tag `risco_irrealista` (nunca cancela o sinal, só registra e exclui da
  análise condicional);
- `python -m signals_mvp.scripts.auditar_trades --db dados/estado.sqlite [--versao v1|v2] [--simbolo X]`
  — auditoria SOMENTE LEITURA (não escreve no banco) dos candles de cada trade, com veredito
  LIMPO/SUSPEITO por candle;
- `python -m signals_mvp.scripts.marcar_contaminados --db dados/estado.sqlite --trade v1:6 --trade v2:2`
  — marca retroativamente (idempotente, com backup antes) trades confirmados contaminados pela
  auditoria; a tag `contaminado_candle` exclui o trade da análise condicional;
- um sinal "atrasado" num pool ainda `ativo` nunca fecha mais de cara como `perdido_offline` — o
  ciclo normal de atualização busca os candles perdidos e retoma o acompanhamento com os preços
  reais; só fica `perdido_offline` quando o pool não vai mais ser atualizado.

**PEDIDO 2026-10-27 (H8/H9, carteiras "pro"):**

- `signals_mvp/dados/carteiras_pro_papodefi.json` (fornecido pelo operador, nunca baixado) +
  `python -m signals_mvp.scripts.carregar_carteiras_pro --db dados/estado.sqlite` — valida/registra
  a lista (sha256 + `lista_versao`) e gera `carteiras_grupos.csv` (agrupamento por pessoa);
- a cada ENTRADA, e a cada hora para pools com posição aberta OU na fase runner/pullback (V1 ou V2
  — PEDIDO 2026-10-29; orçado em SNAPSHOTS/dia por `CARTEIRAS_MAX_CHAMADAS_DIA`, padrão 600/dia,
  ~22 chamadas RPC por snapshot), o bot cruza os top-20 holders do token contra a lista —
  `pr1_signals.carteiras_pro_presentes`/`n_pessoas_pro` e `pr_carteiras_snapshot`.
  `SEM_CARTEIRAS=1` desliga por completo.

**PEDIDO (PARTE 2A, FASE 3/4): sombra dos filtros + contexto/execução:**

- Candidatos que `filtrado_mc_baixo`/`filtrado_idade` barraram, ou que a V1/V2 matariam como
  `ONDA_INVALIDA` entre 96% e 99,5% de queda (a V2 já cobre 90–96%), mas que TERIAM gerado gatilho,
  viram sinais sombra (`pr_sombra`) — medição ao lado, nunca entram na banca/CSV oficiais nem em
  `/relatorio v1|v2`; aparecem só em `/analise [v1|v2]` (R médio com vs sem o filtro) e, só para a
  queda extrema, um aviso curto no Telegram sem botões. `SOMBRA_MAX_POOLS` (padrão 10) limita
  detectores sombra simultâneos; `SEM_SOMBRA=1` desliga tudo.
- `pr1_signals`/`pr2_signals`/`pr_sombra` ganharam colunas nullable de contexto/execução na ENTRADA
  (dia da semana, idade em dias, MC na entrada, volume/transações/ticket médio em 24h, tamanho da
  caixa, % do maior holder, slippage estimado de uma mão de US$10 pela liquidez do pool e o R líquido
  com esse modelo simples) — tudo com dado que o GT já tinha devolvido, zero chamada nova; nunca
  usadas por regra/filtro/tamanho/saída (o R oficial não muda). Aparecem nos CSVs
  `pos_runner_v1.csv`/`pos_runner_v2.csv` (colunas no fim).

---

## Meta do dia (`meta.txt`)

```
IA: ai, agent, gpt
GATO: cat, kitty, meow
```

Uma linha por grupo (`ROTULO: palavra, palavra`). O casamento é em **nome, ticker e descrição** do token
(maiúscula/acento não importam; `KittyAI` separa em `kitty` + `ai`; palavra curta, com menos de 4 letras, só casa
inteira; palavra maior também casa dentro de outra, ex. `agent` em `AIAgent`). Nome e ticker são avaliados
**separados** (para não fabricar uma expressão que nenhum dos dois tem). Você pode editar **com o bot rodando**: ele
recarrega e grava a `versao_meta` (hash do conteúdo, sem contar comentários) em cada linha do `sinais.csv`.

Sem nenhum casamento, o componente de narrativa dá 0 e o alerta depende dos números; por isso, com os pesos
iniciais, **um meta vazio ou que não casa praticamente não gera alertas** (os tokens continuam sendo avaliados e
logados). Medido no mercado real em 2026-10-13: tokens com bom fluxo e **sem** casamento ficaram em 42–52 pontos.

---

## Como o score funciona (0–100, tudo em `config.yaml`)

| componente | teto | do que vem |
|---|---|---|
| Narrativa | 25 | casamento com o `meta.txt` (15 pts por palavra em nome/ticker, 8 só na descrição) |
| Fluxo | 35 | volume m5 (12), aceleração (10), pressão de compra (8), compradores únicos (5) |
| Distribuição | 20 | top10 de holders (12), dispersão = compradores únicos ÷ compras (8) |
| Liquidez | 20 | nível (12), posição padrão como % da liquidez (8) |
| Penalidades | − | volume suspeito (giro vol/liq, poucas carteiras girando, compras sem nenhuma venda, ticket minúsculo), liquidez baixa, segurança `parcial`/`sem_dado` |

Dado ausente vale **0 ponto + aviso** (nunca um chute). Só alerta acima de `score.minimo_alerta` (60); **todo token
avaliado é logado e acompanhado**, enviado ou não. Uma avaliação por (pool, etiqueta): vale o **primeiro** instante
em que o gatilho dispara.

**Gatilhos (etiquetas):**

- `novo` — pool com menos de 10 min, com volume m5, nº de transações, compras, % de compras e compradores únicos acima
  dos limites do config.
- `sobrevivente20` — pool com 20–25 min, preço ≥ 40% do preço inicial e compras ainda ativas. É um gatilho
  **operacional aproximado, feito com dados de API**; **não é** o gatilho **H2 pré-registrado** do programa de pesquisa
  (que usa swaps reais decodificados — v1). O "preço inicial" é o do primeiro avistamento, e só vale se o pool foi visto
  nos primeiros 180 s de vida.

**Cortes de segurança** (falhou = descarta e loga o motivo em `descartados.csv`): honeypot, taxa de compra/venda
> 5%, contrato não verificado (EVM), LP não travada/queimada (pool v2), top10 > 30% (sem pool/par/curva/queima), flags
perigosas do GoPlus (`cannot_sell_all`, `hidden_owner`, …); Solana: mint e freeze authority, `closable`, transfer hook,
conta nascendo congelada, taxa de transferência. Mais liquidez mínima por chain e MC absurdo (> 50 M).

---

## Onde o v0 NÃO é o que parece — leia

Estes pontos foram **medidos em 2026-10-13** (ou documentados), e estão assim de propósito:

1. **A GoPlus quase nunca tem dado de token novo.** Consultei tokens com 47 s a ~12 min de vida: dado para **1 de 19
   (Solana), 1 de 19 (BSC) e 0 de 20 (Robinhood)**; e não melhorou esperando (mesmos tokens ainda ausentes aos 12 min).
   Quando o token aparece depois, tem dado. Com "sem dado = descarta", o gatilho `novo` praticamente não dispararia.
   Por isso o padrão é `seguranca.sem_dado_acao: liberar_com_aviso`: **segue, mostra `SEM DADO ⚠`, desconta pontos
   (−10) e nunca marca `ok`**. Quer o modo estrito? Mude para `descartar` (global ou por chain) — o preço é quase não
   receber sinal de token novo. Para medir se essa população era perigosa, no fim do acompanhamento o bot **reconsulta
   a GoPlus uma vez** e guarda o veredito tardio em `sinais_detalhe.csv` (`seguranca_tardia`) — sem reescrever o
   `seguranca` da hora da decisão (isso seria olhar o futuro).
2. **Solana: mint/freeze** podem vir do GeckoTerminal (token info) quando a GoPlus não tem o token; aparece como
   `ok (GT)` e fica registrado. Se qualquer fonte disser que a autoridade existe, reprova. **Top10 na Solana é `s/d`
   na v0** (não há fonte confiável via essas APIs; vira RPC na v1) — por isso vale 0 ponto de distribuição lá.
3. **Robinhood Chain: ligada.** A rede `robinhood` existe no GeckoTerminal e o DexScreener usa o slug `robinhood`
   (conferidos pela API). A GoPlus lista a chain (id `4663`) mas **devolveu um registro vazio** no token testado
   (tratado como `sem_dado`, nunca `ok`). **Confirme o slug do GMGN** (`chains.robinhood.gmgn_slug`; não dá para
   verificar sem scraping). Se a rede deixar de existir no GeckoTerminal, o bot desliga a chain sozinho e avisa.
4. **MC = FDV** quando o GeckoTerminal não tem market cap (comum em pool novo; em token de oferta fixa toda circulante
   é igual). Os MCs de +5/+15/+60 supõem oferta constante: `MC_t = MC_entrada × preço_t ÷ preço_entrada`.
5. **Curva de bonding** (`pump-fun`, `four-meme`): o GeckoTerminal reporta liquidez virtual/pequena (~US$ 2,5–3,2 k no
   início). Em `meteora-dbc` ela vem **0**; aí a liquidez é tratada como **desconhecida** (vazia no CSV, não cortada,
   com aviso `liq desconhecida`). Ajuste `liquidez_min_usd` por chain se quiser pegar curva mais cedo.
6. **Descoberta é por polling.** `new_pools` dá as ~20 mais novas por chamada (≈ 1 min de Solana): por isso a Solana
   lê 2 páginas por ciclo. Em volume muito alto algum pool pode passar batido. A **latência medida** (`latencia_s`)
   inclui esse atraso; na v0 ela é aceita (30–90 s), e **precisa ser olhada de verdade**.
7. **Rate limit do GeckoTerminal** (~30/min por IP, com resposta `429` e `retry-after: 0`, inútil): o bot usa 15/min
   no máximo, **corta o ritmo pela metade a cada 429 e volta a subir sozinho**, e prioriza "terminar o que começou"
   (candidato já disparado) antes de procurar pools novos. Num IP compartilhado/apertado o bot degrada com elegância
   (candidatos adiados aparecem no `descartados.csv` como etapa `adiado`) — veja a latência.
8. **Acompanhamento = simulação causal, otimista em alguns pontos e conservadora em outros:**
   - entrada no preço da foto da decisão; **sem slippage e sem o seu atraso** de operador. **Medido em 2026-10-16**
     nos 16 sinais do teste ao vivo de 13/10 (acompanhamento refeito contra o OHLCV real, 0 divergência numa conferência
     independente): o 1º open do minuto seguinte ficou a **~7% (mediana)** do preço da foto, e a **mais de 20% em 6 de
     16** (de −54% a +32%). Em pool de poucos minutos o `resultado_liq` é muito sensível a esse instante — leia como
     ordem de grandeza, não como o que você teria conseguido;
   - só entram candles de 1 min que **começam depois da decisão** (até ~59 s de movimento são ignorados);
   - TP e SL no **mesmo candle** ⇒ `ambiguo`, e o `resultado_liq` assume o **pior caso (SL primeiro)**;
   - stop com **gap** (candle abre abaixo do stop) sai na abertura; TP sai exatamente no nível;
   - taxas: `plano.taxa_terminal_pct` (1%) do valor negociado + `fee_rede_usd` fixo, **por perna** (entrada + cada saída);
   - `tp1_antes_sl` e `resultado_liq` valem para o prazo `plano.tempo_min` (15 min por padrão; o exemplo do handoff usa 5);
     `max`/`min` e os MCs cobrem os 60 min.
9. **Valor de compras/vendas** vem do endpoint de trades do GeckoTerminal (últimas ~300 trades); em pool muito movimentado
   cobre só os últimos instantes (marcado com `*`). Contagens e compradores únicos vêm do próprio pool e são completos.

---

## Interpretações do handoff (confirme comigo se alguma estiver errada)

1. **"Acompanhamento de enviados E descartados"** = enviados **e avaliados-mas-não-enviados** (score abaixo do mínimo): é o
   que permite medir se o score separa bons de ruins. Os tokens **cortados** (segurança, liquidez, gatilho que expirou)
   ficam em `descartados.csv`, que não tem colunas de resultado, e **não têm o preço acompanhado**. Acompanhá-los
   (para medir falso positivo do corte) é uma extensão pequena — o `tracker.py` já faz o trabalho.
2. **"Re-checar os pools acompanhados com até 60 min"**: o bot re-checa a cada ciclo só os pools cujo gatilho ainda pode
   disparar (`novo`: até 10 min; `sobrevivente20`: 20–25 min). O que aconteceu até +60 min vem de **uma** consulta ao OHLCV
   de 1 min depois que a janela fecha (MCs de +5/+15/+60, máx/mín, TP/SL) — mesma fonte, bem mais barata em chamadas.
3. **`tempo_min` do plano = 15** (o exemplo do handoff mostra 5). Mude em `plano.tempo_min` (vira nova versão).
4. **Unidades:** `max`/`min` e `mc_*` em **USD de MC** (não %); `resultado_liq` em **%**; `compras`/`vendas` =
   **contagens** do m5 (o valor em USD das compras/vendas fica no alerta e em `sinais_detalhe.csv`).
5. **Tickers sem `$`** no CSV (`token` = símbolo puro); `chain` = `solana` / `bsc` / `robinhood`.

---

## O que cada CSV tem

`sinais.csv` — **um token avaliado por linha** (enviado ou não). Colunas, nesta ordem (formato estável):

| coluna | significado |
|---|---|
| `data` | instante da decisão (UTC, ISO). Todo o score usa a foto do pool desse instante |
| `chain` | `solana` / `bsc` / `robinhood` |
| `token`, `contrato` | ticker e endereço do token |
| `etiqueta` | `novo` / `sobrevivente20` |
| `score`, `componentes_score` | 0–100 e `narr=…;fluxo=…;dist=…;liq=…;pen=…` |
| `mc`, `liq` | USD (`liq` vazio = desconhecida) |
| `vol_m5`, `acel_vol` | volume dos últimos 5 min e aceleração (vazio se pool < 5 min) |
| `compras`, `vendas` | nº de transações de compra/venda no m5 |
| `top10` | % dos 10 maiores holders sem pool/par/queima (vazio = sem dado) |
| `seguranca` | `ok` / `parcial` / `sem_dado` — **na hora da decisão** |
| `narrativa_match` | grupos do `meta.txt` que casaram (ex.: `GATO+IA`) |
| `enviado`, `operou` | 1/0: alerta enviado; você tocou `entrei` / usou `/entrei` |
| `mc_5m`, `mc_15m`, `mc_1h` | MC +5/+15/+60 min depois da decisão |
| `max`, `min` | MC máximo/mínimo (candles de 1 min) nos 60 min depois da decisão |
| `tp1_antes_sl` | `sim` / `nao` / `ambiguo` / `nenhum` (nenhum dos dois no prazo) / `pendente` (ainda acompanhando) / `sem_dado` |
| `resultado_liq` | % líquido do plano (TP1 parcial, SL, saída por tempo), com taxas |
| `latencia_s` | evento (criação do pool) → alerta (ou → decisão, se não enviado) |
| `versao_config`, `versao_meta` | hashes de 12 caracteres do `config.yaml` e do `meta.txt` vigentes |

`descartados.csv`: `data,chain,token,contrato,etapa,motivo,valor,versao_config` — `etapa` ∈ `filtro`,
`liquidez_minima`, `gatilho` (expirou sem disparar), `seguranca`, `duplicado`, `adiado` (o gatilho disparou mas não deu
para avaliar a tempo). `trades_operador.csv`: `data,chain,contrato,acao,valor,sinal_relacionado`.

Para analisar, cole `sinais.csv` (e, se quiser, `descartados.csv`/`trades_operador.csv`) num chat. **Filtre por
`versao_config`** — linhas de versões diferentes não são comparáveis.

---

## Disciplina dos dados e recalibração

- **`versao_config`** = hash do conteúdo do `config.yaml`: mudar **qualquer** número/lista = **nova versão**. O bot
  recarrega o arquivo sozinho, avisa no console/Telegram (`CONFIG: nova versão A → B`) e cada linha nova carrega a
  versão e o **plano** (TP/SL/tempo/taxas) da versão em que foi decidida. Config inválida não derruba: ele fica na
  versão anterior e avisa. Cópias legíveis ficam em `dados\config_versoes\<hash>.json`.
- **Recalibrar pesos (v3):** calibrar num período → **congelar** → **validar num período seguinte nunca visto**.
  **Nunca ajuste e avalie no mesmo dado.** Esta v0 não faz recalibração nenhuma.
- Não toque no `config.yaml` "no meio do dia" e continue comparando como se nada tivesse mudado — a versão existe
  exatamente para isso.

## Problemas comuns

| sintoma | o que fazer |
|---|---|
| `py` não é reconhecido | reinstale o Python marcando **Add python.exe to PATH**, ou troque `py -3` por `python` |
| `teste-telegram` falha | token errado, ou você não mandou `/start` para o seu bot; o chat id é só números |
| nenhum alerta | veja `sinais.csv`: os scores dos tokens que dispararam. Meta vazio/sem casamento ⇒ scores 40–50 (medido). Ajuste `meta.txt` ou `score.minimo_alerta` (vira nova versão) |
| muitos `HTTP 429` no console | normal em IP compartilhado: o ritmo se ajusta sozinho; baixe `gt.req_por_min` se quiser |
| `O bot ja esta rodando` | rode `parar.bat`; se o PC reiniciou e sobrou um pid velho, `iniciar --forcar` |
| `sinais.csv esta aberto em outro programa` | feche o Excel (ou abra uma cópia); o bot regrava no próximo ciclo |
| link do Axiom/GMGN abre página errada | ajuste `links.*` e `gmgn_slug` no `config.yaml` |
| `O relogio do PC esta ADIANTADO/ATRASADO` | sincronize a hora do Windows: a idade dos pools e a `latencia_s` dependem do relógio |
| Telegram `409 Conflict` no log | outro programa (ou um webhook) está lendo o mesmo bot; use um bot só para este programa |
| erros estranhos de banco/`database is locked` | não deixe a pasta dentro do **OneDrive/Dropbox/Google Drive** (sincronizam o SQLite no meio da escrita); use algo como `C:\bots\` |

## Estrutura

`signals_mvp/` é autocontido (não importa nada do resto do repositório): `config.yaml`, `meta.txt`, `.env.example`,
`requirements.txt`, `*.bat`, e os módulos — `geckoterminal.py`/`goplus.py` (clientes + parsers escritos contra
respostas reais), `security.py`, `triggers.py`, `metrics.py`, `scoring.py`, `narrative.py`, `tracker.py`
(acompanhamento), `engine.py` (ciclo), `storage.py` (SQLite + CSVs), `telegram.py`/`alerts.py`/`summary.py`,
`worker.py`/`supervisor.py`/`cli.py`, `selfcheck.py`/`netcheck.py` e `tests/` (stdlib `unittest`, com respostas reais
reduzidas em `tests/fixtures/`). `pos_runner/` é a hipótese POS-RUNNER-V0: `detector.py` (fases 0–3, causal),
`simulate.py`/`costs.py` (paper A/B), `candles.py`/`quotes.py` (OHLCV e USD), `live.py` (Parte B, ao vivo),
`parte_a/` (backtest sem viés, ainda não executado) e `passo0.py` (o que o detector vê nos 5 exemplos; relatórios em
`passo0_relatorio/` e `passo0_relatorio_v2/`). Testes: `py -3 -m signals_mvp selfcheck`, ou `py -3 -m unittest discover -s signals_mvp\tests -t .`

## Próximos passos

- **v1 (Solana rápida):** reaproveitar o pipeline ao vivo do repositório (stream + decoder Carbon, que já grava reservas e
  fees) para latência de segundos e métricas **por trade** — compradores únicos, uniformidade das trades, holders por
  minuto, % da liquidez. RPC: QuickNode (`H2_BACKFILL_RPC_URLS`) + Helius de fallback, com limitador e circuit breaker.
  Contar como trade só swap real decodificado (nunca "assinatura que referencia o pool"). Top10 real na Solana.
  Gatilho H2 exato, **pré-registrado**: sobrevivente aos +20 min com ≥ 20 swaps reais em 5 min.
- **v2+:** cluster de financiamento; narrativa cruzada com X / J7Tracker (oficial: j7tracker.io / @j7trackerio — nunca
  bookmarklet nem site clone); smart money com lucro realizado medido em dado novo. **Execução automática: fora de
  escopo** até os sinais terem resultado positivo comprovado no papel, e só com decisão explícita do operador.

# POS-RUNNER-V1 — Interpretações do Claude (pendentes de confirmação do operador)

Status: **PROPOSTA DE INTERPRETAÇÃO**, não uma regra fechada, até o operador confirmar cada ponto. O "PROMPT
DEFINITIVO: POS_RUNNER V1" pede explicitamente que os pontos abaixo sejam documentados para o operador
confirmar antes do gatilho valer de verdade (itens 2.6, 2.7, 2.9).

**Confirmado pelo operador em 2026-10-22** (complemento à revisão FASE 1.1): `reacao_suporte` (§1a),
exaustão/TP1 30% só no TOPO (§2), stop 2% abaixo do wick mais baixo (§3), idade como filtro estrito (§10a).
Cada seção confirmada tem sua própria marca abaixo. `VAMP_RISK` (§4) e as exclusões de `HOLDER_CONCENTRADO`
(§5) **continuam sem confirmação** — ainda são interpretação do Claude, não confirmadas pelo operador.

## 1. Gatilhos (item 2.6)

Pré-requisito comum aos 3: zona madura (Setup 1 já formado — pico ≥ 300k, queda 80–90%, fundo acima de L_bc,
consolidação ≥ 12 candles com 1 a 3 wicks de rejeição inferior), fechamento do candle do tf principal, execução
no open do candle seguinte. R = teto da caixa (maior máxima da consolidação). "Wick de rejeição inferior" =
candle cuja mínima entra na região do suporte (mesma definição do V0: mínima ≤ S × 1,10) e cujo fechamento
recupera de volta para dentro/acima da caixa — ou seja, reaproveito literalmente o conceito de "teste de
suporte" do detector V0 (`detector.py`, `Zone.tests`), só trocando os nomes para o vocabulário do prompt V1.

### (a) `reacao_suporte`
**CONFIRMADO PELO OPERADOR em 2026-10-22.**

**Interpretação:** candle verde (fechamento > abertura) cujo fechamento **fecha acima da máxima do candle do
wick** mais recente, e cuja própria mínima (ou a mínima do wick que ele reage a) está na zona `S × (1 ± 5%)`.
Concretamente: seja `w` o último wick de rejeição registrado (como teste de suporte do V0); o gatilho dispara
no primeiro candle verde depois de `w` cujo `close > high(w)`, contanto que `low(w)` esteja em `[S×0,95,
S×1,05]`. Não exige rompimento de R — é um gatilho de reação dentro da caixa, mais cedo que (b)/(c).

### (b) `power_candle_rompimento`
**Interpretação:** candle verde com amplitude (`high - low`) `>= 3 × ATR(20)` (mesmo limiar `power_atr_mult`
do V0) **e** que fecha acima de R. Sem exigência de volume (diferente de (c) — o prompt já separa os dois).

### (c) `rompimento_volume`
Literal no prompt, sem interpretação: fechamento acima de R com volume `>= 2×` a média de volume dos candles da
caixa (mesma `vol_ratio` já calculada no V0).

Os 3 são mutuamente não exclusivos num mesmo candle (ex.: um `power_candle_rompimento` pode também satisfazer
`rompimento_volume`); quando mais de um dispara no mesmo candle, o alerta registra **todos** em `gatilho`
(lista), não escolhe um.

## 2. Saídas — exaustão / pavio superior longo (item 2.9)

**CONFIRMADO PELO OPERADOR em 2026-10-22** (exaustão do TP1 e TP1 de 30% só no TOPO).

TP1 = 30% da posição, **no TOPO** (resistência anterior = `P_peak` da onda, igual ao conceito já usado no V0),
"diante de sinal de exaustão". Como o preço pode nunca negociar exatamente no nível de `P_peak`, a execução é:
quando a **máxima do candle atinge `P_peak`** (`high >= P_peak`) **e** o candle mostra exaustão, TP1 preenche em
`min(high, P_peak)` (nunca acima do nível — não persegue o preço).

**Exaustão** (qualquer uma das duas, OU):
- **power candle de exaustão**: `high - low >= 3 × ATR(20)` (mesmo limiar de (b) acima), de qualquer cor;
- **pavio superior longo**: pavio superior (`high - max(open, close)`) `>= 2 ×` o corpo (`|close - open|`); se o
  corpo for ~0 (candle doji), pavio superior `>= 60%` da amplitude total do candle.

EXIT FULL (os 70% restantes) é literal no prompt, sem interpretação: novo alerta quando um candle de 1h
**FECHAR** abaixo de S (o suporte da consolidação que gerou a entrada) — nunca pela máxima/mínima, só fechamento.

## 3. Stop (item 2.8)

**CONFIRMADO PELO OPERADOR em 2026-10-22** (stop 2% abaixo da mínima do wick mais baixo).

"2% abaixo da mínima do MENOR wick da consolidação": interpreto "menor" como **a mínima mais baixa** entre os 1
a 3 wicks de rejeição contados na caixa (o pavio que desceu mais, não o pavio visualmente mais curto) — porque o
stop precisa ficar abaixo do ponto mais testado/mais profundo, não do mais raso. Na prática isso quase sempre
coincide com S (a mínima da própria caixa), já que S é definido como a mínima da zona: `stop = S × (1 − 0,02)`.
Guardo os 1–3 wicks individualmente (não só S) para o caso raro de a mínima global da caixa não ter sido
classificada como "wick de rejeição" (ex.: um candle de queda brusca sem recuperação, que fixa S mas não é um
teste) — nesse caso o stop usa a mínima do wick de rejeição mais baixo, que pode ser ligeiramente acima de S.

Risco esperado (`(entrada − stop) / entrada`) fora de `[15%, 22%]` → tag `risco_fora_da_faixa` (nunca descarta o
sinal, só avisa).

## 4. `VAMP_RISK` (item 2.7)

**Ainda sem confirmação do operador** (confirmado em 2026-10-22: só §1a/§2/§3/§10a — ver topo do documento).

**Interpretação (heurística do Claude, via DexScreener/GeckoTerminal):** buscar por ticker (símbolo, comparação
case-insensitive, igualdade exata — não substring, para não gerar falso positivo em tickers comuns tipo "AI")
outros tokens na mesma chain com (a) data de criação mais antiga que a do candidato **e** (b) MC atual ou de
pico histórico maior que o MC atual do candidato. Se existir pelo menos um → tag `⚠️ VAMP_RISK` (nunca bloqueia
o alerta). Fonte de busca: GeckoTerminal `/search/pools?query=<ticker>` (já appendado, 1 chamada cacheável por
ticker) como primário; DexScreener só para o link/metadado do achado (confirma nome/MC), nunca como fonte de
OHLCV (a API pública dele não tem histórico, conforme já registrado no `CLAUDE.md` deste módulo). Sem resultado
de busca (erro de rede, API fora) = tag ausente, nunca um "sim" ou "não" adivinhado.

## 5. `HOLDER_CONCENTRADO` — exclusões (item 2.7)

**Ainda sem confirmação do operador** (confirmado em 2026-10-22: só §1a/§2/§3/§10a — ver topo do documento).

"Holder individual > 1,5% do supply, excluindo vaults do pool/AMM, bonding curve, contas de queima e
programas." Lista de exclusão concreta (Solana, via `getTokenLargestAccounts` + `getAccountInfo` dos top N para
achar o `owner`):

- os 2 vaults (base/quote) do(s) pool(s) já conhecidos da linhagem deste token (endereços vêm de
  `Lineage`/`pr_pools`);
- a conta/PDA da bonding curve do launchpad de origem (pump.fun/LaunchLab/DBC — endereços derivados pelo
  programa, mesmo método de `enumerate.py`/`lineage.py` já usado para achar a graduação);
- conta de queima conhecida (`1nc1nerator11111111111111111111111111111` — padrão Solana/pump.fun) e qualquer
  conta cujo `owner` seja o System Program seguida de supply zerado por burn explícito;
- qualquer conta cujo `owner` seja um id de programa conhecido (Token Program, Associated Token Program, o
  programa do próprio launchpad, o programa do DEX de graduação) — presume-se custódia operacional, não um
  holder humano.

Holder cuja conta não resolve (`getAccountInfo` falha) fica de fora da comparação só com um aviso de log — o
pool não é descartado, e se **nenhum** holder resolver a tag fica `holders_indisponivel` em vez de "não".

## 6. `dado_invalido` ao vivo (item 3.6) — faixa plausível de `L_bc`

Mesma conclusão já revisada e aceita na EMENDA do V0 (`docs/pos-runner-v0/EMENDA_QUALIDADE_DADOS_PROPOSTA.md`,
proposta, mesma lógica agora adotada para o V1 desde o início): **sem teto fixo por launchpad** — a curva do
pump.fun é fixa (medido 28–51k em 16/10/2026, ver `CLAUDE.md`), mas Meteora DBC e Raydium LaunchLab são
configuráveis por projeto; um teto pump.fun-específico penalizaria graduação legítima de DBC/LaunchLab só por
ser maior. Regras (launchpad-agnósticas, propriedades do próprio candle/pool, nunca de resultado):
- `wick_ratio_1º_candle_real = high/close >= 3,0` → `dado_invalido` (defeito de candle, já confirmado via
  `mc_auditoria.py` como defeito específico de histórico GT em DBC);
- `L_bc robusto < US$100` → `dado_invalido` (pool morto/precisão, não um teto de legitimidade).

`L_bc` robusto = `min(open, close do 1º candle real, open do 2º)` (mesmo robustecimento já revisado na EMENDA).

**Revisão da FASE 1 (2026-10-22)**, com evidência nova do operador (GeckoTerminal, checkpoint real): 547 de 917
pools Meteora DBC têm `L_bc > 500k` (alguns ~US$4bi); 47 de 132 pools pump.fun têm `L_bc < 1k`. Pedido do
operador: derivar um teto dos parâmetros de graduação de cada launchpad, não de resultado. **Pesquisado e não
encontrado**: este repositório não tem nenhum parâmetro numérico de graduação *sourced* para Raydium LaunchLab
(nunca foi pesquisado) nem para Meteora DBC (documentado como configurável por projeto); `enumerate.py`
também não captura a reserva/raise real da transação de migração on-chain — só identifica a transação. Sem
isso, um teto *preciso por launchpad* seria inventado, não derivado. Adiciono em vez disso um **teto de
sanidade único e agnóstico de launchpad**, `l_bc_ceiling_usd = US$10.000.000`: nenhuma graduação legítima por
bonding curve (de nenhum dos 3) chega perto disso, e o valor pega exatamente o cluster de centenas de
milhares a bilhões que o operador reportou, sem assumir a curva específica de nenhum launchpad. Uma precisão
maior (teto mais apertado por launchpad) exigiria pesquisa nova dos parâmetros reais de cada programa —
registrado como pendente em `docs/pos-runner-v1/STATUS_FASE1.md`.

## 7. Janela de ouro (item 2.3)

`janela_ouro_brt: ["08:30","14:00"]`, fuso fixo UTC−3 sem horário de verão (Brasil não observa DST desde 2019,
então UTC−3 é constante). Pela hora de **fechamento** do candle de entrada (não da abertura). Limites
inclusivos nos dois lados: `08:30 <= hora_fechamento_brt <= 14:00`.

## 8. Anti-lixo (item 2.4)

"Pool ainda em bonding curve" = pré-graduação — fora do universo do V1 (igual ao V0: só pools já graduados
entram). O filtro real é: pool graduado cujo MC **atual** (mais recente candle fechado) ainda está abaixo de
`min_mc_usd=100000`. Esse pool nunca gera alerta nem é promovido a watchlist, mas fica registrado como
`filtrado_mc_baixo` com `(pool, mc_atual)` e contado no resumo diário — exatamente como pedido, para o operador
ver o efeito do filtro sem virar motivo de alerta.

## 9. Modelo de execução (sync vs async) — item 3.2

O repositório inteiro (`engine.py`, `live.py`, `worker.py`, `TelegramPoller`, `LineageVerifier`) é **síncrono
com threads dedicadas** (nenhum `asyncio` em uso). A V1 mantém esse modelo: `ChainAdapter`/detector/notificador
V1 seguem o mesmo padrão de thread-por-responsabilidade-lenta (linhagem RPC, poller do Telegram) já usado no V0,
sem introduzir `asyncio` — evita duplicar infraestrutura de concorrência no mesmo processo e mantém
`KeyboardInterrupt` como único sinal de desligamento (sem `loop.add_signal_handler`, que o prompt já exclui por
ser Windows).

## 10a. Idade (item 2.2) — filtro, não atributo

**CONFIRMADO PELO OPERADOR em 2026-10-22** (idade `[2,7]` dias como filtro estrito, não atributo).

Diferente do V0 (onde a idade só separa sinal "primário" de "diagnóstico", mas o setup ainda é detectado e
registrado fora da janela), a V1 é uma estratégia de negócio nova, não um teste de hipótese estatística com
registro de primário/secundário — então trato `age_window_days=[2,7]` como **filtro real**: fora da janela, o
gatilho simplesmente não dispara alerta nem entra no paper (fica só como contagem em `filtrado_idade` no resumo
diário, mesmo espírito do `filtrado_mc_baixo`). Isso é diferente de `janela_ouro_brt` (item 2.3), que o próprio
prompt diz explicitamente que NUNCA filtra ("o alerta é SEMPRE enviado"; só rotula e prioriza a fila).

## 10b. V0 silencioso (item 0 das regras inegociáveis)

"Continua rodando em silêncio sobre os mesmos candles" = a MESMA instância de `PosRunnerLive` (V0) já em
produção continua recebendo os candles (via `offer`/`tick`), mas com todos os `alerta_*` de `LiveSettings`
efetivamente `False` quando a flag `--sem-v0` NÃO está ligada e o V1 está ativo — ou seja, "silencioso" não é um
modo novo: é o V0 de sempre com a configuração de alertas zerada, gravando só em banco/CSV para a comparação
pedida. `--sem-v0` desliga o V0 por completo (nem roda, nem grava) quando o operador quiser economizar
orçamento de chamadas.

## 11. Segunda ENTRADA no mesmo token (mint) com a primeira ainda aberta — por desenho, não erro

**Pergunta do operador (pedido de ajustes de alerta/medição, item 2): é esperado o bot alertar uma 2ª
ENTRADA no mesmo token enquanto a 1ª ainda está `aberto` em `pr1_signals`?**

Sim, é por desenho — e já estava documentado em `detector_v1.py` (linha ~27): "Uma decisão (ENTRADA) por
zona; depois dela a zona recomeça. Nova máxima acima de `P_peak` = nova onda." A chave `UNIQUE` de
`pr1_signals` é `(chain, pool, tf, evento, ts_fechamento)` — um sinal por **decisão** (candle de
fechamento), não um sinal por token. Depois de uma ENTRADA, a zona atual é descartada
(`_new_zone(i + 1)`) e o detector volta a procurar fase RUNNER → FASE2 → zona madura outra vez; se o preço
fizer uma nova máxima acima do `P_peak` anterior antes disso, começa uma **onda nova** (`_new_wave`), com
seu próprio pico/queda/zona, inteiramente independente da onda que gerou a 1ª ENTRADA. Não há nenhum
bloqueio "1 posição aberta por token" no detector — isso é responsabilidade da gestão de banca
(`bankroll_v1.py`: `max_posicoes_abertas`, compartilhado entre TODOS os tokens, não por token), que decide
se o trade entra ("pulado: limite") ou não, igual trataria 2 tokens diferentes.

Em outras palavras: múltiplas ENTRADA simultaneamente abertas no mesmo mint não são um bug de
deduplicação — são setups/wicks genuinamente diferentes (onda 1 e onda 2 do mesmo gráfico), cada um
avaliado e simulado de forma independente, exatamente como o prompt pede para qualquer par
`(pool, tf, zona)`. `token_signal_seq` (novo campo de instrumentação, mesmo pedido) só numera essa ordem
(1º sinal do token = 1, 2º = 2, ...) para facilitar agrupar por token no `/relatorio` e na análise Monte
Carlo — nunca muda a decisão de entrada/saída/tamanho.

### 11a. Correção (pedido de ajustes de alerta/medição, fase 4): o ヤギ e o McRib NÃO são o caso "nova onda"

**Achado do operador:** as 2 ENTRADA do ヤギ (`EU1MHvQv...`) e as 2 do McRib (`8idEA8Qo...`) têm o MESMO
`P_peak` (e por isso o mesmo TP1, já que `TOPO=self.peak`) — então a explicação acima ("nova máxima acima
do pico anterior = nova onda") **não se aplica** a esses dois casos. A explicação da seção 11 estava
incompleta: ela descreve só UM dos dois jeitos de ter 2 ENTRADA no mesmo mint; o ヤギ/McRib são o OUTRO
jeito, mais comum.

**O que exatamente reinicia a zona:** a própria emissão da 1ª ENTRADA. Em `detector_v1.py::_check_zone`
(linha ~207), **toda** ENTRADA é seguida, no MESMO candle de fechamento, por `self._new_zone(i + 1)` —
incondicional, não exige nova máxima nem checa o estado da onda. `_new_zone` só cria uma `Zone` nova
(zona_no+1, S/R/testes zerados) a partir do candle seguinte; ela **não chama `_new_wave`**, então
`self.peak`/`self.peak_idx` (e portanto `P_peak`/`TOPO`/TP1) continuam exatamente os mesmos da onda em
curso. Enquanto o preço não fizer nova máxima (o que trocaria de onda via `_update_wave` linha 215-218) E
não passar dos limiares de invalidação da onda (queda > `drop_max` ou mínima abaixo de `L_bc`, que
emitiriam ONDA_INVALIDA e chamariam `_new_wave` — linha 237-241), a MESMA onda continua em
`PHASE_PULLBACK`. Candle a candle, essa onda ainda viva constrói uma zona NOVA do zero (fundo → dentro →
testando, igual à 1ª vez) usando o mesmo `self.peak` como referência; se essa zona nova maturar (`armed`,
`zone_min_candles` candles com 1 a 3 wicks) e um gatilho disparar de novo (`reacao_suporte`,
`power_candle_rompimento` ou `rompimento_volume` — os mesmos 3 de sempre), dispara uma 2ª ENTRADA com o
MESMO `P_peak`/`TOPO`/TP1 da 1ª, porque o pico nunca mudou — só a zona (consolidação/suporte) é nova.

**Confirmação: é o comportamento esperado, não um bug.** A regra "uma decisão por zona; depois dela a
zona recomeça" (linha 27 do mesmo arquivo) sempre previu isso — ela só não deixava claro que o reinício
da zona NÃO depende de uma onda nova. Em termos de mercado: depois do rompimento que gerou a 1ª ENTRADA,
o preço voltou a consolidar (um novo range/suporte) SEM fazer uma máxima nova acima do pico anterior, e
rompeu esse 2º range de novo — 2 setups de reação/rompimento genuinamente distintos dentro da MESMA onda,
com o mesmo teto (pico) ainda válido. Nenhuma regra, parâmetro ou hash da V1 muda com esta investigação —
é só a explicação em texto que foi corrigida.

## 12. PEDIDO (PARTE 1 de 2) — trajetória pós-entrada + baseline pareada (`pos_runner/evidencia.py`)

Medição **AO LADO** de V1/V2 (`pr_trajetoria`/`pr_baseline`): roda depois de `_update_paper_v1`/
`_update_paper_v2`, nunca altera detecção/entrada/saída/banca/Telegram/CSV oficial. Nenhuma regra ou
hash da V1/V2 muda. Decisões de desenho não totalmente especificadas no pedido:

### 12a. Confirmação do operador (regra 9 do pedido): "2d" = idade do token

Murillo confirmou que "2d" (e, de forma geral, os limites de `age_window_days` da V1/V2) se referem à
**idade do token desde a criação on-chain** (`DetectorV1.age_days`/`criado_ts`, confirmado via
linhagem on-chain — ver seção 10a acima), **não** à idade desde a graduação (`grad_age_days`) nem a
qualquer outra âncora. Interpretação registrada aqui; não altera V1/V2 (a janela já usava
`age_days`/`criado_ts` desde a 10a). `candidatos_elegiveis` (FASE 2a) usa a MESMA âncora e a MESMA
janela (`params.age_window_days`) da versão (V1 ou V2) que gerou o sinal real.

### 12b. Baseline pareada — por que `TOPO`/`S` do controle são escalados pela razão do sinal real

`simulate_v1` precisa de um `TOPO`/`S` em preço absoluto para decidir TP1/exit_full — não existe uma
forma de simular "o mesmo risco_pct, mas sem alvo nenhum". O pedido só fixa explicitamente "mesmo
risco_pct do sinal" para o `stop`; para `TOPO`/`S` (sem os quais `simulate_v1` não roda) a interpretação
adotada foi escalar os dois pela MESMA razão preço/entrada do sinal real
(`topo_mult = topo_sinal/entry_sinal`, `s_mult = s_suporte_sinal/entry_sinal`, aplicados ao
`entry_controle`) — é a única forma de reusar `simulate_v1` sem inventar uma lógica de saída nova e sem
copiar a lógica existente, e preserva a MESMA "forma" relativa de saída em R que o sinal real teve.
Ver `evidencia.evento_controle`.

### 12c. Elegibilidade do controle ("depois de um pico, queda >= 80%, MC >= 100k")

`candidatos_elegiveis` usa, para cada candle `i`, o pico = maior `high` de QUALQUER candle anterior
(`bars[0:i]`, não só o pico da onda/zona do detector) e a queda = `1 - close[i]/pico`. Interpretação
deliberadamente mais ampla que o conceito de "onda"/"zona" do detector (que exigiria reconstruir o
estado interno do `DetectorV1` para cada candidato) — mede exatamente o texto do pedido ("depois de um
pico, queda >= 80% desde esse pico"), não a semântica de onda da V1/V2 (que, aliás, nunca é alterada
por esta medição).

### 12d. Escopo cortado nesta entrega (regra 3 do pedido — fila de evidência de baixa prioridade)

A regra 3 do pedido autoriza "1 fetch/hora" de candle novo quando faltar no cache, com teto de
créditos/DexPaprika configurável e pausa automática em 429 alto. **Esta entrega não implementa esse
fetch extra.** FASE 1/2 usam EXCLUSIVAMENTE `pr_bars` já em cache (zero chamada nova de
GeckoTerminal/DexPaprika) — o caminho normal de refresh da V1/V2 já mantém `pr_bars` atualizado para
TODO pool `ativo` independente de ter sinal aberto ou não (`_due_list` varre `pr_pools("ativo")`
inteiro), então o caso comum (pool continua `ativo` durante a janela de 72h) já funciona sem nenhum
fetch extra. O caso que o fetch extra cobriria — um pool já `encerrado`/podado antes dos 72h da
trajetória terminarem — ficou de fora porque implementá-lo corretamente exigiria reusar o pipeline de
conversão candle→MC/USD (`_usd_prefix`/`to_mc_bars`/`fill_gaps`) que hoje só existe dentro de
`_refresh_core` (o hot path **congelado** de V1/V2); duplicar essa lógica junto da medição arrisca
divergir dela silenciosamente, e refatorar `_refresh_core` para compartilhá-la contraria a regra 2
("nunca altera" o caminho oficial). Os env vars de teto/orçamento (`POS_RUNNER_429_TETO_PCT` etc., já
existentes da FASE 6) continuam válidos para esse fetch quando ele for implementado num pedido futuro;
por ora não há nenhum fetch de evidência para pausar.

### 12e. `carteiras_pro_presentes` (H8)

Coluna nullable adicionada a `pr1_signals`/`pr2_signals` (sempre `NULL` nesta entrega — a coleta da
lista de carteiras "pro" ainda não existe, fica para um pedido futuro). Mesmo padrão das colunas de
instrumentação anteriores (`ts_fechamento_candle`, `retorno_sol_dia`, etc.): não entra no hash de
`ParamsV1`/`ParamsV2`, não filtra nem altera nenhum sinal.

## 13. DIAGNÓSTICO 2026-10-27 — McRib (ENTRADA ~10:05) e ヤギ (TP1 12:07)

Investigação **somente leitura do código** pedida pelo operador (log do Telegram de 27/10). Este
container não tem acesso ao `estado.sqlite` real da VM (só existe aqui o banco de pesquisa da Parte
A, `signals_mvp/dados/pos_runner_parte_a/parte_a.sqlite` — outro banco, sem relação com os trades ao
vivo). As `SELECT`s reais pedidas pelo operador (candles brutos, `fonte_candle`, `candle_divergente`,
R nas tabelas/CSVs) **não puderam ser executadas aqui** — seguem como pendência do operador, com as
queries abaixo. O que segue é hipótese fundada em leitura de código, não confirmação de dado real.

**McRib — "entrada 44,1M" no alerta vs "STOP 440k (−0,0%)" no EXIT FULL.** O alerta ENTRADA mostra
`signal["entry_price"]` no momento em que é ENVIADO (`live.py: _entry_v1`, `entry_price:
ev.data.get("close")`) — um valor PROVISÓRIO, porque o fill real (`bars[j0].open`, o candle seguinte
ao gatilho — "Entrada no OPEN do candle seguinte ao sinal") ainda não é conhecido nesse instante
(`simulate_v1.py`, `res.entry_price = bars[j0].open`). Quando o fill real é conhecido,
`_update_paper_v1` corrige silenciosamente `pr1_signals.entry_price` (`if res.entry_price is not
None and signal["entry_price"] != res.entry_price: ...pr1_update_signal(entry_price=res.entry_price)`)
— SEM nunca corrigir/seguir o alerta ENTRADA já enviado. Isso por si só já explica a aparência de
inconsistência entre os dois alertas, **independente** de qualquer defeito de candle: são dois
preços de entrada diferentes (provisório no alerta, corrigido no EXIT FULL) do mesmo trade. Classificação:
**(b) bug de código/UX** — o cálculo e a saída estão corretos dado o valor que cada mensagem usa; o
problema é a falta de correção/retificação do alerta original.

Separadamente, um salto de ~100x entre "pico 1,4M" e "entrada 44,1M" é compatível com o defeito de
candle GeckoTerminal **já documentado** neste repositório (`qualidade_v1.py`, docstring: "GeckoTerminal
tem candle histórico defeituoso em pools Meteora DBC — picos de 1 candle, `high`/`close` até ~4e9") e
com o `CLAUDE.md` raiz ("Post-Transition Fresh Economic Discovery V0": impactos de preço Jupiter
observados de ~2,5pp e ~87,6pp). `dado_invalido` ficou 0 porque `avaliar_qualidade` (`qualidade_v1.py`)
**só examina `bars[0]`** (o primeiro candle cacheado do pool), uma única vez, na construção do
detector (`live.py: _detector_v1`) — nunca em nenhum candle seguinte. Um candle corrompido em QUALQUER
posição depois do primeiro passa batido por este gate. Classificação: **(a)+(b)** — dado real
corrompido (se confirmado) + lacuna de código no escopo do gate (que deveria, mas não consegue,
pegar exatamente esse caso).

**ヤギ — "TP1 parcial em 227k (−5,5%)" quando a regra é 30% no TOPO (2,6M) com exaustão.** Lógica
exata do gatilho (arquivo/linha): `signals_mvp/pos_runner/simulate_v1.py` linhas 147–150
(`if not tp1_done: atr = _atr(bars, j, params.atr_period); if bar.high >= topo and
_exhaustion(bar, atr, params): ...`); `_exhaustion` nas linhas 72–83; `_atr` nas linhas 61–69. Se o
candle `j` tiver `high` corrompido/inflado independentemente de `open`/`low`/`close` (mesmo defeito
Meteora DBC citado acima), **tanto** `bar.high >= topo` **quanto** `upper_wick = bar.high -
max(open,close)` ficam artificialmente grandes a partir do MESMO campo espúrio — disparando uma
"exaustão" e um TP1 falsos. O FILL do TP1 usa o preço real do candle seguinte (`exit_next_open`),
que pode estar em prejuízo — exatamente o "parcial com prejuízo rotulada TP1" relatado. Sem o candle
bruto real não há como confirmar que foi isso (vs. outra causa); a lógica em si está implementada
como especificado. Classificação condicionada: **se o candle `high` estiver mesmo corrompido, (a)+(b)**
(mesma lacuna do item anterior: nenhum gate reavalia candles depois do primeiro); **se o candle for
genuíno, (c)** — sinalização de exaustão correta dado um pico real que depois recuou.

**Consultas que o operador pode rodar no banco real (ou numa cópia), só SELECT:**

```sql
-- candles brutos em torno do candle_ts do sinal (substituir POOL/TS)
SELECT ts, o, h, l, c, v, fonte FROM pr_bars WHERE pool='<POOL>' AND tf='1h'
  ORDER BY ts;  -- filtrar visualmente pelos ts em torno do gatilho

-- preco de entrada GRAVADO vs o do alerta (coluna nova desta entrega, NULL em sinais anteriores a ela)
SELECT id, pool, symbol, status, entry_price, entry_price_alerta, stop, topo, tp1_price, exit_full_price,
  fonte_candle, ts_fechamento FROM pr1_signals WHERE symbol IN ('McRib','ヤギ') ORDER BY id;

-- conferencia cruzada DexPaprika (so grava quando ja confirmou divergencia alem da tolerancia)
SELECT * FROM pr1_dexpaprika_divergencias WHERE pool IN (
  SELECT pool FROM pr1_signals WHERE symbol IN ('McRib','ヤギ')
);
```

**Conserto proposto (NÃO aplicado — decisão do operador):** estender `avaliar_qualidade`
(`qualidade_v1.py`) para validar CADA candle novo que chega (não só `bars[0]`) — por exemplo,
consistência OHLC (`low <= open,close <= high`) e/ou o mesmo teste de `wick_ratio` já existente,
repetido a cada candle, chamado a partir do ponto em `live.py` onde cada candle novo é consumido
(mesmo `_refresh_core`/`_on_event_v1`, hoje só chama `avaliar_qualidade` 1x na construção do
detector). **Impacto no hash:** se implementado como lógica pura dentro de `qualidade_v1.py` SEM
adicionar campo novo a `ParamsV1`, o hash da V1 (`279b79ffa3f0`) **NÃO muda** (o hash é
`short_hash(ParamsV1.as_dict())`, e `as_dict()` não inclui código). Se o conserto precisar de um
limiar novo configurável (ex.: tolerância OHLC), isso É um campo novo de `ParamsV1` e o hash MUDA —
nesse caso é uma nova versão, decisão do operador, nunca automática.

**Regra de exclusão pré-declarada** adicionada a `PLANO_ANALISE_PREREGISTRADO.md` (seção "Exclusão
pré-declarada por candle/preço absurdo") e implementada em `signals_mvp/analise/condicional.py`
(`carregar_sinais_e_excluidos`/`Excluido`) — ver aquele documento para os critérios exatos. Coluna
nova `entry_price_alerta` (`pr1_signals`/`pr2_signals`, nullable, nunca sobrescrita, nunca lida por
regra/filtro/alerta/banca de V1 ou V2 — só por esta regra de exclusão) para permitir o critério 1
sem reconstruir o alerta original a partir de outra fonte.

### 13b. PATCH 2026-10-27 — qualidade de candle aplicada (operador confirmou FAÇA)

Depois do diagnóstico acima, o operador discordou de "(c) comportamento correto" para o McRib
(close de gatilho 44,1M com pico 1,4M = candle absurdo; fill ~441k colado no stop 440k = risco
~0,2% que distorce R) e confirmou que o power candle provavelmente só disparou pelo close
inflado, e que o TP1 do ヤギ (mesmo campo `high`) tem a mesma cara. Pedido explícito: aplicar o
patch de qualidade a V1 **e** V2, hashes de `ParamsV1`/`ParamsV2` intactos — confirmado:
V1 `279b79ffa3f0`, V2 `d57b4331d51d` (inalterados antes/depois; o patch é lógica pura em módulos
novos/`detector_v1.py`/`simulate_v1.py`, nenhum campo novo em `ParamsV1`/`ParamsV2`).

**`signals_mvp/pos_runner/qualidade_candle.py`** (módulo novo, config própria —
`LimiaresQualidadeCandle`, fora do hash): `motivo_suspeito(bar, vizinho_anterior_close, peak,
vizinho_seguinte_open=None, dex_divergente=False)` — `None` = confiável; motivos: `ohlc_incoerente`
(low/high inconsistentes com open/close — decisivo, nunca depende de vizinho),
`dexpaprika_divergente` (linha já confirmada em `pr1_dexpaprika_divergencias` para o candle),
`close_vs_pico` (close > 3× o pico/TOPO — pega o caso McRib isolado), `candle_isolado_vs_vizinhos`
(salto > 10× vs. o candle anterior que NÃO persiste no candle seguinte — confirma que foi um
glitch, não um movimento real), `sem_confirmacao_candle_seguinte` (salto suspeito vs. o anterior,
mas ainda sem como confirmar/descartar — não decide nada, nem a favor nem contra).

**Duas aplicações, por desenho (pedido explícito: gatilho é veto absoluto; TP1/EXIT pode
confirmar depois):**
- **Gatilho** (`detector_v1.py: DetectorV1._check_zone`): antes de consumir a zona e emitir
  ENTRADA, checa `motivo_suspeito(bar, candle_anterior.close, self.peak)` — **sem** o candle
  seguinte (regra "sem lookahead" do `CLAUDE.md`: a decisão é causal, só pode usar o que já
  fechou). Candle suspeito → `return` sem consumir a zona; a zona continua armada e um candle
  LIMPO mais tarde ainda pode disparar normalmente. **Limitação conhecida e deliberada**: o
  rastreamento de onda/pico (`_update_wave`, fora do escopo pedido — só gatilho/entrada/TP1/saída)
  continua rodando sobre o MESMO candle suspeito mesmo quando o gatilho é vetado; um candle com
  `high` corrompido ainda pode resetar a onda (nova "P_peak" falsa). Corrigir isso tocaria a
  mecânica de onda/zona do detector congelado além do que foi pedido — não feito aqui.
- **TP1/EXIT** (`simulate_v1.py: simulate_v1`, novo parâmetro opcional `candle_confiavel`, default
  `None` = todo candle confiável = saída IDENTICA a antes do patch): quem monta o callback
  (`PosRunnerLive._candle_confiavel_cb`, `live.py`) passa o candle seguinte quando ele JÁ existe
  nesta chamada (o simulador é re-simulado do zero a cada ciclo sobre os candles mais recentes —
  não é um estado novo, é a mesma janela de 1 candle de atraso que a execução no OPEN seguinte já
  usa) e consulta `pr1_dexpaprika_divergencias` (compartilhada por V1/V2 — mesmos candles do mesmo
  pool). Candle não confiável: o loop pula esse candle (nenhuma decisão de stop/TP1/exit_full, nem
  atualização de `max_high`) e tenta de novo no candle seguinte — nunca perde a posição, só atrasa.
  `_atualizar_trajetoria` (medição FASE 1, `pos_runner/evidencia.py`) usa o MESMO callback, pelos
  mesmos motivos (reflete a mesma realidade que o paper oficial). As simulações de CONTROLE da
  baseline pareada (FASE 2a) continuam sem o gate — fora do escopo pedido (gatilho/entrada/TP1/
  saída do trade REAL, não dos controles sintéticos).

**`entry_price_alerta`/"ENTRADA CONFIRMADA"** (`live.py: _confirmar_entrada`): quando o fill real é
conhecido (`res.entry_price`), manda 1x (idempotente, `pr_alert_once`) uma mensagem curta
respondendo ao alerta ENTRADA original com fill/stop/risco REAIS — nunca reescreve/edita a
mensagem original (API do Telegram não permite editar texto de forma simples aqui, e preservar o
alerta original intacto é mais auditável). `RISCO_IRREALISTA_MIN_PCT = 3.0`: risco real < 3% grava
a tag `risco_irrealista` em `tags` (idempotente) e aparece na própria mensagem de confirmação —
**nunca cancela/bloqueia o sinal**, que continua no paper normalmente (pedido explícito do
operador: "não bloqueio silencioso: registrar"). A tag alimenta a 3ª regra de exclusão em
`PLANO_ANALISE_PREREGISTRADO.md`.

**`qualidade_versao`** (`pr1_signals`/`pr2_signals`, nullable): grava `qualidade_candle.
QUALIDADE_VERSAO = "candle_v1_2026-10-27"` em todo sinal novo — permite filtrar/auditar quais
sinais já nasceram sob este gate (sinais antigos ficam `NULL`, nunca retroativo).

**`signals_mvp/scripts/auditar_trades.py`** (SOMENTE LEITURA — abre o SQLite com
`file:...?mode=ro`, nunca passa por `Storage`/migração): para cada ENTRADA de `pr1_signals`/
`pr2_signals`, imprime os candles brutos (3 antes do gatilho até 1 depois da saída), a conferência
DexPaprika quando houver, e um veredito LIMPO/SUSPEITO(motivo) por candle e por trade — usa a MESMA
`qualidade_candle.motivo_suspeito`, com o candle seguinte sempre disponível (leitura offline, com
hindsight completo). Uso: `python -m signals_mvp.scripts.auditar_trades --db dados/estado.sqlite
[--versao v1|v2] [--simbolo McRib]`.

## 14. PEDIDO 2026-10-27 — lista de carteiras "pro" (H8) carregada, validada e agrupada por pessoa

Lista fornecida pelo operador (NUNCA baixada da internet; só endereço público/`trackedWalletAddress`,
nunca chave privada) salva em `signals_mvp/dados/carteiras_pro_papodefi.json`.
`signals_mvp/pos_runner/carteiras_pro.py` valida (JSON válido, cada endereço decodifica de base58
para exatamente 32 bytes, deduplica) e `signals_mvp/scripts/carregar_carteiras_pro.py` registra o
resultado em `meta`.

**Validação (lista como entregue, 121 entradas):**

- 121 entradas → 121 válidas (todas decodificam para 32 bytes) → 121 únicas (nenhuma duplicata) —
  bate exatamente com o esperado "~121", sem diferença a reportar.
- `sha256` do arquivo: `71d6ee62a458290496f364496f33c20382ebc3db53530869478e121139b87aba`.
- `lista_versao = 1` (`carteiras_pro.LISTA_VERSAO_ATUAL`), travado em `meta` (`carteiras_pro_sha256`/
  `carteiras_pro_versao`) na 1ª execução do script na VM — mudar o arquivo depois disso é uma lista
  NOVA (`ListaAlteradaError`, `lista_versao` incrementada), nunca uma edição silenciosa.
- `alertsOn`/`emoji` nunca lidos (ignorados pelo pedido) — só `trackedWalletAddress`/`name`.

**Agrupamento por pessoa** (`carteiras_grupos.csv`, 121 linhas, colunas `endereco,nome,grupo`) —
heurística DETERMINÍSTICA (sem IA/fuzzy matching, sempre a mesma ordem de passos):

1. nome em minúsculas;
2. remove as palavras `side`, `main`, `fomo`, `new`, `multi`, `wallet` — substring, em QUALQUER
   posição (não exige separador: cobre tanto `"gake side"` quanto `"CupMain"` concatenado);
3. remove sufixo numérico final (`_N` ou dígito simples, com ou sem separador — `"dani1"`→`"dani"`,
   `"cup 3"`→`"cup"`);
4. remove qualquer caractere que não seja letra/dígito (espaço, underscore, pontuação
   remanescente) — assim `"jack duval"` e `"jackduval_2"` caem no MESMO grupo (`"jackduval"`).

Resultado: **79 pessoas distintas**, **21 grupos com mais de 1 carteira**:

```
aloh:7  dani:6  marcell:5  cup:4  doc:4  orange:4  gake:3  lunarfang:3  nyhrox:3
beanz:2  eq:2  ily:2  itai:2  jackduval:2  jijo:2  kadenox:2  loopier:2  nosa:2  ogantd:2  pxblo:2  schoen:2
```

Limitação conhecida e deliberada (literal ao pedido, sem inventar regra nova): a heurística só
remove sufixo NUMÉRICO + as 6 palavras listadas — nunca faz *stemming*/prefixo comum. Por isso
`"orangie"` (sem sufixo numérico, não é uma das 6 palavras) fica um grupo PRÓPRIO, separado de
`"orange"`/`"orange2"`/`"orange3"`/`"orange4"`, mesmo sendo provavelmente a mesma pessoa — e
`"nhyrox"` (erro de digitação real da lista) nunca agrupa com `"nyhrox"`, pelo mesmo motivo
(a heurística é literal, não corrige ortografia). `sha256` de `carteiras_grupos.csv`:
`78d88711f61d2a30538b1fe57cde15fabde8c976517c4f069d53382a3df1eace` — travado junto do `sha256` da
lista em `meta` (`carteiras_grupos_sha256`); editar o CSV à mão depois do registro também levanta
`ListaAlteradaError` (o agrupamento é imutável junto da lista).

**Contrato para H8 e qualquer H9 derivada** (a coleta de holders em si — cruzar os maiores holders
de cada token com esta lista — ainda não existe, fica para um pedido futuro): toda coluna/estatística
baseada nesta lista reporta **`n_pessoas_pro`** (grupos distintos) **além de** `n_carteiras_pro`
(endereços distintos), nunca só o 2º — 121 carteiras são só 79 pessoas, e tratar as duas contagens
como equivalentes infla artificialmente "quantas pessoas distintas" um token teve entre os maiores
holders.

## 15. PEDIDO 2026-10-27 (item 2 pós-auditoria) — coleta de snapshots de carteiras "pro" (H9)

A lista (§14) é só o pré-requisito; este item implementa a COLETA em si —
`pr_carteiras_snapshot`, `PosRunnerLive._registrar_snapshot_carteiras`/`_atualizar_carteiras_horaria`.

**Fonte dos holders — reaproveitada, zero mudança de hash**: `ChainAdapter.holders()` (já existia,
`chain_adapter.py`, usado para `holders_tag`/`HOLDER_CONCENTRADO`) ganhou o campo `top_holders:
list[tuple[owner, pct]]` (antes só guardava o `top_holder_pct` máximo, descartando a lista
resolvida) — MESMA chamada RPC (`getTokenLargestAccounts` + `getAccountInfo` por conta, já exclui
queima/programas base/vaults do pool), nenhuma chamada nova. `getTokenLargestAccounts` já devolve
no máximo 20 contas (sem paginação) — é literalmente o "top 20" pedido, sem precisar de limite extra.

**Dois momentos de snapshot:**
- **ENTRADA** (`_entry_v1`/`_entry_v2`): reusa a MESMA chamada de `adapter.holders()` que essas
  funções já fazem para `holders_tag` — zero custo extra. Preenche `pr1_signals.
  carteiras_pro_presentes` (agora guarda `n_carteiras_pro`, a CONTAGEM, não um booleano — H8 lê
  `>= 1`) e `n_pessoas_pro`; ambos `NULL` quando `holders.tag == "holders_indisponivel"` (nunca um
  0 fabricado quando o RPC falhou/não existe).
- **HORÁRIA** (`_atualizar_carteiras_horaria`, chamada dentro de `_refresh_core` depois do ciclo
  normal de GT): chamada NOVA de RPC, só para pools com **pelo menos 1 posição aberta** (V1 ou V2 —
  nunca gasta orçamento em pools sem posição), 1x por pool por hora UTC
  (`int(now // 3600)`, nunca reabre a mesma hora), orçada por `carteiras_max_chamadas_dia`
  (env `CARTEIRAS_MAX_CHAMADAS_DIA`, padrão 200/dia, contado por dia UTC corrido em
  `pr_carteiras_snapshot_count_since`). Orçamento esgotado = simplesmente não coleta nessa hora
  (nunca um erro, nunca atrasa o ciclo do GT).

**`pr_carteiras_snapshot`** (`storage.py`): `chave` (`"entrada:{versao}:{entry_id}"` ou
`"horaria:{pool}:{hora_utc}"`) é a idempotência — `INSERT OR IGNORE`, nunca duplica nem sobrescreve.
Guarda `top_holders_json` (lista completa, auditoria), `n_carteiras_pro`/`n_pessoas_pro`/`grupos_json`
(já cruzados contra `carteiras_pro.carregar_mapa_grupos()`, carregado 1x na construção do
`PosRunnerLive` — arquivo ausente = dict vazio, nunca derruba o bot). Nunca lida por regra/filtro/
alerta/banca de V1 ou V2, fora do hash de `ParamsV1`/`ParamsV2` (confirmado: `279b79ffa3f0`/
`d57b4331d51d` inalterados).

**`SEM_CARTEIRAS=1`**: desliga a coleta HORÁRIA e também o cruzamento na ENTRADA (nunca só a
tabela de snapshot — `carteiras_pro_presentes`/`n_pessoas_pro` ficam `NULL` nos sinais novos
também, mesmo reusando uma chamada "grátis").

**H9**: proposta em `PLANO_ANALISE_PREREGISTRADO.md` (`n_pessoas_pro >= 2`) — marcada PENDENTE DE
CONFIRMAÇÃO do operador antes da 1ª coleta real contar para o Holm (mesma disciplina do registro de
hipóteses: pré-registro antes da coleta que julga, nunca depois de ver o dado).

## 16. INCIDENTE 2026-10-27/28 — fila de atualização (1h) presa 30-59min (pós H9)

**Sintoma real na VM** (Telegram, conta Placidussax, 20:59-22:55 UTC-3, duas janelas de hora
distintas): dezenas de `⚠ POS-RUNNER: fila de atualizacao (1h) ainda com 1 pool(s)/tf pendente(s)
N min depois do fechamento da hora`, N subindo de ~31 a ~59 dentro da mesma hora, repetindo-se a
cada hora — sempre exatamente 1 pool/tf, nunca 0 nem >1. Timing bate com o deploy do item H9
(commit `8fd15dd`).

**Causa raiz**: `_atualizar_carteiras_horaria` (coleta horária de top-holders "pro", item H9) é uma
chamada RPC NOVA (`adapter.holders()`, até 1 + 20 chamadas sequenciais à `SolanaRpc`, cada uma
podendo levar até `max_total_wait_s` — ver docstring de `SolanaRpc.__init__`, BUG PRIORITARIO
2026-10-22 — antes de desistir) que foi colocada, dentro de `_refresh_core`, **ANTES** de
`self._schedule(pool, tf, now)`. Isso significa que qualquer lentidão/rate-limit nessa chamada
atrasava o PRÓPRIO reagendamento do `(pool, tf)` que tem posição aberta (`_due_list` só deixa de
marcar o par como "pendente" depois que `_schedule` roda) — exatamente o sinal que
`_checar_fila_atrasada` audita, e exatamente o único pool elegível (a coleta horária só roda para
pools com >= 1 posição aberta). Viola o princípio de "medição ao lado nunca afeta a operação
oficial" (`CLAUDE.md` raiz) mesmo sem alterar nenhum sinal/trade — o efeito colateral é na
cadência/alerta operacional, não na detecção.

**Conserto (mínimo, sem mudar nenhum hash/regra V1/V2)**: em `_refresh_core`
(`pos_runner/live.py`), inverteu-se a ordem — `self._schedule(...)` (ou o early-reschedule de
"faltou cotação no fim") agora roda SEMPRE antes de `_atualizar_carteiras_horaria`. A coleta de
carteiras "pro" nunca mais pode atrasar o reagendamento oficial do candle, por mais lenta que a RPC
fique. Nenhuma mudança em `SolanaRpc`/`adapter.holders()` foi necessária — o circuit-breaker
(`max_total_wait_s`) já existia e já evitava travar o bot para sempre; o bug era de ORDEM, não de
teto de espera.

**Teste de regressão**: `test_pos_runner_v1_live.py::EntradaTests::
test_hourly_carteiras_collection_runs_after_the_schedule_is_already_advanced` — substitui
`adapter.holders` por uma função que lê `self.live.sched[(pool, "1h")]["next"]` no momento exato
da chamada e confirma que já está no futuro (ou seja, `_schedule` já rodou) ANTES da RPC de
carteiras ser feita.

**Limitação conhecida (fora do escopo deste conserto)**: o `tick()` do bot ainda é síncrono/single-
thread — uma chamada de `adapter.holders()` muito lenta (pior caso teórico: ~21 × `max_total_wait_s`)
ainda bloqueia o resto do ciclo (outros pools, heartbeat, `_checar_alerta_429`) enquanto dura,
mesmo não mais atrasando o PRÓPRIO reagendamento do pool que a originou. Isso já era verdade para a
chamada de ENTRADA (pré-existente, não nova nesta entrega); mover a coleta horária para uma thread
separada ou dar-lhe um teto de espera próprio e mais curto é uma mudança maior, não feita aqui por
não ser necessária para resolver o incidente relatado (o alerta media reagendamento, não tempo de
ciclo) — fica anotado para o operador decidir se quer endurecer isso depois de observar o
comportamento real.

## 17. PEDIDO 2026-10-28 — R contaminado pelo McRib, fila de atualização idempotente, fallback por pendência

### Item 1 — R acumulado/médio contaminado (resumo diário)

**(a) onde `contaminado_candle`/`risco_irrealista` entravam e a exclusão aplicada:**

| Consumidor | Antes | Depois |
|---|---|---|
| Resumo diário (`daily_summary_v1`/`v2`, `_stats_r_de_fechados`) | recalculava `risco_pct` de `entry_price`/`stop`, sem olhar tags | pula o trade (motivo contado em `excluidos`), mostra `excluídos: N (motivo)` |
| `/relatorio` (`relatorio_semanal_v1`/`v2`) | `pnl_pct`/votos/quebras usavam TODOS os sinais da semana | mesma exclusão (1x por `id`, nunca conta 2x mesmo entrando em `rows` E `sinais_semana`), mostra `excluídos: N (motivo)` |
| `/analise` (`condicional.py: carregar_sinais_e_excluidos`) | já excluía (`_risco_irrealista`/`_contaminado_candle`, PATCH 2026-10-27) | sem mudança — já listava motivo por `entry_id` |
| CSVs (`pos_runner_v1.csv`) | linha por sinal, SEM coluna de R-múltiplo (só `risco_pct`/`resultado_liq_pct` crus) | sem mudança — é despejo bruto auditável (nunca deleta dado), a tag `contaminado_candle`/`risco_irrealista` já aparece na coluna `tags` |
| `/fechados`/`/abertos` (R realizado/não realizado individual) | mesma fórmula sem checar tag | R individual também fica `s/d` (nunca remove o trade da lista) |
| PnL da banca ($100, `pr1_bankroll_resumos`) | ledger sequencial, já executado | **sem mudança, por decisão** — ver abaixo |

**PnL da banca não foi alterado de propósito**: `BankrollStateV1`/`pr1_bankroll_trades` é um ledger
CUMULATIVO (saldo/sequência de trades já simulados), não uma média recomputável a cada chamada —
excluir um trade dele exigiria reproduzir o ledger inteiro sem ele, o que reescreveria histórico
científico já "queimado" (proibido pelo `CLAUDE.md` raiz, invariante 11, e pela decisão explícita do
operador no PATCH 2026-10-27: risco_irrealista "nunca bloqueia o sinal — continua negociando no
paper normalmente"). Além disso o PnL da banca é em **%/USD realizados** (não é uma divisão por
`risco_pct`), então o McRib não o explode do mesmo jeito que explode o R-múltiplo — ver item (b).

**(b) como se chegou a ~-561R**: `R = 100 × resultado_líquido_% / risco_%`, com
`risco_% = 100 × (1 − stop/entry_price)`. O candle contaminado (spike de ~100×, volume 0) fez o
`entry_price` registrado (fill real, `simulate_v1.py`) ficar colado a poucos pontos-base do `stop`
original — risco real medido ≈0,008% (bem abaixo do teto de 3% de `RISCO_IRREALISTA_MIN_PCT`). Um
`resultado_líquido_%` comum de stop (algo como -0,045%, já líquido de custo) dividido por um
`risco_%` de 0,008% produz `R ≈ -0,045/0,00008 ≈ -561` — a mesma fórmula que qualquer outro trade
usa, só que o denominador quase zero amplifica qualquer resultado pequeno em centenas de R. A
confirmação de que `-564,74/4 ≈ -141` (R médio informado) é consistente com 4 trades fechados na V1
onde só este domina a soma (os outros 3 somam ≈ -3,3R, plausível para trades normais) apoia esse
mecanismo — não há acesso ao banco real de produção neste container para extrair os valores exatos
linha a linha; a explicação é a fórmula + a ordem de grandeza relatada, não uma leitura direta do
SQLite da VM.

**(c) nunca calcular R com risco <3%**: `_motivo_exclusao_r` (tag) + o teto `risco_pct <
RISCO_IRREALISTA_MIN_PCT` direto em `_stats_r_de_fechados`/`_bloco_fechados`/`_bloco_abertos` — dupla
proteção: cobre tanto sinais já tagueados quanto, por segurança, qualquer sinal com risco real <3%
mesmo que a tag não tenha sido gravada por algum motivo (nunca depende SÓ da marcação manual).

**(d) marcação retroativa — manual, nunca automática**: `scripts/marcar_contaminados.py` não é
chamado por nenhuma migração/startup (confirmado via grep — só aparece em comentários/testes). É
deliberado: "só o operador que leu a auditoria decide o que marcar" (docstring do script). Comando
exato para a VM (os 3 trades já identificados na auditoria anterior):

```bash
python -m signals_mvp.scripts.marcar_contaminados --db dados/estado.sqlite \
    --trade v1:6 --trade v2:2 --trade v2:1
```

Faz backup automático (`Storage.backup_to`) ANTES de qualquer escrita, é idempotente (rodar 2x não
duplica a tag). Nuance: o McRib (V1#6/V2#2) já fica fora do R-múltiplo automaticamente pelo teto de
3% do item (c), com ou sem rodar o script — mas a ヤギ V2#1 (TP1 mal-rotulado, não necessariamente
risco baixo) só fica marcada/excluída depois de rodar o script, porque esse tipo de contaminação não
é detectável por limiar de risco. Rodar o script continua necessário para os 3, inclusive pro
registro de auditoria explícito e para a exclusão em `/analise` (H1-H8).

### Item 2 — alerta de fila atrasada agora idempotente (`_checar_fila_atrasada`)

Sintoma real: a versão anterior re-alertava a cada transição 0→≥1 DENTRO da mesma hora — como o
pendente oscilava (flapping), isso produzia ~1 Telegram a cada 1-2 min por quase 30 min seguidos.
Reescrito para no máximo 3 avisos por hora de fechamento (no teto configurável — padrão 30min —,
+60min e +120min) mais exatamente 1 mensagem "✅ ... normalizada" quando a fila esvazia de verdade
(só se algum aviso tinha saído nessa hora). Cada aviso lista, por `(pool,tf)` pendente: token, fase
do detector V1 (`_fase_label_v1`, lê `self.dets_v1`), há quanto tempo foi a última tentativa e qual
foi o último erro/fonte (`_diagnostico_pool_fila`, lê `self.sched` — campos novos `ultimo_erro`
`429|timeout|network|http|not_found|bad_json|sem_cotacao_usd|sem_cotacao_no_fim|sem_candle_novo|
erro_inesperado`, `ultima_tentativa`, `fonte` `gt|dexpaprika_fallback`, gravados em
`_refresh_safe`/`_refresh_core`/`_refresh_fallback_dexpaprika`, nunca influenciam detecção/sinal).

**Diagnóstico do travamento real**: a causa já identificada e corrigida na §16 (coleta horária de
carteiras "pro" atrasando o próprio `_schedule`) explica por que ESTE pool específico (o único com
posição aberta) ficava pendente; o novo campo `ultimo_erro` deixa visível, nas próximas ocorrências,
se a causa é 429/timeout da GeckoTerminal ou outra coisa, sem precisar adivinhar pelo log.

### Item 3 — fallback DexPaprika por pendência (`_tentar_fallback_por_pendencia`)

Independente do motivo (erro explícito do GT ou só "sem candle novo ainda"), um `(pool,"1h")`
pendente ≥ `POS_RUNNER_FALLBACK_DP_MIN` (padrão 20) minutos depois do fechamento da hora tenta o
DexPaprika uma vez (no máximo 1x por hora por pool — nunca martela a cada tick). Reaproveita
`_refresh_fallback_dexpaprika`/`_refresh_core`, que já passa pela MESMA validação de qualidade de
candle do caminho GT (`_usd_prefix`/`to_mc_bars`/`fill_gaps`) — nenhuma regra nova de qualidade.
Continua "nunca reagenda/encerra por conta própria" (o `_schedule`/alerta de fila seguem dependendo
só do GT se recuperar) — este item é sobre continuidade de dado para detecção/paper, não sobre
silenciar o alerta do item 2.

## 18. PEDIDO 2026-10-29 — ELON (fase runner) nunca tentado, flapping real, prioridade, saúde geral

### Item 1 — flapping real (alerta disparando a cada ~1min, limite de 3/h não valia)

**Causa raiz**: o estado do §17/item 2 era UM ÚNICO dict global (`self._fila_estado["avisos"]`),
zerado por completo a cada tick em que a lista de pendentes ficava vazia. Um pool que oscila
pendente/vazio a cada ciclo (ELON) apagava o histórico de avisos nessa lacuna momentânea e podia
re-alertar imediatamente — o limite de 3/hora nunca chegava a valer de verdade.

**Conserto**: estado agora é por `(pool, hora_de_fechamento)` (`self._fila_pools`) — ver §17/item 2
reescrito. "Resolvido" só com **histerese real** (`POS_RUNNER_FILA_RESOLVIDO_MIN`, padrão 10min
contínuos sem pendência, OU imediato se `self.sched` registrar uma atualização bem-sucedida desse
pool específico depois da última vez visto pendente) — nunca mais uma lacuna de 1 tick. Reincidência
genuína (resolvido e depois pendente de novo na MESMA hora) reabre um novo ciclo de até 3 avisos.
Teste que reproduz a oscilação relatada (devido/vazio a cada ~1min por ~30min):
`test_pos_runner_operational_alerts.py::FilaAtrasadaTests::
test_flapping_between_pending_and_empty_every_tick_never_spams_and_never_resolves_early`.

### Item 2 — por que ELON nunca foi tentado ("última tentativa: nunca desde que o bot subiu")

**Não foi possível ler o banco real da VM neste container** (sem acesso) — o diagnóstico abaixo
vem de leitura de código (`live.py`), não de uma query real contra `estado.sqlite`.

**Explicação consistente com o sintoma**: `self.sched` é um dict **só em memória**, nunca
persistido — zera por completo a cada reinício do processo. `self.dets_v1` (fase do detector) É
reconstruído a partir de `pr_bars` (candles já persistidos), então um pool pode legitimamente
mostrar `fase: runner` (candles antigos, de ANTES de um restart) e, ao mesmo tempo,
`ultima_tentativa: None` (nenhuma tentativa **desde o último restart**) — não é uma contradição.

Logo após um restart, **todo pool ativo fica "devido" ao mesmo tempo** (`self.sched.get(key) is
None` nunca é filtrado por `_due_list`). Com o orçamento padrão de só `chamadas_por_ciclo=3`
chamadas por ciclo e a ordem antiga (rank 0 primeiro, DEPOIS descoberta, DEPOIS rank>0, numa única
passada e um único `try` que aborta tudo que vem depois na exceção `ApiError("budget")`), bastava
haver posições abertas suficientes consumindo o orçamento inteiro, ciclo após ciclo, para que um
pool rank>0 (watchlist/runner, caso do ELON) nunca recebesse NENHUMA chamada — não é "hora sem
negociação" (esse caso já é tratado corretamente, ver abaixo), é orçamento que nunca sobrava.

**Conserto** (ver item 3 abaixo, mesma mudança resolve os 2): reserva mínima de orçamento pro
rank>0 + desempate "nunca tentado vem primeiro" dentro do mesmo rank — depois disso, nenhum pool
ativo pode ficar com ZERO chamadas para sempre.

**"Hora sem negociação" (sem inventar candle)**: já tratado corretamente por `fill_gaps()`
(`pos_runner/candles.py`) — quando o provedor não devolve candle pra um intervalo, o código
preenche com um candle **parado** (OHLC = close anterior, volume 0, `filled=True`), nunca um
movimento de preço inventado. Matematicamente esse candle não pode, por si só, disparar um
gatilho/saída novo (não cruza nenhum nível que o candle anterior já não tivesse tocado). Regra
documentada aqui por pedido explícito — nenhuma mudança de código foi necessária, o comportamento
já era o correto.

**Fallback DexPaprika de 20min registra a tentativa**: corrigido — antes, `_tentar_fallback_por_
pendencia` não gravava nada em `self.sched` independente do desfecho, então o diagnóstico do
alerta mostrava `fonte: s/d` mesmo depois do fallback ter rodado. Agora sempre grava
`ultima_tentativa`/`fonte="dexpaprika_fallback"`/`ultimo_erro` (`None` se trouxe candle,
`"dexpaprika_sem_candle_novo"` ou `"dexpaprika_falhou"` se não). Teste:
`test_dexpaprika_live_integration.py::PendenciaFallbackTests::
test_the_attempt_itself_is_always_registered_in_sched_regardless_of_outcome`.

### Item 3 — prioridade absoluta de posições abertas + fim da fome de rank>0

Posição aberta (rank 0, `_due_list`) **já tinha** e **continua tendo** prioridade absoluta — sempre
processada numa passada separada, ANTES de qualquer pool watchlist/runner. O que faltava era uma
**garantia de progresso** pro resto: `tick()` agora arma o `BudgetedHttp` em 2 fases —
1ª fase (rank==0): orçamento limitado a `chamadas_por_ciclo - reserva` (`POS_RUNNER_
RESERVA_RANK_MAIOR`, padrão 1) — rank 0 continua recebendo tudo que precisar até esse teto;
2ª fase (descoberta + rank>0): usa o que sobrou do orçamento real do ciclo (nunca mais que
`chamadas_por_ciclo` no total). Só excede o teto um caso raro (mais posições abertas no MESMO ciclo
do que `chamadas_por_ciclo - reserva` permite) atrasa 1 delas por 1 tick — nunca perdida, nunca
troca a ordem de prioridade.

Reforço complementar em `_due_list`: dentro do MESMO rank de calor, um `(pool,tf)` que nunca
recebeu nenhuma tentativa nesta sessão vai pra frente dos que já foram tentados ao menos 1x (mesmo
que há muito tempo) — nunca muda a ordem ENTRE ranks, só evita que o mesmo pool perca a disputa por
orçamento indefinidamente dentro do seu próprio rank.

Testes (`test_pos_runner_live.py::PriorityAndStarvationTests`):
`test_open_positions_are_always_serviced_before_watchlist_runner_pools`,
`test_watchlist_pools_still_get_a_chance_even_when_open_positions_alone_would_spend_the_whole_budget`,
`test_the_reserve_is_configurable_via_env`,
`test_a_never_attempted_pool_is_sorted_before_a_same_rank_pool_already_tried_before`.

### Item 4 — `scripts/saude.py`

Script somente leitura, ver seu próprio docstring para o que cobre e o comando de uso na VM. Uso:

```bash
python -m signals_mvp.scripts.saude --db dados/estado.sqlite
```

**Correção feita durante a auditoria**: o heartbeat ("💓 ... ativo", a cada `heartbeat_interval_s`,
padrão 6h) só mandava o bloco da V1 — a V2 ficava invisível no "vivo" periódico, só aparecia 1x/dia
no resumo diário. `heartbeat_text_v2` (`telegram_v1.py`) + `_phase_counts_v2`/chamada em
`_heartbeat_v1` (`live.py`) — mesma janela/gatilho do heartbeat V1, mensagem própria (nunca mistura
com a V1), só com o que é genuinamente específico da V2 (fase do detector próprio, filtros próprios)
— uptime/chamadas-por-min/429/fila já são do processo inteiro (1 só GT compartilhado) e já saem no
heartbeat V1, nunca duplicados. Desligado junto com `--sem-v2`. Testes:
`test_pos_runner_v1_live.py::HeartbeatTests::test_v2_heartbeat_fires_alongside_v1_with_its_own_counters`,
`test_v2_heartbeat_is_skipped_when_sem_v2_is_set`.

**Limitações conhecidas do `saude.py`** (documentado no próprio script, nunca escondido): créditos
DexPaprika restantes no plano, contadores do heartbeat em memória e o último ping bem-sucedido do
Healthchecks.io só existem no processo ao vivo ou no painel de um serviço externo — nunca persistidos
no SQLite. Essas linhas aparecem como "s/d" explícito, nunca um número inventado.

## PEDIDO 2026-10-29 (ajustes pós-relatório de saúde)

Nenhum destes 4 itens tocou `detector.py`/`simulate_v1.py`/`params_v1.py`/`params_v2.py` nem
qualquer regra V1/V2 — hashes seguem `279b79ffa3f0` (V1) / `d57b4331d51d` (V2).

1. **`saude.py` — log e fila**: `_agrupar_mensagens` agrupa por TEXTO EXATO da mensagem (nunca só o
   módulo), devolvendo as 5 mais frequentes de ERRO e de AVISO com contagem + 1ª/última ocorrência.
   `_secao_fila` agora nomeia (símbolo + prefixo do pool) os pools sem candle 1h novo há >2h, em vez
   de só contar.
2. **Uptime de sessão vs acumulado**: `PosRunnerLive._uptime_sessao_inicio` (em memória, zera a cada
   restart) somado ao `pr1_uptime` já persistido (nunca apagado por restart). Heartbeat V1
   (`telegram_v1.heartbeat_text`) e `saude.py` mostram os dois valores lado a lado, nunca só o
   acumulado.
3. **`scripts/backfill_evidencia.py`** (novo): preenche `pr_trajetoria`/`pr_baseline` das ENTRADAs
   V1/V2 anteriores à instrumentação (FASES 1-2), reusando as MESMAS funções puras do bot ao vivo
   (`evidencia.calcular_trajetoria`/`candidatos_elegiveis`/`sortear_controles`/`simular_controle`,
   `simulate_v1.simulate_v1`) sobre candles JÁ em `pr_bars` — zero chamada nova de rede. Só processa
   sinal cuja `versao_config_v1`/`versao_config_v2` bate com o hash ATUAL (mesma regra de
   `live.py:_update_evidencia_v1/v2`, nunca mistura versão congelada). Sem cotação SOL/USD em cache
   de processo, usa o MESMO fallback conservador de custo de 1% que o bot ao vivo já usa nessa
   situação (nenhum valor novo inventado). Quando o pool/tf não tem candle em `pr_bars`, marca a nova
   coluna `pre_instrumentacao=1` (`storage.py`, `_ensure_columns` em `pr_trajetoria`/`pr_baseline`) em
   vez de deixar a linha simplesmente ausente, distinguindo "nunca vai ter esse dado" de "ainda não
   teve tempo". Faz backup (`Storage.backup_to`) antes de qualquer escrita; idempotente. Uso:
   `python -m signals_mvp.scripts.backfill_evidencia --db dados/estado.sqlite`.
   Teste (`test_backfill_evidencia.py`) comprova: reproduz os mesmos valores de trajetória/baseline
   de uma entrada com a linha apagada (exceto `fechado`, que depende de quanto tempo real passou até
   o momento do cálculo — o bot ao vivo e o backfill rodando em momentos diferentes podem
   legitimamente diferir aqui) e de controles (a seleção de controles só roda 1x, na criação da
   linha, com os bars em cache naquele momento — reproduzir os MESMOS índices depois que mais candles
   chegaram não é garantido por desenho; o backfill garante uma baseline válida, não os mesmos
   índices); marca `pre_instrumentacao` quando não há candle em cache; nunca toca
   `pr1_signals`/`pr2_signals`; é idempotente.
4. **`saude.py` — DexPaprika**: lista as últimas 15 divergências em 24h (token, hora, campo, diff%)
   e explicita a regra que decide a tag `candle_divergente` — todo registro em
   `pr1_dexpaprika_divergencias` já excedeu a tolerância (padrão 1.0%) por construção
   (`dexpaprika_v1.comparar_candle`); a tag confirma por presença (candle_ts do sinal bate com algum
   registro já logado), sem limiar novo.

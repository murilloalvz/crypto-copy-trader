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

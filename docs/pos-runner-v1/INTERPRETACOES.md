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

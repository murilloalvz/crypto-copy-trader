# Rodada 22 — FASE A: auditoria do modelo de execução + viabilidade (só leitura)

PAPER/READ-ONLY. Nenhum código, parâmetro, detector, H1, sinal ou critério alterado. Hashes recomputados
nesta sessão e intactos (V1 `279b79ffa3f0`, V2 `d57b4331d51d`, V3 `56762db29cd6`, plano `2bc8e32a0663`).
Branch `signals-mvp`, HEAD `aaffc0e`. Nenhuma análise de desfecho foi feita.

**Limite desta sessão (fato):** o banco real (`signals_mvp/dados/estado.sqlite`) não está no checkout
(`signals_mvp/.gitignore`: `dados/`), nem a lista `carteiras_pro_papodefi.json`. Tudo que depende
deles está marcado **[VM]**, com o comando/consulta exato. As medições de rede abaixo rodaram **neste
container de nuvem** (IP diferente da VM, RPC público + GeckoTerminal gratuito): 26 chamadas RPC e
73 chamadas GT no total — nada passou pelo orçamento do bot.

Convenções: **F** = fato verificado (código/medição); **H** = hipótese/inferência. IC = Clopper-Pearson
95% exato para proporções. "n" é sempre a unidade indicada.

---

## A1. Auditoria do modelo de execução

### a) Stop

- **F** — Preenchimento **intracandle no preço do stop**: `fill = min(bar.open, stop)` quando
  `bar.low <= stop` (`pos_runner/simulate_v1.py:147-155`). Não é o fechamento nem a abertura
  seguinte. Velas de 1h (`pos_runner_v3.yaml`: `timeframes: ["1h"]`).
- **F** — Gap: se o candle **abre** abaixo do stop, preenche no `open` (pior que o stop). Se abre
  acima e a mínima cruza, preenche **exatamente no stop**, sem slippage além do custo de perna.
- **F** — Existe um R paralelo "abertura seguinte" (`r_exit_open_seguinte`, `simulate_v1.py:156-164`),
  calculado mas **nunca** usado em R oficial, H1, horizonte fixo ou carteira.
- **F** — Candle vetado pelo filtro de qualidade é **pulado inteiro**, inclusive o stop
  (`simulate_v1.py:144-146`). O veto amplo só detecta pico para cima (`qualidade_candle.py:82-94`,
  usa `max(high,open,close)`), então um candle de queda real não é vetado por vizinho; só por
  `ohlc_incoerente`.
- **F** — Stop tem prioridade sobre TP1/EXIT FULL no mesmo candle (conservador).
- **F (aritmética do modelo)** — Nos caminhos offline (replay, retro, `simular_v3_carteira`,
  `horizonte_fixo`) `sol_usd=None` ⇒ perna = 1,25% fee (teto) + 1,0% terminal + 0,2% rede + 1,0%
  slippage = **3,45%/perna** (`costs.py:56-75`). Um stop preenchido **exatamente** no nível, sem gap,
  dá `R = ((1−r)(1−0,0345)² − 1)/r`:

  | distância do stop r | R no stop limpo |
  |---|---|
  | 12% | −1,50R |
  | 12,7% | −1,47R |
  | 15% (risk_min V3) | −1,38R |
  | 22% (risk_max V3) | −1,24R |
  | 33% | −1,14R |

  **Todo stop com distância < 25,3% sai pior que −1,2R por construção, mesmo sem gap.** A faixa de
  risco de desenho da V3 é 15–22% (`pos_runner_v3.yaml`: `risk_min/risk_max`; só flag, não filtro —
  `detector_v1.py:208`), então **todo stop dentro da faixa sai < −1,2R**. A mediana −1,45R citada na
  Rodada 19 (stops ~12,7%) bate com −1,47R do modelo puro ⇒ **H**: o gap mediano é ≈0; quase todo o
  excesso além de −1R é custo modelado.
- **[VM]** Distribuição real do R nos stops (quantos < −1,2R, quantos por gap). Consulta mínima,
  somente leitura:
  ```bash
  sqlite3 -readonly signals_mvp/dados/estado.sqlite "SELECT COUNT(*), SUM(result_net/(1.0-stop/entry_price) < -1.2), SUM(result_net/(1.0-stop/entry_price) < -2.0) FROM pr3_signals WHERE evento='ENTRADA' AND status='fechado' AND reason='stop' AND (1.0-stop/entry_price) >= 0.03;"
  ```
  (repetir para `pr1_signals`/`pr2_signals`; para replay/retro, `auditoria_fidelidade_v3`/`exit_lab`
  já reportam `reason` — sem número aqui porque não há banco.)

### b) `perdido_offline` e pool encerrado/dormente

Como cada caminho trata (**F**):

| caminho | tratamento | arquivo:linha |
|---|---|---|
| H1 legado (relatório `/analise`) | **excluído** — `dif_pareada` só existe se `status=='fechado'` | `live.py:3684`; `analise/condicional.py:1054` (chamado sem `horizonte=`) |
| horizonte fixo (`pr_horizonte_fixo`) | **sem filtro de status**; série de candles termina quando o pool sai de `ativo`; restante **marcado ao último candle com volume>0** (status `marcado`) | `scripts/horizonte_fixo.py:73-115`; `exit_lab.py:146-157` (pula `volume==0` via `candles.py:305`) |
| `simular_v3_carteira` (ao_vivo) | mesmo do horizonte fixo; **some em silêncio** se os candles foram podados (`j0 is None → continue`) | `simular_v3_carteira.py:240-263` |
| poda de candles | `pr_bars` de pool `encerrado`/`rejeitado` apagados **21 dias** após `checked_ts` | `storage.py:1293-1300`, chamado a cada 1h `live.py:1498-1500` |

Achados derivados (**F**, mecanismo; magnitude **[VM]**):

1. **Posição V3 aberta não protege o pool de aposentadoria.** `_retire` (idade > 14 d da graduação)
   só checa sinais **V0** (`pr_signals`, `live.py:1082-1088`); `_retire_estagnado` só V1/V2
   (`live.py:1099-1103`); `_rotacionar_vagas` só V1/V2 e `_evidencia_pendente` só V1/V2
   (`live.py:1210-1213`, `1133`). Ao aposentar, `dets_v3` é removido (`live.py:1120`) → o sinal V3
   fica `aberto` congelado até o próximo restart, quando vira `perdido_offline`
   (`live.py:941-947`). **H**: este é o caminho provável dos 2 casos V3; confirmar com `pr_pools.motivo`.
   Para V1/V2, `_retire` (idade) também não os protege.
2. **Marcação de pool morto no último preço negociado.** Pool aposentado por "sem candle há 24h" ou
   rug com retirada de liquidez é marcado no último `close` com volume>0. **H**: direção otimista
   (preço realizável real tende a ser menor).
3. **Sobrevivência pela poda:** sinais e replays em pools encerrados há >21 d perdem os candles e
   desaparecem de `simular_v3_carteira`/replay sem contagem. **H**: os removidos são majoritariamente
   pools mortos ⇒ viés otimista nos números exploratórios recalculados depois de 21 d.

**Casos reais (PEAK ×2, WASTED ×3, V3 ×2) com o valor usado: [VM] — não listáveis aqui.** Consulta:
```bash
python -m signals_mvp.scripts.passo0e_topo_e_fechamento --db signals_mvp/dados/estado.sqlite
sqlite3 -readonly signals_mvp/dados/estado.sqlite "SELECT h.versao, s.symbol, h.horizonte, h.status, h.r_mult, h.candle_marca_ts, p.status, p.motivo FROM pr_horizonte_fixo h JOIN pr3_signals s ON h.versao='v3' AND h.origem='ao_vivo' AND h.entry_key=CAST(s.id AS TEXT) LEFT JOIN pr_pools p ON p.pool=s.pool WHERE s.status='perdido_offline';"
```
(trocar `pr3_signals`/`'v3'` por `pr1_signals`/`'v1'` e `pr2_signals`/`'v2'`; colunas conferidas
contra `storage.py:550-557`. Sinal sem linha aqui = candles já podados ou sem trajetória.)

### c) Custo

- **F** — `custo_fixo` US$0,05 (`simular_v3_carteira.py:83-95`) é um custo **adicional** em US$ por
  trade, aplicado como `custo_fixo/(tamanho_usd·risk_frac)` em R (`:557-559`). Não está documentado
  quem o pediu; a leitura no próprio código é "priority fee/tip MEV", **NÃO CONFIRMADA**.
- **F** — O que já está no R: fee de pool (teto 1,25% offline), terminal 1%, rede 0,0003 SOL/perna
  **expressa como 0,2% de 0,15 SOL fixo** (não escala com o tamanho real), slippage 1% fixo offline.
- **F** — Impacto por tamanho na carteira: `IMPACT_COEF_R × tamanho/volume_do_candle` (`:417-424`),
  linear, coeficiente 1,0 escolhido sem calibração.
- **O que falta (F, nenhum termo no código):** priority fee/Jito real; MEV/sandwich; impacto do
  tamanho real contra a reserva real do pool (o caminho estatístico usa 0,15 SOL fixo — achado P1 já
  registrado em `revisao-2026-11-10/PARTE_E`); slippage de saída em queda correlacionada; taxa de
  transferência Token-2022; aluguel de ATA (`costs.py:8`: "ATA = 0"; recuperável ao fechar a conta);
  transação falha/expirada; fee de pool real por faixa (offline sempre usa o teto).

Custo total em R (stop limpo, sem gap, sem o termo de impacto que depende do volume do candle):

| posição | stop 12% | stop 33% |
|---|---|---|
| CostModel offline (ida+volta) | 0,497R | 0,138R |
| + custo_fixo US$0,05 em US$10 | +0,042R → **0,539R** | +0,015R → **0,153R** |
| + custo_fixo US$0,05 em US$25 | +0,017R → **0,514R** | +0,006R → **0,144R** |

Ou seja, com stop de 12% ~**0,5R por trade** vai para custo modelado — antes de qualquer custo que
falta. Ao vivo, o bot usa cotação SOL/USD cacheada (`live.py:4370-4372`) ⇒ fee por faixa + slippage por
fórmula, normalmente **menor** que o offline; mas `simular_v3_carteira` recalcula as 3 origens com o
mesmo modelo offline, então a diferença −0,99R/−0,35R/+0,60R **não** vem de modelo de custo diferente.

Achado adicional (**F**): a "correção de preço por latência" de `simular_v3_carteira` **não chega ao
R**. `_montar_trade` corrige `entry_price`/`risk_frac` (`:183-189`), mas `r_72h` vem de
`calcular_r_horizonte` (`:198`), que reentra em `bars[j0].open` (`simulate_v1.py:111`). Para sinais
com `entrada_atrasada`, o R reportado é o do preço **não** corrigido, e é multiplicado depois pelo
`risk_frac` corrigido (`:559-560`). Também: o corte de horizonte inclui o candle que **começa** no
corte (`horizonte_fixo.py:132`, `b.ts <= ts_corte`) ⇒ janela efetiva ≈73h (simétrico entre origens).

### d) Admissão de pool no replay/retro (lookahead de seleção)

- **F — replay_v3**: universo = `pr_pools` com status **atual** `ativo/dormente/encerrado`
  (`avaliar_v3_retro.py:57-60`), detector rodado sobre **todos** os candles desde o 1º, **sem** o
  filtro `decision_ts >= added_ts` e `>= version_v3_start` que o ao vivo aplica (`live.py:3086-3091`).
  O pool só entrou em `pr_pools` porque, **na descoberta (depois)**, tinha MC ≥ 300k, idade ≤ 14 d e
  ganhou vaga por maior MC (`live.py:978-1011`, `1056-1078`). Todo sinal de replay **anterior à
  admissão** é condicionado a informação posterior (o pool sobreviveu e estava grande depois).
  Somado à poda de 21 d (A1b), o universo favorece sobreviventes.
- **F — retro_lote1**: a lista congelada (`pr_retro_candidatos`) é ex-ante (bloqueados por vaga
  naquele momento). Mas `exit_lab`/`simular_v3_carteira` só usam o subconjunto com
  `pr_pools.added_ts` não nulo — **admitidos depois do congelamento** (`simular_v3_carteira.py:288-290`,
  `exit_lab.py:369-372`). Os candles são truncados antes da admissão (`exit_lab.py:347-351`), mas a
  **seleção** depende de o pool ter sobrevivido até ganhar vaga. Lookahead de seleção.
- **F** — O pico (`P_peak`/TOPO) é rastreado causalmente pelo detector; não achei uso do pico futuro.
- **H**: as duas seleções acima empurram replay/retro para cima, consistente com a ordem
  retro +0,60R > replay −0,35R > ao vivo −0,99R. Não testado.

**[VM] Contagem que mede isso** (sem desfecho): nº de eventos de replay com `decision_ts < added_ts`
e nº de pools do lote 1 sem `added_ts`. O ao vivo já registra os pré-admissão em
`pr_evento_pre_admissao` (`live.py:3089-3091`).

---

## A2. Paridade replay × ao vivo — NÃO executada

**Por quê:** requer `estado.sqlite`. Divergências esperadas **por construção** (**F**), a medir sinal a sinal:

1. replay inclui sinais antes de `added_ts` e antes de `version_v3_start` (A1d);
2. sinais decididos durante reinício não viram sinal ao vivo ("replaying frozen bars never creates
   retroactive signals", `signals_mvp/CLAUDE.md`);
3. ao vivo usa divergências DexPaprika no veto de candle; offline não (`qualidade_candle.py:109-113`);
4. ao vivo descarta ENTRADA atrasada (`_late`); replay não;
5. pool aposentado com V3 aberta congela o sinal ao vivo (A1b), replay continua;
6. custo: ao vivo com SOL/USD, offline sem (A1c).

**O que falta exatamente:** (i) cópia somente leitura do banco (ou rodar na VM com `nice -n 19` fora
do horário de pico); (ii) um script de junção que, para cada `pr3_signals` ENTRADA, ache o evento de
replay com mesmo `pool` e `decision_ts`, compare `t_entrada`, `entry_price`, `stop`, R@72h, e
classifique cada evento sem par pelos motivos 1–6 usando `pr_pools.added_ts`,
`pr3_version_start`, `pr_evento_pre_admissao`, `pr1_uptime` e `pr3_filtrados`. Esse script **não**
foi escrito (Fase A = só leitura); é leve (zero rede, um passo de detector por pool admitido).

---

## A3. Placar V1/V2 pela regra pré-registrada

**Regra (F):** `docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md` — futilidade em n=15 tokens
distintos com média de `dif_pareada` < −0,5R; decisão em N=30 por (a)-(d) da Emenda 1. A Opção A
(futilidade só em N=60) vale **só para V3**; V1/V2 seguem inalteradas (`EMENDA_2026-11-10_FUTILIDADE_CAUDA_OPCAO_A.md:126-130`).

**Último número commitado (F):** ENTRADA/fechados = V1 7/4, V2 3/1 (`EMENDA_2026-11-03_CORRECAO_PASSO0E_EXIT_LAB_V3_RETRO.md:24`,
2026-11-03; contagem de sinais, não de tokens; sem IC). Nenhum doc posterior registra n de tokens com
`dif_pareada`.

**Status pela regra:** com o último n conhecido < 15 tokens, a regra não produz decisão (nem FUTIL nem
N=30) — **em coleta**. Número atual: **[VM]**
```bash
python -m signals_mvp.analise.condicional --versao v1
python -m signals_mvp.analise.condicional --versao v2
```

---

## A4. Viabilidade do backtest de cópia de carteiras (só contagens)

### a) Data de congelamento da lista (sha256 `71d6ee62a458…`)

**F** — Evidência mais antiga: commit `ac4ff4c`, **2026-10-27 19:09:46 UTC**, "PEDIDO 2026-10-27:
carrega/valida a lista de carteiras pro (H8)", que grava o sha256 completo em
`docs/pos-runner-v1/INTERPRETACOES.md:449` (121 endereços, 79 pessoas). O arquivo em si nunca foi
commitado. Data de commit é declarada pelo autor; corroboração independente: hora do push no GitHub
ou a chave `carteiras_pro_sha256` em `meta` na VM. (Nota: o clone desta sessão era raso; precisei
buscar o histórico completo para achar esse commit.)

**H, importante:** a lista foi curada por desempenho **passado**. Compras **anteriores** a
2026-10-27 estão dentro da amostra que a selecionou — servem só para descrever, nunca para testar.
Só as compras posteriores são teste justo: hoje são **20 dias** (27/10 → 16/11).

### b) Reconstrução das compras por carteira

Método (**F**, APIs já usadas no projeto, `solana_rpc.py:308-317`): `getSignaturesForAddress`
paginado (1000/página) por carteira → `getTransaction` (`jsonParsed`, **`maxSupportedTransactionVersion: 1`**)
→ compra = carteira com saldo de token ↑ e SOL/WSOL ↓ no mesmo tx (`pre/postTokenBalances`). Contar
compras não exige preço.

**Contagens por carteira/token antes/depois: [VM/arquivo]** — a lista não está aqui. A contagem barata
(só assinaturas, sem `getTransaction`) custa `ceil(N_assinaturas/1000)` chamadas por carteira; a de
compras custa 1 `getTransaction` por assinatura.

**Achado lateral (F):** `SolanaRpc.transaction()` pede `maxSupportedTransactionVersion: 0`
(`solana_rpc.py:317`). Na amostra de hoje, **1 de 15** transações de migração pump.fun era **versão 1**
e falhou com esse parâmetro (6,7%; IC95% 0,2%–31,9%). Os caminhos ao vivo de linhagem e enumeração já
usam `1` (`live.py:282`, `enumerate.py:229`); o único chamador de `transaction()` é
`lineage.account_origin` (`lineage.py:198`), sem chamador fora de testes. Logo: latente, não está
quebrando o bot hoje — mas qualquer script novo de carteiras **precisa** usar versão 1.

### c) Fonte de preço e cobertura (medido, n=15 graduações pump.fun, 11–12/11/2026)

- Pós-graduação: candles GT 1m/1h. **13/15** graduações com ≥1 candle de 1h nas 72h seguintes
  (87%; IC95% 59,5%–98,3%). Mediana de **4 candles de 1h** com negociação em 72h (de 72 possíveis;
  intervalo 0–64). GT só emite candle com trade ⇒ ausência = sem negociação, não dado faltante.
- Pré-graduação (curva de bonding): GT indexa o pool "pump-fun" em **13/15** tokens (mesmo IC acima),
  mas os candles de 1m antes da graduação são ralos: mediana **2 candles** (1–35; 7/13 com só 1 candle,
  9/13 cobrindo ≤5 min). **Conclusão:** para compras na curva, a GT não serve como fonte de preço em
  t+atraso. É preciso reconstruir on-chain (preço executado vem do próprio tx da carteira; preço em
  t+atraso exige a sequência de trades da conta da curva). Isso é caro.
- Resolução de segundos: com candle de 1m, atraso < 60 s não é resolvível; usar o open do 1º candle
  ≥ t+atraso é aproximação, não preço executável.

**Cobertura esperada (H):** ~87% das compras pós-graduação com preço GT; compras na curva com preço
confiável só via on-chain.

### d) Custo, tempo e onde rodar

- Chamadas: `Σ ceil(N_sig/1000)` + `N_tx` `getTransaction` (carteiras) + ~1 GT OHLCV 1m por token
  comprado (1000 candles/chamada ≈ 16,7 h) + para compras na curva, assinaturas+tx da conta da curva.
  Sem a lista não há como converter em número.
- Onde: **fora da VM** (PC do operador ou sessão de nuvem), SQLite **separado**, retomável
  (mesmo padrão de `parte_a cli baixar-bruto` / `OhlcvStore`, checkpoint em disco), limitador próprio
  e **chave RPC própria** (não `POS_RUNNER_RPC_URLS` nem `CARTEIRAS_RPC_URL`). RPC público tem limite
  por IP; nesta sessão usei 30/min sem 429.

### e) Placebo pareado por atividade (lição RED-COHORT)

Desenho proposto (não implementado, definido **sem** olhar desfecho):
1. Universo de placebo: compradores dos **mesmos pools** nas **mesmas janelas** (assinaturas do
   pool/curva), excluindo a lista pro, programas/PDAs e bots de alta frequência (corte de tx/dia
   fixado antes).
2. Pareamento só com features do período **pré-congelamento**: compras/dia, tamanho mediano da compra
   em SOL, idade mediana do token na compra (min desde a criação), mix de launchpad. K=3 vizinhos por
   carteira pro, com caliper, seed fixa.
3. Mesma regra de cópia, mesmo atraso, mesmo custo aplicados aos dois braços, só em compras
   **pós-congelamento**; unidade = token; descarte por confundimento se lift placebo ≥ lift pro
   (mesma regra do `PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.md` §4).
4. **Limite que o placebo não resolve:** a seleção da lista por desempenho passado. Por isso o
   período pré-congelamento só serve para parear, nunca para estimar efeito.

---

## A5. Viabilidade do holdout histórico da família gráfica

- **Lista ex-ante de todas as graduações (F):** enumeração on-chain pela conta de migração de cada
  launchpad (`pos_runner/enumerate.py:1-60`). Pega tokens mortos (não depende de indexador). Limites
  declarados: DBC com outras configs DAMM v2/v1 e LaunchLab→AMM v4 não cobertas.
- **Já existe uma lista assim (F):** `holdout_selado.json` / checkpoint
  `dados/pos_runner_parte_a/checkpoint_handoff/parte_a_2026-10-19.sqlite.gz`: **27.349 graduações**
  (pump.fun 9.075, Meteora DBC 17.861, LaunchLab 413) em 400 janelas de 30 min, **2026-08-02 → 2026-09-22**.
  Tabelas de estágio/trades **vazias** ⇒ nenhum desfecho calculado. **Mas é o holdout SELADO do
  POS-RUNNER-V0** (registro: PRE-REGISTRADA). Usá-lo para a família V1/V3 gasta esse holdout —
  **decisão do operador**, não minha.
- **Tokens nunca vistos (H, verificar [VM]):** o bot só admite pools com ≤14 d desde a graduação e a
  Parte B começou ~16/10 ⇒ qualquer graduação anterior a ~01/10/2026 não pode estar em
  `pr_pools`/retro/replay. Conferir com `SELECT MIN(grad_ts) FROM pr_pools`. Janelas candidatas
  **não seladas e não vistas**: 2026-09-22 → (mín `grad_ts` de `pr_pools`), e a semana de embargo do
  V0 (2026-07-26 → 08-02).
- **Volume (medido, F):** a conta de migração pump.fun teve **8.622** assinaturas sem erro em 145,8 h
  (2026-11-10 03:18 → 11-16 05:06) ≈ **1.419/dia**; 15/15 da amostra eram migrações (IC95% 78%–100%).
  Em ago–set (checkpoint): pump.fun ≈1.089/dia, DBC ≈2.143/dia, LaunchLab ≈50/dia.
- **Cobertura de candles:** ver A4c (87% com ≥1 candle de 1h em 72h; IC95% 59,5%–98,3%; n=15).
  A fração que vira runner (pico ≥ 300k) é **desconhecida** — é o número que decide se N=30 tokens é
  alcançável. Ela se mede com os próprios candles 1h (filtro de elegibilidade, não desfecho).
- **Custo:** por graduação, 1 `getTransaction` (pool/mint) + ~1 GT 1h (1000 candles/chamada).
  Um dia de pump.fun ≈ 1.419 RPC + 1.419 GT. Ritmo gratuito da GT não medido aqui (CLAUDE.md:
  429 com `retry-after: 0`); a 30/min seriam ~47 min de GT por dia de graduações. Referência real:
  a Parte A gastou 35.143 RPC para 1.200 janelas (`meta.rpc_calls_total`).
- **Prazo (F, CLAUDE.md):** OHLCV gratuito da GT cobre ~180 dias ⇒ janela de 02/08 começa a sair
  ~29/01/2027; o discovery do V0 (05/06) ~02/12/2026.

---

## O que mudou / não mudou

- Mudou: só este documento.
- Não mudou: código, detector, parâmetros, H1, hashes, dados históricos. Nenhum restart necessário.
- Medições de rede (fora da VM): janela pump.fun 2026-11-10 03:18 → 11-16 05:06 UTC; 15 graduações
  amostradas entre 4 e 5,5 dias atrás (seed 20261116). Só contagens foram lidas/registradas; nenhum
  preço/retorno foi calculado. Essas 15 devem ficar **fora** de qualquer holdout futuro por precaução.
- Não verificado: tudo marcado [VM]. As duas consultas SQL foram escritas contra o schema de
  `storage.py`, mas não rodadas contra o banco real.

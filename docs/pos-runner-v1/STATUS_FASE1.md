# POS-RUNNER-V1 — status da FASE 1 (PROMPT DEFINITIVO)

**V1 CONGELADA em 2026-10-22, hash `279b79ffa3f0`** (`ParamsV1.version` sobre `pos_runner_v1.yaml`, ao fim da
revisão FASE 1.1 — ver §2c). A partir deste commit, qualquer mudança de parâmetro em `pos_runner_v1.yaml`
gera um hash novo (versão nova); nunca um retune silencioso da congelada — exatamente a mesma disciplina já
usada no pré-registro do V0. A V1 ainda não teve nenhum alerta real em produção até este congelamento.

**FASE 1 concluída, ligada ao bot ao vivo e revisada em 2026-10-22, em TRÊS rodadas no mesmo dia** (ver §2 —
rodada 1 — §2b — rodada 1.1 — e §2c — complemento: confirmações, testes explícitos e congelamento).
**Fase 2 também feita** (detecção de capacidade
real de BSC/Robinhood, `capable()` continua `False` por decisão explícita — ver §3). Branch `signals-mvp`
(espelho `claude/pensive-wright-62usq8`, PR #7). PAPER / READ ONLY inalterado. Nada do V0 foi alterado em
*comportamento interno* — só aditivos no código (novas colunas/tabelas, novos parâmetros opcionais) — mas **o
`config.yaml` de produção mudou**: os 4 flags `pos_runner.alertas.*` do V0 foram para `false` (ver §2). Os 296
testes originais do V0 continuam verdes, mais 89 testes novos da V1 (**385/385** no total nesta branch).

## 1. O que está pronto, testado e LIGADO

| módulo | o que faz | testes |
|---|---|---|
| `docs/pos-runner-v1/INTERPRETACOES.md` | decide cada ponto que o prompt deixou em aberto (gatilhos, exaustão, stop, VAMP_RISK, holders, dado_invalido, idade como filtro, modelo sync) — **pendente de confirmação do operador** | — |
| `params_v1.py` + `pos_runner_v1.yaml` | config V1 versionada (hash próprio, independente do V0); teto `l_bc_ceiling_usd` novo | 5 |
| `detector_v1.py` | Setup 1 (Range/Bear Trap) + os 3 gatilhos (reação_suporte, power_candle_rompimento, rompimento_volume), reaproveitando a `Zone` do V0 | 9 |
| `simulate_v1.py` | TP1 (30% no TOPO com exaustão) + EXIT FULL (fecha abaixo de S) + stop (2% abaixo do menor wick) | 4 |
| `qualidade_v1.py` | `dado_invalido` (bloqueia): wick do 1º candle, `L_bc` abaixo do piso (US$5.000) OU acima do teto de sanidade (US$10M); `l_bc_suspeito` (tag suave, nunca bloqueia): `L_bc` < US$20.000 ou entre US$500k e o teto | 8 |
| `brt.py` | hora BRT (UTC-3 fixo) e janela de ouro (nunca filtra, só rotula) | 2 |
| `chain_adapter.py` | `ChainAdapter`/`SolanaAdapter` (descoberta, OHLCV, links com assert https://, `holders()`, `vamp_risk()`); `BscAdapter`/`RobinhoodAdapter` com detecção de capacidade real (3 passos: `/networks`→`/trending_pools`→`/ohlcv`), OHLCV funcional, aviso no Telegram 1x, sempre `capable()=False` (Fase 2, decisão explícita) | 24 |
| `bankroll_v1.py` | gestão híbrida (mão fixa US$10 < US$200 de banca, 10% acima disso) | 8 |
| `telegram_v1.py` | os 6 templates + heartbeat (startup + a cada 6h, campos expandidos na rodada 1.1) + teclado via `link_for` | 6 |
| `storage.py` (`pr1_*`) | `pr1_signals` (idempotente), `pr1_filtrados` (agora também `l_bc_suspeito`), `pr1_uptime`, `pr1_bankroll_*`; 3 CSVs | 6 |
| `live.py` (`PosRunnerLive`, integração) | V1 alimentada no MESMO `_refresh` do V0; `--sem-v0` corta de verdade o orçamento (descoberta/promoção continuam — ver §2b); `_heat` considera a V1; heartbeat no startup + periódico, com fases/fila/429; janela de ouro nunca bloqueia, idade sempre bloqueia (testes explícitos — ver §2c) | 12 |
| `worker.py` (`make_pos_runner`) | `resolve_chamadas_por_ciclo` (env `POS_RUNNER_CHAMADAS_POR_CICLO` sempre manda; padrão 8/ciclo com `--sem-v0` se o operador não setou nada); checagem de capacidade da Fase 2 no startup | 5 |

Suite inteira: `python -m unittest discover -s signals_mvp/tests -t .` → **385/385**.

## 2. Revisão de 2026-10-22 — o que a evidência do operador corrigiu

| achado | antes | depois |
|---|---|---|
| **V0 alertava por padrão** (esperado: só gravar) | `config.yaml`: `pos_runner.alertas.{watchlist,entrada,invalidado,saida}: true` | Mudados para `false` no `config.yaml` de produção — V0 só grava; a V1 é quem alerta |
| **`dado_invalido` sem teto de `L_bc`** | só floor (US$100) + wick; 547/917 pools DBC com `L_bc>500k` (até ~US$4bi) passavam | `l_bc_ceiling_usd=US$10M`, agnóstico de launchpad — **pesquisei e confirmei que este repo não tem parâmetro de graduação *sourced* para LaunchLab/DBC** (DBC é documentado como configurável por projeto; LaunchLab nunca foi pesquisado; `enumerate.py` não extrai a reserva real da migração). Por isso é um teto de **sanidade**, não uma precisão por launchpad — ver `INTERPRETACOES.md` §6 |
| **`--sem-v0` não reduzia chamada nenhuma** | só silenciava `_detector`/`_detector_fecham`; `_due_list` continuava buscando os timeframes do V0 (5m/4h) do mesmo jeito | `tfs()` agora devolve só `params_v1.timeframes` (padrão `["1h"]`) quando `sem_v0=True` |
| **`_heat` (prioridade da fila) não via a V1** | só olhava `self.dets`/`pr_signals` (V0); com `--sem-v0` todo pool ficava "sem carga" e perdia a prioridade de fase 2/trade aberto | `_heat` agora é o melhor entre `_heat_v0`/`_heat_v1` |
| **Heartbeat nunca existia** | `telegram_v1.heartbeat_text` escrito mas nunca chamado | Mensagem "💓" a cada 4h (`heartbeat_interval_s`) com uptime, pools acompanhados, chamadas/min (desde o heartbeat anterior), `dado_invalido`/`filtrado_mc_baixo` |

## 2b. Revisão de FASE 1.1 (2026-10-22, mesmo dia, nova evidência do operador)

| pedido | antes | depois |
|---|---|---|
| **Piso de `L_bc` baixo demais** — menor graduação legítima medida (pump.fun, N=8) é ~28k; 164 pools do operador têm `L_bc` entre US$14-1.000 (impossível) | `l_bc_floor_usd=US$100` deixava passar o cluster impossível inteiro | `l_bc_floor_usd=US$5.000`; teto duro US$10M mantido (como já era); wick ≥ 3,0× mantido |
| **Faixa suspeita** (nem defeito óbvio, nem limpo) | não existia | tag suave `l_bc_suspeito` (`L_bc` < US$20.000 ou entre US$500.000 e o teto) — **nunca bloqueia**: o alerta sai normalmente, com a tag no texto/CSV e contada no `pr1_filtrados`/heartbeat, para o operador conferir a mão no GeckoTerminal |
| **`--sem-v0` e a descoberta/promoção** | pedido: cortar "chamadas do V0" na descoberta/promoção também | **Não é separável**: descoberta/promoção (`_discover`/`offer`/`_promote`) é a MESMA fila de pools ativos que a V1 consome (item 0 do prompt — nunca uma descoberta separada); cortar isso mataria a V1 também, o que não foi pedido. O corte real de "chamada só do V0" já é total: `tfs()` (zero 5m/4h), `det=None`/`det_fecham=None` (zero `Detector` do V0 criado) — documentado em `live.py: tfs()` e testado (`h.live.dets == {}`) |
| **Orçamento configurável** | `pos_runner.chamadas_por_ciclo` só vinha do `config.yaml` (padrão 3) | `POS_RUNNER_CHAMADAS_POR_CICLO` (env) sempre manda quando setado; sem ele, `--sem-v0` muda o padrão para **8**/ciclo (~10/min) se o operador não escreveu nada no `config.yaml`. O backoff adaptativo em 429 (AIMD) já existia, compartilhado por toda chamada do GT (`http.py`) — nada novo construído aí |
| **Heartbeat só depois da 1ª janela, poucos campos, 4h** | esperava a 1ª janela inteira para o 1º beat; só uptime/pools/chamadas-min/2 contadores | Sai **já no 1º ciclo** (não espera a janela) e a cada **6h**; agora traz `versao_config_v1`, pools por FASE do detector (`runner`/`pullback`/`sem_fase`), fila de atualização pendente, 429 na janela, e os 4 contadores (`dado_invalido`/`l_bc_suspeito`/`filtrado_mc_baixo`/`filtrado_idade`) |

## 2c. Complemento à FASE 1.1 (2026-10-22, mesmo dia): confirmações, testes explícitos e congelamento

**Confirmações do operador** — `docs/pos-runner-v1/INTERPRETACOES.md` agora marca com data: `reacao_suporte`
(§1a), exaustão do TP1 e TP1 de 30% só no TOPO (§2), stop 2% abaixo do wick mais baixo (§3), idade `[2,7]`
dias como filtro estrito (§10a). Piso `l_bc_floor_usd=US$5.000` e teto `l_bc_ceiling_usd=US$10M` também
confirmados (sem mudança de código — já estavam assim desde a rodada 1.1, ver §2b). `VAMP_RISK` (§4) e as
exclusões de `HOLDER_CONCENTRADO` (§5) **continuam sem confirmação** — o documento agora diz isso
explicitamente em cada seção, para não dar a impressão de que tudo foi validado.

**Testes explícitos** (`test_pos_runner_v1_live.py`, para não confundir os dois conceitos):
- `JanelaDeOuroTests`: um sinal **fora** da janela de ouro (08:30–14:00 BRT) **alerta igual** (`janela_ouro`
  nunca bloqueia, item 2.3), com "fora da janela de ouro" no texto do alerta e `janela_ouro=fora_da_janela`
  no `pr1_signals`/CSV; e o caso simétrico (dentro da janela) para contraste.
- `IdadeFilterTests`: um sinal com idade fora de `[2,7]` dias (token criado ~1 dia antes da entrada, abaixo
  do mínimo de 2) **nunca alerta, nunca entra no `pr1_signals`** (paper), e incrementa `filtrado_idade` —
  confirma que idade e janela de ouro têm comportamentos OPOSTOS (uma bloqueia, a outra nunca bloqueia).

**Congelamento** — `ParamsV1().version` sobre o `pos_runner_v1.yaml` final desta revisão: hash
**`279b79ffa3f0`**. **V1 congelada em 2026-10-22, hash `279b79ffa3f0`.** `pos_runner_v1.yaml` já documenta
isso no cabeçalho. A partir de agora, qualquer mudança em `parametros:` do YAML produz um `versao_config_v1`
novo (nunca um retune silencioso) — mesma disciplina do pré-registro do V0 (`CLAUDE.md` raiz, regra de
hash). 3 testes novos (`JanelaDeOuroTests`×2, `IdadeFilterTests`×1): **385/385** na suite inteira.

## 3. O que ainda falta do PROMPT DEFINITIVO (revisão item a item)

### Fase 1 (itens que ficaram incompletos, não a Fase 2/3 do próprio prompt)
- **Item 2.3 (janela de ouro) — "prioridade na fila de envio"**: implementado o rótulo (`janela_ouro`/
  `fora_da_janela`) e que ele nunca filtra, mas **não existe uma fila de envio real** para priorizar (cada
  evento manda na hora; não há um buffer que ordene por janela de ouro quando vários disparam no mesmo
  ciclo). Pendente.
- **Item 2.7 — `mint_authority`/`freeze_authority`/`liquidez_usd`**: colunas existem no CSV/tabela,
  continuam `None` ("forward columns"). Fonte de dado nova (GoPlus ou RPC direto), não implementada.
- **Item 3.4 — "fila priorizada" explícita (pools fase 2/3 > candidatos novos > varredura geral)**: existe
  via `_heat`/`_due_list` (agora V1-aware, corrigido nesta revisão), mas não é uma fila com 3 níveis
  explícitos — é um rank numérico derivado da fase do detector. Efeito prático equivalente, forma diferente.
- **Item 3.8 — `BSCSCAN_API_KEY`/`HELIUS_API_KEY`/`COINGECKO_API_KEY`**: não adicionados ao `.env.example`
  ainda (só fazem sentido quando a Fase 2/holders EVM existirem).
- **Item 4 — template de ENTRADA**: as tags (gatilho, HOLDER_CONCENTRADO, VAMP_RISK, nao_validado,
  risco_fora_da_faixa) saem em linhas separadas depois de "Setup 1 | Gatilho", não numa única linha
  "Setup 1 | Vamp Risk" como o texto literal do prompt sugere — mesma informação, formatação ligeiramente
  diferente. Nunca revisado contra o gosto real do operador.
- **Item 6 — equivalência backtest vs. live para a V1**: existe só para o V0 (já validado antes desta
  sessão). A V1 não tem um harness de backtest/"Parte A" próprio ainda — só os testes de integração do
  `live.py` (seção `EntradaTests`/`QualityFilterTests` em `test_pos_runner_v1_live.py`). Construir uma Parte
  A para a V1 não foi pedido no prompt definitivo, mas também não existe.
- **`python -m signals_mvp teste-pos-runner`**: continua testando só o V0; não manda nenhuma mensagem de
  teste da V1 (templates/heartbeat). Não pedido explicitamente, mas seria uma extensão natural.

### Fase 2 — feita nesta revisão (2026-10-22), mantendo BSC e Robinhood desligadas por padrão
- **Network ids confirmados contra a API real do GeckoTerminal** (não mais candidatos nunca testados):
  `bsc` e `robinhood` SÃO ids reais; `bsc` teve OHLCV real confirmado (pool TartSwap/WBNB, `pancakeswap_v2`);
  o OHLCV de `robinhood` não pôde ser confirmado por rate-limit (429) durante a pesquisa — `check()` refaz essa
  confirmação de verdade, em tempo real, a cada processo (nunca memoriza o resultado da pesquisa).
- `detect_capability()` agora faz uma verificação real de 3 passos (`/networks` → `/trending_pools` → `/ohlcv`
  de um pool de amostra), em vez de só olhar `/networks` e assumir `has_ohlcv=False`.
- `_DisabledAdapter.ohlcv()` agora funciona de verdade (mesmo `OhlcvStore` da Solana, rede diferente) — só não
  é chamado pelo ciclo ao vivo enquanto `capable()` for `False`.
- `check()` manda um aviso no Telegram (1x por processo, nunca repete) quando a rede não é encontrada ou não
  tem OHLCV — antes só logava.
- `worker.py` (`_check_fase2_capabilities`, chamado 1x no startup de `make_pos_runner`) roda esse `check()`
  para BSC e Robinhood assim que o bot liga, só para registrar/avisar o estado real — nunca liga descoberta.
- 9 testes novos (`test_chain_adapter.py`): os 3 passos do probe (sucesso completo, sem rede listada, sem pool
  de amostra, OHLCV vazio), aviso no Telegram 1x (inclusive com um cliente de Telegram que lança exceção —
  nunca derruba o startup), `ohlcv()` com erro claro quando a capacidade não foi confirmada, `ohlcv()`
  delegando pro `OhlcvStore` real quando é confirmada, e que o `OhlcvStore` é construído só uma vez (não a
  cada chamada).

**Ainda não feito (decisão explícita do operador, não um esquecimento):**
- `capable()` continua `False` sempre — descoberta/holders reais de BSC/Robinhood (via API de explorer) não
  foram implementados; é só detecção de capacidade + OHLCV.
- Tag `nao_validado` para sinais fora da Solana (parâmetros calibrados na Solana) — não implementada porque
  não há sinal fora da Solana ainda (`capable()=False` garante isso).
- `BSCSCAN_API_KEY`/`HELIUS_API_KEY`/`COINGECKO_API_KEY` no `.env.example` — só fazem sentido quando a
  descoberta/holders EVM existirem de verdade.

### Fase 3 (não começada)
- Botões de feedback (👍/👎/📝), comandos `/entrei`/`/sai`/`/nota`, tabela própria, relatório semanal de
  "bons vs ruins".

## 4. Como a integração em `live.py` funciona (resumo)

Mesmo padrão que já existia para a 2ª medida da queda do V0 (`dets_fecham`/`_detector_fecham`): a V1 tem seu
próprio dicionário de detectores (`dets_v1`) alimentado **dentro do mesmo `_refresh`**, candle a candle, a
partir dos mesmos `pr_bars` — nunca uma descoberta/candle-fetch separada. Antes de criar o `DetectorV1` de um
pool, `qualidade_v1.avaliar_qualidade` decide `dado_invalido` (nunca cria o detector, conta em
`pr1_filtrados`) e o MC do primeiro candle disponível decide `filtrado_mc_baixo` (idem, mas não é definitivo —
tenta de novo se o MC crescer). `ENTRADA` grava em `pr1_signals` (idempotente), monta as tags e manda o
alerta; cada `_refresh` seguinte re-simula (`simulate_v1`) o sinal aberto e alerta TP1/EXIT FULL quando
aparecem, chamando `BankrollLedgerV1.step` só quando o trade fecha de verdade. Ao reiniciar (`_startup`), um
evento cuja decisão ficou velha demais vira `perdido_offline` em vez de alertar atrasado.

## 5. Documentos desta fase

- `docs/pos-runner-v1/INTERPRETACOES.md` — decisões sobre os pontos ambíguos, incluindo a revisão do teto de `dado_invalido` (pendente de confirmação do operador).
- `docs/pos-runner-v0/RUNBOOK_PARTE_B_WINDOWS.md` — comandos Windows, onde ficam os arquivos, como ler o CSV, heartbeat, erros comuns.

# POS-RUNNER-V1 — status da FASE 1 (PROMPT DEFINITIVO)

**FASE 1 concluída, ligada ao bot ao vivo e revisada em 2026-10-22** (revisão do operador com evidência real
encontrou 3 problemas reais — teto de `dado_invalido`, `--sem-v0` não cortava chamada nenhuma, heartbeat
nunca implementado — todos corrigidos, ver §2). Branch `signals-mvp` (espelho `claude/pensive-wright-62usq8`,
PR #7). PAPER / READ ONLY inalterado. Nada do V0 foi alterado em *comportamento interno* — só aditivos no
código (novas colunas/tabelas, novos parâmetros opcionais) — mas **o `config.yaml` de produção mudou**: os 4
flags `pos_runner.alertas.*` do V0 foram para `false` (ver §2). Os 296 testes originais do V0 continuam
verdes, mais 69 testes novos da V1 (**365/365** no total nesta branch).

## 1. O que está pronto, testado e LIGADO

| módulo | o que faz | testes |
|---|---|---|
| `docs/pos-runner-v1/INTERPRETACOES.md` | decide cada ponto que o prompt deixou em aberto (gatilhos, exaustão, stop, VAMP_RISK, holders, dado_invalido, idade como filtro, modelo sync) — **pendente de confirmação do operador** | — |
| `params_v1.py` + `pos_runner_v1.yaml` | config V1 versionada (hash próprio, independente do V0); teto `l_bc_ceiling_usd` novo | 5 |
| `detector_v1.py` | Setup 1 (Range/Bear Trap) + os 3 gatilhos (reação_suporte, power_candle_rompimento, rompimento_volume), reaproveitando a `Zone` do V0 | 9 |
| `simulate_v1.py` | TP1 (30% no TOPO com exaustão) + EXIT FULL (fecha abaixo de S) + stop (2% abaixo do menor wick) | 4 |
| `qualidade_v1.py` | `dado_invalido`: wick do 1º candle, `L_bc` abaixo do piso OU acima do teto de sanidade (novo) | 5 |
| `brt.py` | hora BRT (UTC-3 fixo) e janela de ouro (nunca filtra, só rotula) | 2 |
| `chain_adapter.py` | `ChainAdapter`/`SolanaAdapter` (descoberta, OHLCV, links com assert https://, `holders()`, `vamp_risk()`); `BscAdapter`/`RobinhoodAdapter` com detecção de capacidade real, sempre desligadas (Fase 2) | 15 |
| `bankroll_v1.py` | gestão híbrida (mão fixa US$10 < US$200 de banca, 10% acima disso) | 8 |
| `telegram_v1.py` | os 6 templates + heartbeat (novo) + teclado via `link_for` | 6 |
| `storage.py` (`pr1_*`) | `pr1_signals` (idempotente), `pr1_filtrados`, `pr1_uptime`, `pr1_bankroll_*`; 3 CSVs | 6 |
| `live.py` (`PosRunnerLive`, integração) | V1 alimentada no MESMO `_refresh` do V0; `--sem-v0` agora corta de verdade o orçamento (corrigido); `_heat` agora também considera a V1 (corrigido); heartbeat periódico (novo) | 9 |

Suite inteira: `python -m unittest discover -s signals_mvp/tests -t .` → **365/365**.

## 2. Revisão de 2026-10-22 — o que a evidência do operador corrigiu

| achado | antes | depois |
|---|---|---|
| **V0 alertava por padrão** (esperado: só gravar) | `config.yaml`: `pos_runner.alertas.{watchlist,entrada,invalidado,saida}: true` | Mudados para `false` no `config.yaml` de produção — V0 só grava; a V1 é quem alerta |
| **`dado_invalido` sem teto de `L_bc`** | só floor (US$100) + wick; 547/917 pools DBC com `L_bc>500k` (até ~US$4bi) passavam | `l_bc_ceiling_usd=US$10M`, agnóstico de launchpad — **pesquisei e confirmei que este repo não tem parâmetro de graduação *sourced* para LaunchLab/DBC** (DBC é documentado como configurável por projeto; LaunchLab nunca foi pesquisado; `enumerate.py` não extrai a reserva real da migração). Por isso é um teto de **sanidade**, não uma precisão por launchpad — ver `INTERPRETACOES.md` §6 |
| **`--sem-v0` não reduzia chamada nenhuma** | só silenciava `_detector`/`_detector_fecham`; `_due_list` continuava buscando os timeframes do V0 (5m/4h) do mesmo jeito | `tfs()` agora devolve só `params_v1.timeframes` (padrão `["1h"]`) quando `sem_v0=True` |
| **`_heat` (prioridade da fila) não via a V1** | só olhava `self.dets`/`pr_signals` (V0); com `--sem-v0` todo pool ficava "sem carga" e perdia a prioridade de fase 2/trade aberto | `_heat` agora é o melhor entre `_heat_v0`/`_heat_v1` |
| **Heartbeat nunca existia** | `telegram_v1.heartbeat_text` escrito mas nunca chamado | Mensagem "💓" a cada 4h (`heartbeat_interval_s`) com uptime, pools acompanhados, chamadas/min (desde o heartbeat anterior), `dado_invalido`/`filtrado_mc_baixo` |

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

### Fase 2 (explicitamente não começada agora, por pedido do operador — "mantendo BSC e Robinhood desligadas por padrão")
- `BscAdapter`/`RobinhoodAdapter`: descoberta, OHLCV, holders (via API de explorer) reais — hoje só
  detecção de capacidade (`/networks` do GT), sempre `capable()=False`.
- Resolver os network ids reais de BSC/Robinhood no GeckoTerminal (candidatos `("bsc","bnb_chain",
  "binance-smart-chain")`/`("robinhood",)` nunca foram confirmados contra a API real).
- Tag `nao_validado` para sinais fora da Solana (parâmetros calibrados na Solana) — não implementada
  porque não há sinal fora da Solana ainda.

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

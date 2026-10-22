# POS-RUNNER-V1 — status da FASE 1 (PROMPT DEFINITIVO)

**FASE 1 concluída e ligada ao bot ao vivo.** Branch `signals-mvp` (espelho `claude/pensive-wright-62usq8`,
PR #7). PAPER / READ ONLY inalterado. Nada do V0 foi alterado em comportamento — só aditivos (novas
colunas/tabelas no `storage.py`, novos campos opcionais em `config.Paths`/`PosRunnerLive.__init__`); os 296
testes originais do V0 continuam verdes, mais 64 testes novos da V1 (360 no total nesta branch).

## O que está pronto, testado e LIGADO

| módulo | o que faz | testes |
|---|---|---|
| `docs/pos-runner-v1/INTERPRETACOES.md` | decide cada ponto que o prompt deixou em aberto (gatilhos, exaustão, stop, VAMP_RISK, holders, dado_invalido, idade como filtro, modelo sync) | — |
| `params_v1.py` + `pos_runner_v1.yaml` | config V1 versionada (hash próprio, independente do V0) | 4 |
| `detector_v1.py` | Setup 1 (Range/Bear Trap) + os 3 gatilhos (reação_suporte, power_candle_rompimento, rompimento_volume), reaproveitando a `Zone` do V0 | 9 |
| `simulate_v1.py` | TP1 (30% no TOPO com exaustão) + EXIT FULL (fecha abaixo de S) + stop (2% abaixo do menor wick) | 4 |
| `qualidade_v1.py` | `dado_invalido` (wick do 1º candle ou L_bc robusto abaixo do piso) — mesma conclusão já revisada na EMENDA do V0, mas nativa da V1 desde o 1º congelamento | 4 |
| `brt.py` | hora BRT (UTC-3 fixo) e janela de ouro (nunca filtra, só rotula) | 2 |
| `chain_adapter.py` | `ChainAdapter`/`SolanaAdapter` (descoberta, OHLCV, links com assert https://, `holders()` com exclusão de vaults/programas/queima, `vamp_risk()`); `BscAdapter`/`RobinhoodAdapter` com detecção de capacidade real (sempre `capable()=False` — Fase 2) | 15 |
| `bankroll_v1.py` | gestão híbrida (mão fixa US$10 < US$200 de banca, 10% acima disso), mesmo padrão de pausa diária/semanal do V0 | 8 |
| `telegram_v1.py` | os 6 templates (ENTRADA no formato exato do operador, TP1, EXIT FULL, INVALIDADO, WATCHLIST, RESUMO) + teclado via `link_for` | 6 |
| `storage.py` (`pr1_*`) | `pr1_signals` (idempotente pela UNIQUE chain+pool+tf+evento+ts_fechamento), `pr1_filtrados`, `pr1_uptime`, `pr1_bankroll_*`; 3 CSVs novos | 6 |
| `live.py` (`PosRunnerLive`, integração) | `_detector_v1`/`_on_event_v1`/`_entry_v1`/`_update_paper_v1`/`_update_bankroll_v1` alimentados no MESMO `_refresh` do V0, mesmos candles (`pr_bars`); `--sem-v0` via env `POS_RUNNER_SEM_V0`; `shutdown()` fecha a sessão de uptime | 6 |

Suite inteira: `python -m unittest discover -s signals_mvp/tests -t .` → **360/360**.

## Como a integração funciona (resumo do que foi aplicado em `live.py`)

Mesmo padrão que já existia para a 2ª medida da queda do V0 (`dets_fecham`/`_detector_fecham`): a V1 tem seu
próprio dicionário de detectores (`dets_v1`) alimentado **dentro do mesmo `_refresh`**, candle a candle, a
partir dos mesmos `pr_bars` — nunca uma descoberta/candle-fetch separada. Antes de criar o `DetectorV1` de um
pool, `qualidade_v1.avaliar_qualidade` decide `dado_invalido` (nunca cria o detector, conta em
`pr1_filtrados`) e o MC do primeiro candle disponível decide `filtrado_mc_baixo` (idem, mas não é definitivo —
tenta de novo se o MC crescer). `ENTRADA` grava em `pr1_signals` (idempotente), monta as tags
(`risco_fora_da_faixa`, `HOLDER_CONCENTRADO`/`holders_indisponivel` via `adapter.holders`, `VAMP_RISK` via
`adapter.vamp_risk`) e manda o alerta; cada `_refresh` seguinte re-simula (`simulate_v1`) o sinal aberto e
alerta TP1/EXIT FULL quando aparecem, chamando `BankrollLedgerV1.step` só quando o trade fecha de verdade.
`ONDA_INVALIDA`/`WATCHLIST` mandam `invalidado_text`/`watchlist_text`. Ao reiniciar (`_startup`), um evento
cuja decisão ficou velha demais (processo desligado/hibernado) vira `perdido_offline` em vez de alertar
atrasado; o resumo diário da V1 (`telegram_v1.resumo_diario_text`) sai junto com o resumo do V0.

`PosRunnerLive` ganhou parâmetros novos, todos com default seguro (nenhum chamador existente quebra):
`rpc` (para `adapter.holders`), `sem_v0` (desliga o V0 por completo), `terminal`/`chain_name` (Axiom/GMGN e
"Solana" nos templates). `worker.py` já passa tudo isso (`rpc` reaproveitado da mesma instância que alimenta
`LineageVerifier`, `sem_v0` lido do env `POS_RUNNER_SEM_V0`) e chama `live.shutdown(now)` no desligamento
limpo.

## O que ainda falta (fora do escopo desta FASE 1 — itens explicitamente adiados)

- **`liquidez_usd`/`mint_authority`/`freeze_authority`**: colunas já existem no CSV/tabela, continuam
  `None` ("forward columns", igual ao Bloco 1 original pedia) — preencher isso é uma fonte de dado nova
  (GoPlus ou RPC direto), não decidida ainda.
- **BSC/Robinhood (Fase 2)**: `BscAdapter`/`RobinhoodAdapter` já detectam capacidade real via `/networks`
  do GT, mas ficam `capable()=False` até a Fase 2 implementar descoberta/OHLCV/holders próprios.
- **Botões de feedback (Fase 3)**: `/entrei`, `/sai`, `/nota`, relatório semanal — não começado.
- **`--sem-v0` como flag de CLI** (em vez de variável de ambiente `POS_RUNNER_SEM_V0`): funcionalmente
  idêntico, só não tem a sintaxe literal `--sem-v0` na linha de comando; documentado no RUNBOOK.

## Documentos desta fase

- `docs/pos-runner-v1/INTERPRETACOES.md` — decisões sobre os pontos ambíguos (pendente de confirmação do operador).
- `docs/pos-runner-v0/RUNBOOK_PARTE_B_WINDOWS.md` — comandos Windows, onde ficam os arquivos, como ler o CSV, erros comuns.

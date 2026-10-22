# POS-RUNNER-V1 — status da FASE 1 (PROMPT DEFINITIVO)

Branch `signals-mvp` (espelho `claude/pensive-wright-62usq8`, PR #7). PAPER / READ ONLY inalterado. Nada do V0
foi tocado além de aditivos (novas colunas/tabelas no `storage.py`, novos campos em `config.Paths`) — os 296
testes originais do V0 continuam verdes, mais 58 testes novos da V1 (354 no total nesta branch).

## O que está pronto e testado (independente, sem tocar `live.py`)

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
| `storage.py` (pr1_\*) | tabelas `pr1_signals` (idempotente pela UNIQUE chain+pool+tf+evento+ts_fechamento), `pr1_filtrados`, `pr1_uptime`; CSVs `pos_runner_v1.csv`/`pos_runner_v1_filtrados.csv` | 6 |

Tudo acima é testado isoladamente (fakes, sem rede) e **pronto para ser ligado**.

## O que FALTA (a integração em si — ainda não aplicada, de propósito)

`live.py` (`PosRunnerLive`) hoje só conhece o V0. A integração é **aditiva**, no exato padrão que já existe
para a 2ª medida da queda do V0 (`dets_fecham`/`_detector_fecham`/`_on_event_fecham`, alimentados dentro de
`_refresh` junto com o detector primário, candle a candle, do mesmo `pr_bars`):

1. `__init__`: `self.params_v1 = load_params_v1()`, `self.adapter = SolanaAdapter(self.http, ctx, self.ohlcv, rpc, links)`,
   `self.dets_v1: dict[(pool,tf), DetectorV1] = {}`, `self._bankroll_v1: dict[str, BankrollLedgerV1] = {}`,
   `self.version_v1 = self.params_v1.version`, `self.version_v1_start` (mesmo padrão de `pr_version_start`, chave
   própria `pr1_versao_inicio:<hash>`), `self._uptime_id = self.storage.pr1_uptime_start(now)` no 1º ciclo.
2. `_refresh`: depois de `det_fecham = self._detector_fecham(...)`, acrescentar `det_v1 = self._detector_v1(row, tf, now)`;
   depois do laço de `det_fecham.update(b)`, o laço equivalente de `det_v1.update(b)` → `self._on_event_v1(row, tf, det_v1, ev, now)`.
3. **Antes** de criar o `DetectorV1` de um pool (mesmo ponto em que `row["l_bc"] is None` decide o 1º candle):
   rodar `qualidade_v1.avaliar_qualidade(bars_ja_vistos, self.params_v1)` — `dado_invalido` grava
   `pr1_add_filtrado(..., "dado_invalido", motivo, self.version_v1)` e **nunca** cria o `DetectorV1` para aquele
   pool (filtro permanente, não por ciclo). Mesmo ponto: MC atual < `min_mc_usd` → `filtrado_mc_baixo` (idem,
   nunca bloqueia o V0/a Parte A, só a V1).
4. `_on_event_v1`: `RUNNER`/`FASE2`/`TESTE` → nada (uso interno); `WATCHLIST` → `telegram_v1.watchlist_text` +
   `pr_alert_once` (reaproveita a MESMA tabela `pr_alerts` do V0, só com chave `f"v1:w:..."`); `FORA_DA_IDADE` →
   `pr1_add_filtrado(..., "filtrado_idade", ...)`, nunca alerta; `ENTRADA` → `pr1_insert_signal` (idempotente pela
   UNIQUE), tags (`risco_fora_da_faixa` do próprio evento; `HOLDER_CONCENTRADO`/`holders_indisponivel` via
   `adapter.holders(mint, excluded)`; `VAMP_RISK` via `adapter.vamp_risk`), `telegram_v1.entrada_text` +
   `telegram_v1.keyboard`, e registra a entrada aberta para a 2ª passada (TP1/EXIT FULL) continuar simulando a
   cada novo candle (mesmo padrão do `_update_paper` do V0: reconsulta `simulate_v1` a cada `_refresh`, grava
   TP1/EXIT FULL quando aparecem nos `legs`, manda `tp1_text`/`exit_full_text` uma vez cada via `pr_alert_once`,
   e só então chama `BankrollLedgerV1.step`).
5. Resumo diário: `engine.maybe_send_daily_summary` ganha uma chamada a mais, `telegram_v1.resumo_diario_text`
   com `pr1_filtrado_counts`/contagem de `pr1_signals`/`pr1_uptime_hours`.
6. `--sem-v0` (regra 0 do prompt): flag de CLI/env que, quando ligada, pula `self._detector`/`self._detector_fecham`
   inteiros em `_refresh` (o V1 continua) — não gasta orçamento de GT/RPC com o V0 quando o operador quiser.
7. `perdido_offline`: ao religar (`_startup`), qualquer `ENTRADA`/`TESTE` cujo `decision_ts` caia numa lacuna maior
   que o intervalo esperado do tf (processo desligado/hibernado) marca `status='perdido_offline'` em vez de
   tentar alertar com atraso — mesmo `_late()` já usado pelo V0, só mudando o destino do que falha esse teste.

## Por que parei aqui em vez de aplicar

`live.py` é o arquivo mais crítico e mais testado do módulo (296 testes do V0 dependem do comportamento exato
dele). Toda a "cabeça" da V1 (regras, simulação, qualidade, banca, textos, adapter) já está pronta e testada
isoladamente — o que falta é mecânico (os 7 pontos acima), mas colar tudo dentro do ciclo ao vivo sem uma
sessão dedicada a isso arrisca um bug sutil num bot que decide alertas de dinheiro (ainda que paper) sem
revisão. Prefiro entregar isto pronto para a próxima sessão/revisão do operador em vez de arriscar.

## Comandos (Windows, raiz do repo, venv ativo)

```powershell
git pull
python -m unittest discover -s signals_mvp/tests -t .   # 354 testes, offline
```

O bot ao vivo (`python -m signals_mvp live` / `teste-pos-runner`) continua exatamente como antes — a V1 ainda
não manda nenhum alerta nem grava nenhuma linha em `pr1_*` até o passo acima ser aplicado.

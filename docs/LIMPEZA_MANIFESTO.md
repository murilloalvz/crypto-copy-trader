# Manifesto de limpeza do repositório

Mapeamento feito ANTES de mover ou apagar qualquer coisa (FASE B do pedido de limpeza, branch
`limpeza-e-analise`). Regra aplicada: **REMOVER só lixo óbvio** (arquivo solto sem referência,
sobra de build, cache, duplicata exata, lockfile sem uso no CI); **na dúvida, MANTER ou ARQUIVAR,
nunca apagar**. Pesquisa histórica/pausada vai para `archive/` com README próprio, nunca é
apagada.

## Achado principal

Este repositório tem **dois programas de pesquisa sem acoplamento entre si**:

1. `signals_mvp/` — o bot de sinais PAPER (V0+V1) descrito no pedido de limpeza. Autocontido: não
   importa nada de fora de si mesmo, e nada fora dele importa `signals_mvp`.
2. Um programa muito maior e mais antigo ("Opportunity Intelligence Engine" — o mesmo que o
   `CLAUDE.md` da raiz descreve: Signal Plane em Rust, holdouts selados, dezenas de hipóteses
   versionadas) espalhado por ~150 scripts na raiz, 73 subpastas de `benchmarks/`, `src/`+`app.py`
   (dashboard Streamlit), `tests/`, `wallets/`, `research/` e ~230 documentos em `docs/`.

A limpeza move o **programa antigo, sem acoplamento com o bot**, para `archive/`. Nada do que o
`CLAUDE.md` da raiz cita como autoridade (docs de migração, registro de hipóteses, Gate 2, o
holdout `native-participant-quality-holdout-v1`, o incidente de capacidade da Research Plane, o
kernel Rust) foi movido — são referências ativas de um arquivo de contrato que esta tarefa não foi
autorizada a editar.

## Confirmações de segurança (antes de mover)

- **Segredo versionado**: nenhum encontrado. Não há `.env` commitado (só `.env.example`, na raiz e
  em `signals_mvp/`, ambos só com placeholder). Ocorrências de `api_key`/`token`/`secret` em
  `benchmarks/*` são nomes de PARÂMETRO de função, nunca um valor fixo. As strings base58 longas em
  `signals_mvp/pos_runner/examples.py` e `signals_mvp/tests/fixtures/gt_trades_solana.json` são
  assinaturas de transação/endereços públicos de um fixture real da GeckoTerminal — nunca uma
  chave privada (este projeto nunca tem chave privada, é PAPER em toda a sua extensão).
- `pyproject.toml`/`setup.py`: não existem em nenhum lugar do repositório.
- `.gitignore` da raiz já cobre `.env`, `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`,
  `artifacts/`, `**/target/`, `data/`, `logs/*.log`. Faltam: `*.sqlite`/`*.sqlite3` genérico,
  `build/`/`dist/`/`*.egg-info/`, e `logs/` para qualquer extensão (não só `.log`) — completados
  nesta revisão. O `.gitignore` de `signals_mvp/` (escopo próprio) já cobria `.env`, `dados/`,
  `logs/`, `__pycache__/` corretamente.
- `.github/workflows/tests.yml` roda `unittest discover -s tests` (a pasta `tests/` da RAIZ) — nunca
  testou `signals_mvp/tests/`. Como `tests/` vai para `archive/`, o workflow foi reescrito para
  testar `signals_mvp/tests/` (o único código ativo que resta na raiz do checkout do bot); os
  outros 26 workflows testavam scripts do programa antigo e foram arquivados junto com ele (ver
  tabela) — continuam no histórico do git, só não disparam mais.

## Tabela

| Caminho | O que é | Ação | Motivo |
|---|---|---|---|
| `signals_mvp/` (tudo) | Bot de sinais PAPER (V0+V1), autocontido | MANTER | Núcleo do projeto, escopo desta limpeza |
| `signals_mvp/dados/pos_runner_parte_a/checkpoint_handoff/*.sqlite.gz` | Checkpoint commitado da Parte A | MANTER | Regra: nunca mover/apagar Parte A/checkpoints |
| `docs/pos-runner-v0*`, `docs/pos-runner-v1/` (inclusive os 3 arquivos "soltos" `pos-runner-v0-handoff-2026-10-16.md`, `pos-runner-v0-handoff-2026-10-19.md`, `pos-runner-v0-preregistration-DRAFT-2026-10-15.md`) | Docs/holdout selado (`3f648e95`) da V0/V1 | MANTER | Protegido explicitamente pelo pedido; o preregistro é lido em runtime por `signals_mvp/pos_runner/parte_a/cli.py` (achado rodando a suíte depois da 1ª passada da limpeza — os 3 arquivos tinham ido para `archive/docs/` por engano, corrigido) |
| `docs/migration/` | Mapa de autoridade entre branches | MANTER | Citado por nome pelo `CLAUDE.md` da raiz |
| `docs/research-hypothesis-registry-v1-2026-10-04.md` | Registro de hipóteses | MANTER | Citado por `signals_mvp/CLAUDE.md` E pelo `CLAUDE.md` da raiz |
| `docs/templates/batch-preregistration-template-v1.md`, `docs/live-readiness-gates-v1.md` | Template/Gate 2 | MANTER | Citados por nome pelo `CLAUDE.md` da raiz |
| `docs/native-participant-quality-holdout-v1-result-2026-09-24.md` | Resultado do holdout nativo (KILL) | MANTER | Citado por nome ("Evidence authority") pelo `CLAUDE.md` da raiz |
| `docs/role-normalized-research-plane-capacity-incident-2026-09-24.md` | Incidente de capacidade | MANTER | Citado por nome pelo `CLAUDE.md` da raiz |
| `docs/sig-fast-*.md` (7 arquivos) | Documentação do `benchmarks/sig_fast_v0` | MANTER | Documenta sistema protegido |
| `docs/*` — demais ~190 arquivos | Docs do programa antigo sem referência ativa fora dele | ARQUIVAR em `archive/docs/` | Pesquisa histórica/pausada |
| `benchmarks/sig_fast_v0/` | Discovery/H2 do sig_fast | MANTER | Protegido explicitamente pelo pedido |
| `benchmarks/integrated_market_signal_plane_v1/` (incl. `rust_runner/`) | Kernel Rust do Signal Plane | MANTER | "Kernel Rust", protegido explicitamente; citado pelo `CLAUDE.md` da raiz |
| `benchmarks/*` — demais 71 subpastas (lista completa abaixo) | Experimentos do programa antigo | ARQUIVAR em `archive/benchmarks/` | Pesquisa histórica/pausada, sem acoplamento com `signals_mvp` |
| `app.py` + `src/` (220 arquivos) | Dashboard Streamlit do copy-trader antigo | ARQUIVAR em `archive/app/` | Sem dependência de `signals_mvp` |
| `tests/` (raiz, 414 arquivos) | Testes do programa antigo | ARQUIVAR em `archive/tests/` | Nunca testou `signals_mvp`; CI corrigido para testar o bot |
| `research/` | 1 subpasta (`external_intelligence/gmgn_capability_audit`) | ARQUIVAR em `archive/research/` | Pesquisa pontual antiga |
| `wallets/` (3 `.txt`) | Cohorts de carteiras do programa antigo | ARQUIVAR em `archive/wallets/` | Dado de pesquisa histórico |
| ~150 scripts `.py` na raiz (`wallet_*`, `route_research_*`, `unified_market_*`, `participant_quality_*`, `social_*`, `radar.py`, `discover.py`, `collect.py`, `evaluate*.py`, `monitor*.py`, `backtest_concurrent.py`, `causal_quote_ingest.py`, `opportunity_context.py`, `rejection_lab.py`, `market_*`, `jupiter_*`, `hazard_provider_attempt_diagnostic.py`, `forward_exit_route_probe_v39.py`, `signal_plane_*.py`, `simulate_bankroll.py`) | Scripts do programa de pesquisa antigo | ARQUIVAR em `archive/scripts/` | Pesquisa histórica, zero uso por `signals_mvp` |
| `start-monitor.ps1` | Lança `monitor.py` (antigo) | ARQUIVAR em `archive/scripts/` | Acompanha o script que referencia |
| `.github/workflows/*.yml` (26 dos 27 arquivos) | CI do programa antigo | ARQUIVAR em `archive/ci_antigo/` | Testavam só código que foi arquivado; preservados no histórico, não disparam mais |
| `.github/workflows/tests.yml` | CI | MANTER, com correção | Reescrito para rodar `signals_mvp/tests/` em vez da `tests/` arquivada |
| `.claude/` | Config/skills do Claude Code | MANTER | Infraestrutura, não dado de pesquisa |
| `.env.example` (raiz) | Placeholders do dashboard antigo | ARQUIVAR em `archive/app/` junto com `app.py` | Específico do dashboard que foi arquivado; `signals_mvp/.env.example` é o que vale para o bot |
| `.gitignore` | Config | MANTER, com complemento | Faltavam `*.sqlite`, `build/`/`dist/`/`*.egg-info/`, `logs/` genérico |
| `requirements.txt` | Dependências da raiz | MANTER, com ajuste | `streamlit`/`pandas`/`plotly` eram só do dashboard arquivado; `signals_mvp` só precisa de `python-dotenv`+`numpy` (próprios) |
| `CLAUDE.md`, `PROJECT_CONTEXT.md` (raiz) | Contrato/estado do programa antigo | MANTER, sem edição de conteúdo | Autoridade de um sistema fora do escopo deste pedido; não foi pedido para reescrever |
| `README.md` (raiz) | README atual, descreve o programa antigo | Substituído pelo novo README (item 4 da FASE B) | Trocar o conteúdo não é "arquivar o arquivo" |
| `LICENSE` | Não existia | Criado (MIT) | Pedido explícito |

### As 71 subpastas de `benchmarks/` arquivadas (verificadas uma a uma: mesmo padrão — um
módulo/coletor/análise por hipótese versionada, sem nenhuma referência a `signals_mvp`):

`burst_incremental_tournament_v0`, `burst_participation_structure_discovery_v0`,
`burst_selection_diagnostic_v0`, `burst_selection_diagnostic_v1`, `burst_tail_selection_scan_v0`,
`buy_event_acceleration_replication_v0`, `carbon_decoder_parity_v1`, `carbon_kernel_ingress_v0`,
`carbon_kernel_ingress_v1`, `carbon_runtime_replay_v1`, `carbon_stream_bridge_v0`,
`carbon_stream_bridge_v1`, `commodity_signal_plane_v0`, `convergence_v0`,
`curve_capacity_replication_v0`, `deployer_prior_quality_v0`, `early_balance_concentration_v0`,
`early_buyer_churn_prospective_v1`, `early_buyer_churn_robustness_v0`, `early_buyer_churn_v0`,
`early_buyer_prior_quality_replication_v0`, `early_buyer_prior_quality_v0`,
`free_historical_corpus_v2`, `helius_standard_wss_shadow_v0`, `holder_ownership_native_v1`,
`holder_ownership_rpc_v2`, `holder_ownership_structure_v0`, `launch_burst_candidate_parity_v0`,
`launch_burst_control_taker_sim_v0`, `launch_burst_coverage_audit_v0`,
`launch_burst_feature_redundancy_v0`, `launch_burst_live_capture_v0`, `launch_burst_live_capture_v1`,
`launch_burst_live_capture_v2`, `launch_burst_live_feature_analysis_v0`,
`launch_burst_matched_unit_coverage_v0`, `launch_burst_momentum_v0`, `launch_burst_opportunity_lab_v0`,
`launch_burst_prospective_economic_v1`, `launch_burst_prospective_route_live_v3`,
`launch_burst_prospective_route_live_v4`, `launch_burst_prospective_route_paper_v2`,
`launch_burst_readiness_v0`, `launch_burst_replay_v0`, `launch_burst_run_inventory_v0`,
`launch_burst_shadow_v0`, `launch_burst_sniper_v1`, `launch_burst_stability_audit_v0`,
`launch_burst_trajectory_audit_v0`, `market_activity_discovery_v0`,
`market_first_bonding_curve_geometry_v1`, `market_first_capacity_harness_v0`,
`market_first_cross_run_edge_stability_v0`, `market_first_entry_availability_diagnostic_v0`,
`market_first_feature_discovery_v1`, `market_first_liquidity_discovery_v0`,
`market_first_live_discovery_v0`, `market_first_live_smoke_v0`, `market_first_postrun_readiness_v0`,
`market_first_routeable_edge_discovery_v2`, `market_first_signal_plane_v0`,
`market_protocol_facts_v0`, `market_regime_detector_v0`, `move_first_h_coverage_audit_v0`,
`move_first_long_horizon_baseline_v0`, `pumpswap_identity_bootstrap_v0`, `raw_transaction_corpus_v1`,
`social_event_first_v0`, `v60_opportunity_wallet_convergence_v0`, `v68_signal_plane_bridge_v0`,
`yellowstone_raw_stream_v2`.

## O que NÃO foi tocado (confirmação)

Holdout selado `3f648e95` e seus artefatos/docs (`docs/pos-runner-v0*`), Parte A
(`signals_mvp/pos_runner/parte_a/` + o checkpoint commitado), `benchmarks/sig_fast_v0/`,
`benchmarks/integrated_market_signal_plane_v1/` (kernel Rust), `signals_mvp/pos_runner/*.yaml` e
`params*.py` (V0/V1), `docs/pos-runner-v1/INTERPRETACOES.md`/RUNBOOK/STATUS, `signals_mvp/dados/`
e `signals_mvp/logs/` do operador (ignorados pelo git), `iniciar.bat`/`parar.bat`
(`signals_mvp/`), e todo o conteúdo citado por nome no `CLAUDE.md` da raiz.

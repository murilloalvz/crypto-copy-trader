# CD-PROMO-V0 — Runbook de coleta e veredito — 2026-10-05

Pré-registro (ler primeiro, define os critérios congelados):
`docs/concentration-decay-promotion-v0-preregistration-2026-10-05.md`.

Modo: PAPER / RESEARCH / READ ONLY / ROUTE-SHADOW. Nenhum passo abaixo assina
ou submete transação, nem abre posição funded. Rode isto na sua máquina (não
no sandbox) — é uma screening de 900s contínuos.

## 0. Antes de começar

- `.env` (gitignored, nunca commitar) precisa ter `HELIUS_API_KEY`,
  `JUPITER_API_KEY`, `SOLANA_RPC_URL` válidos (`SOLANA_RPC_FALLBACK_URLS` é
  opcional). Nunca reuse uma chave que já foi colada no chat.
- Confirme que está na branch certa:
  ```bash
  git status
  git log --oneline -3
  ```
  Espera-se `research/rust-signal-plane-live-shadow-v0` com o commit deste
  runbook no topo. O pipeline Launch Burst Sniper V1 (preflight, screening,
  discovery benchmark, verdict script) já está presente nesta branch — **não
  precisa `git switch` para nenhuma outra branch** (confirmado lendo os
  arquivos diretamente nesta checkout).
- Desative suspensão de energia durante a janela (lição do v68-09: um
  `print()`/console travado pode zerar a coleta sem erro nenhum).
- Redirecione a saída pra arquivo em todo passo "live" abaixo — nunca escreva
  só no console.

## 1. Preflight (read-only, não abre coleta)

```bash
python3 -m benchmarks.launch_burst_sniper_v1.preflight 2>&1 | tee logs/cd-promo-v0-preflight.log
```

Espera-se `PASS_LAUNCH_BURST_SNIPER_V1_PREFLIGHT` com todos os gates `true`.
Se não passar, **não** inicie o passo 2 — resolva o bloqueio de
suporte/configuração e rode o preflight de novo, sem mudar nada além disso.

## 2. Screening congelada de 900s (live, abre a coleta real)

```bash
python3 -m benchmarks.launch_burst_control_taker_sim_v0.run_v4_sniper_v1 \
  --duration-seconds 900 \
  2>&1 | tee logs/cd-promo-v0-screening.log
```

- A duração é fixa pelo próprio runner (recusa mudança in-place) — não tente
  `--duration-seconds` diferente de 900.
- Anote o diretório de run impresso no log (ex.: algo como
  `artifacts/launch_burst_control_taker_sim_v0/<run-dir>/`) — chame de
  `$RUN_DIR` nos próximos passos. É esse diretório, com
  `route-input-v2.json`, `route-result-v2.json`, `sniper-comparison-v1.json`
  e `processed-chunks/`, que os passos 3-4 consomem.
- Preserve o diretório completo depois — não edite nenhum JSON gerado à mão.

## 3. Discovery do Market-First a partir do run-dir (replay, não é rede nova)

```bash
python3 -m benchmarks.market_first_feature_discovery_v1.run \
  --run-dir "$RUN_DIR" \
  2>&1 | tee logs/cd-promo-v0-discovery.log
```

Espera-se `classification: PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1` no JSON
compacto impresso. Isso grava
`"$RUN_DIR"/market-first-feature-discovery-v1.json` com, entre outras coisas,
`rows[].features.mf_top_wallet_gross_share_delta_pct_points_late_minus_early`
e `rows[].fixed_return_pct` por episódio — a matéria-prima do veredito.

Se vier `FAIL_MARKET_FIRST_FEATURE_DISCOVERY_V1` (erro de paridade causal), a
coleta do passo 2 não é reaproveitável pra esta hipótese — reporte o erro, não
tente "corrigir" os dados à mão.

## 4. Veredito CD-PROMO-V0 (aplica os critérios já congelados, sem interpretação manual)

```bash
python3 -m benchmarks.market_first_feature_discovery_v1.cd_promo_v0_verdict \
  --report "$RUN_DIR/market-first-feature-discovery-v1.json" \
  2>&1 | tee logs/cd-promo-v0-verdict.log
```

Opcional, antes de rodar com dado real (confere que o script em si está
correto, usando dado sintético, não o seu):

```bash
python3 -m benchmarks.market_first_feature_discovery_v1.cd_promo_v0_verdict --self-check
```

Saída esperada do passo com `--report`: um JSON com `verdict` igual a um dos
três valores abaixo (ver seção 4 do pré-registro para a definição exata):

- `PASS_CD_PROMO_V0` — feature promovida: ver seção 7 do pré-registro pro que
  muda em `src/opportunity_feature_matrix_v0.py` e `docs/research-hypothesis-registry-v1-2026-10-04.md`.
- `FAIL_CD_PROMO_V0` — feature permanece `diagnostic_only`; sem segunda
  tentativa, sem retune.
- `INCONCLUSIVE_CD_PROMO_V0_SUPPORT` — permite no máximo 1 extensão de coleta
  (rodar os passos 2-4 de novo, run-dir novo, sem mudar nada da regra); se a
  extensão também não bater o suporte mínimo, fecha permanente.

## 5. Depois de ter o veredito

Não decida nada sozinho além do que a seção 7 do pré-registro já manda. Reporte:

- o JSON completo do passo 4;
- `$RUN_DIR` (caminho, pra preservação do artefato);
- os 4 logs de `logs/cd-promo-v0-*.log`.

Isso vai pro commit que atualiza o registro de hipóteses — mesmo padrão já
usado por V48/V55/V68/PQ-V1/PQ-TR-V0 neste repositório.

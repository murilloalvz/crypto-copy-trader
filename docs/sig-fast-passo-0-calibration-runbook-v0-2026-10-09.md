# SIG-FAST — Passo 0 (calibração) — Runbook — 2026-10-09

Contexto: `docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md`
(rev. 3), seção "Plano de coleta" -- Passo 0 é **puro systems check, não
julga nenhuma hipótese e não gasta tentativa do registro**
(`docs/research-hypothesis-registry-v1-2026-10-04.md`, regra 5). Mede, com
dado real, o que hoje só existe como estimativa derivada de outro sistema
(enumeração de migração).

Modo: PAPER / RESEARCH / READ ONLY. Nenhum passo assina ou submete
transação. RPC Helius dedicado (pago) — o free tier já falhou nesta linha de
pesquisa (ver runbook do PQ-TR).

**NUNCA rode este runbook ao mesmo tempo que a replicação do PQ-TR**
(`docs/participant-quality-tail-risk-replication-v1-collection-runbook-2026-10-07.md`).
Os dois disputam a mesma chave Helius e a mesma CPU/rede da sua máquina;
rodar os dois juntos arrisca contaminar ambas as medições com latência
artificial, sem gerar um erro visível que avise disso. Espere um terminar
antes de começar o outro.

## 0. Antes de começar

- `.env` com `HELIUS_API_KEY`, `SOLANA_RPC_URL` (RPC dedicado) válidos.
  Nenhuma outra tarefa deve usar essas chaves durante a janela abaixo —
  inclusive o PQ-TR (ver aviso acima).
- Confirme a branch e o commit (espera-se `sig-fast-price-path-persistence-v0`
  com os commits do item (a)/(a2)/(b) desta revisão no topo):
  ```powershell
  git status
  git log --oneline -5
  ```
- Confirme no Helius o consumo de créditos **ANTES** de começar (dashboard do
  seu plano) — anote o número. Não existe medidor de consumo Helius dentro
  deste repositório; o delta antes/depois é manual, feito por você.
- Desative suspensão de energia durante toda a sessão:
  ```powershell
  powercfg /change standby-timeout-ac 0
  ```
- Saída de todo passo "live" **só em arquivo** (nunca `Tee-Object`/`| tee` —
  trava o processo se o console travar, ex. seleção de texto no modo
  QuickEdit do PowerShell; foi a causa raiz da falha de sistema do v68-09,
  ver `RESEARCH_STATE_LEDGER_2026-09-27.md`). Use `*> arquivo.log` em todo
  comando abaixo.
- Pra acompanhar sem o risco do `Tee-Object`, abra uma **segunda janela**
  PowerShell:
  ```powershell
  Get-Content logs\sig-fast-passo0-live-shadow.log -Wait -Tail 20
  ```
- **Chave de execução descartável.** Use uma chave só desta calibração, nunca
  reusada no discovery real (o DRAFT exige coleta nova e sem overlap — ver
  "Discovery NÃO é retrospectivo"). Sugestão:
  ```powershell
  $RUN_KEY = "sig-fast-passo0-calib-2026-10-09-01"
  ```
  Se repetir o Passo 0 outro dia, incremente o sufixo (`-02`, `-03`, ...) —
  nunca reaproveite `-01`.

## 1. Bootstrap de identidade PumpSwap (live, ~60s)

Mesmo passo do runbook do PQ-TR — reaproveite o artefato se já tiver um
recente (<1h); senão rode de novo:

```powershell
python -m benchmarks.pumpswap_identity_bootstrap_v0.bootstrap --cargo cargo *> logs/sig-fast-passo0-bootstrap.log
```

Confirme `valid_bootstrap: true` no `report.json` impresso. Guarde o caminho:

```powershell
$BOOTSTRAP_REPORT = "artifacts/pumpswap_identity_bootstrap_v0/<run-dir-do-passo-1>/report.json"
```

## 2. Sessão de calibração (live, 2-4h)

```powershell
python -m benchmarks.integrated_market_signal_plane_v1.live_shadow `
  --bootstrap-report "$BOOTSTRAP_REPORT" `
  --duration-seconds 10800 `
  --research-plane-run-key "$RUN_KEY" `
  --cargo cargo `
  --out artifacts/rust_signal_plane_live_shadow_v7/passo0-report.json *> logs/sig-fast-passo0-live-shadow.log
```

- `--duration-seconds 10800` = 3h, dentro da janela 2-4h (7200 a 14400)
  pedida pelo operador. Ajuste se quiser outro ponto da janela.
- `--research-plane-run-key` (não `--episode-bridge-run-key` — são
  mutuamente exclusivos) é o que persiste cada trade/lifecycle real em
  `market_trade_observations`/`market_lifecycle_observations` com essa MESMA
  chave como `acquisition_run_key` — é o que o passo 3 vai ler.
- **Stall guard (item (b), novo nesta revisão)**: se o processo travar por
  >30s entre ciclos do loop consumidor (ex. console travado, sleep do SO), a
  sessão para sozinha com `classification=FAIL_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH`,
  gate `no_consumer_loop_stall=false`, e `consumer_stall_detected=true` +
  `consumer_stall_gap_seconds=<N>` no `--out`. Se isso acontecer, **não é
  erro de hipótese nem precisa tocar o kernel Rust** — é só o sinal de que
  algo externo (SO, console) bloqueou a máquina; reinicie a sessão com uma
  chave nova (`-02`) depois de resolver a causa (ex.: não clicar/selecionar
  texto na janela do processo).
- Acompanhar (segunda janela): `Get-Content logs\sig-fast-passo0-live-shadow.log -Wait -Tail 20`.
- Ao final, confira no `--out` (`passo0-report.json`): `process_ready` (ambos
  `true`), `errors` (vazio), `gates.no_fatal_or_signal_errors`,
  `gates.no_consumer_loop_stall`. Qualquer gate falso aqui é falha de
  sistema — reporte, não interprete como dado de calibração válido.

## 3. Auditoria de cobertura + continuidade (read-only, segundos)

Depois que o passo 2 terminar (ou for interrompido no fim da janela de
3h — `Ctrl+C` fecha a sessão de forma limpa, grava o que já foi persistido):

```powershell
python -m benchmarks.sig_fast_v0.path_coverage_audit `
  --acquisition-run-key "$RUN_KEY" `
  --limit 500 `
  --output artifacts/sig_fast_v0/passo0-coverage-report.json
```

- Mesma `$RUN_KEY` do passo 2 — é a coluna `acquisition_run_key` em
  `market_trade_observations`, não um novo valor.
- O relatório tem 3 blocos: `tokens` (por token, já existia em F1c),
  `run_summary` (novo, rollup da run inteira) e
  `graduation_continuity_summary` + `graduation_continuity_tokens` (novo,
  item (b) desta revisão — continuidade pós-graduação pra PumpSwap).
- **Se `graduation_continuity_summary.n_dropped_before_60min_floor > 0`**:
  o motor está "soltando" tokens graduados antes de 60min enquanto a run
  continua observando outros tokens — isso é exatamente a condição que o
  operador mandou **PARAR e trazer, sem mexer no kernel Rust**. Reporte
  quais tokens (`graduation_continuity_tokens`, filtrando
  `drop_reason="dropped_before_60min_floor"`) e o `continuity_seconds` de
  cada. Não investigue a causa (janela de radar, admissão de episódio) nem
  tente corrigir sozinho — essa investigação toca código fora do escopo
  autorizado deste runbook.
- `n_run_ended_before_60min_floor > 0` não é um problema por si — pode ser só
  um token que graduou perto do fim da janela de 2-4h. Só é preocupante se
  **todos** os graduados caírem nessa categoria (sinal de que a sessão foi
  curta demais, não de bug).

## 4. O que reportar (SÓ contagens, nunca preço/retorno)

Do `passo0-coverage-report.json` (passo 3) e do `passo0-report.json`
(passo 2):

| Métrica | Campo | Observação |
|---|---|---|
| Trades/hora (proxy de taxa de sinal, não é H1/H2 exato) | `run_summary.trades_per_hour` | H1/H2 exatos exigem o loader ainda não construído (`docs/sig-fast-disc-v0-runbook-v0-2026-10-08.md`, pré-condição 2) |
| Graduações pump→PumpSwap/hora (proxy de taxa de sinal do H2, teto superior) | `run_summary.graduations_per_hour` | H2 exige também o filtro de >=20 trades/5min, não contado aqui |
| Cobertura de preço (meta >=95%, ver DRAFT) | `100 - run_summary.pct_missing_price_from_amounts_overall` | abaixo de 95% é bloqueador de sistema pro discovery real |
| Continuidade pós-graduação | `graduation_continuity_summary` completo | ver regra de PARAR acima se houver `dropped_before_60min_floor` |
| Duração do caminho (distribuição) | `graduation_continuity_summary.continuity_seconds_{min,p50,p95,max}` | |
| Stall guard disparado? | `passo0-report.json`: `consumer_stall_detected`, `consumer_stall_gap_seconds` | |
| Consumo Helius da sessão | dashboard do seu plano Helius, depois menos antes (passo 0 acima) | não medido por este repositório |

Não reporte preço, retorno, EV, PF ou qualquer leitura da métrica (a)/(b) do
DRAFT — Passo 0 não lê outcome e não deve viajar nenhum número desse tipo,
mesmo que calculável a partir dos dados persistidos.

## 5. Depois do Passo 0

- Isto NÃO é uma coleta de discovery — a chave `$RUN_KEY` desta sessão nunca
  deve ser reusada ou misturada com a janela de discovery real (que exige
  chave própria, nova, sem overlap — DRAFT, seção 1).
- Os números acima entram na seção "Plano de coleta" do DRAFT como
  calibração real, substituindo as estimativas derivadas (taxa de migração
  observada) — não decidem sozinhos a duração do bloco 1 nem da janela de
  discovery, mas destravam a conversa sobre elas.
- Se `n_dropped_before_60min_floor > 0`: pare aqui, traga o achado antes de
  qualquer outra etapa do work order.

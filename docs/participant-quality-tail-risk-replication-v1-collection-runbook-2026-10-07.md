# Participant Quality Tail-Risk Rejection — Replication V1 — Runbook — 2026-10-07

Pré-registro (ler primeiro, define a regra congelada):
`docs/participant-quality-tail-risk-replication-v1-preregistration-2026-10-07.md`.

Modo: PAPER / RESEARCH / READ ONLY. Nenhum passo assina ou submete transação, nem abre posição
funded. Rode isto na sua máquina (PowerShell), com RPC Helius dedicado (pago) — o free tier já
falhou 3x nesta linha de pesquisa.

## 0. Antes de começar

- `.env` com `HELIUS_API_KEY`, `SOLANA_RPC_URL` (RPC dedicado), `JUPITER_API_KEY` válidos. Nenhuma
  outra tarefa deve usar essas chaves durante a janela de coleta abaixo.
- Confirme a branch:
  ```powershell
  git status
  git log --oneline -3
  ```
  Espera-se `research/rust-signal-plane-live-shadow-v0` com o commit deste runbook no topo.
- Desative suspensão de energia durante toda a sessão abaixo:
  ```powershell
  powercfg /change standby-timeout-ac 0
  ```
  (reative depois com o valor original, se quiser — não é parte do protocolo, só convivência com o
  resto do seu uso da máquina).
- Redirecione a saída de todo passo "live" **só para arquivo**, nunca com `Tee-Object`/`| tee`. O
  `Tee-Object` continua escrevendo no console além do arquivo — se o console travar (modo QuickEdit
  do PowerShell, seleção de texto com o mouse trava a escrita até você soltar), o `Tee-Object` trava
  esperando o console, o pipe enche, e o processo Python trava junto, sem erro nenhum. Foi exatamente
  esse mecanismo que causou a falha de sistema do v68-09 (ver `RESEARCH_STATE_LEDGER_2026-09-27.md`).
  Use `*> arquivo.log` (redireciona todos os streams só pro arquivo, sem eco no console) em todo
  comando abaixo.
- Pra acompanhar o progresso sem o risco do `Tee-Object`, abra uma **segunda janela** PowerShell e
  rode, por exemplo (ajuste o nome do log pro passo que está rodando):
  ```powershell
  Get-Content logs\pq-tr-repl-v1-holdout.log -Wait -Tail 20
  ```
  `Get-Content -Wait` só lê o arquivo (sem travar o processo que escreve nele) — clicar/selecionar
  texto nessa segunda janela não afeta a coleta na primeira.
- Confirme que nenhuma coleta V68 está rodando (não deveria haver nenhuma — V68 está fechado
  permanentemente desde 2026-10-05).

## 1. Bootstrap de identidade PumpSwap (live, ~60s)

```powershell
python -m benchmarks.pumpswap_identity_bootstrap_v0.bootstrap --cargo cargo *> logs/pq-tr-repl-v1-bootstrap.log
```

Acompanhar (opcional, segunda janela): `Get-Content logs\pq-tr-repl-v1-bootstrap.log -Wait -Tail 20`

Note o diretório impresso, ex. `artifacts/pumpswap_identity_bootstrap_v0/<ts>-<id>/report.json`.
Confirme `valid_bootstrap: true`. Guarde o caminho como `$BOOTSTRAP_REPORT`:

```powershell
$BOOTSTRAP_REPORT = "artifacts/pumpswap_identity_bootstrap_v0/<run-dir-do-passo-1>/report.json"
```

## 2. Memory build — nova lineage causal (live, ~minutos)

```powershell
python -m participant_quality_native_memory_v1 `
  --base-run-key participant-quality-tail-risk-replication-v1-20261007-01 `
  --bootstrap-report "$BOOTSTRAP_REPORT" *> logs/pq-tr-repl-v1-memory.log
```

Acompanhar (segunda janela, recomendado — este passo demora minutos):
`Get-Content logs\pq-tr-repl-v1-memory.log -Wait -Tail 20`

- Chave base **exata**, não mude — o pré-registro e o wrapper do passo 4 dependem dela
  literalmente.
- Espere `classification=READY_TO_PREREGISTER_NATIVE_PARTICIPANT_QUALITY_HOLDOUT`. Qualquer outra
  classificação é falha de sistema — não conta como tentativa; registre e pare.
- Anote `outcome_blind_median_cutoff` impresso na auditoria de cobertura — é só para registro
  descritivo do que esta amostra nova teria produzido por conta própria; **não é usado** para
  classificar HIGH/LOW nesta replicação (ver pré-registro, seção "O que muda").
- Saída: `artifacts/participant_quality_native_memory_v1/participant-quality-tail-risk-replication-v1-20261007-01-report.json`
  — chame de `$MEMORY_REPORT`.

```powershell
$MEMORY_REPORT = "artifacts/participant_quality_native_memory_v1/participant-quality-tail-risk-replication-v1-20261007-01-report.json"
```

## 3. Self-check do wrapper (antes de tocar dado real)

```powershell
python participant_quality_tail_risk_replication_v1.py --self-check
```

Espera-se `self-check OK: fresh-sample cutoff mismatch tolerated, lineage mismatch still rejected`.
Se falhar, **pare** e reporte — não rode o passo 4.

## 4. Holdout acquisition — cutoff do V0 fixo (live, ~minutos)

```powershell
python participant_quality_tail_risk_replication_v1.py `
  --memory-run-key-base participant-quality-tail-risk-replication-v1-20261007-01 `
  --base-run-key participant-quality-tail-risk-replication-v1-20261007-01 `
  --memory-report "$MEMORY_REPORT" `
  --bootstrap-report "$BOOTSTRAP_REPORT" *> logs/pq-tr-repl-v1-holdout.log
```

Acompanhar (segunda janela, recomendado — este passo demora minutos):
`Get-Content logs\pq-tr-repl-v1-holdout.log -Wait -Tail 20`

- Se falhar por sistema (bridge/900s-maturity não `PASS`, `INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_HOLDOUT_ACQUISITION`
  ou `_900_MATURITY`): não conta como tentativa. Pode retry com `--base-run-key ...-02` (mesma
  `--memory-run-key-base`, sem mudar nada do pré-registro).
- Saída esperada: `KEEP_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE` ou
  `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE` impresso por `print_summary` — **este
  classifier não é o veredito desta hipótese**, é o classifier genérico herdado do script original
  (compara HIGH vs LOW diretamente). O veredito real vem do passo 5.
- Confere no log a linha `v0_frozen_cutoff_pinned=-86.0484432047999` e
  `fresh_sample_own_cutoff_not_used=<algum outro número>` — se esses dois números saírem iguais por
  coincidência, não é erro, só anote.
- Artefato: `artifacts/participant_quality_tail_risk_replication_v1/participant-quality-tail-risk-replication-v1-20261007-01-report.json`
  — chame de `$HOLDOUT_REPORT`.

```powershell
$HOLDOUT_REPORT = "artifacts/participant_quality_tail_risk_replication_v1/participant-quality-tail-risk-replication-v1-20261007-01-report.json"
```

## 5. Veredito real: tail-risk rejection (reusa o avaliador do V0 sem mudança)

```powershell
python participant_quality_tail_risk_rejection_v0.py --holdout-report "$HOLDOUT_REPORT" `
  --out artifacts/participant_quality_tail_risk_replication_v1/verdict-report.json *> logs/pq-tr-repl-v1-verdict.log
```

Opcional antes, com dado sintético:

```powershell
python participant_quality_tail_risk_rejection_v0.py --self-check
```

Saída esperada do passo com `--holdout-report`: um dos três valores definidos na seção "Regra
congelada" do pré-registro — `PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`,
`FAIL_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`, ou
`INCONCLUSIVE_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0_SUPPORT`.

## 6. Depois do veredito

Não decida nada sozinho além do que a seção "Disciplina de falha" do pré-registro já manda.
Reporte:

- o JSON completo do passo 5;
- `$HOLDOUT_REPORT` e `$MEMORY_REPORT` (caminhos, para preservação do artefato);
- os 4 logs de `logs/pq-tr-repl-v1-*.log`;
- o `outcome_blind_median_cutoff` anotado no passo 2 (só para registro, não decide nada).

Isso vai para o commit que atualiza `docs/research-hypothesis-registry-v1-2026-10-04.md` — mesmo
padrão já usado por V48/V55/V68/PQ-V1/PQ-TR-V0/CD-PROMO-V0 neste repositório.

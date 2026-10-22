# v60 Opportunity Wallet Convergence — Discovery V0 — Runbook de coleta — 2026-10-07

Pré-registro (ler primeiro, define os parâmetros congelados):
`docs/v60-wallet-convergence-discovery-v0-preregistration-2026-10-07.md`.

Modo: PAPER / RESEARCH / READ ONLY. Nenhum passo abaixo assina ou submete
transação, nem abre posição funded. É só leitura de RPC (histórico público
das 8 wallets semente) e leitura do seu próprio SQLite local. Rode isto na
sua máquina (PowerShell), não no sandbox.

## 0. Antes de começar

- `.env` (gitignored, nunca commitar) precisa ter `HELIUS_API_KEY` e
  `SOLANA_RPC_URL` válidos — os mesmos já usados na coleta do CD-PROMO-V0.
  Este passo **não** precisa de `GMGN_API_KEY` (confirmado lendo
  `src/services.py::sync_wallet` — usa só `SolanaClient`, sem GMGN).
- Confirme a branch:
  ```powershell
  git status
  git log --oneline -3
  ```
  Espera-se `research/rust-signal-plane-live-shadow-v0` com o commit deste
  runbook no topo.
- Nunca reuse uma chave que já foi colada no chat.

## 1. Sincronizar as 8 wallets semente (RPC, read-only)

```powershell
python wallet_strategy_lab.py --sync-onchain --pages 3 --json `
  CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o `
  Bi4rd5FH5bYEN8scZ7wevxNZyNmKHdaBcvewdPFxYdLt `
  2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f `
  4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9 `
  J6TDXvarvpBdPXTaTU8eJbtso1PUCYKGkVtMKUUY8iEa `
  B32QbbdDAyhvUQzjcaM5j6ZVKwjCxAwGH5Xgvb9SJqnC `
  ardinRsN1mNYVeoJWTBsWeYeXvuR9UUDGMsCDKpb6AT `
  BTf4A2exGK9BCVDNzy65b9dUzXgMqB4weVkvTMFQsadd *>&1 | Tee-Object logs/v60-sync-seeds.log
```

- São as mesmas 8 wallets do protocolo v60 (Cented, Theo, Cupsey, Decu,
  Pain, Kadenox, Trunoest, Kev), na mesma ordem.
- `--pages 3` é o padrão do script; se alguma wallet tiver pré-período
  (30 dias) com menos de `MIN_PRE_PERIOD_SWAPS=20` swaps dentro de 3
  páginas, aumente para `--pages 6` ou `--pages 10` **antes** de rodar o
  passo 2 — mudar `--pages` aqui é só garantir dado suficiente, não é
  retune de nenhum parâmetro congelado no pré-registro.
- Isso popula o SQLite local (`transactions`, `wallets`) — o passo 2 lê só
  daí, sem nova chamada de rede.

## 2. Congelar o manifesto da coorte (`freeze_cohort.py`)

```powershell
python -m benchmarks.v60_opportunity_wallet_convergence_v0.freeze_cohort --self-check
```

Espera-se `self-check OK: <hash> ...`. Isso confere que o script está
correto com dado sintético, antes de tocar o seu dado real. Se falhar,
**pare** e reporte — não rode o passo com `--self-check` omitido.

```powershell
python -m benchmarks.v60_opportunity_wallet_convergence_v0.freeze_cohort `
  --pre-period-days 30 --min-pre-period-swaps 20 *>&1 | Tee-Object logs/v60-freeze-cohort.log
```

- Usa `--pre-period-end` padrão (agora). Isso fixa `pre_period_end` e
  `registered_at = pre_period_end + 1` no manifesto — exatamente os
  parâmetros congelados na seção 2 do pré-registro.
- Saída esperada: `classification: PASS_V60_DISCOVERY_V0_COHORT_FROZEN` e o
  arquivo `benchmarks/v60_opportunity_wallet_convergence_v0/frozen_cohort_v60_discovery_v0.json`.
  Se vier `FAIL_V60_DISCOVERY_V0_NO_ELIGIBLE_SEED`, nenhuma wallet teve
  `MIN_PRE_PERIOD_SWAPS` no pré-período — reporte e não force o parâmetro
  pra baixo (seria retune depois de ver o dado).
- **Commite este JSON imediatamente**, antes de qualquer leitura de episódio
  de mercado:
  ```powershell
  git add benchmarks/v60_opportunity_wallet_convergence_v0/frozen_cohort_v60_discovery_v0.json
  git commit -m "data: freeze v60 discovery-v0 wallet cohort manifest"
  git push -u origin research/rust-signal-plane-live-shadow-v0
  ```
  Esse commit é o ato de freeze/sign-off — depois dele, os membros da
  coorte (lista de wallets elegíveis) não podem mais mudar para esta
  rodada do v60.

## 3. Depois do freeze

Nenhum outro comando deste runbook está pronto ainda — por design. A
seção 3 do pré-registro (saídas descritivas: tamanho da coorte, cobertura de
identidade, etc.) e a seção 4 (auditoria causal) exigem episódios
**estritamente posteriores** a `registered_at`, ou seja, exigem que o
detector market-first rode e capture episódio novo depois do commit do
passo 2 acima. Isso custa calendário (não é replay de dado antigo).

Quando houver episódios suficientes acumulados pelo pipeline normal de
captura (`N_EPISODES_MIN=200` para decidir o próximo passo, seção 5 do
pré-registro), o próximo runbook (lab de agregação descritiva sobre
`$RUN_DIR`/episódios capturados, cruzando com o manifesto congelado) é
escrito nessa ocasião — ainda não existe porque depende de ver quantos
episódios e com que cobertura de identidade a captura normal realmente
produz. Não é um passo que falta "terminar agora"; é um passo que só pode
ser desenhado depois que o freeze do passo 2 estiver commitado e a captura
market-first normal continuar rodando por conta própria.

## 4. Reportar

Depois do passo 2, reporte:

- o JSON completo da saída do passo 2 (classification + manifest);
- o hash `manifest_sha256` (confirma que o freeze é reprodutível);
- `logs/v60-sync-seeds.log` e `logs/v60-freeze-cohort.log`;
- a lista de `excluded` (wallets que não bateram `MIN_PRE_PERIOD_SWAPS`), se
  houver.

Isso vai para o commit que atualiza
`docs/research-hypothesis-registry-v1-2026-10-04.md` com o manifesto
efetivamente congelado (hash, contagem de membros, exclusões) — mesmo
padrão já usado por V48/V55/V68/CD-PROMO-V0 neste repositório.

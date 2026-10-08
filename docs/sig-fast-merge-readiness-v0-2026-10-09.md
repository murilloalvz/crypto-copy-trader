# SIG-FAST + Bundle — prontidão de merge na autoridade (2026-10-09)

Item 5 (parte 2) da revisão do operador. **Merge preparado e testado em
worktree descartável — NÃO executado.** Nenhum merge real foi feito em
nenhuma branch; isto é um relatório de ensaio.

## O que seria mergeado

Um único merge de `sig-fast-price-path-persistence-v0` (origin) em
`research/rust-signal-plane-live-shadow-v0` (autoridade) — confirmado que
`bundle-bot-detection-v0-plumbing` é ancestral direto de
`sig-fast-price-path-persistence-v0` (`git merge-base` == ponta de `bundle-bot-detection-v0-plumbing`,
commit `7f72804`), então um único merge traz as duas branches de uma vez; não
há necessidade de dois merges separados.

## Ensaio (worktree descartável, sem commit nas branches reais)

```
git worktree add --detach <scratch> origin/research/rust-signal-plane-live-shadow-v0
cd <scratch>
git merge --no-commit --no-ff origin/sig-fast-price-path-persistence-v0
```

- **Resultado**: `Automatic merge went well; stopped before committing as requested`
  — **zero conflitos**. 30 arquivos, +4207/-43 linhas.
- **Suíte completa de testes** (`python3 -m unittest discover -s tests -p "test_*.py"`),
  rodada dentro do worktree pós-merge: **1926 testes, 1 falha**.
  - A falha (`test_pumpswap_demoted_audit_lane_v9.py::test_audit_pressure_does_not_overtake_later_stateful_work`)
    é a mesma falha isolada já observada (sem o merge, só rodando a suíte
    inteira) — sensível a timing/carga da máquina (`assertLess` contra um
    valor de contagem sob pressão de CPU), não relacionada a nenhuma mudança
    desta sessão. Confirmado: passa isoladamente, tanto antes quanto depois
    do merge de ensaio. Arquivo não tocado nesta sessão nem pela branch
    sig-fast nem pela bundle.
- Worktree removido depois (`git worktree remove --force`) — nenhum resíduo,
  nenhum push, nenhum merge commitado em nenhuma branch real.

## O que isso significa

O merge está **tecnicamente limpo e testado**. **Não foi executado.** Falta
só a sua confirmação explícita — a instrução foi "preparar... mas NÃO
mergear sem eu confirmar", e é isso que está acontecendo aqui.

**Pré-condição ainda pendente, independente da sua confirmação do merge**:
a replicação do PQ-TR precisa estar rodando (ou já ter rodado) a partir do
worktree isolado no commit `d044304` (ver item 5 parte 1,
`docs/participant-quality-tail-risk-replication-v1-collection-runbook-2026-10-07.md`)
— o merge real pode acontecer em paralelo a essa replicação sem afetá-la,
mas o registro do programa (`docs/research-hypothesis-registry-v1-2026-10-04.md`)
ainda trata a replicação como não rodada; isso não muda com este merge.

**Se você confirmar o merge**: é um fast-forward-safe merge commit comum
(`git merge sig-fast-price-path-persistence-v0` na branch de autoridade,
sem `--no-commit`), push pra `origin/research/rust-signal-plane-live-shadow-v0`.
Nenhum passo adicional de limpeza é necessário — o ensaio já confirmou que
não há conflito.

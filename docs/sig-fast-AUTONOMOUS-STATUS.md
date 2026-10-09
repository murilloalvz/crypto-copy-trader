# SIG-FAST H2 — status do mandato autônomo (operador viajando até segunda)

Documento vivo. Única via de comunicação até o operador voltar — atualizado a
cada fase, commitado e empurrado junto com o código/DRAFT de cada fase.

Mandato original (verbatim, resumo): chegar ao veredito de H2
(SIG-FAST-POSTMIG) no histórico, com toda a disciplina do CLAUDE.md, sem
precisar de decisão do operador. Tudo pré-autorizado com critérios fixados
antes de qualquer retorno. Proibido: tocar o kernel Rust congelado, gastar
dinheiro, imprimir/commitar URLs ou chaves, reabrir hipótese fechada, mudar
regra depois de ver dado.

Branch de trabalho: `research/rust-signal-plane-live-shadow-v0` (autoridade
Systems/Signal Plane/Research Plane do CLAUDE.md — **não** a branch default
do harness `claude/upbeat-keller-lbgv7i`, que não recebe trabalho real deste
mandato).

## Checklist de fases

- [x] **Fase 0 — correções de protocolo (antes de qualquer download novo)**
  - [x] 0a: baseline de `seal_block` corrigida (amostra de TODAS as
    migrações classificadas, não só não-sobreviventes). Self-check novo
    (`_self_check_baseline_samples_all_classified`, prova por perfuração de
    casas). Commit: ver seção "Commits desta sessão".
  - [x] 0b: preço de entrada/saída contra o pool — **já implementado**
    em `src/opportunity_path_metrics_v0.py` (F2)/`src/opportunity_path_baseline_v0.py`
    (F3), achado ao revisar antes de codar (nenhum código novo necessário).
    Decisão nova documentada: resolução de fee bps por evento decodificado
    mais próximo do mesmo pool (reusa lookback existente), fallback =
    missingness explícito, nunca uma tabela de bps inventada sem fonte.
    Desvio do pedido literal ("tabela escalonada por faixa") documentado
    explicitamente no DRAFT para revisão de segunda.
  - [x] 0c: parâmetros congelados confirmados no DRAFT (tabela 1:1 com os
    nomes de parâmetro do código): Δ=32s (30s+2s detecção), Δ_exit=32s,
    tamanho 0.15 SOL, terminal 1%/leg, rede 0.0003 SOL/leg, ATA 0, W=900s,
    barreira +50%/−30%, 6 saídas fixas, MFE descritivo-only.
  - [x] 0d: regra de sobrevivente confirmada (já correta desde a correção
    de viés anterior) — sem mudança de código.
  - [x] Registro de hipóteses: `SIG-FAST-DISC-V0`/H2 passou de "RASCUNHO,
    aguarda sign-off" para **PRE-REGISTRADA** em
    `docs/research-hypothesis-registry-v1-2026-10-04.md` (o mandato
    autônomo do operador é o sign-off) — feito ANTES de qualquer download
    desta rodada, por disciplina do CLAUDE.md ("pré-registrada antes da
    coleta que julga").
- [x] **Fase 1 — enumeração sem Helius + validação de paridade obrigatória**
  Novo `benchmarks/sig_fast_v0/h2_enumeration_no_helius_v0.py`: busca binária
  por slot (blockTime, nunca undershoot) + âncora + `getSignaturesForAddress`
  paginado pra trás + `getTransaction` confirma CreatePool (reaproveita a
  mesma lógica de confirmação do caminho Helius) + dedup. `seal_block` agora
  usa isso como default (recebe `rotator`, não `rpc_url`), Helius só como
  último recurso dentro do próprio rotator. **Paridade validada com rede
  real na 1ª tentativa: 7/7 pool_mints idênticos aos do piloto Helius, zero
  missing, zero unexpected.** Achado extra: as 55 chamadas da validação
  foram 100% servidas pelo endpoint de 1ª preferência (nunca Helius),
  remontando ~2,5 meses -- suficiente pros dois blocos reais.
- [ ] **Fase 2 — download + selagem real (regra de parada por contagem)**
- [ ] **Fase 3 — gate de cobertura**
- [ ] **Fase 4 — avaliação discovery**
- [ ] **Fase 5 — confirmação (só se CANDIDATE)**
- [ ] **Fase 6 — relatório final**
- [ ] Reserva 1 — spec/código paper ao vivo (self-check only)
- [ ] Reserva 2 — plano H1 (copy) ao vivo
- [ ] Reserva 3 — ampliar testes dos módulos novos

## Bloqueadores conhecidos

- **Helius `getTransactionsForAddress` com 429 sustentado**, observado 4x
  nesta sessão (antes deste mandato) só na enumeração de migrações (Estágio
  1 do método antigo). É exatamente o motivo da Fase 1: construir um método
  de enumeração que NUNCA dependa de Helius, com Helius só como último
  recurso. Validação de paridade obrigatória contra os 7 candidatos já
  conhecidos do piloto antes de confiar no método novo em qualquer coisa
  real.
- Nenhum outro bloqueador até agora.

## Decisões tomadas sem o operador (todas dentro do pré-autorizado)

1. Fee bps sem tabela escalonada inventada — ver Fase 0b acima. Reversível
   pelo operador na segunda se ele tiver uma fonte/tabela específica em
   mente.
2. `entry_latency_seconds`/`exit_latency_seconds` = 32 (literal, fora da
   grade `ENTRY_LATENCY_GRID_SECONDS`/`EXIT_LATENCY_GRID_SECONDS` que só
   tem 30) para representar exatamente "30s + 2s de detecção" — os pontos
   da grade continuam diagnóstico-apenas.

## Commits desta sessão (mandato autônomo)

Atualizado a cada fase. Ver `git log` na branch acima para a lista completa
incluindo o trabalho anterior a este mandato (piloto, correção de viés,
infraestrutura de selagem).

- Fase 0: correção da baseline em `seal_block` + self-check novo + addendum
  Fase 0 no DRAFT + atualização do registro de hipóteses + este documento.

## O que falta pra fechar o mandato (resumo pra segunda)

Fases 1–6 completas (ou classificação `INCONCLUSIVE_SYSTEM`/bloqueio
documentado, com reserva tomada), commits empurrados, este documento
refletindo o estado final.

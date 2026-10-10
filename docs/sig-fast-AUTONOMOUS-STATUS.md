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
- [x] **Fase 2 — download + selagem real (regra de parada por contagem) — TERMINADA**
  **Resultado final real: 202 migrações, 76 sobreviventes/126
  não-sobreviventes (37,6%), 126 tokens selados no Estágio 2, 0 erro de
  sistema, k_windows_final=26 (sem extensão -- 50 sobreviventes no
  treino, acima do gatilho de 30). 4 ciclos de queda-e-retomada do
  container, zero dado perdido.** Infra pronta e testada: nova
  `sample_calendar_windows_ordered` (sequência embaralhada UMA vez, prefixo
  estável -- `random.Random(seed).sample()` não garante isso entre k's
  diferentes, bug que eu tinha identificado antes deste mandato) +
  `seal_discovery_block_with_stopping_rule` em `h2_block_seal_v0.py`
  (treino = primeiros 70% do calendário; se sobreviventes no treino < 30,
  estende k em passos de 5 janelas, mesma sequência estável, até atingir
  >= 36 ou esgotar 10 extensões -- documentado como
  `extension_exhausted` se esgotar). `seal_block` em si só trocou a fonte
  das janelas (prefixo estável em vez de `.sample()`) -- sem mudança de
  comportamento pros self-checks existentes. Testado: self-check completo
  (3 cenários da regra de parada: sem extensão, estende até o alvo, esgota
  sem atingir) + **smoke test real em 1 janela do bloco de discovery
  real** (2026-08-20..09-17): 5 migrações achadas, 1 sobrevivente, 4
  não-sobreviventes, baseline amostrada de todas as 5 (Fase 0a), Estágio 2
  completo em 2 tokens, hash gravado -- pipeline ponta a ponta validado
  com rede real antes de disparar a rodada completa.
  **Download real em andamento -- padrão operacional estabelecido: o
  container reinicia periodicamente numa folga entre check-ins (2
  ocorrências confirmadas até agora, `uptime` voltando a "up 0 min"),
  mas o checkpoint nunca perde trabalho e o ciclo retoma/avança sempre**
  (atualizado 2026-10-09 ~15:03). Enumeração e Estágio 1 **100%
  completos** -- 26/26 janelas, 202 migrações, 202 classificadas, 0 erro
  de sistema. **76 sobreviventes / 126 não-sobreviventes (taxa 37,6%)**.
  Regra de parada: não precisou estender k_windows. Estágio 2: alvo
  ~123-152 tokens distintos.
  - Ciclo 1: 0 -> 31 selados (~2h), container reiniciou.
  - Ciclo 2 (retomado ~07:53): 31 -> 51 selados, container reiniciou de
    novo.
  - Ciclo 3 (retomado ~15:03): container reiniciou de novo SEM progresso
    adicional (ainda 51 -- ciclo curto, pouco tempo rodando).
  - Ciclo 4 (retomado 2026-10-10 ~00:36, `PRAGMA integrity_check: ok`
    confirmado antes de retomar): em andamento agora. Monitoramento
    migrado pra um cron recorrente (`/loop 2h`, job `9c9609eb`,
    expira em 7 dias) no lugar da cadeia de `send_later` manual.
  Cada retomada chama o mesmo wrapper, que pula tudo já feito (janelas,
  Stage1, tokens de Stage2 já selados) e continua exatamente de onde
  parou -- zero reprocessamento, zero dado perdido, confirmado em 2
  reinícios reais consecutivos. Ritmo observado ~17-20 tokens de
  Stage2/ciclo de ~45min -- a ~51/~123-152 tokens, estimativa de mais
  4-6 ciclos (várias horas) até completar. Processo sempre relançado via
  `run_in_background` direto da ferramenta (nunca `nohup`/`&` manual).
  Vou continuar checando periodicamente (agendado via `send_later`,
  ~40-45min) e retomando sempre que precisar -- esse ciclo é esperado e
  seguro, não é mais tratado como anomalia.
  Confirmação (K=13, sem regra de parada -- não tem treino/retentor)
  ainda não disparada; K=26 final (sem extensão) já decide a densidade.
- [x] **Fase 3 — gate de cobertura — RODADO COM DADO REAL, REPROVOU**
  `evaluate_coverage_gate` rodado contra o `coverage_report.json` real.
  **Classificação: `INCONCLUSIVE_SYSTEM`.** Reprovou 2 de 7 critérios:
  - % buckets Estágio 2 resolvidos: 44,76% < 95% (real -- sobreviventes
    65,87%, baseline morto por desenho 12,69%; os dois critérios, cada
    um correto isolado, são incompatíveis do jeito que foram fixados).
  - % eventos com reservas+fee: 59,41% < 95% (**artefato de cálculo** --
    confirmado 100% de cobertura real direto no banco; a média por token
    pesa errado os 126 não-sobreviventes que corretamente nunca tentam
    decodificar preço).
  Os outros 5 critérios passaram (paridade, não abortou, 100% janelas,
  missing_source 0%, 50 sobreviventes no treino >= 30). Nenhuma correção
  foi aplicada -- mudar critério depois de ver resultado é retune
  proibido. Ver `docs/sig-fast-h2-RESULTADO-2026-10-10.md`.
- [x] **Fase 4 — avaliação discovery — NUNCA RODOU (gate bloqueou antes)**
  Código pronto e testado, mas a Fase 3 reprovou primeiro -- por desenho,
  Fase 4 não roda sem o gate passar. Nenhum retorno/EV/barreira foi
  calculado com dado real.
- [x] **Fase 5 — confirmação — NÃO SE APLICA (Fase 4 não produziu CANDIDATE)**
  Código pronto e testado, mas nunca executado -- não há saída escolhida
  pra congelar. Bloco de confirmação nunca foi baixado.
- [x] **Fase 6 — relatório final — ESCRITO**
  `docs/sig-fast-h2-RESULTADO-2026-10-10.md`: veredito `INCONCLUSIVE_SYSTEM`,
  H2 permanece aberta (falha de sistema não gasta tentativa, CLAUDE.md),
  diagnóstico completo das 2 causas de reprovação, recomendação de
  correção de protocolo pra uma rodada futura (decisão do operador).
  Registrado em `docs/research-hypothesis-registry-v1-2026-10-04.md`.
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

**Mandato principal (Fases 0-6) concluído em 2026-10-10.** Veredito:
`INCONCLUSIVE_SYSTEM` -- gate de cobertura (Fase 3) reprovou antes do
teste econômico, nenhum retorno/EV calculado. H2 permanece aberta (não é
FAIL/KILL). Relatório completo em `docs/sig-fast-h2-RESULTADO-2026-10-10.md`,
registrado no registro de hipóteses. Duas correções de protocolo
identificadas (critério de buckets por grupo; métrica de reservas+fee
excluindo não-tentativas) ficam para decisão do operador antes de
qualquer nova coleta -- os 202 candidatos e o banco já selado
provavelmente bastam, sem precisar baixar nada de novo.

Restam as 3 tarefas de RESERVA (spec/código do paper ao vivo, plano de
H1 ao vivo, ampliar testes) -- trabalho autônomo continua nelas até o
operador voltar.

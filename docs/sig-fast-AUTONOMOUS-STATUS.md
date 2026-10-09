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
- [~] **Fase 2 — download + selagem real (regra de parada por contagem)**
  EM ANDAMENTO (real, em background). Infra pronta e testada: nova
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
  **Download real em andamento, progresso real às 2h de execução**
  (atualizado 2026-10-09, ~05:09 depois do início): enumeração e Estágio
  1 **100% completos** -- 26/26 janelas, 202 migrações encontradas, 202
  classificadas, 0 erro de sistema. **76 sobreviventes / 126
  não-sobreviventes (taxa 37,6% -- mesma ordem de grandeza do 0,333
  bias-corrigido do piloto)**. Regra de parada (Fase 2): 76 >= 30
  (gatilho) -- **não precisou estender k_windows**, os 26 iniciais já
  bastaram. Estágio 2 (grade completa de preço): alvo ~123-152 tokens
  distintos (sobreviventes + baseline, com overlap esperado pela Fase
  0a); **31 selados até agora** (~2h reais). Ritmo médio observado
  ~3,9min/token (mais lento que o benchmark de 1 token isolado -- real
  tem mais variância de volume entre tokens) -- **estimativa real: mais
  várias horas até terminar o Estágio 2 completo**. Processo roda
  destacado (`nohup`, PID próprio) e sobrevive independente deste chat;
  checkpoint garante que nada já selado é reprocessado. Vou continuar
  checando periodicamente (agendado via `send_later`) e reportando aqui.
  Confirmação (K=13, sem regra de parada -- não tem treino/retentor)
  ainda não disparada; densidade final por dia já está decidida (K=26
  final, sem extensão), então o K=13 da confirmação já pode ser usado
  como estava quando a discovery terminar o Estágio 2.
- [~] **Fase 3 — gate de cobertura**
  Código pronto e testado (`benchmarks/sig_fast_v0/h2_coverage_gate_v0.py`,
  `evaluate_coverage_gate`): todos os 7 critérios do mandato (paridade
  Fase 1, não abortou, >=90% janelas processadas, >=95% buckets Estágio
  2, missing_source<=5%, >=95% reservas+fee, >=30 sobreviventes no
  treino) com self-check isolando cada critério. Ainda não rodado contra
  o `coverage_report.json` real -- esperando Fase 2 terminar.
- [~] **Fase 4 — avaliação discovery**
  Código pronto e testado (`benchmarks/sig_fast_v0/h2_discovery_evaluation_v0.py`):
  carrega preços/fee do banco selado (`PathTrade` + fee bps real, nunca
  inventado), reusa F2 (`find_causal_entry`/`first_barrier_touch`/
  `simulate_exit`) sem nenhuma mudança, calcula edge de barreira
  sinal-menos-baseline, escolhe a melhor das 6 saídas por EV no treino
  (exige EV>0 e PF>1), revalida a MESMA saída no retentor, classifica
  CANDIDATE/FAIL. Self-check cobre a agregação (cenário calculável a mão)
  + o pipeline completo a partir de um banco SQLite sintético (preço via
  reservas AMM na entrada, preço executado real no rastreamento
  pós-entrada -- bug real encontrado e corrigido durante a escrita do
  teste). Nunca abre o bloco de confirmação. Ainda não rodado com dado
  real -- esperando Fase 2 terminar.
- [~] **Fase 5 — confirmação (só se CANDIDATE)**
  Código pronto e testado (`benchmarks/sig_fast_v0/h2_confirmation_evaluation_v0.py`):
  `freeze_evaluation_rule` grava um manifesto (hash do código de
  avaliação + parâmetros + saída escolhida) ANTES de qualquer acesso ao
  bloco de confirmação; `run_confirmation_evaluation` **recusa rodar**
  (`ConfirmationNotFrozenError`) se esse manifesto não existir ainda --
  fail-closed. PASS/FAIL só em (a) edge>=10pp e (b) EV>0 e PF>1 pra saída
  JÁ escolhida (nunca reescolhe). Sensibilidade de custo 2x reportada
  como diagnóstico, nunca decide o veredito. Só roda de verdade se Fase 4
  (no dado real) produzir CANDIDATE -- e só depois do bloco de
  confirmação ser baixado (K=13, ainda não disparado -- depende da
  densidade final de Fase 2, que só se sabe quando discovery terminar).
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

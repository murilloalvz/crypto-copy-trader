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

## RESERVA 1 concluída: spec+código do paper ao vivo (self-check only)

- `docs/sig-fast-live-paper-log-v0-spec-2026-10-10.md` -- spec completa.
- `benchmarks/sig_fast_v0/live_paper_log_v0.py` -- código, só
  `--self-check` (nenhum ponto de entrada "rodar ao vivo" existe no
  arquivo, de propósito). Reusa sem alterar F2
  (`src/opportunity_path_metrics_v0.py`) e o padrão de "run congelado" de
  `src/shadow_execution_store.py`.
- Duas tabelas SQLite novas (append-only, idempotentes): registro do
  sinal no momento da detecção (config/contexto congelados) e registro do
  resultado medido depois (primeiro valor persistido é canônico, nunca
  sobrescrito).
- `python -m benchmarks.sig_fast_v0.live_paper_log_v0 --self-check` →
  `self-check OK`.
- Sem rede, sem chave privada, sem ordem, sem wiring a nenhum feed real --
  exatamente o escopo da tarefa de RESERVA.

## RESERVA 2 concluída: plano de H1 (copy) ao vivo com dados novos

- `docs/sig-fast-h1-live-collection-plan-v0-2026-10-10.md` -- plano
  consolidado, não execução. Nenhuma sessão ao vivo foi iniciada.
- Reproduz o que já está congelado (seção 2/1a do DRAFT) sem reabrir nem
  retunar nada; organiza pré-condições, cronograma (Passo 0 -> loader do
  cohort -> bloco 1 -> discovery -> confirmação -> veredito) e o que fica
  explicitamente para o operador decidir (run keys, datas, orçamento
  Helius).
- Identifica o gap de código real: o loader que lê
  `market_trade_observations` e monta `DiscoverySignalInput` pro
  `discovery_v0.py` (engine já pronto, agnóstico de família) ainda não
  existe para H1 -- documentado como próximo passo de código, não
  construído agora (sem dado real do cohort pra testar contra, e a
  tarefa pedida foi o plano, não o código).
- Explica por que a infra de RPC de H2 (EndpointRotator/RateLimiter) não
  se aplica à sessão WS contínua de H1 -- o StallGuard existente já é o
  mecanismo certo para esse padrão de carga.

## RESERVA 3 concluída: ampliar testes dos módulos novos (sem tocar congelado)

Nenhuma lógica de produção/critério econômico foi alterada -- só casos de
teste novos, isolados, dentro dos próprios `_self_check()` já existentes:

- `h2_coverage_gate_v0.py`: valor EXATAMENTE no limiar de cada critério
  passa (prova que as comparações são `>=`/`<=` inclusivas, sem folga
  implícita) + duas falhas simultâneas aparecem as duas (não só a
  primeira que o `all()` encontra) -- relevante porque o relatório real
  de H2 teve exatamente esse caso (2 de 7 critérios reprovando juntos).
- `h2_discovery_evaluation_v0.py`: `resolve_fee_pct_at`/`_total_fee_pct`
  testados isolados (sem banco, sem pipeline inteiro) -- fronteira causal
  exata (`<=`, nunca `<`), fallback pro primeiro evento quando não há
  nenhum no passado, e missing explícito (`None`) quando o pool não tem
  nenhum evento de fee ou quando falta qualquer um dos 3 componentes de
  bps. Essas duas funções só eram exercitadas antes pelo caminho feliz do
  self-check de pipeline completo.
- Todos os 7 self-checks dos módulos novos desta sessão (incluindo os 2
  das RESERVAS 1/2) rodados de novo depois das mudanças: todos OK, sem
  regressão.

## Mandato autônomo encerrado (2026-10-10)

Fases 0-6 concluídas (veredito `INCONCLUSIVE_SYSTEM` em H2, H2 permanece
aberta) + as 3 tarefas de RESERVA concluídas (paper ao vivo self-check,
plano de H1, testes ampliados). Nenhum bloqueador pendente. Nenhuma
execução de dinheiro real, nenhuma chave privada, nenhuma automação ligada
em nenhum momento desta sessão. Tudo commitado e empurrado pra
`research/rust-signal-plane-live-shadow-v0`. Próxima ação é do operador:
decidir sobre as duas correções de protocolo do gate de cobertura (Fase 3)
e, separadamente, se/quando iniciar a coleta ao vivo de H1 conforme o
plano consolidado.

## Decisão do operador recebida (2026-10-11): corrigir o gate (implementação, não limite)

Operador decidiu: as duas reprovações da Fase 3 são erros de
IMPLEMENTAÇÃO do gate, não limites errados. Addendum escrito no DRAFT
ANTES de qualquer execução (ver
`docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md`,
"Addendum — correção de implementação do gate de cobertura"). Passo 1
(hash do banco selado) já conferido nesta sessão: sha256 do
`discovery.db` atual == `stage2_hash` gravado no `coverage_report.json`
ANTES de qualquer cálculo de Fase 3/4 -- **MATCH**, banco inalterado.
Próximo: recomputar a correção (a)/(b) e re-rodar a Fase 3.

## Resultado da Fase 3 corrigida (2026-10-11): ainda INCONCLUSIVE_SYSTEM, margem pequena

Código corrigido (`h2_block_seal_v0.py`, `h2_coverage_gate_v0.py`) +
módulo novo `h2_coverage_recount_v0.py` (recomputa só o denominador de
buckets que faltava, read-only, mesmo banco). Hash conferido de novo
antes de gastar qualquer crédito: MATCH. Recontagem real rodada contra
os 126 pools selados (4.133 créditos, read-only, nenhum preço novo).

Resultado real:
- reservas+fee: 59,41% → **100,0%** (confirma artefato puro de cálculo).
- buckets total: 44,76% → **95,36%** (passa).
- buckets grupo sinal: **96,53%** (passa).
- buckets grupo baseline: **94,37%** (reprova, 0,63pp abaixo de 95%).

Só 1 de 9 critérios reprova agora (era 2 de 7, com margens enormes).
Causa raiz diagnosticada (268 créditos, read-only, `getTransaction` em
6 buckets não-resolvidos do pior pool do baseline): parecem ser trocas
roteadas via agregador (Prism + 1 program ID não identificado) via CPI,
que o decoder Carbon atual não decodifica (só a instrução de nível
superior, não `innerInstructions`).

**Veredito final: `INCONCLUSIVE_SYSTEM` de novo.** Por instrução
explícita do operador para este caso ("se reprovar: INCONCLUSIVE_SYSTEM
de novo, causa raiz documentada, sem mexer em limite, e parar") --
**parando aqui.** Fase 4 não rodou. Nenhum retorno/EV/barreira
calculado. H2 permanece aberta. Detalhe completo em
`docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md`
("Resultado real da Fase 3 CORRIGIDA").

## Investigação da causa raiz antes de corrigir o decoder (2026-10-11/12)

Antes de implementar a correção de decoder pedida numa rodada anterior
(ler `innerInstructions` em qualquer profundidade), investiguei a
premissa (read-only, ~1200 créditos): a hipótese do agregador via CPI
**não se confirma** -- o PumpSwap nunca aparece como `invoke`/`success`
nos logs das 20 transações verificadas, só como conta referenciada.
Reportado ao operador antes de tocar em qualquer código.

## Decisão do operador (2026-10-12): corrigir "trade vs. referência sem execução"

Causa real: erro de implementação de duas regras já pré-registradas,
não um problema de decoder. Addendum escrito no DRAFT ANTES de
qualquer código (ver "Addendum — correção de implementação 'trade vs.
referência sem execução'"). Teto mantido: última tentativa de sistema
neste bloco. Implementado `h2_trade_verification_v0.py` (commit
`acbf6d8`): classifica cada tx em `trade` / `not_trade` /
`missing_genuine` via diff de saldo das 2 contas-cofre do pool,
validado contra tx reais já diagnosticadas.

## Execução real da recontagem (2026-10-12): 4 ciclos, bug de checkpoint corrigido

Reclassificação de buckets por pool rodando em ciclos de 2h (mesmo
padrão da Fase 2 original). Ciclo 1: +16 pools. Ciclo 2: +27 pools
(43/126 acumulado). Ciclo 3: **+0 pools** -- bug real encontrado: o
checkpoint só salvava progresso quando um pool TERMINAVA inteiro, então
1 pool travado (`87JEX3WusGGKNXfrpViaHmgvQzLkiCN8nzbWggt5pump`) consumiu
as 2h sem nada persistido. Corrigido: checkpoint agora salva por
BUCKET, não só por pool (nenhum ciclo futuro pode perder progresso
parcial de novo).

### Três ajustes do operador (2026-10-12), sem mudar regra

1. Prioridade: recontagem dos 76 sobreviventes (parada em 20 trades
   confirmados) antes de continuar os pools.
2. Parada antecipada por bucket: primeira tx `trade`/`missing_genuine`
   já decide que o bucket fica no denominador -- não precisa checar o
   resto (só buckets 100% `not_trade` precisam checar todas).
3. Créditos: reportar consumo real e pausar perto do limite.

### Incidente de infraestrutura (2026-10-12): cota diária da QuickNode esgotada

Ao rodar a Fase 1 (prioridade) pela primeira vez com os 3 ajustes, o
processo ficou 2h em background **sem nenhum progresso e sem erro**
(nenhum sobrevivente salvo, hash do checkpoint inalterado). Diagnóstico
bounded (sondas diretas, read-only, <10 créditos) achou a causa raiz:

- QuickNode: cota diária gratuita **esgotada agora** (`X-Ratelimit-Remaining: 0`
  de `X-Ratelimit-Limit: 50000, 50000;w=86400`, reset em ~43.497s / ~12h
  a partir de ~11:55 UTC de 2026-10-12, ou seja reset perto de ~23:58 UTC).
- RPC público (`api.mainnet-beta.solana.com`) e Helius: ambos saudáveis,
  respondendo em <1s numa chamada direta.
- Causa do travamento: `EndpointRotator` sempre tenta a QuickNode
  primeiro (por desenho, pra poupar a Helius); a lógica de retry/backoff
  de 429 (`h2_pilot_v0.install_rate_limited_rpc`) insiste até 600s num
  endpoint antes do chamador cair pro próximo -- confirmado com uma
  chamada real isolada: sucesso em 613,9s, só depois de cair pro RPC
  público. Com dezenas de chamadas necessárias por sobrevivente, isso
  tornaria a Fase 1 inviável (~50h) até a cota resetar.
- Correção aplicada (só no script de execução, scratchpad, nada
  congelado/commitado tocado; puramente de ritmo/custo, zero efeito na
  classificação): `max_429_stall_seconds` reduzido de 600s pra 15s só
  nesta execução, enquanto a QuickNode estiver esgotada -- endpoint
  morto é abandonado em segundos, não minutos, e cai pro RPC
  público/Helius (saudáveis) rapidamente.
- Efeito colateral encontrado ao relançar: os 3 endpoints deram 429 ao
  mesmo tempo por um instante (rajada transitória, não a mesma
  exaustão de 12h da QuickNode), derrubando a execução inteira no
  primeiro sobrevivente. Corrigido com um retry curto (3 tentativas,
  20s de espera) só para esse padrão especifico de erro, por item
  (sobrevivente/pool) -- não é um novo limite nem muda nenhuma
  classificação, só evita perder o lote inteiro por um instante de
  rajada compartilhada.
- Relançado em background após as duas correções; hash re-verificado
  (bate de novo com o selo). Resultado da Fase 1 ainda pendente -- ver
  próxima seção quando disponível.

**Créditos/orçamento real (item 3 do operador), honesto:** QuickNode =
0 de 50.000/dia restante agora, reset em ~12h (número real, lido do
cabeçalho HTTP do próprio provedor, não estimado). RPC público e
Helius: sem número de cota mensal/diária configurado em nenhum lugar
deste código nem documentado no repositório -- não determinável a
partir daqui; ambos saudáveis agora. O circuit breaker
`SAFETY_PAUSE_AT_CUMULATIVE_CALLS=150000` no script é um limite
arbitrário de segurança, não uma medida real de cota.

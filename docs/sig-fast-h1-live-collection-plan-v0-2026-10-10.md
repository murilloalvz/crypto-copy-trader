# H1 (SIG-FAST-COPY-G) — plano de coleta ao vivo, consolidado (RESERVE 2, 2026-10-10)

## Status

**PLANO, não execução.** Nenhuma sessão ao vivo foi iniciada por este
documento. H1 já está `PRE-REGISTRADA` com sign-off do operador (seção 2 de
`docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md`, rev. 4,
"Addendum Fase 0"). O que faltava era consolidar o plano operacional num só
lugar, dado que o runbook original (`docs/sig-fast-disc-v0-runbook-v0-2026-10-08.md`)
mistura H1+H2 e ficou parcialmente obsoleto depois que a rev. 4 separou H2
para o caminho histórico selado. Este documento não introduz nenhum critério
econômico novo, não reabre nem retunа nenhuma regra congelada — só organiza o
que já está decidido e separa, de forma explícita, o que ainda falta
construir do que já está pronto.

## O que já está congelado (não decidir de novo aqui)

Tudo abaixo vem de `docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md`,
seção 2 (H1) e seção 1a — reproduzido aqui só como referência rápida, a fonte
de verdade continua sendo aquele documento:

- Gatilho: BUY on-chain de uma carteira do cohort smart-money.
- Cohort formado e congelado no **bloco 1** (primeiro bloco temporal da
  coleta); sinais de H1 só avaliados nos blocos seguintes, nunca dentro do
  bloco 1.
- `size_sol = 0.15`, janela primária `W=900s`, alvo +50%/stop -30%,
  **Δ primário = 30s fixo** (grade `{5,15,60,120}s` é só diagnóstico),
  terminal 1%/perna.
- Suporte mínimo: n>=30 pares primários no Δ primário.
- PASS exige: edge >=10pp (treino) + EV líquido>0 e PF>1 na melhor das 6
  saídas (treino) + ambos sustentam no holdout 30% **e** na confirmação
  prospectiva fresca separada, mesma regra, nada reajustado.
- Vetos: freeze authority (disponível), PQ-TR (fora até replicar), bundle/
  sniper/bump (depende do merge do plumbing).
- Cobertura mínima de preço derivável: >=95% dos trades no caminho.
- Execução continua manual; nenhum PASS aqui autoriza automação, shadow ou
  live money (CLAUDE.md).

## O que muda neste documento: consolidação operacional

### 1. Pré-condições antes de qualquer sessão real

1. Caminho de aquisição corrigido ativo: `run_live_shadow_v0` a partir do
   commit `fd87939` (`docs/sig-fast-live-engine-wiring-v0-2026-10-09.md`) —
   trades anteriores a isso não têm `base_reserves_raw`/`quote_reserves_raw`
   e não servem pra este discovery.
2. Passo 0 (2-4h, runbook `docs/sig-fast-passo-0-calibration-runbook-v0-2026-10-09.md`)
   rodado e aprovado pelo operador: cobertura de preço (`path_coverage_audit.py`)
   >=95%, `audit_graduation_continuity` sem drop sistemático, e uma amostra
   real de consumo de créditos Helius pra extrapolar o custo do bloco 1 e da
   janela de discovery.
3. Run keys frescas, nunca usadas, definidas pelo operador no momento do
   sign-off da sessão (não antes — evita que uma chave fique associada a um
   plano que ainda pode mudar de data).
4. PC sem suspensão de energia garantida pela duração inteira de cada sessão
   (bloco 1: 48-72h; discovery: 5-7 dias; confirmação: mesma ordem de
   grandeza) — sessões são contínuas, não retomáveis por reinício de
   container como o discovery histórico de H2 foi.

### 2. O que falta construir (ainda não existe, diferente de H2)

`benchmarks/sig_fast_v0/discovery_v0.py` (F7) é o motor de cálculo genérico
— já pronto, já testado (`--self-check` só com dado sintético), e **agnóstico
de família**: ele recebe uma lista já montada de sinais+baseline, nunca decide
o que conta como sinal. O que falta, especificamente para H1, é o **loader**
que lê `market_trade_observations`/`market_lifecycle_observations` do banco
real e produz essa lista — isto é trabalho de código ainda não feito, não um
bloqueio de decisão (a decisão, cohort do bloco 1 + regras de H1, já está
congelada na seção 2 do DRAFT, reproduzida acima). Ficou de fora desta rodada
de RESERVA porque:

- escrevê-lo contra um esquema de banco real sem nenhum dado real de H1 pra
  testar contra (o cohort só existe depois que o bloco 1 rodar de verdade)
  arriscaria um self-check que prova menos do que parece provar;
- a tarefa de RESERVA pedida aqui foi o **plano**, não o código — manter o
  escopo do que foi pedido evita alargar a tarefa sem evidência (CLAUDE.md).

Quando o operador decidir rodar H1 de verdade, o próximo passo de código é
esse loader: ler os trades da(s) carteira(s) do cohort no bloco 1, calcular
lucro realizado round-trip só com preço derivável nesta coleta nova (nunca
na memória do PQ-V1), congelar a lista do cohort, e então varrer os blocos
seguintes procurando BUYs dessas carteiras como `DiscoverySignalInput` pro
engine existente.

### 3. Infra reaproveitável de H2 (RPC) que NÃO se aplica direto a H1 (WS)

A Fase 2 do mandato autônomo construiu, pro discovery histórico de H2,
`EndpointRotator` (rotação entre endpoints RPC) e `RateLimiter`/circuit
breaker/credit tracker (`benchmarks/sig_fast_v0/h2_historical_backfill_v0.py`,
`h2_pilot_v0.py`) — essa infra é para **chamadas RPC pontuais em rajada**
(enumeração + busca de trades por janela). A coleta de H1 é uma **sessão WS
contínua** (`run_live_shadow_v0`), um padrão de carga diferente (poucas
chamadas de setup, depois um stream longo) — o `StallGuard` do loop
consumidor principal (rev. 3, item (b) do operador) já cobre o caso
equivalente (gap > 30s entre ticks → `break` explícito, nunca espera
indefinida), e é esse mecanismo, não o rate limiter de RPC, que é o
análogo correto pra H1. Não há necessidade de portar `EndpointRotator`/
`RateLimiter` para o caminho de H1 — seria complexidade sem necessidade
(ponytail: já existe o mecanismo certo pro padrão de carga certo).

O padrão de **retomada após reinício de container**, validado 3+ vezes
durante a Fase 2 de H2 (checar `PRAGMA integrity_check`/JSON do checkpoint,
relançar o mesmo script via processo rastreado, nunca `nohup ... &` dentro
de um `run_in_background`), **se aplica igual a H1**: uma sessão WS de dias
também precisa sobreviver a um reinício do container sem perder o cohort já
formado. Isso já é coberto pelo fato de `run_live_shadow_v0` persistir no
banco a cada trade (não em memória) — confirmar isso explicitamente é um
item do Passo 0, não deste plano.

### 4. Cronograma proposto (ordem, não datas — datas são decisão do operador)

1. Passo 0 (2-4h) — já tem runbook próprio, roda primeiro, decide se o motor
   está pronto.
2. Construir o loader do cohort (item 2 acima) — código, self-check contra
   dado sintético, sem rodar nada real ainda.
3. Bloco 1 (48-72h) — formação do cohort, congelado ao final.
4. Discovery (5-7 dias, 70/30 temporal dentro da janela) — só depois do
   bloco 1 fechado.
5. Confirmação prospectiva fresca (mesma ordem de grandeza de dias, sem
   overlap com discovery) — só depois do discovery estar congelado e
   commitado (hash antes do número, como em H2).
6. Veredito seguindo a seção 2 do DRAFT ("PASS exige todos"), registrado no
   mesmo commit no `docs/research-hypothesis-registry-v1-2026-10-04.md`.

Nenhum desses passos foi iniciado por este documento. Os números de duração
(2 a 6) continuam as mesmas estimativas provisórias já no DRAFT, "ainda não
confirmados pelo operador" — este plano não os re-decide, só os organiza em
sequência executável.

## O que este plano explicitamente não decide (fica para o operador)

- As run keys reais.
- A data de início de qualquer sessão.
- Se o orçamento de créditos Helius medido no Passo 0 é suficiente pros
  5-7 dias propostos (ou se o número precisa encolher).
- Se construir o loader do item 2 agora (antes do Passo 0 real) ou depois —
  ambas as ordens são defensáveis; este documento só nota que o loader é
  pré-requisito de código, não de decisão.

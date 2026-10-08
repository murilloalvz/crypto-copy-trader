# Pré-registro em lote — SIG-FAST-DISC-V0 — 2026-10-08 (RASCUNHO, rev. 2 2026-10-09)

Status: **RASCUNHO, aguardando sign-off do operador.** Nenhuma coleta foi rodada
para julgar este lote. Segue o formato de
`docs/templates/batch-preregistration-template-v1.md`, adaptado à régua nova do
SIG-FAST (caminho de preço, não retorno de horizonte fixo — ver
`docs/strategy-options-move-first-2026-10-07.md`, "Revisão 4"/"Opção SIG-FAST").

**Rev. 2 (2026-10-09): revisão do operador aplicada integralmente.** Mudanças
principais desta revisão, detalhadas abaixo: (1) discovery deixa de ser
retrospectivo — exige coleta nova com o motor corrigido (ver
`docs/sig-fast-live-engine-wiring-v0-2026-10-09.md`); (2) Δ primário passa a
ser fixo em 30s (os outros valores da grade ficam só diagnóstico); (3)
multiplicidade recontada: 2 famílias × 6 saídas no treino = 12 comparações de
decisão; (4) as 6 perguntas abertas da rev. 1 estão respondidas e aplicadas.
Nada da rev. 1 foi apagado silenciosamente — este documento substitui a rev. 1
por completo, autocontido.

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`.

Instrumento de medida (congelado para este lote, trocar exige lote novo):
`src/opportunity_path_metrics_v0.py` (F2) + `src/opportunity_path_baseline_v0.py`
(F3) + modelo de custo em `docs/sig-fast-cost-model-v0-2026-10-08.md` (F4).
Persistência de caminho de preço: F1b + wiring do motor ao vivo (F1b +
`docs/sig-fast-live-engine-wiring-v0-2026-10-09.md`), branch
`sig-fast-price-path-persistence-v0`, ainda não mergeada na autoridade —
aguarda replicação do PQ-TR.

## Item (c) da métrica primária — resolvido pelo operador

Resposta do operador, substitui a nota de interpretação da rev. 1: **(c) = os
dois, não um ou outro.** (i) Retenção de 30%: o resultado de (a) e (b) no
holdout de 30% dentro do discovery precisa se sustentar, com o MESMO sinal, o
mesmo Δ e a mesma regra de saída escolhidos nos 70% de treino — nada
reajustado ao ver o holdout. (ii) Separadamente, depois do discovery+holdout
congelados e commitados, uma confirmação prospectiva fresca (coleta nova, sem
overlap com o discovery) precisa repetir o mesmo resultado, com a regra
idêntica. As duas etapas são exigidas, em sequência — isso é a disciplina de
3 passos do registro (PASS no pré-registrado → PASS na replicação fresca →
Gate 2) aplicada à régua de caminho de preço.

## 1. Coleta que julga este lote

**Discovery NÃO é retrospectivo.** Os trades já capturados antes de
2026-10-09 não têm reservas (`base_reserves_raw`/`quote_reserves_raw`
nulos — confirmado em F1c contra o sandbox, 100% de cobertura faltante). O
motor ao vivo só passou a gravar esses campos a partir do commit `fd87939`
(`docs/sig-fast-live-engine-wiring-v0-2026-10-09.md`). **O discovery exige
coleta nova**, rodando o motor corrigido, em sessões longas e contínuas — ver
"Plano de coleta" abaixo.

- Run key(s): `<a definir no sign-off — chaves frescas, nunca usadas>`
- Caminho de aquisição: `run_live_shadow_v0` (motor corrigido, commit `fd87939`
  ou posterior) → `market_trade_observations` com `base_amount_raw`/
  `quote_amount_raw`/`base_reserves_raw`/`quote_reserves_raw` populados
  (PumpSwap completo; Pump sem `base_reserves_raw` até o bloqueador do Rust
  não-congelado ser resolvido pelo operador — ver doc de wiring).
- Janela e cohorts: split temporal **70/30 dentro do discovery**; confirmação
  prospectiva fresca **depois**, em coleta separada, sem overlap temporal com
  o discovery.
- Instrumento de medida: `opportunity_path_metrics_v0` + `opportunity_path_baseline_v0`,
  **tamanho fixo de 0,15 SOL por posição** (confirmado pelo operador — nada de
  US$, nada de cotação SOL/USD necessária; `size_sol=0.15` direto no
  `CostModel`/`find_causal_entry`).
- **Δ primário = 30s, fixo** (confirmado pelo operador — provisório até ele
  medir a latência real dele). Δ ∈ {5, 15, 60, 120}s continuam na grade, mas
  só como **diagnóstico** — nunca contam para o veredito PASS/FAIL, só servem
  pra calibrar quando o operador souber a latência real dele.
- **Terminal primário = 1%/perna** (confirmado pelo operador). A grade
  {0%, 1%} de F4 permanece como sensibilidade diagnóstica, não como parte da
  decisão.
- Gates de sistema que precisam passar antes de qualquer número econômico:
  cobertura de preço derivável (`benchmarks/sig_fast_v0/path_coverage_audit.py`,
  F1c) **>=95%** dos trades no caminho com preço derivável (confirmado pelo
  operador); nenhum worker/traceback error na coleta; missingness explícita
  onde a cobertura falhar (nunca tratada como 0).
- Condições operacionais: saída redirecionada para arquivo, hash dos dados
  commitado antes de qualquer cálculo (ver F7), PC sem suspensão durante toda
  a coleta (sessões de horas, não minutos).

### Plano de coleta

**Passo 0 — calibração, não julga nada (puro systems check, não gasta
tentativa).** Sessão curta (2-4h) só para medir, com dado real, a taxa de
sinais/hora de cada família e a cobertura de preço (`path_coverage_audit.py`)
sob o motor corrigido. Isso não lê outcome (contagem de sinais e cobertura são
métricas de sistema, não preço/retorno) e informa o dimensionamento real dos
passos seguintes, em vez de travar nas estimativas abaixo.

**Estimativa de taxa de sinal (de systems data já coletado, não é outcome)**:
o job de enumeração da conta de migração (parado, servia H, dado 100%
sistêmico) registrou, em dias recentes (jul/ago 2026), entre ~730 e ~1.220
graduações pump→PumpSwap por dia (`pools=` no log de
`benchmarks/move_first_h_coverage_audit_v0`), média aproximada **~950/dia
(~40/hora)**. MemeTrans mede que ~72,96% dessas caem abaixo de 40% do preço
de migração em 20min — ou seja, **no máximo ~27% (~10-11/hora) passam só essa
condição** da definição de sobrevivente de H2; o filtro adicional de ">=20
trades nos últimos 5min" reduz esse número mais, mas **não tenho dado medido
de quanto** — fica como "não confirmado", a calibrar no Passo 0, não
inventado aqui. Para H1, a taxa de sinal depende do cohort de carteiras, que
só existe depois do bloco 1 (abaixo) — **não estimável antes da primeira
sessão real**.

**Bloco 1 — formação do cohort H1 (bloco temporal inicial, congelado depois).**
Proposta: 48-72h contínuas de coleta antes de qualquer avaliação de sinal de
H1 — tempo suficiente pra algumas carteiras acumularem round-trips realizados
com preço (compra+venda, ambas com preço derivável nesta mesma coleta nova).
**Não confirmado com dado real** quantas carteiras atingem round-trips
suficientes nesse intervalo — o Passo 0 não mede isso (é outcome de lucro
realizado, ainda que sem ser o veredito da hipótese); a calibração real desse
bloco só acontece rodando-o. H2 **não depende** deste bloco — pode gerar
sinais desde o primeiro minuto de coleta, pois seu gatilho é por token, não
por cohort.

**Discovery (H2 desde o início; H1 só após o bloco 1).** Estimativa, com a
taxa acima e suporte mínimo n>=30 por família: a ~10/hora (limite superior,
H2, antes do filtro de volume), **n=30 é alcançável em poucas horas** de
coleta contígua; o fator dominante de incerteza é o filtro de volume não
medido e, para H1, o tamanho do cohort que emergir do bloco 1. **Proposta
conservadora**: uma janela contínua única de **5-7 dias** (cobre o bloco 1 de
H1 inteiro + folga para H2 e H1 atingirem n>=30 cada, considerando vetos que
reduzem a amostra elegível — PQ-TR ainda fora, bundle/sniper ainda fora até o
merge). Dividir em 70/30 por ordem temporal dentro dessa janela.

**Confirmação prospectiva fresca.** Nova janela contínua, iniciada só depois
do discovery (regra+Δ+saída) estar congelada e commitada — sem overlap. Mesma
ordem de grandeza de dias que o discovery, para ter suporte comparável.

**Stall guard.** O motor de discovery (`benchmarks/sig_fast_v0/discovery_v0.py`,
F7) já tem `StallGuard`. A **coleta em si** (`run_live_shadow_v0`) não foi
auditada nesta revisão para um stall guard próprio de sessão longa (horas) —
**pendência a verificar antes de uma sessão real de dias**, não assumida como
já resolvida.

**Custo de créditos Helius da coleta contínua.** **Não confirmado nesta
revisão** — o volume de trades Pump/PumpSwap observado no sandbox já mostrou
picos de >250k trades/dia só para a conta de migração (não é o volume de
notificação WS, que é por evento, não por polling, mas ainda proporcional ao
volume on-chain real). Recomendo o operador checar o uso do plano Helius dele
depois do Passo 0 (2-4h), que já vai dar uma amostra real de consumo pra
extrapolar pros 5-7 dias propostos — não estimado aqui sem dado de preço do
plano, que eu não tenho.

**Os números de duração acima (Passo 0, bloco 1 de 48-72h, janela de
discovery de 5-7 dias) são estimativas derivadas de taxa de migração
observada, não medição direta de taxa de sinal — ainda não confirmados pelo
operador.** Recomendo rodar o Passo 0 primeiro e só então fixar os números
maiores; isso vai para as perguntas abertas no fim deste documento, não foi
decidido aqui.

## 2. Hipóteses (K = 2)

### H1 — SIG-FAST-COPY-G (copy-trading filtrado, desenho E11)

- **Família**: coordenação / qualidade de wallet.
- **Tipo**: entrada (família candidata dentro do caminho SIG-FAST).
- **Origem**: nova — primeira vez que o desenho do E11 é testado com dado
  próprio sob a régua de caminho de preço; não é resgate de V48/V55/V68/PQ-V1
  (features de fluxo genérico, não smart-money). **Aprovado pelo operador
  como hipótese nova** (mecanismo ≠ PQ-V1).
- **As 5 perguntas**:
  1. De quem vem o dinheiro: vantagem posicional/informacional da carteira
     smart-money copiada (E11, arXiv 2601.08641v3) — quem compra depois dela,
     ou vende antes dela, paga a diferença.
  2. Por que read-only/30s atrasado ainda captura: **não está respondido pelo
     paper** (achado da revisão 3 do memo — o +3% do E11 assume atraso
     ~zero). É a pergunta central que este discovery mede empiricamente, no
     Δ primário fixo de 30s (grade {5,15,60,120}s só diagnóstico).
  3. Evidência: E11, peer-reviewed, mesmo domínio (Pump.fun); Grade A/B no
     `docs/research-evidence-registry-v1-2026-09-02.md`.
  4. Teste mais barato: **coleta nova** (não retrospectivo, ver seção 1) —
     mais barato que alternativas porque reusa o mesmo motor/coleta de H2.
  5. Critério de morte: ver "PASS exige" abaixo.
- **Gatilho de entrada (sinal)**: BUY detectado on-chain de uma carteira do
  cohort smart-money. **Formação do cohort (resolvido pelo operador)**: lucro
  realizado calculado **só nos dados novos desta coleta, com preço
  derivável** (nunca na memória do PQ-V1, nunca em dado antigo sem reservas)
  — o cohort é formado no **bloco 1** (primeiro bloco temporal da coleta, ver
  "Plano de coleta") e **congelado** a partir daí; sinais de H1 só são
  avaliados nos blocos temporais seguintes ao bloco 1, nunca dentro dele.
  `signal_time` = `chain_time` do trade da carteira copiada.
- **Dependências de observabilidade**: `slot`/`creator`/`creation_slot` (branch
  `bundle-bot-detection-v0-plumbing`, não mergeada) para os filtros
  bundle/sniper/bump do E11 (Algoritmos 1-3). Sem esses campos, os filtros
  bundle/sniper/bump ficam **INCONCLUSIVE por cobertura**, não pulados
  silenciosamente.
- **Vetos (rejeição)**:
  - PQ-TR (LOW vs ALL, corte `-86.0484432047999` congelado) — **aguarda
    replicação do PQ-TR** antes de entrar como veto ativo; sem ela, fica fora
    do veto set desta rodada (não substituído por outro corte).
  - Freeze authority (`src/opportunity_onchain_hazard.py::freeze_authority_present`)
    — disponível hoje, sem custo.
  - Bundle/sniper/bump (E11 Algoritmos 1-3) — depende do merge do plumbing
    acima.
  - Histórico do criador — a definir a métrica exata no sign-off (não
    inventada aqui).
- **Janela primária**: W=900s (15min), alvo +50%/stop −30% para a métrica (a),
  **Δ=30s fixo**. Outras janelas (60/300/3600s), barreiras (±20/100/200%) e
  Δ∈{5,15,60,120}s são diagnóstico.
- **Suporte mínimo**: n>=30 pares primários (no Δ primário fixo; mesma régua
  da CHURN-V0/EBPQ-REPL-V0).
- **PASS exige todos**:
  1. P(+50% antes de −30% em 15min) do sinal − baseline (F3) >= 10pp, no
     Δ primário (30s);
  2. EV líquido > 0 **e** PF líquido > 1, sob a melhor das 6 regras de saída
     (`EXIT_RULE_IDS`) escolhida nos 70% de treino, Δ=30s, terminal 1%/perna
     (custos do sweep 1x/2x só como diagnóstico adicional, disciplina do
     Gate 2);
  3. (1)+(2) se sustentam no holdout de 30% (mesmo Δ, mesma saída, nada
     reajustado) **e** na confirmação prospectiva fresca separada (ver "Item
     (c)" acima).
- **FAIL**: qualquer um dos 3 falha no holdout ou na confirmação fresca, ou o
  edge (1) não aparece no Δ primário.
- **INCONCLUSIVE**: suporte < n mínimo, ou cobertura de preço derivável abaixo
  de 95%.
- **Controles/placebo**: baseline pareado (F3) — K tokens elegíveis no mesmo
  `signal_time`, mesma venue, mesma faixa de idade, mesma atividade mínima,
  seed fixa. MFE reportado só como teto teórico, nunca somado ao EV/PF.
- **O que um PASS não prova**: fill real, latência além da simulada (30s é a
  do treino, não necessariamente a real do operador — grade diagnóstica serve
  pra isso), execução automatizada, shadow, live. Execução continua manual
  (CLAUDE.md).

### H2 — SIG-FAST-POSTMIG (sobreviventes pós-migração, desenho MemeTrans)

- **Família**: metadado do token / momentum de sobrevivência.
- **Tipo**: entrada (família candidata dentro do caminho SIG-FAST).
- **Origem**: nova — usa a semântica de timing do MemeTrans (quando NÃO
  entrar), nunca testada aqui como gatilho positivo de entrada; não toca
  nenhuma feature de hipótese fechada deste programa.
- **As 5 perguntas**:
  1. De quem vem o dinheiro: MemeTrans (arXiv 2602.13480, n=41.470) mede que
     ~72,96% dos tokens caem para <40% do preço de migração em 20min — quem
     compra no instante da graduação, às cegas, paga a maioria desse colapso.
     A minoria que sobrevive esse intervalo já filtrou boa parte do pânico de
     venda inicial; o lado comprador que entra depois herda uma população com
     menos vendedores de pânico ainda por vir.
  2. Por que read-only/30s atrasado ainda captura: o próprio desenho exige
     esperar 20 minutos pós-graduação antes de entrar — atraso de segundos é
     irrelevante por construção.
  3. Evidência: MemeTrans, mesma fonte já verificada diretamente na Tabela 6 do
     paper (citada em `docs/strategy-options-move-first-2026-10-07.md`, Opção F).
  4. Teste mais barato: coleta nova (ver seção 1), mesma coleta de H1.
  5. Critério de morte: ver "PASS exige" abaixo.
- **Gatilho de entrada (sinal) — definição única, resolvida pelo operador (não
  é mais grade de X)**: `idade_pos_graduacao == 20 minutos` **e** preço no
  marco de 20min >= 40% do preço de migração (definição exata do MemeTrans)
  **e** >=20 trades nos últimos 5 minutos antes do marco (15-20min
  pós-graduação). `signal_time` = o instante do marco dos 20 minutos.
- **Dependências de observabilidade**: `market_lifecycle_observations` com
  venue="pumpswap" pra graduação; `base_reserves_raw`/`quote_reserves_raw`
  (F1b) pra medir volume/liquidez sustentada sem reconstruir o histórico de
  swap inteiro; `base_amount_raw`/`quote_amount_raw` pra contar os >=20 trades
  e derivar o preço no marco.
- **Vetos (rejeição)**: os mesmos 4 de H1 (PQ-TR aguardando replicação, freeze
  authority disponível, bundle/sniper/bump dependente do merge, histórico do
  criador a definir) — pouco relevante numa moeda já sobrevivente 20min, mas
  ainda computável se os campos existirem.
- **Janela primária**: W=900s, alvo +50%/stop −30%, mesma métrica (a) de H1,
  **Δ=30s fixo**.
- **Suporte mínimo**: n>=30 pares primários (Δ=30s fixo).
- **PASS exige todos**: os mesmos 3 itens de H1 (edge >=10pp no Δ primário; EV
  líquido>0 e PF>1 sob a melhor das 6 saídas; sustenta no holdout de 30% E na
  confirmação fresca).
- **FAIL**: mesmos critérios de H1.
- **INCONCLUSIVE**: suporte insuficiente, ou cobertura de preço/graduação
  abaixo de 95%.
- **Controles/placebo**: baseline pareado (F3), mesma venue="pumpswap", mesma
  faixa de `idade_pos_graduacao` (20min ± tolerância), mesma atividade
  mínima. MFE só descritivo.
- **O que um PASS não prova**: o mesmo de H1.

## Candidatas consideradas e deixadas de fora (registro da triagem, não é descarte formal)

- **Aceleração de fluxo de compra nos primeiros segundos** (mecanismo do
  `BUY-ACCEL`/`mf_buy_event_rate_acceleration_per_s2`): deixada de fora desta
  rodada. `BUY-ACCEL` já é uma família FECHADA (FAIL como alpha, retida só
  como evidência de tail-risk) — qualquer família aqui que reusasse esse
  mecanismo contaria como hipótese nova em dado novo, exigindo OK explícito do
  operador por essa regra do work order. Na dúvida ("se usa feature de
  hipótese fechada, na dúvida deixar de fora"), não entrou nesta rodada.
- Nenhuma terceira família com evidência própria/externa limpa e não
  sobreposta a hipótese fechada foi encontrada nesta pesquisa — K=2 ficou
  abaixo do teto de 5 por falta de candidata adicional qualificada, não por
  limite artificial.

## 3. Multiplicidade e próximos passos

- Este lote julga **K = 2** hipóteses na mesma coleta (discovery + holdout
  70/30 + confirmação prospectiva fresca separada).
- **Comparações de decisão, recontadas (rev. 2)**: 2 famílias × 6 regras de
  saída (seleção da melhor em treino, Δ=30s fixo) = **12 comparações**.
  Métrica (a) é lida uma vez por família no Δ primário (+2), totalizando
  **14 leituras que entram na decisão**. A grade diagnóstica
  (Δ∈{5,15,60,120}s, janelas 60/300/3600s, barreiras ±20/100/200%) é
  computada e reportada, mas **nenhuma delas conta para PASS/FAIL** — são só
  calibração para quando o operador souber a latência real dele.
- Hipótese com PASS → status `PASS (aguarda replicação)` no registro →
  replicação sozinha, regra congelada, chave nova, pré-registro próprio
  (nota: a confirmação prospectiva fresca exigida pelo item (c) **já cobre**
  essa replicação — um PASS que já passou pelas duas etapas desta própria
  rodada vai direto pro Gate 2, não precisa de uma 3ª coleta redundante,
  salvo decisão em contrário do operador).
- Hipótese com FAIL/KILL → fecha. Nenhuma variação é testada de novo nesta
  amostra.
- Falha de sistema da coleta → nenhuma hipótese recebe veredito; o lote pode
  ser reaproveitado numa coleta nova sem mudança de regra.
- **Critério de morte do caminho inteiro (não só de uma família)**: se o edge
  (métrica a) some no Δ primário (30s) para AMBAS as famílias, o caminho
  manual SIG-FAST morre — automação continua bloqueada pelo modo atual de
  qualquer forma, então isso não abre uma porta de automação, só encerra o
  programa de memecoin pela regra de parada já registrada (nenhum caminho 2
  reservado foi ocupado). A grade diagnóstica (incluindo Δ>=30s mais largo)
  informa esse veredito mas não o decide isoladamente.

## 4. Proibido depois de ver dado

Mudar corte, direção, horizonte, suporte, gates ou controles; incluir ou
remover hipóteses do lote; olhar só um subgrupo; combinar as duas famílias num
score; trocar a regra de saída ou o Δ escolhidos no treino depois de ver o
holdout ou a confirmação; reabrir `BUY-ACCEL` ou qualquer outra família
fechada para "salvar" um resultado fraco; promover um valor da grade
diagnóstica (Δ≠30s) a decisório depois de ver que ele teria passado.

## 5. Atualização do registro

Depois do resultado: uma linha por hipótese em
`docs/research-hypothesis-registry-v1-2026-10-04.md` e os contadores
atualizados, no mesmo commit que registra o resultado. Esta linha de
RASCUNHO não conta como `PRE-REGISTRADA` até o sign-off do operador.

## Perguntas abertas — todas as 6 da rev. 1 respondidas pelo operador

1. ~~Confirmar a leitura do item (c).~~ Resolvido: "os dois" (ver seção
   dedicada acima).
2. ~~Latência real / terminal.~~ Resolvido: Δ=30s e terminal 1% como
   primários provisórios, até o operador medir a latência real dele.
3. ~~Tamanho de posição.~~ Resolvido: 0,15 SOL fixo.
4. ~~Cotação SOL/USD.~~ Resolvido: desnecessária, tudo em SOL.
5. ~~Piso de cobertura / grade de X do H2.~~ Resolvido: piso=95%; H2 usa X=20min
   único (não é mais grade).
6. ~~Grade de X reduzida a valor único ou mantida como grade.~~ Resolvido:
   reduzida a valor único (20min), conforme item 5.

### Novas perguntas abertas (desta revisão, ainda sem resposta)

1. Confirmar a duração/sessões do "Plano de coleta" acima (Passo 0 de
   calibração, bloco 1 de 48-72h, janela de discovery de 5-7 dias) — são
   estimativas a partir de taxa de migração observada (dado de sistema já
   coletado), não medição direta de taxa de sinal.
2. Métrica exata do veto "histórico do criador" (ainda não definida em
   nenhuma revisão).
3. Checar/implementar stall guard próprio pra sessões de coleta de
   horas/dias em `run_live_shadow_v0` (distinto do stall guard do
   `discovery_v0.py`, que já existe) antes da sessão real.
4. Custo de créditos Helius da coleta contínua de dias — não confirmado,
   proposta é calibrar no Passo 0 antes de comprometer a janela de dias.

# Pré-registro em lote — SIG-FAST-DISC-V0 — 2026-10-08 (RASCUNHO)

Status: **RASCUNHO, aguardando sign-off do operador.** Nenhuma coleta foi rodada
para julgar este lote. Segue o formato de
`docs/templates/batch-preregistration-template-v1.md`, adaptado à régua nova do
SIG-FAST (caminho de preço, não retorno de horizonte fixo — ver
`docs/strategy-options-move-first-2026-10-07.md`, "Revisão 4"/"Opção SIG-FAST").

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`.

Instrumento de medida (congelado para este lote, trocar exige lote novo):
`src/opportunity_path_metrics_v0.py` (F2) + `src/opportunity_path_baseline_v0.py`
(F3) + modelo de custo em `docs/sig-fast-cost-model-v0-2026-10-08.md` (F4).
Persistência de caminho de preço: F1b (branch `sig-fast-price-path-persistence-v0`,
ainda não mergeada na autoridade — aguarda replicação do PQ-TR).

## Nota de interpretação (pedir confirmação do operador)

O work order original diz, na métrica primária, item (c): "retentor com o
mesmo sinal". A palavra não é clara isolada. Interpretação adotada aqui,
consistente com a disciplina de validação já usada no resto do registro
(PASS no pré-registrado → PASS de novo na replicação com a regra congelada):
**(c) = o resultado de (a) e (b) precisa se sustentar na confirmação
prospectiva fresca, com a definição do sinal idêntica à do discovery (nenhum
parâmetro reajustado depois de ver o dado da confirmação).** Se essa não for a
leitura pretendida, corrigir antes do sign-off — nada foi decidido
silenciosamente, fica marcado aqui como pendência aberta.

## 1. Coleta que julga este lote

- Run key(s): `<a definir no sign-off — chaves frescas, nunca usadas>`
- Caminho de aquisição: trades já capturados via `src/pump_bonding_stream.py` /
  `src/pumpswap_stream.py` (estendidos em F1b) + `market_trade_observations`;
  nenhuma coleta nova de outcome é necessária para o discovery retrospectivo —
  só os trades já existem no `.db` local do operador.
- Janela e cohorts: split temporal **70/30 dentro do discovery**; confirmação
  prospectiva fresca separada, com a regra idêntica congelada (ver "Nota de
  interpretação").
- Instrumento de medida: `opportunity_path_metrics_v0` + `opportunity_path_baseline_v0`,
  tamanho de posição ~US$25 (padrão do programa), convertido pra SOL pela
  cotação SOL/USD no momento do sinal (fonte a definir no sign-off — não
  inventada aqui).
- Gates de sistema que precisam passar antes de qualquer número econômico:
  cobertura de preço derivável (`benchmarks/sig_fast_v0/path_coverage_audit.py`,
  F1c) acima de um piso mínimo por token (valor a definir no sign-off, ex.
  >=80% dos trades no caminho com preço derivável); nenhum worker/traceback
  error na coleta; missingness explícita onde a cobertura falhar (nunca
  tratada como 0).
- Condições operacionais: saída redirecionada para arquivo, hash dos dados
  commitado antes de qualquer cálculo (ver F7), PC sem suspensão durante a
  coleta.

## 2. Hipóteses (K = 2)

### H1 — SIG-FAST-COPY-G (copy-trading filtrado, desenho E11)

- **Família**: coordenação / qualidade de wallet.
- **Tipo**: entrada (família candidata dentro do caminho SIG-FAST).
- **Origem**: nova — primeira vez que o desenho do E11 é testado com dado
  próprio sob a régua de caminho de preço; não é resgate de V48/V55/V68/PQ-V1
  (features de fluxo genérico, não smart-money).
- **As 5 perguntas**:
  1. De quem vem o dinheiro: vantagem posicional/informacional da carteira
     smart-money copiada (E11, arXiv 2601.08641v3) — quem compra depois dela,
     ou vende antes dela, paga a diferença.
  2. Por que read-only/segundos atrasado ainda captura: **não está respondido
     pelo paper** (achado da revisão 3 do memo — o +3% do E11 assume atraso
     ~zero). É a pergunta central que este discovery mede empiricamente, grade
     Δ ∈ {5,15,30,60,120}s.
  3. Evidência: E11, peer-reviewed, mesmo domínio (Pump.fun); Grade A/B no
     `docs/research-evidence-registry-v1-2026-09-02.md`.
  4. Teste mais barato: histórico de transações já capturado (mesmo caminho do
     WFWD-v2), sem coleta nova.
  5. Critério de morte: ver "PASS exige" abaixo.
- **Gatilho de entrada (sinal)**: BUY detectado on-chain de uma carteira do
  cohort smart-money, selecionado por critério de dados em holdout temporal
  (não lista fixa — WFWD-v2/v60 já mostraram que lista fixa falha por amostra).
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
- **Janela primária**: W=900s (15min), alvo +50%/stop −30% para a métrica (a).
  Outras janelas (60/300/3600s) e barreiras (±20/100/200%) são diagnóstico.
- **Suporte mínimo**: n>=30 pares primários por Δ (mesma régua da CHURN-V0/EBPQ-REPL-V0).
- **PASS exige todos**:
  1. P(+50% antes de −30% em 15min) do sinal − baseline (F3) >= 10pp, em pelo
     menos um Δ da grade;
  2. EV líquido > 0 **e** PF líquido > 1, sob a melhor das 6 regras de saída
     (`EXIT_RULE_IDS`) escolhida nos 70% de discovery, custos do sweep 1x/2x
     (disciplina do Gate 2);
  3. (a)+(b) se sustentam na confirmação prospectiva fresca com a regra
     idêntica (ver "Nota de interpretação").
- **FAIL**: qualquer um dos 3 falha na confirmação fresca, ou o edge (a) não
  aparece em nenhum Δ da grade.
- **INCONCLUSIVE**: suporte < n mínimo, ou cobertura de preço derivável abaixo
  do piso do gate de sistema.
- **Controles/placebo**: baseline pareado (F3) — K tokens elegíveis no mesmo
  `signal_time`, mesma venue, mesma faixa de idade, mesma atividade mínima,
  seed fixa. MFE reportado só como teto teórico, nunca somado ao EV/PF.
- **O que um PASS não prova**: fill real, latência além da simulada, execução
  automatizada, shadow, live. Execução continua manual (CLAUDE.md).

### H2 — SIG-FAST-POSTMIG (sobreviventes pós-migração, desenho MemeTrans)

- **Família**: metadado do token / momentum de sobrevivência.
- **Tipo**: entrada (família candidata dentro do caminho SIG-FAST).
- **Origem**: nova — usa a semântica de timing do MemeTrans (quando NÃO entrar),
  nunca testada aqui como gatilho positivo de entrada; não toca nenhuma feature
  de hipótese fechada deste programa (CD-V0/CD-PROMO-V0 são sobre concentração
  de holders, não sobre timing de sobrevivência pós-graduação — mecanismo
  diferente, não é resgate).
- **As 5 perguntas**:
  1. De quem vem o dinheiro: MemeTrans (arXiv 2602.13480, n=41.470) mede que
     ~72,96% dos tokens caem para <40% do preço de migração em 20min — quem
     compra no instante da graduação, às cegas, paga a maioria desse colapso.
     A minoria que sobrevive esse intervalo já filtrou boa parte do pânico de
     venda inicial; o lado comprador que entra depois herda uma população com
     menos vendedores de pânico ainda por vir.
  2. Por que read-only/segundos atrasado ainda captura: o próprio desenho exige
     esperar X minutos pós-graduação antes de entrar — atraso de segundos é
     irrelevante por construção (mesmo argumento do antigo caminho H, mas
     aplicado a um gatilho de entrada no token, não a LP).
  3. Evidência: MemeTrans, mesma fonte já verificada diretamente na Tabela 6 do
     paper (citada em `docs/strategy-options-move-first-2026-10-07.md`, Opção F).
  4. Teste mais barato: trades já capturados pós-graduação (PumpSwap,
     `market_trade_observations` + `market_lifecycle_observations` pra saber o
     timestamp de graduação) — sem coleta nova.
  5. Critério de morte: ver "PASS exige" abaixo.
- **Gatilho de entrada (sinal)**: BUY no token (não LP) quando o token atinge
  `idade_pos_graduacao >= X minutos` **e** volume mínimo sustentado nesse
  intervalo (grade X ∈ {10, 20, 30} min — a definir qual sobrevive ao sign-off;
  volume mínimo a definir sem olhar o resultado). `signal_time` = o instante em
  que a condição de sobrevivência+volume é satisfeita.
- **Dependências de observabilidade**: `market_lifecycle_observations` com
  venue="pumpswap" pra graduação; `base_reserves_raw`/`quote_reserves_raw`
  (F1b) pra medir volume/liquidez sustentada sem reconstruir o histórico de
  swap inteiro.
- **Vetos (rejeição)**: os mesmos 4 de H1 (PQ-TR aguardando replicação, freeze
  authority disponível, bundle/sniper/bump dependente do merge, histórico do
  criador a definir) — pouco relevante numa moeda já sobrevivente há minutos,
  mas ainda computável se os campos existirem.
- **Janela primária**: W=900s, alvo +50%/stop −30%, mesma métrica (a) de H1.
- **Suporte mínimo**: n>=30 pares primários por combinação (X, Δ).
- **PASS exige todos**: os mesmos 3 itens de H1 (edge >=10pp em algum Δ; EV
  líquido>0 e PF>1 sob a melhor das 6 saídas; sustenta na confirmação fresca).
- **FAIL**: mesmos critérios de H1.
- **INCONCLUSIVE**: suporte insuficiente, ou cobertura de preço/graduação
  abaixo do piso do gate de sistema.
- **Controles/placebo**: baseline pareado (F3), mesma venue="pumpswap", mesma
  faixa de `idade_pos_graduacao` (não a idade total do token), mesma atividade
  mínima. MFE só descritivo.
- **O que um PASS não prova**: o mesmo de H1.

## Candidatas consideradas e deixadas de fora (registro da triagem, não é descarte formal)

- **Aceleração de fluxo de compra nos primeiros segundos** (mecanismo do
  `BUY-ACCEL`/`mf_buy_event_rate_acceleration_per_s2`): deixada de fora desta
  rodada. `BUY-ACCEL` já é uma família FECHADA (FAIL como alpha, retida só
  como evidência de tail-risk) — qualquer família aqui que reusasse esse
  mecanismo contaria como hipótese nova em dado novo, exigindo OK explícito do
  operador por essa regra do work order. Na dúvida ("se usa feature de
  hipótese fechada, na dúvida deixar de fora"), não entrou nesta rodada. Pode
  voltar como H3 futura, com OK explícito do operador e mecanismo
  explicitamente reformulado (não um retune do corte fechado).
- Nenhuma terceira família com evidência própria/externa limpa e não
  sobreposta a hipótese fechada foi encontrada nesta pesquisa — K=2 ficou
  abaixo do teto de 5 por falta de candidata adicional qualificada, não por
  limite artificial.

## 3. Multiplicidade e próximos passos

- Este lote julga **K = 2** hipóteses na mesma coleta (discovery retrospectivo
  + confirmação prospectiva fresca).
- Comparações contadas: 2 famílias × 5 valores de Δ (entrada) × 6 regras de
  saída (seleção da melhor em treino) = **60** combinações na seleção de
  EV/PF, mais 2×5=**10** leituras da métrica (a) (probabilidade de barreira)
  = **70 comparações no total deste lote**, registradas aqui antes de ver
  qualquer resultado (regra 4 do registro). H2 soma mais 3 valores de X
  (janela de sobrevivência) × as mesmas combinações — a definir exatamente no
  sign-off se X entra como grade adicional ou como escolha única pré-fixada;
  se entrar como grade, o total sobe e deve ser recontado **antes** da coleta,
  não depois.
- Hipótese com PASS → status `PASS (aguarda replicação)` no registro →
  replicação sozinha, regra congelada, chave nova, pré-registro próprio.
- Hipótese com FAIL/KILL → fecha. Nenhuma variação é testada de novo nesta
  amostra.
- Falha de sistema da coleta → nenhuma hipótese recebe veredito; o lote pode
  ser reaproveitado numa coleta nova sem mudança de regra.
- **Critério de morte do caminho inteiro (não só de uma família)**: se o edge
  (métrica a) some em Δ >= 30s para AMBAS as famílias, o caminho manual
  SIG-FAST morre — automação continua bloqueada pelo modo atual de qualquer
  forma, então isso não abre uma porta de automação, só encerra o programa de
  memecoin pela regra de parada já registrada (nenhum caminho 2 reservado foi
  ocupado).

## 4. Proibido depois de ver dado

Mudar corte, direção, horizonte, suporte, gates ou controles; incluir ou
remover hipóteses do lote; olhar só um subgrupo; combinar as duas famílias num
score; trocar a regra de saída escolhida no treino depois de ver a
confirmação; reabrir `BUY-ACCEL` ou qualquer outra família fechada para
"salvar" um resultado fraco.

## 5. Atualização do registro

Depois do resultado: uma linha por hipótese em
`docs/research-hypothesis-registry-v1-2026-10-04.md` e os contadores
atualizados, no mesmo commit que registra o resultado. Esta linha de
RASCUNHO não conta como `PRE-REGISTRADA` até o sign-off do operador.

## Perguntas abertas para o operador (antes do sign-off)

1. Confirmar a leitura da "Nota de interpretação" do item (c) da métrica
   primária, ou corrigir.
2. Latência real do operador na prática (qual Δ da grade é o mais realista
   para ele) e qual terminal ele usa de fato (afeta qual `terminal_fee_pct` da
   grade {0%,1%} é mais representativo — ver F4).
3. Tamanho de posição real que ele pretende usar (confirmar ~US$25 ou outro).
4. Fonte da cotação SOL/USD no momento do sinal (não definida aqui).
5. Piso mínimo de cobertura de preço derivável para o gate de sistema (ex.
   80%?) e piso de volume mínimo / grade de X minutos para H2 — ambos a
   decidir sem olhar o resultado.
6. Se H2's grade de X (10/20/30min) deve ser reduzida a um valor único
   pré-registrado (mais simples, menos multiplicidade) ou mantida como grade
   (mais exploratória, multiplicidade maior, já contabilizada acima).

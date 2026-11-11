# Parte G — Caminho até o edge: hipóteses ranqueadas (Rodada 16)

**REVISADO na Rodada 17 (item 7, 2026-11-10/11), por EVIDÊNCIA — nunca por preferência.** Mudanças:
reordenação (alvo curto desce, carteiras forward/bundle sobem), downgrade do limite de 1,5% do
supply de P1 para P2 (com a conta pro tamanho de posição real), correção da entrada no suporte (B4:
30-55% acima do suporte, stop mediano ~33%, nunca "curto") e correção de direção no red team sobre o
viés do H1 (fechado-apenas SUBESTIMA o desempenho, não o contrário). Texto original da Rodada 16
preservado onde não contestado; cada mudança está marcada inline com "Rodada 17, item 7".

PAPER/READ-ONLY. Esta parte é síntese e julgamento, não um script read-only — ela não "acha um bug",
ela decide, com a evidência acumulada nas Partes A-F desta rodada mais o histórico das 16 rodadas
deste projeto, **onde vale mais a pena gastar o próximo tempo de coleta**. Nenhuma recomendação aqui
implica em "a hipótese X tem edge" — toda promoção formal continua exigindo os 3 passos do registro
de hipóteses (PASS pré-registrado, replicação fresca, Gate 2) e, em qualquer caso envolvendo dado
novo, um placebo/controle que replique o sinal se o efeito for confundimento (lição RED-COHORT/PQ-V1).

## Ponto de partida (o que já sabemos, sem repetir a evidência completa — ver Partes A-F)

- Sinal ≈ passeio aleatório em várias leituras exploratórias já feitas (B2-B8, varredura_v3); saídas
  (saída fiel, grade de 24 variantes) não mudaram isso de forma decisiva — **gestão de saída não é
  onde está o edge, se ele existir**.
- Poder estatístico em N=30 é baixo (MDE≈1,2-1,4R para V3; ≈2,1-2,4R para carteiras forward) — qualquer
  efeito real, mas modesto, tende a `INCONCLUSIVO` por muito tempo com o desenho atual (cauda, N=30/60).
- PQ-V1 (participante nativo, fonte on-chain agregada) foi KILL depois de separação descritiva forte
  — lição: "parece promissor visualmente" não basta; placebo/controle pareado é agora **obrigatório**
  em qualquer hipótese de dado novo (já incorporado no pré-registro de carteiras forward).
- V1/V2/V3 compartilham literalmente o mesmo detector-base (achado da Parte C) — reparametrizar
  indefinidamente sobre o MESMO mecanismo tem retorno decrescente; um bug no detector-base (se
  existir) afeta as 3 simultaneamente, então "3 hipóteses" não são 3 chances independentes.
- Achados P1 das Partes A-F que PRECISAM ser corrigidos (ou pelo menos citados) antes de confiar em
  qualquer número de R/edge: H1 nunca migrada pro motor de horizonte fixo (Parte C — ver também a
  quantificação de direção do viés na Rodada 17, item 6: fechado-apenas SUBESTIMA o desempenho real,
  nunca o contrário — correção abaixo no red team); `CostModel` da via estatística usa posição fixa
  de 0,15 SOL, desacoplada da banca real (Parte E); `horizonte_fixo.py` não aplica o veto de candle
  corrompido (Parte B — já corrigido na Rodada 17, item 1, reusando a mesma função do caminho ao
  vivo); V3 ainda não tem detecção de clone/vamp NO ALERTA ao vivo (Parte B, já P2 — a Rodada 17
  item 2 corrigiu um problema DIFERENTE, a identidade por mint nos scripts exploratórios offline,
  nunca o `vamp_risk` do caminho ao vivo, que continua exclusivo de V1/V2).
- **REBAIXADO de P1 para P2 (Rodada 17, item 7)**: o limite de 1,5% do supply nunca ser aplicado
  (Parte E) é um fato de código verificado, mas a conta com o tamanho de posição real do operador
  (~US$30, não o `mao_fixa_usd=$10` modelado) mostra que ele dificilmente BATE em qualquer sinal que
  o próprio detector já aceitaria — ver seção 0 abaixo para a conta completa.

## Ranking (ordem de prioridade recomendada)

**Nota de leitura**: os números abaixo são a prioridade (Rodada 17, item 7) — a ORDEM FÍSICA das
seções no arquivo preserva a posição original da Rodada 16 pra facilitar diff/revisão, então não lê
0→1→2→3→4→5 de cima a baixo. Para a ordem de leitura/execução, use o "Resumo da ordem de execução
recomendada" no final do documento.

### 0. [PRÉ-REQUISITO, fazer ANTES de qualquer hipótese nova — barato, não é "edge" em si] Higiene de qualidade de sinal
- **Lógica**: nenhuma das hipóteses abaixo vale a pena testar se o R medido já está contaminado por
  candles corrompidos não vetados, clones/vamp não filtrados na V3, ou posições modeladas maiores do
  que o supply/liquidez permitiria de verdade. Isto não é uma hipótese econômica — é a condição para
  que qualquer p-valor futuro signifique algo.
- **Evidência a favor de priorizar**: achados P1 da Parte B (`horizonte_fixo.py` sem
  `candle_confiavel`, mesma classe do incidente McRib -561R — **já corrigido na Rodada 17, item 1**)
  e Parte E (`CostModel` com posição fixa 0,15 SOL desacoplada da banca real) e Parte C (H1 nunca
  migrada pro motor correto — ver Rodada 17 item 6 pra direção do viés e rascunho de emenda).
  Nenhuma evidência contra — é manutenção, não especulação.
- **REBAIXADO de P1 para P2 (Rodada 17, item 7)**: o limite de 1,5% do supply nunca aplicado (Parte
  E) deixa de estar nesta lista de pré-requisito urgente. A conta com o tamanho de posição REAL do
  operador (~US$30, não o `mao_fixa_usd=$10` modelado em `ParamsV1`): `posicao_pct_supply = 100 ×
  posicao_usd / (entry_price × supply) = 100 × posicao_usd / MC_na_entrada`. Pra bater o limiar de
  1,5% com US$30, precisaria de `MC_na_entrada <= 100×30/1,5 = US$2.000`. Mas o próprio detector V3
  exige `P_peak >= runner_min_mc = US$300.000` e a zona só começa depois de uma queda de 80-90%
  (`drop_min`/`drop_max`, `params_v1.py:45-46`) — o piso da zona (suporte S) já fica em torno de
  `300.000 × (1-0,90) = US$30.000` no cenário MAIS extremo, e a entrada (achado B4, Rodada 11: 30-55%
  ACIMA do suporte) fica ainda mais alta. Ou seja: **qualquer sinal que o detector já aceitaria tem
  MC de entrada tipicamente >= US$30.000-40.000, 15-20x acima do limiar que faria US$30 importarem**
  — o bug de código é real, mas sua chance de realmente distorcer qualquer R já medido é baixa dado
  o piso estrutural de MC que o próprio detector impõe. Mantido como P2 (corrigir visibilidade/
  relatório é barato e vale a pena, mas não é um pré-requisito antes de confiar em H1).
- **Custo/tempo**: baixo — são 2-3 correções pontuais e bem localizadas (ver Partes B/C para o
  código exato), cada uma isolada, nenhuma precisa de coleta nova de dado externo.
- **Amostra necessária**: nenhuma — é correção de código/instrumentação, julgada por revisão, não por
  N.
- **Pré-registro/controle**: qualquer correção que mude o DESFECHO já reportado de H1 (ex.: migrar
  H1 para horizonte fixo) precisa de uma emenda formal datada (muda o hash de
  `PLANO_ANALISE_PREREGISTRADO.md`) — nunca um ajuste silencioso. Correções que só ADICIONAM
  instrumentação/veto sem mudar H1 (vamp na V3, veto de candle corrompido no motor exploratório) não
  tocam hash de H1 e podem ser feitas sem emenda.

### 3. [REBAIXADO nesta rodada — precisa de justificativa nova antes de voltar a subir] Redesenho estrutural: alvo curto de alta frequência
- **Lógica econômica**: o próprio projeto já mediu (rodadas 9-14) que a estratégia de cauda (2ª
  corrida pós-queda) tem poder estatístico baixo em N=30 e só decide `FUTIL` em N=60 — o tempo até
  qualquer veredito formal é longo porque o desfecho primário (R@72h de uma posição que pode levar
  dias para resolver) é lento. A lógica de "um alvo CURTO gera N mais rápido" continua válida em
  termos de VELOCIDADE de coleta — mas isso é ortogonal a se o alvo curto TEM edge, que é o que
  decide se vale a pena.
- **REBAIXADO (Rodada 17, item 7) — evidência CONTRA já medida, nunca testada antes desta rodada**:
  a curva de toque já medida pelo projeto mostra `P(+1R antes de -1R) = 39,8%` contra um equilíbrio
  de 50% — pra um alvo fixo de ±1R (a versão mais simples/direta de "alvo curto"), isso dá
  `EV = 0,398×(+1R) + 0,602×(-1R) ≈ -0,204R`, ou seja, **negativo**, na direção ERRADA pra justificar
  prioridade alta. Um "alvo curto de alta frequência" que simplesmente decide mais rápido sobre o
  MESMO payoff ±1R não ataca o bottleneck estatístico — ele gera N rápido para confirmar um EV já
  conhecido como desfavorável. Downgrade mantido até que a hipótese seja refeita com uma justificativa
  que NÃO dependa do payoff fixo ±1R simétrico já medido como perdedor (ex.: um alvo assimétrico, um
  horizonte genuinamente mais curto que ainda não teve sua PRÓPRIA curva de toque medida, ou uma
  condição de entrada diferente da atual) — a lógica de velocidade de coleta continua válida, só não
  basta mais por si só.
- **Custo/tempo**: médio — reusa o MESMO detector/candles já cacheados (zero coleta nova de dado de
  mercado), só precisa de um horizonte de decisão mais curto e um novo pré-registro (nunca uma
  reinterpretação do que já existe). Pode rodar em paralelo, silenciosa, sem tocar V1/V2/V3.
- **Amostra necessária**: recalcular MDE para o horizonte curto escolhido (reusar a mesma metodologia
  da `EMENDA_PODER_ESTATISTICO_N30`, nunca inventar um número novo) — mas o N necessário por TEMPO de
  coleta deveria ser muito menor dado o giro mais rápido, SE a justificativa do item acima for
  resolvida primeiro.
- **Pré-registro/controle**: pré-registro NOVO e próprio (horizonte, desfecho, critério, Holm/
  Bonferroni se comparado a V1/V2/V3), placebo = MESMO tipo de controle pareado já usado no resto do
  projeto (pools sem sinal, mesma fase/tf). Só volta a ser candidata de alto valor esperado depois de
  resolver o downgrade acima — não é mais a prioridade #1 só por atacar a velocidade de coleta.

### 1. [JÁ EM ANDAMENTO, BEM DESENHADO, CUSTO=TEMPO] Carteiras rastreadas / smart money (forward, V3)
- **Lógica econômica**: carteiras "pro" curadas pelo operador supostamente têm informação/skill acima
  da média; presença delas nos top holders no momento do sinal deveria correlacionar com retorno
  melhor SE a lista for genuinamente informativa.
- **Evidência a favor/contra**: nenhum dado real ainda (tabela nova, Rodada 15 Parte 3/4). PQ-V1
  (fonte de dado DIFERENTE — métrica on-chain agregada sobre qualquer participante) foi KILL após
  separação descritiva forte falhar o teste de profit factor — isto não é evidência direta contra
  ESTA hipótese (lista curada manualmente é uma fonte diferente), mas é a razão pela qual o placebo
  aqui é OBRIGATÓRIO, não opcional (já incorporado no pré-registro).
- **Custo/tempo**: zero custo de engenharia adicional (já implementado e rodando); custo é só TEMPO —
  V3 é um gerador raro de sinais, então acumular n=20/braço pode levar bastante tempo de coleta.
- **Amostra necessária**: 20 tokens/braço mínimo declarado (`PREREGISTRO_CARTEIRAS_FORWARD_2026-11-10.
  md`), com MDE honesto já calculado (~2,1-2,4R — grande, espera-se `INCONCLUSIVO` por um tempo).
- **Pré-registro/controle**: já feito, já com placebo obrigatório. Ação recomendada: NENHUMA mudança,
  só paciência — e revisar a cobertura (`cobertura_valida`) periodicamente via `saude.py` pra garantir
  que o RPC dedicado da Rodada 15 está realmente coletando.

### 2. [LÓGICA ECONÔMICA FORTE, NUNCA TENTADO NESTE PROJETO, CUSTO DE ENGENHARIA MÉDIO-ALTO] Bundle/cluster de funding
- **Lógica econômica**: no universo pump.fun/Solana, é um padrão conhecido (fora deste projeto,
  observação de mercado geral) que insiders/snipers financiam múltiplas carteiras a partir de uma
  fonte comum antes de operar um lançamento — detectar um CLUSTER de carteiras com a mesma origem de
  funding comprando cedo é um sinal de dinheiro informado mais direto do que uma lista estática
  curada (carteiras "pro") e mais específico que uma métrica agregada de qualidade (PQ-V1).
- **Evidência a favor/contra**: nenhuma testada NESTE projeto ainda — é uma hipótese genuinamente
  nova, nunca vista/julgada por nenhum dado deste repositório (vantagem: "o que já foi visto nunca
  pode julgar a si mesmo" não se aplica aqui, é limpo).
- **Custo/tempo**: médio-alto — exige rastrear a origem de funding das carteiras compradoras cedo
  (`getSignaturesForAddress`/`getTransaction` em cadeia, um grafo de transferências antes do
  lançamento), um custo de RPC NOVO e não-trivial, por token. **Risco direto de repetir o erro da
  Rodada 15** (RPC compartilhado/orçamento mal dimensionado) se implementado sem o MESMO cuidado de
  RPC dedicado/orçamento por tentativa já corrigido para carteiras_pro.
- **Amostra necessária**: mesma ordem de grandeza de carteiras forward (nível token, mínimo ~20/braço
  declarado antes de olhar).
- **Pré-registro/controle**: pré-registro novo e próprio; placebo = mesmo padrão de pools de controle
  sem cluster detectado, pareados por fase/tf — reusar `_carteiras_pools_controle` como referência de
  desenho.

### 4. [LÓGICA PLAUSÍVEL, MAS JÁ TESTADA (DESFAVORAVELMENTE) EM LINHA RELACIONADA] Fluxo/participação genérico
- **Lógica econômica**: features de fluxo (participação de compradores, buy-share, contagem de
  participantes distintos) proxy "demanda real" vs volume artificial/bot.
- **Evidência CONTRA já existente (fonte relacionada, não este código)**: `CLAUDE.md` raiz documenta
  que a linha de pesquisa do Signal Plane (branch diferente, mesmo projeto maior) já testou
  `flow60_buy_share_pct` (V55→V68) e o holdout formal **FALHOU** (`V68 Flow60 buy-share holdout`,
  CLOSED), e PQ-V1 (participante nativo, métrica relacionada) foi KILL. Mesma CATEGORIA de ideia
  (qualidade/fluxo de participante), duas tentativas formais já fecharam sem edge.
- **Recomendação**: NÃO retestar a mesma métrica/seletor (proibido por CLAUDE.md: "never rescue V68
  using MID, a different horizon, new bins, another feature, or same-sample tuning"). Só vale a pena
  se for uma feature GENUINAMENTE nova (não um retune), e mesmo assim entra depois de #1-#3 no
  ranking, dado o precedente desfavorável na categoria.
- **Custo/tempo**: médio-alto (mesma classe de custo de RPC/dado on-chain do item 3).

### 5. [BARATO, JÁ RODANDO, RESOLVE CATEGORIA EXISTENTE — NÃO ABRE FRONTEIRA NOVA] Entrada no suporte — reclassificada (Rodada 17, item 7)
- **CORRIGIDO (Rodada 17, item 7)**: a formulação anterior ("entrar na reação de suporte com stop
  LOGO ABAIXO/CURTO é uma estrutura de payoff favorável, perda truncada e pequena") está incorreta à
  luz do achado B4 (Rodada 11, Parte B4 — quartis de risco%/distância a S/topo por gatilho): a
  entrada real acontece **30-55% ACIMA do suporte**, com stop **mediano ~33%** de distância — isto
  é um stop de risco MODERADO, nunca "curto"/"logo abaixo". O argumento de payoff estrutural (perda
  truncada e pequena, taxa de acerto não precisa ser alta) **não se sustenta** com um risco mediano
  de ~33%: uma perda de ~33% por trade não é "pequena" no sentido que o argumento original presumia.
- **Lógica econômica revisada**: o grupo `reacao_suporte` continua uma estrutura de entrada
  legítima (reação de preço num nível de suporte testado), mas o argumento de justificar prioridade
  por "stop curto = payoff favorável mesmo com baixa taxa de acerto" precisa ser substituído por uma
  avaliação direta do R médio/mediano do grupo (já coletado via H2/Holm) — sem o atalho do argumento
  estrutural, que esta rodada mostrou inválido para o risco% real observado.
- **Evidência**: já é o grupo `reacao_suporte` de H2 (`PLANO_ANALISE_PREREGISTRADO.md`), dentro da
  família de Holm existente — zero engenharia nova, só precisa de mais dado ao vivo pra atingir n>=10.
- **Custo/tempo**: zero — já instrumentado, já rodando. Recomendação: deixar rodar passivamente, não é
  prioridade de ATENÇÃO nova, mas não custa nada continuar coletando — SEM se apoiar no argumento de
  payoff estrutural corrigido acima pra justificar isso.

## O que NÃO vale mais a pena testar agora

- **Mais variantes de gestão de SAÍDA** (saída fiel, grade de 24 variantes de saídas parciais já
  rodaram) — o próprio projeto já tem evidência acumulada de que mudar COMO sai não muda o quadro
  fundamental; investir mais tempo aqui tem retorno marginal baixo comparado às hipóteses acima.
- **Reparametrizar V1→V2→V3 indefinidamente sobre o MESMO detector-base** sem evidência de bug
  específico — como a Parte C confirmou, as 3 versões compartilham literalmente `DetectorV1`/
  `simulate_v1`; variar só `Params` é a MESMA aposta repetida, não 3 chances independentes.
- **Reabrir PQ-V1** com qualquer retune (cutoff, horizonte, feature derivada da mesma fonte) — CLOSED/
  KILL por disciplina do projeto, nunca resgatável na mesma amostra.
- **Perseguir mais estratos/subgrupos dentro de H2-H14** sem dado novo — a família de Holm já está
  carregada (achado P1 da Parte D: múltiplas famílias paralelas já acumuladas); adicionar mais cortes
  sem n suficiente só aumenta a superfície de busca sem aumentar poder.

## Red team — o que tornaria esta conclusão (negativa/cautelosa) errada

- **H1 nunca migrada pro horizonte fixo (achado da Parte C) — CORRIGIDO na direção (Rodada 17, item
  6)**: a formulação anterior assumia que TODOS os sinais nunca resolvidos por regra (`aberto` +
  `perdido_offline`) são "sistematicamente PIORES" — mas isso mistura dois subgrupos com evidência
  em direções OPOSTAS. Pra `aberto` especificamente, a emenda `EMENDA_2026-11-05_HORIZONTE_FIXO_
  PROPOSTA.md` já documentou, por escrito, o mecanismo contrário: "perdedores fecham rápido (stop
  bate cedo) e entram logo na amostra; vencedores demoram e são excluídos enquanto correm" — ou
  seja, excluir `aberto` tende a jogar fora VITÓRIAS que ainda estão correndo, não derrotas. Isso
  faz H1 hoje estar **MENOS favorável** do que o horizonte fixo mostraria, não mais (ver quantificação
  e rascunho de emenda completos em `docs/pos-runner-v1/RODADA_17_ITEM6_VIES_H1_CENSURA_HORIZONTE_
  FIXO.md`). Já `perdido_offline` especificamente (token que o bot perdeu de vista porque o projeto
  morreu/rugou) é um subgrupo MENOR e mais estreito que PODE, sim, ser sistematicamente pior — mas
  nunca foi separado do `aberto` geral na formulação anterior. A direção NETA (soma dos dois efeitos)
  é desconhecida sem decompor a amostra real — esta sessão não tem acesso ao banco pra fazer essa
  decomposição (ver limitação no documento citado). Migrar H1 pro motor correto continua a correção
  certa; a motivação é separar os dois efeitos, não assumir uma direção única sem evidência.
- **Candle corrompido não vetado no motor exploratório (achado da Parte B)**: um outlier tipo McRib
  (-561R) não detectado nas análises que alimentam `varredura_v3.py` pode estar distorcendo a MÉDIA
  (nunca a mediana, que é robusta a outlier único) de qualquer leitura exploratória já feita — se
  essa distorção for na direção NEGATIVA, o projeto pode estar descartando prematuramente uma
  estratégia que, sem o outlier, pareceria mais promissora (ou vice-versa).
- **Universo de replay/retro (`retro_lote1`/`universo_admitido`) tem viés de seleção**: só inclui
  pools que JÁ sobreviveram o suficiente para ter candles cacheados em `pr_bars` — um token que
  morreu rápido demais para nunca ser admitido/rastreado nunca aparece em NENHUMA análise retrospectiva
  (nem como vencedor nem como perdedor). Se esses tokens mortos-rápido forem desproporcionalmente
  perdedores OU desproporcionalmente os melhores "foguetes" perdidos, a amostra toda já está torta
  antes de qualquer detector decidir algo.
- **Realismo de execução na direção CONTRÁRIA à pessimista**: a Parte E mostrou que o R modelado é um
  teto (faltam custos reais). Mas é logicamente possível que o detector tenha um pequeno edge real que
  os custos de execução (ainda não medidos de verdade) simplesmente NUNCA teriam superado de qualquer
  forma — nesse cenário, a conclusão correta seria "há sinal, mas não é executável", diferente de
  "não há sinal" — a auditoria atual não consegue distinguir os dois cenários com o dado disponível
  aqui.
- **Bug não encontrado nesta rodada**: esta auditoria (Partes A-F) não teve acesso ao banco real da
  VM — qualquer bug que só se manifesta com volume real de dados/candles de produção (ex.: um caso de
  borda em `fill_gaps`, ou um comportamento de `DexPaprika` fallback nunca exercitado num fixture)
  pode existir sem que esta rodada o tenha encontrado.

## Resumo da ordem de execução recomendada (REORDENADO na Rodada 17, item 7 — ver evidência em cada item)

1. Corrigir/documentar a higiene de sinal (item 0) — barato, condição para confiar em qualquer R;
   já avançado na Rodada 17 (candle corrompido em `horizonte_fixo.py`, direção do viés do H1
   quantificada). O limite de 1,5% do supply SAI desta lista de pré-requisito (rebaixado a P2 — a
   conta com posição real de ~US$30 mostra que ele dificilmente bate em qualquer sinal que o
   detector já aceitaria).
2. Deixar carteiras forward (item 1, ex-item 2) rodando — já correto, já bem desenhado, só precisa
   de tempo. SOBE na ordem porque não depende de nenhuma justificativa pendente.
3. Avaliar o custo real de RPC do bundle/funding (item 2, ex-item 3) antes de implementar — se o
   orçamento permitir sem repetir o erro da Rodada 15, é a próxima fronteira de dado genuinamente
   nova, com lógica econômica forte e nunca testada. SOBE na ordem pelo mesmo motivo.
4. Redesenhar o alvo curto de alta frequência (item 3, ex-item 1) — **DESCE na ordem**: a curva de
   toque já medida (P(+1R)=39,8%, EV≈-0,20R pro payoff ±1R simétrico) é evidência CONTRA a versão
   simples desta hipótese; só volta a ser prioridade alta com uma justificativa que não dependa desse
   payoff já medido como perdedor.
5. Fluxo/participação genérico (item 4) fica em espera, só com feature genuinamente nova.
6. Entrada no suporte / `reacao_suporte` (item 5) continua rodando passivamente — o argumento de
   "payoff estrutural, stop curto" foi CORRIGIDO (B4: entrada 30-55% acima do suporte, stop mediano
   ~33%, nunca curto); avaliação deste grupo passa a depender do R médio/mediano real, sem o atalho
   estrutural.

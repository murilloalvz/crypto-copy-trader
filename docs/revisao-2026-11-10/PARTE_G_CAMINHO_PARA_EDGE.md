# Parte G — Caminho até o edge: hipóteses ranqueadas (Rodada 16)

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
  qualquer número de R/edge: H1 nunca migrada pro motor de horizonte fixo (Parte C); `CostModel` da
  via estatística usa posição fixa de 0,15 SOL, desacoplada da banca real (Parte E); limite de 1,5%
  do supply nunca é aplicado (Parte E); `horizonte_fixo.py` não aplica o veto de candle corrompido
  (Parte B); V3 não tem detecção de clone/vamp (Parte B).

## Ranking (ordem de prioridade recomendada)

### 0. [PRÉ-REQUISITO, fazer ANTES de qualquer hipótese nova — barato, não é "edge" em si] Higiene de qualidade de sinal
- **Lógica**: nenhuma das hipóteses abaixo vale a pena testar se o R medido já está contaminado por
  candles corrompidos não vetados, clones/vamp não filtrados na V3, ou posições modeladas maiores do
  que o supply/liquidez permitiria de verdade. Isto não é uma hipótese econômica — é a condição para
  que qualquer p-valor futuro signifique algo.
- **Evidência a favor de priorizar**: achados P1 da Parte B (`horizonte_fixo.py` sem
  `candle_confiavel`, mesma classe do incidente McRib -561R) e Parte E (`CostModel` com posição fixa
  0,15 SOL desacoplada da banca real; limite 1,5% supply nunca aplicado) e Parte C (H1 nunca migrada
  pro motor correto). Nenhuma evidência contra — é manutenção, não especulação.
- **Custo/tempo**: baixo — são 3-4 correções pontuais e bem localizadas (ver Partes B/C/E para o
  código exato), cada uma isolada, nenhuma precisa de coleta nova de dado externo.
- **Amostra necessária**: nenhuma — é correção de código/instrumentação, julgada por revisão, não por
  N.
- **Pré-registro/controle**: qualquer correção que mude o DESFECHO já reportado de H1 (ex.: migrar
  H1 para horizonte fixo) precisa de uma emenda formal datada (muda o hash de
  `PLANO_ANALISE_PREREGISTRADO.md`) — nunca um ajuste silencioso. Correções que só ADICIONAM
  instrumentação/veto sem mudar H1 (vamp na V3, veto de candle corrompido no motor exploratório) não
  tocam hash de H1 e podem ser feitas sem emenda.

### 1. [MAIOR EXPECTATIVA DE INFORMAÇÃO POR TEMPO] Redesenho estrutural: alvo curto de alta frequência, em PARALELO à cauda
- **Lógica econômica**: o próprio projeto já mediu (rodadas 9-14) que a estratégia de cauda (2ª
  corrida pós-queda) tem poder estatístico baixo em N=30 e só decide `FUTIL` em N=60 — o tempo até
  qualquer veredito formal é longo porque o desfecho primário (R@72h de uma posição que pode levar
  dias para resolver) é lento. Um alvo CURTO (ex.: decidir em minutos/poucas horas, R menor mas
  resolvido rápido) gera N muito mais rápido por unidade de tempo de coleta — o mesmo poder
  estatístico que hoje leva semanas/meses de paper poderia ser atingido em dias. Economicamente,
  momentum de meme-coin recém-graduado é um fenômeno de MINUTOS/HORAS (decaimento de informação
  rápido); esperar uma 2ª perna de reaceleração pode estar testando um fenômeno estruturalmente mais
  raro e lento do que o que o mercado realmente oferece com mais frequência.
- **Evidência a favor**: nenhuma direta ainda (hipótese nova) — mas é apoiada indiretamente por TODA
  a dificuldade de poder estatístico já documentada (MDE alto, INCONCLUSIVO esperado) com o desenho
  lento atual, e pela própria natureza do detector (candles de 5m/1h já capturam movimento rápido).
- **Evidência contra**: nenhuma testada ainda; risco de que um alvo curto simplesmente reproduza o
  mesmo "sinal ≈ aleatório" já visto, só mais rápido (não resolve o problema de fundo, só acelera a
  descoberta de que não há edge, SE não houver).
- **Custo/tempo**: médio — reusa o MESMO detector/candles já cacheados (zero coleta nova de dado de
  mercado), só precisa de um horizonte de decisão mais curto e um novo pré-registro (nunca uma
  reinterpretação do que já existe). Pode rodar em paralelo, silenciosa, sem tocar V1/V2/V3.
- **Amostra necessária**: recalcular MDE para o horizonte curto escolhido (reusar a mesma metodologia
  da `EMENDA_PODER_ESTATISTICO_N30`, nunca inventar um número novo) — mas o N necessário por TEMPO de
  coleta deveria ser muito menor dado o giro mais rápido.
- **Pré-registro/controle**: pré-registro NOVO e próprio (horizonte, desfecho, critério, Holm/
  Bonferroni se comparado a V1/V2/V3), placebo = MESMO tipo de controle pareado já usado no resto do
  projeto (pools sem sinal, mesma fase/tf). **Esta é a hipótese de maior valor esperado desta rodada**
  precisamente porque ataca o bottleneck estatístico que o projeto já identificou e sofreu na própria
  pele (futilidade suspensa, N=60 necessário) — não é uma aposta em "este feature tem edge", é uma
  aposta em "resolver a pergunta mais rápido", que tem valor mesmo se a resposta final for negativa.

### 2. [JÁ EM ANDAMENTO, BEM DESENHADO, CUSTO=TEMPO] Carteiras rastreadas / smart money (forward, V3)
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

### 3. [LÓGICA ECONÔMICA FORTE, NUNCA TENTADO NESTE PROJETO, CUSTO DE ENGENHARIA MÉDIO-ALTO] Bundle/cluster de funding
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

### 5. [BARATO, JÁ RODANDO, RESOLVE CATEGORIA EXISTENTE — NÃO ABRE FRONTEIRA NOVA] Entrada no suporte com stop curto
- **Lógica econômica**: entrar na reação de suporte com stop logo abaixo é uma estrutura de payoff
  favorável (perda truncada, pequena) mesmo que a taxa de acerto não seja alta — argumento estrutural,
  não preditivo.
- **Evidência**: já é o grupo `reacao_suporte` de H2 (`PLANO_ANALISE_PREREGISTRADO.md`), dentro da
  família de Holm existente — zero engenharia nova, só precisa de mais dado ao vivo pra atingir n>=10.
- **Custo/tempo**: zero — já instrumentado, já rodando. Recomendação: deixar rodar passivamente, não é
  prioridade de ATENÇÃO nova, mas não custa nada continuar coletando.

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

- **H1 nunca migrada pro horizonte fixo (achado da Parte C)**: se `perdido_offline`/sinais nunca
  resolvidos por regra forem sistematicamente PIORES que a média (ex.: tokens que o bot perdeu de
  vista porque o projeto morreu/rugou), excluí-los da média de H1 estaria JOGANDO FORA perdas reais —
  H1 pode estar, hoje, mais FAVORÁVEL do que deveria, não menos. Migrar H1 pro motor correto poderia
  revelar um resultado PIOR do que o já visto, nunca melhor — isto pesa a favor de migrar antes de
  confiar em qualquer leitura "sinal ≈ aleatório" como conclusão estável.
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

## Resumo da ordem de execução recomendada

1. Corrigir/documentar a higiene de sinal (item 0) — barato, condição para confiar em qualquer R.
2. Desenhar e pré-registrar o alvo curto de alta frequência (item 1) — maior valor esperado por tempo
   de coleta, ataca o bottleneck de poder estatístico que o projeto já sofreu.
3. Deixar carteiras forward (item 2) rodando — já correto, só precisa de tempo.
4. Avaliar o custo real de RPC do bundle/funding (item 3) antes de implementar — se o orçamento
   permitir sem repetir o erro da Rodada 15, é a próxima fronteira de dado genuinamente nova.
5. Fluxo/participação genérico (item 4) fica em espera, só com feature genuinamente nova.
6. Suporte com stop curto (item 5) continua rodando passivamente, sem atenção extra necessária.

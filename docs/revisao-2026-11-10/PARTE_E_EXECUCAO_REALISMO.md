# Rodada 16 — Parte E: Realismo de execução

Auditoria read-only (PAPER). Nenhum código/parâmetro/hash alterado. Resumo: encontrei dois achados
P1 bem evidenciados e um já reconhecido pelo próprio projeto. O mais importante: o modelo de custo
(`CostModel`) usa um tamanho de posição **fixo e hardcoded** (`position_sol=0.15`) para calcular
slippage, **desacoplado** do tamanho de posição real reportado como covariável V3
(`banca_inicial_usd`/`posicao_pct_supply`) — o R/edge que decide H1 nunca é recalculado para o
tamanho de posição que o operador realmente usaria. O limite de 1,5% do supply nunca é aplicado
(só reportado). MEV/priority fee/jito NUNCA são modelados em lugar nenhum — isso já é admitido
abertamente pelo próprio `EMENDA 1` do plano de análise, então não é um achado novo, é uma
confirmação com citação de linha.

### [P1] R estatístico (H1/dif_pareada) usa posição FIXA de 0,15 SOL — a banca/bankroll real usa outro `CostModel`, nunca cruzados
- **Evidência**: `signals_mvp/pos_runner/costs.py:51` (`position_sol: float = 0.15`, default do
  `CostModel`) e `costs.py:68-69` (`slippage_pct` usa `self.position_sol` contra a reserva estimada
  do pool). O caminho ESTATÍSTICO que decide H1/`dif_pareada`/R@72h sempre usa esse default:
  `signals_mvp/scripts/horizonte_fixo.py:73` (`costs = CostModel()`, recém-instanciado, 0,15 SOL) é
  o `CostModel` passado para `calcular_r_horizonte`/`simulate_v1` em TODA chamada do script que
  alimenta `pr_horizonte_fixo`/`dif_pareada`/H1 (`analise/condicional.py`). Em paralelo, o projeto
  JÁ TEM um mecanismo para recalcular custo no tamanho de posição REAL — `bankroll.py:155-156` e
  `bankroll_v1.py:143-144` fazem `dataclasses.replace(self.base_costs, position_sol=position_usd /
  sol_usd_entry)` — mas isso só alimenta a simulação de banca/CSV de trades (`pos_runner_banca.csv`),
  NUNCA o caminho estatístico de `horizonte_fixo.py`/`analise/condicional.py`. São dois mecanismos
  de custo que já existem no código, cada um correto para seu próprio fim, mas nunca cruzados.
- **Impacto nas conclusões**: o R que decide H1/EDGE_PROVISORIO é sempre calculado como se a posição
  fosse exatamente 0,15 SOL (≈US$20-40, dependendo do preço do SOL), não o tamanho de posição que a
  simulação de banca (`banca_inicial_usd`/`posicao_frac`) de fato usa e reporta ao operador. Se o
  tamanho de posição real for maior, o slippage real seria **maior** que o modelado em H1 (a fórmula
  de `slippage_pct` cresce quase linear com `position_sol` sobre uma reserva fixa) — o R que decide
  H1 seria, nesse cenário, um TETO otimista frente ao que a própria simulação de banca do projeto já
  sabe calcular. Se for menor, o inverso.
- **Correção proposta**: ligar o `CostModel` usado por `horizonte_fixo.py`/`analise/condicional.py`
  ao MESMO mecanismo `dataclasses.replace(..., position_sol=...)` já existente em `bankroll.py`, ou,
  no mínimo, documentar explicitamente por que o caminho estatístico usa um tamanho de posição fixo
  diferente do caminho de banca.
- **Toca hash/exige restart?**: SIM, se corrigido — mudar o `CostModel` do caminho estatístico
  recalcula custos de TODO sinal passado e futuro sob H1, portanto reabre qualquer resultado já visto
  sob o hash atual (mudança de hipótese, não ajuste cosmético) — exigiria uma emenda formal.
- **Confiança**: alto — verificado diretamente no código (dois mecanismos de custo reais no projeto,
  nunca ligados um ao outro no caminho que decide H1).

### [P1] Limite de 1,5% do supply nunca é aplicado — só reportado
- **Evidência**: `signals_mvp/pos_runner/pos_runner_v3.py:86-96`, docstring da própria função
  (`posicao_pct_supply`): "SO MEDICAO/atributo (Passo 1: 'alertar se > 1,5%'), nunca altera a banca
  real nem o tamanho de posicao de verdade". `POSICAO_PCT_SUPPLY_ALERTA = 1.5` (`pos_runner_v3.py:21`)
  só alimenta um campo `posicao_pct_supply_alerta` (flag informativo), nunca um filtro/corte de
  sinal/entrada em `_entry_v3` (`live.py:3104`: o campo é gravado no `row_insert`, mas não há
  `continue`/`return` condicionado a ele antes disso).
- **Impacto nas conclusões**: um sinal "vencedor" no R@72h/H1 pode, na prática, ser um token tão
  pequeno que uma posição do tamanho modelado (`banca_inicial_usd`) compraria mais de 1,5% do supply
  — fisicamente moveria o próprio preço de entrada sozinho, invalidando o preço de entrada modelado
  (que assume que a entrada do trader é pequena o bastante para não afetar o mercado). Isso é
  exatamente o tipo de sinal que, estatisticamente, pode parecer "edge" mas seria irreplicável/
  irrealista de executar de verdade.
- **Correção proposta**: reportar, nas estatísticas de H1/estratos, a fração de sinais com
  `posicao_pct_supply_alerta=1` E o R médio separado desse subconjunto vs o resto — sem precisar
  alterar a regra de entrada agora (isso seria uma mudança de critério, fora do escopo desta
  auditoria read-only), só adicionar visibilidade.
- **Toca hash/exige restart?**: não, para a correção proposta (é só relatório); SIM se no futuro
  decidirem filtrar sinais com esse flag (mudança de critério de sinal).
- **Confiança**: alto — verificado diretamente no código e na docstring explícita da função.

### [P1, já reconhecido pelo próprio projeto] MEV/priority fee/jito nunca modelados
- **Evidência**: `signals_mvp/pos_runner/costs.py` inteiro — `CostModel.leg_pct` soma
  `pool_fee_pct + terminal_pct + network_pct + slippage_pct`, nenhum termo de priority
  fee/jito tip/MEV. `docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md:222-223` (EMENDA 1, seção
  "Limitações registradas") já declara isso abertamente: "MEV/sandwich não está modelado em
  nenhum lugar desta análise (nem no custo conservador do item (d), que é só um modelo de
  taxa/slippage adicional)".
- **Impacto nas conclusões**: tokens recém-graduados no Pump.fun/PumpSwap são um dos ambientes com
  MAIS competição por MEV/sandwich/front-running em Solana — um trade real competiria por inclusão
  de bloco (priority fee) e poderia ser sandwichado, elevando o custo real de entrada/saída acima do
  modelado em cenários de alta atividade. Isso não é um bug — é uma limitação já documentada pelo
  próprio projeto — mas vale reafirmar aqui porque é um dos maiores "furos" entre R modelado e P&L
  real possível.
- **Correção proposta**: nenhuma nova — já está corretamente rotulado como limitação. Se o projeto
  avançar para execução real, modelar isso é pré-requisito antes de qualquer capital de verdade
  (consistente com a regra de `CLAUDE.md`: "execution realism is still required before any execution
  claim").
- **Toca hash/exige restart?**: não (é uma limitação documentada, não uma mudança).
- **Confiança**: alto — citação direta do próprio documento do projeto.

### [P1] Saída (stop/TP) assume preenchimento exato no preço do candle, sem profundidade de book em queda rápida
- **Evidência**: `signals_mvp/pos_runner/simulate_v1.py:147` (`hit_stop = bar.low <= stop`) — o stop
  é preenchido exatamente no nível do stop (ou no open, se abriu em gap abaixo, conforme comentário
  de topo do arquivo, linha 6). O `CostModel.slippage_pct` (usado também na perna de saída, via
  `leg_pct`) estima slippage a partir da reserva do pool NO MOMENTO daquele candle (`mc_usd`
  corrente) — captura alguma dependência de liquidez, mas é uma aproximação de produto-constante
  para UM trade pequeno, não um modelo de livro de ofertas sob pressão de venda simultânea de
  múltiplos participantes (que é o cenário típico de uma queda rápida que aciona o stop de muita
  gente ao mesmo tempo).
- **Impacto nas conclusões**: em quedas rápidas e correlacionadas (o próprio cenário que aciona
  stops), o slippage real de SAÍDA tende a ser PIOR que o modelado — o modelo não distingue "saída
  isolada, mercado calmo" de "saída durante um dump que está acionando vários stops ao mesmo tempo".
- **Correção proposta**: nenhuma implementação agora (fora do escopo read-only) — documentar como
  limitação explícita equivalente à do MEV acima, e, se possível no futuro, usar profundidade real do
  book (se disponível via algum provider) para uma correção de pior-caso na saída.
- **Toca hash/exige restart?**: não para documentar; sim se corrigido de verdade (muda `CostModel`/
  `simulate_v1`, reabre H1).
- **Confiança**: médio — a fórmula de slippage existe e é dependente de preço/liquidez (não é
  totalmente ingênua), mas não captura a correlação entre múltiplas saídas simultâneas.

### [P2] Atraso sinal→ordem não quantificado de forma consolidada nesta auditoria
- **Evidência**: não achei, nesta passada, um número único e consolidado de "latência p95 entre
  candle de decisão e envio do alerta Telegram" pronto para citar — o projeto tem instrumentação
  (`pr_api_uso`, auditorias de atraso de entrada em `scripts/auditar_atraso_entradas.py`) mas eu não
  rodei esses scripts contra dados reais (não há banco ao vivo aqui) nem li o relatório histórico
  deles nesta passada.
- **Impacto nas conclusões**: sem esse número, não posso quantificar aqui quanto da "janela de
  movimento" do token já passou entre a decisão e uma ordem humana real ser enviada.
- **Correção proposta**: rodar `scripts/auditar_atraso_entradas.py` no banco real da VM (somente
  leitura) e citar o p95 real num follow-up desta auditoria.
- **Toca hash/exige restart?**: não.
- **Confiança**: não verificável nesta sessão — não é uma hipótese, é uma lacuna de tempo/acesso.

### [P2] Custo fixo de rede (0,0003 SOL) é desprezível fração do custo total, mas não é a mesma coisa que priority fee competitivo
- **Evidência**: `costs.py:16` (comentário de fonte: "Rede: 0,0003 SOL por perna... sobre a posicao
  de 0,15 SOL = 0,2% por perna"). Isso é só a taxa de rede BASE do Solana, não um priority
  fee/compute-unit-price competitivo (que em lançamentos populares pode ser ordens de magnitude
  maior) — reforça o achado de MEV/priority fee acima, de um ângulo diferente (custo FIXO vs
  variável).
- **Impacto nas conclusões**: mesmo que a posição seja pequena, um priority fee competitivo tem um
  piso em SOL que não escala com o tamanho da posição — para posições muito pequenas (ex.: `mao_fixa_usd`
  pequena), esse piso fixo pode consumir uma fração desproporcional do capital por trade.
- **Correção proposta**: nenhuma agora — mencionar explicitamente ao lado do achado de MEV acima
  quando/se o projeto avançar para execução real.
- **Toca hash/exige restart?**: não.
- **Confiança**: médio — a lógica é sólida, mas não tenho uma fonte de priority fee real "típico"
  para quantificar com números (nunca inventaria um número sem fonte).

## O R@72h reportado hoje é um TETO — nunca um piso

Com tudo acima, o R@72h/MTM que o projeto reporta hoje (incluindo qualquer `EDGE_PROVISORIO` futuro)
representa, na melhor leitura honesta, um **teto de execução quase-perfeita**: entrada no open do
candle seguinte, saída exatamente no nível de stop/TP, custo de pool+terminal+rede+slippage de
produto-constante para uma posição PEQUENA e FIXA, zero MEV/priority fee, zero atraso humano
modelado, zero correlação de saídas simultâneas em pânico. Para virar P&L real, é preciso subtrair,
no mínimo:

- **X = diferença entre slippage modelado (0,15 SOL fixo) e slippage no tamanho de posição real**
  (quantificável, DIREÇÃO depende de qual é maior — ver achado P1 acima; HOJE não quantificável em
  número por falta de decisão de qual é o tamanho de posição "real" pretendido).
- **Y = custo de MEV/priority fee/sandwich** (NÃO quantificável com os dados deste projeto hoje —
  precisaria de medição on-chain real de priority fees pagos por bots competidores no mesmo
  lançamento, fora do escopo deste checkout).
- **Z = atraso de execução humana/latência vs velocidade do token** (NÃO quantificável nesta sessão
  por falta de acesso ao banco ao vivo — ver achado P2 de latência acima).
- **W = pior slippage de saída em quedas correlacionadas** (NÃO quantificável sem dado de book real).

Nenhum desses quatro tem hoje um número confiável e citável — a honestidade correta é dizer que o
R modelado é um LIMITE SUPERIOR, e que o projeto já está ciente disso (CLAUDE.md: "Execution
automation is not required to prove signal value. Execution realism is still required before any
execution claim" e "route-only return != realized P&L" nos Systems invariants) — o estado atual é
coerente com essas regras: nada aqui afirma P&L real, e esta auditoria não encontrou nenhum lugar
onde o projeto tenha, por engano, apresentado R modelado como P&L real.

## O que NÃO foi possível verificar nesta sessão

- Latência real sinal→ordem (p95) — não rodei os scripts de auditoria contra dado real.
- Qualquer número de priority fee/MEV real em Solana para lançamentos Pump.fun — fora do alcance
  desta auditoria (exigiria dado on-chain histórico que não está neste checkout).
- Profundidade de book real em quedas — não há provider desse dado no projeto hoje, então não há
  nada a verificar além do que já está modelado via produto-constante.
- Confirmei que `CostModel.position_sol` É sobrescrito em `bankroll.py`/`bankroll_v1.py` (caminho de
  banca/CSV) — não verifiquei se existe algum OUTRO caminho estatístico (além de `horizonte_fixo.py`)
  que também devesse estar ligado ao tamanho de posição real e não está; o grep cobriu todo
  `signals_mvp/` mas não é garantia de que eu tenha entendido corretamente cada call site.

# Proposta de emenda 2026-11-06 — futilidade e critério (b) compatíveis com payoff de cauda (TEXTO, NÃO IMPLEMENTADO)

PAPER/READ-ONLY. **Isto é só uma PROPOSTA em texto — PEDIDO EXPLÍCITO do operador (rodada 12, Parte
4c) de "não implementar".** Nenhum código, config, regra de `PLANO_ANALISE_PREREGISTRADO.md` (H1,
futilidade, Emenda 1) ou do pré-registro V3 é alterado por este documento. Se o operador decidir
adotar isto, abre-se uma emenda PRÓPRIA e datada no documento vivo (`PLANO_ANALISE_PREREGISTRADO.md`),
nunca por reescrita silenciosa, e a coleta que a julga tem que ser **ainda não vista** a partir dali
(mesma disciplina do registro de hipóteses, `docs/research-hypothesis-registry-v1-2026-10-04.md`).

## Declaração explícita (pedido do operador): isto NÃO é uma proposta "a frio"

Esta proposta é **motivada diretamente** pela análise de poder já entregue em
`docs/pos-runner-v3/EMENDA_2026-11-05_FUTILIDADE_ESTRATEGIA_CAUDA.md` (rodada 11, item C6) — o
operador **já viu** os números daquele disclosure (P(FUTIL aos 15 trades) até 46,3% e P(critério-b
falha aos 30) até 81,2%, nos cenários genuinamente lucrativos de uma estratégia de cauda com taxa de
acerto 5-10% e alvo 11-26R) antes de pedir esta proposta. Isso é dito aqui **explicitamente, nunca
escondido**: as 2 regras abaixo são desenhadas sabendo o resultado que motivou o pedido — por isso,
se um dia forem adotadas, **nunca podem ser julgadas pelos MESMOS dados que já foram vistos** (mesma
regra de "o que já foi visto nunca pode julgar a si mesmo" do `CLAUDE.md`); qualquer promoção exige
coleta nova, ainda não vista, depois da emenda estar registrada por hash.

## Problema que motiva a proposta (resumo do disclosure já entregue)

- **Futilidade atual** (`PLANO_ANALISE_PREREGISTRADO.md`, H1 item 1): para em `n=15` se a média de
  `dif_pareada` < -0,5R. Para uma estratégia de cauda (acerto 5-10%, alvo 11-26R), isso mata até
  **46,3%** das réplicas genuinamente lucrativas só por não ter calhado nenhum vencedor nos 15
  primeiros sinais — a regra mede a MAGNITUDE da média cedo demais, quando o número esperado de
  vencedores em 15 tentativas a 5-10% é **0,75 a 1,5** (quase sempre zero ou um).
- **Critério (b) da Emenda 1** (leave-one-out do melhor trade, estimativa pontual > 0): para a MESMA
  estratégia, falha em **41%-81%** das réplicas lucrativas em n=30 — remover o único trade vencedor
  de uma amostra que só tem 1-2 vencedores é, por desenho, quase garantido devolver média negativa.

Em ambos os casos, o problema de raiz é o MESMO: as regras atuais foram calibradas pra um payoff
simétrico/cauda moderada, onde "pouca sorte nos primeiros trades" ou "um outlier isolado" são sinais
razoáveis de que não há edge. Para cauda EXTREMA (edge concentrado em poucos vencedores raros e
grandes, que é exatamente o que o operador descreveu que o professor faz), magnitude-cedo e
contagem-de-trade-único são as métricas ERRADAS — a métrica certa é a TAXA DE ACERTO observada,
julgada estatisticamente contra o que o próprio pré-registro já assume (p=5-10%), e a métrica certa
pra robustez de outlier é por TOKEN (uma única fonte de acaso/correlação), não por TRADE individual.

## Proposta 1 — futilidade baseada em taxa de acerto, nunca em magnitude cedo

**Regra proposta**: em vez de "n=15, média < -0,5R", a futilidade antecipada passa a ser um teste
binomial exato unilateral contra a taxa de acerto MÍNIMA que o próprio pré-registro já assume como
piso plausível da estratégia (`p_min = 5%`, extremo inferior da faixa 5-10% já citada no disclosure).
A cada novo sinal resolvido (nunca espera um `n` fixo pra olhar), calcula-se:

```
p_valor_futilidade = P(Binomial(n, p_min) <= k_acertos_observados)
```

onde `k_acertos_observados` = nº de sinais com `dif_pareada > 0` (ou, mais estrito, `R >= payout_min`
se o operador quiser julgar contra um alvo mínimo em vez de "qualquer ganho") entre os `n` sinais
resolvidos até agora. `FUTIL` dispara quando `p_valor_futilidade < 0,05` (mesmo nível de confiança
92,5%→95% já usado em outras decisões do projeto, nunca um número novo inventado pra esta proposta).

**Caso particular (k=0, zero acertos ainda)**: `p_valor_futilidade = (1-p_min)^n`; com `p_min=5%`,
isso cai abaixo de 0,05 em **n=59** (calculado exatamente: `0,95^58 ≈ 0,051 > 0,05`, `0,95^59 ≈
0,0485 < 0,05`) — é a origem do "~59 sem nenhum acerto" citado no pedido. A regra GENERALIZA esse
caso particular pra qualquer `k_acertos_observados` observado (não só zero), então ela nunca fica
"travada" esperando um número fixo de trades: se 1 acerto já aparecer antes de n=59, o teste
binomial com k=1 recalcula o novo `n` necessário pra rejeitar (maior que 59, já que 1 acerto é
evidência A FAVOR da taxa mínima); se NENHUM acerto aparecer, para exatamente em n=59 (não antes,
nunca por "falta de sorte cedo" como a regra atual).

**Por que isto é compatível com o payoff de cauda**: a regra só declara `FUTIL` quando a EVIDÊNCIA
ACUMULADA (não a magnitude de 1 trade perdedor isolado) rejeita estatisticamente que a estratégia
acerte pelo menos 5% das vezes — exatamente a pergunta que importa pra uma estratégia cujo edge
inteiro depende de acertar raramente, mas grande. Nunca mede magnitude antes de ter trades
suficientes pra magnitude significar algo.

**Trade-off explícito (nunca escondido)**: n=59 é MUITO maior que n=15 — a estratégia roda por mais
tempo (mais sinais, mais tempo de paper) antes de poder ser declarada `FUTIL`. Isso é uma escolha
deliberada: pra um payoff de cauda real, parar cedo é o próprio risco que o disclosure já quantificou;
o operador pode preferir um `p_min` mais alto (ex.: 7,5% em vez de 5%) se quiser um corte mais cedo,
sabendo que isso assume uma taxa de acerto mínima mais otimista.

## Proposta 2 — critério (b) por teto de contribuição por token, nunca leave-one-out de 1 trade

**Regra atual**: estimativa pontual da média de `dif_pareada` > 0 **depois de remover o único maior
trade individual** (leave-one-out).

**Regra proposta**: em vez de remover 1 TRADE, limita-se a contribuição de qualquer TOKEN individual
à soma total — nunca mais que uma fração pré-fixada `f` (proposta: `f = 1/3`, ou seja, nenhum token
sozinho pode valer mais que 1/3 da soma de TODAS as diferenças pareadas positivas) da soma positiva
total. Formalmente, por token `t` com soma de `dif_pareada` positivas `S_t` (soma 0 se o token não tem
nenhum trade positivo) e soma positiva total `S = Σ S_t`:

```
S_t_capado = min(S_t, f × S)
```

recalcula-se a média com `S_t_capado` no lugar de `S_t` pra cada token (as diferenças NEGATIVAS nunca
são tocadas — o teto só limita o lado positivo, nunca inventa uma perda que não aconteceu); o
critério (b) passa se essa média recalculada > 0.

**Por que isto é mais compatível com cauda real**: leave-one-out de 1 TRADE é devastador quando o
edge inteiro vem de 1-2 vencedores — não importa SE esses vencedores vieram de tokens diferentes
(evidência de que o edge é real e replicável entre tokens) ou do MESMO token repetido (evidência de
que pode ser 1 evento idiossincrático). A regra atual trata os dois casos IGUAL (remove 1 trade de
qualquer jeito); a proposta separa os casos: se os vencedores grandes vêm de tokens DIFERENTES, nenhum
token sozinho bate o teto de 1/3 e a média recalculada fica parecida com a média real (passa mais
fácil que hoje); se um ÚNICO token concentra todos os vencedores grandes (ex.: 1 token com 3 trades
vencedores, nenhum outro token com qualquer ganho), o teto de 1/3 ainda corta a maior parte da
contribuição desse token — protegendo contra o MESMO risco que a regra atual tenta proteger (um
evento isolado sustentando "edge" sozinho), só que medido por TOKEN (a unidade de correlação/acaso
real do projeto, já usada em todo o resto da metodologia — bootstrap por token, Holm por token, etc.)
em vez de por TRADE individual.

**Trade-off explícito (nunca escondido)**: o teto `f=1/3` é uma escolha, não uma verdade matemática —
um `f` menor (ex.: 1/5) é mais conservador (mais parecido com leave-one-out quando há poucos tokens
vencedores); um `f` maior (ex.: 1/2) deixa passar mais facilmente estratégias cujo edge está
concentrado em poucos tokens, mesmo que replicado entre eles. O valor exato fica para o operador
decidir ANTES de qualquer coleta nova ser julgada por ele (nunca escolhido depois de ver o resultado
específico que ele produziria).

## O que esta proposta NÃO faz

- Não altera `PLANO_ANALISE_PREREGISTRADO.md`, a regra de futilidade atual, o critério (b) da
  Emenda 1, nem qualquer código (`analise/condicional.py`, `pos_runner/*`) — é texto, nada é
  implementado nesta rodada.
- Não decide `p_min` (5% vs 7,5%) nem `f` (1/3 vs outro valor) — ambos ficam para o operador escolher
  explicitamente se decidir adotar, e essa escolha precisa ser feita ANTES da coleta que a julga.
- Não promove nenhuma hipótese nem avalia nenhum dado novo — é só a proposta de regra, motivada pelo
  disclosure já visto (declarado explicitamente acima), nunca confirmatória por si só.
- Não substitui os critérios (a)/(c)/(d) da Emenda 1 (bootstrap em blocos, permutação, custo
  conservador) — só (b) é tocado por esta proposta.

## Status

**PROPOSTA registrada em 2026-11-06, texto apenas, nunca implementada.** Se o operador decidir
adotar qualquer parte desta proposta, isso abre uma emenda formal e datada em
`PLANO_ANALISE_PREREGISTRADO.md` (com hash registrado via `garantir_plano_registrado`, ANTES de
qualquer coleta nova ser julgada por ela) — este documento, por si só, nunca altera nenhuma regra em
vigor.

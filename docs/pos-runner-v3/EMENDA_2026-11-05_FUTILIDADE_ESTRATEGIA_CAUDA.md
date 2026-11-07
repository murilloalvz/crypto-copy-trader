# Emenda 2026-11-05 — futilidade e Emenda 1 (leave-one-out) sob um payoff de cauda

PAPER/READ-ONLY. **Disclosure de poder/risco estatístico — NUNCA muda a regra de futilidade nem o
critério (b) da Emenda 1** (`docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md`), nem o pré-registro
V3. Pedido 2026-11-05 (rodada 11, item C6, 2ª parte): "probabilidade de a regra de futilidade (15
trades, média < -0,5R) parar uma estratégia lucrativa, e se o critério 'sem o melhor trade > 0' da
Emenda 1 é compatível com ela [estratégia de cauda, taxa de acerto 5-10%, alvo 11-26R]". Só relatório.

## Regras confirmadas no texto já pré-registrado

- **Futilidade antecipada** (`PLANO_ANALISE_PREREGISTRADO.md`, H1 item 1): com **n=15** sinais
  resolvidos, se a média de `dif_pareada` < **-0,5R**, H1 para — `FUTIL`.
- **Emenda 1, critério (b)**: a estimativa pontual da média de `dif_pareada` > 0 **depois de remover
  o único maior ganho individual** (leave-one-out do melhor trade) — nunca exige limite inferior
  aqui, só o ponto; falhar isso (como falhar qualquer um dos 4 critérios) já impede `EDGE_PROVISORIO`
  nesta rodada (vira `INCONCLUSIVO`, nunca "refutado").

## Modelo usado (simplificação explícita, nunca escondida)

Cada trade: ganha `payout` R com probabilidade `p` (taxa de acerto), perde exatamente `-1R` com
probabilidade `(1-p)` (stop cheio) — aproxima `dif_pareada` por `R` do próprio sinal (controle
contribuindo ~0 em média). Grade: `p` em {5%, 7,5%, 10%} (dentro da faixa "5-10%" do pedido);
`payout` em {11, 18,5, 26} (extremos e meio da faixa "11-26R"). Calculado via binomial EXATA
(`math.comb`), nunca simulado/aproximado.

## Resultado 1 — P(FUTIL aos 15 trades), só nos cenários GENUINAMENTE lucrativos (EV>0)

EV por trade = `p×payout − (1−p)×1`. FUTIL só dispara quando **zero** trades vencedores caem nos
15 primeiros (com qualquer payout nesta faixa, 1 vencedor já tira a média de -0,5R) — então
P(FUTIL) = P(Binomial(15,p)=0), **independente do payout exato**:

| p (taxa de acerto) | EV>0 com payout>= | P(FUTIL aos 15 trades) |
|---|---|---|
| 5% | 26R (EV=+0,35) | **46,3%** |
| 7,5% | 18,5R (EV=+0,46) ou 26R (EV=+1,03) | **31,1%** |
| 10% | 11R (EV=+0,20), 18,5R (EV=+0,95) ou 26R (EV=+1,70) | **20,6%** |

**Leitura**: pra uma estratégia de cauda real (taxa de acerto no chão da faixa, 5%), quase **1 em
cada 2 réplicas** da mesma estratégia LUCRATIVA seria morta como `FUTIL` só por não ter calhado
nenhum vencedor nos primeiros 15 sinais — PURO acaso de amostragem, nunca falta de edge real.

## Resultado 2 — P(critério-b da Emenda 1 FALHA aos 30), só nos cenários lucrativos

| p | payout | EV | P(critério-b falha @ n=30) | P(critério-b falha @ n=100) |
|---|---|---|---|---|
| 5% | 26R | +0,35 | **81,2%** | 43,6% |
| 7,5% | 18,5R | +0,46 | **60,7%** | 37,0% |
| 7,5% | 26R | +1,03 | **60,7%** | 12,2% |
| 10% | 11R | +0,20 | **64,7%** | 45,1% |
| 10% | 18,5R | +0,95 | **41,1%** | 11,7% |
| 10% | 26R | +1,70 | **41,1%** | 2,4% |

**Leitura**: mesmo nos cenários mais favoráveis dentro da faixa pedida, o critério (b) tende a
FALHAR na MAIORIA das réplicas com n=30 (41%-81%) — removendo o único vencedor "grande" de uma
estratégia cujo edge inteiro vem de vencedores raros e grandes **é, por desenho, quase garantido
devolver uma média negativa** quando há só 1-2 vencedores na amostra (o caso típico com p=5-10% e
n=30: nº esperado de vencedores = 1,5 a 3). So melhora de forma relevante perto de n=100 **e** payout
alto — exatamente onde o pedido já situa uma faixa realista (11-26R).

## Compatibilidade: NÃO, não sem ressalva

As duas regras são bem calibradas para um payoff **próximo do simétrico ou de cauda moderada** (onde
"um outlier isolado" é de fato incomum e suspeito). Para uma estratégia de **cauda extrema de
verdade** (acerto 5-10%, alvo 11-26R) — exatamente o que o operador confirmou que o professor faz —
**ambas carregam um risco alto e QUANTIFICADO de matar ou estagnar (`INCONCLUSIVO`) uma estratégia
genuinamente lucrativa**, nos MESMOS tamanhos de amostra (n=15/30) em que as decisões acontecem. Isso
**não é uma falha de implementação** — é uma tensão estrutural conhecida (variância de cauda pesada
vs. decisão em amostra pequena) que o próprio texto já pré-registrado parcialmente reconhece (o
portão de "escalar a mão" exige **n>=100 tokens distintos OU p<0,01 no teste de permutação** — n=100
é justamente onde os números acima melhoram de verdade).

## O que esta emenda NÃO faz

- Não muda a regra de futilidade, o critério (b) da Emenda 1, nem qualquer outro critério (a)/(c)/(d).
- Não promove nenhuma hipótese nem decide nada — é só a probabilidade, calculada ANTES de qualquer
  coleta nova atingir n=15/30 tokens, de que as regras ATUAIS tratem mal um payoff de cauda real.
- Não propõe uma regra nova (fora do pedido explícito "só relatório, sem mudar o pré-registro") --
  se o operador decidir que a tensão acima merece uma regra adaptada (ex.: exigir leave-k-out em vez
  de leave-1-out, ou um limiar de futilidade condicionado a k vencedores observados), isso abre uma
  hipótese/emenda PRÓPRIA, nunca decidida aqui.

## Status

**EMENDA registrada em 2026-11-05**, disclosure de risco/poder estatístico — nunca reescreve as
regras já pré-registradas. Qualquer mudança nesta conta, depois de ver mais resultados, abre uma
NOVA emenda datada.

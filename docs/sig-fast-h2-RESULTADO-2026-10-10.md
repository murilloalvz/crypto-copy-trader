# SIG-FAST H2 (SIG-FAST-POSTMIG) — resultado do discovery histórico, 2026-10-10

## Veredito, em uma frase

**Ainda não dá pra saber se H2 tem edge ou não — o gate de cobertura (Fase 3,
critério fixado antes de ver qualquer retorno) reprovou, então nenhum
retorno/EV/barreira chegou a ser calculado.** Classificação:
`INCONCLUSIVE_SYSTEM`. Isso **não fecha H2** (não é um FAIL econômico, é
uma falha de cobertura antes do gate econômico) e **não gasta uma
tentativa** no registro de hipóteses, por disciplina do CLAUDE.md.

## O que foi feito (tudo real, nada simulado)

- Baixado e selado o bloco de discovery completo (2026-08-20 a 2026-09-17,
  26 janelas sorteadas, método sem Helius validado por paridade real na
  Fase 1).
- 202 migrações reais encontradas, todas classificadas (0 erro de sistema).
- 76 sobreviventes / 126 não-sobreviventes (taxa de sobrevivência real:
  37,6% — mesma ordem de grandeza do 0,333 medido no piloto corrigido por
  viés).
- Baseline amostrada de TODAS as 202 migrações (Fase 0a), 76 tokens.
- Grade completa de preço (Estágio 2) selada em 126 tokens distintos
  (sobreviventes + baseline, com overlap esperado).
- Gate de cobertura (Fase 3) rodado contra os 7 critérios fixados antes de
  qualquer download.

## Por que reprovou (números reais)

| Critério | Resultado | Limite | Passou? |
|---|---|---|---|
| Paridade da Fase 1 validada | sim | sim | ✅ |
| Não abortou | sim | sim | ✅ |
| % janelas processadas | 100% | ≥90% | ✅ |
| % buckets do Estágio 2 resolvidos | **44,76%** | ≥95% | ❌ |
| missing_source | 0% | ≤5% | ✅ |
| % eventos com reservas+fee | **59,41%** | ≥95% | ❌ |
| Sobreviventes no treino | 50 | ≥30 | ✅ |

Só 2 dos 7 critérios reprovaram. Investiguei os dois até a causa raiz
(sem mudar nenhum número do veredito — isso é só diagnóstico):

### "% eventos com reservas+fee" = 59,41% — isso é um artefato de cálculo, a cobertura real é 100%

Confirmado direto no banco: dos 54.191 eventos realmente decodificados em
todo o bloco (53.951 só no Estágio 2), **100% têm reservas E fee**. O
número de 59,41% que aparece no relatório vem de uma média por token que
inclui, com peso igual, os 126 não-sobreviventes — que, pela correção de
viés da Fase 0a/E, **nunca tentam decodificar preço no Estágio 1** (regra:
<20 trades nos últimos 5min = não-sobrevivente direto, sem gastar
nenhuma chamada de preço). Cada um desses 126 contribui 0% pra média, não
porque falhou em decodificar, mas porque **corretamente nunca tentou**.
Isso dilui a média de ~100% (dos que tentaram) pra 59,41%. **Não é um
problema de cobertura de dado real — é a fórmula da métrica que não
distingue "não tentou de propósito" de "tentou e falhou".**

### "% buckets do Estágio 2 resolvidos" = 44,76% — isso É real, e é estrutural

Aqui não tem artefato: sobreviventes (76 tokens) resolveram em média
**65,87%** dos buckets de 5s ao longo dos 80min; os não-sobreviventes
amostrados pro baseline (50 tokens) resolveram em média só **12,69%**.
Isso é exatamente o que se espera de um token que "morreu" cedo — quase
não tem mais nenhum trade depois do início. A média geral (44,76%) é só a
mistura das duas populações. **O problema real é de desenho**: a Fase 0a
exige que o baseline inclua tokens mortos (senão inflaria o edge por
viés de sobrevivência), mas a Fase 3 exige ≥95% de cobertura de preço — e
um token morto, por definição, não tem 95% de preço pra cobrir. As duas
regras, cada uma correta isoladamente, são **estruturalmente incompatíveis**
do jeito que foram fixadas.

## O que isso significa

- **Não prova nem refuta o edge de H2.** O teste econômico (Fase 4) nunca
  rodou — o gate de cobertura bloqueou antes, exatamente como desenhado
  pra fazer quando a cobertura não bate.
- **Não é um erro de execução** — a coleta funcionou, os números batem,
  o pipeline (Fases 0 a 3) está correto e testado. O problema é que o
  CRITÉRIO de cobertura da Fase 3, do jeito que foi fixado, não é
  compatível com um baseline que inclui tokens mortos por desenho.
- **H2 continua aberta.** Por disciplina do CLAUDE.md, uma falha de
  sistema antes do gate econômico não fecha a hipótese nem gasta uma
  tentativa do registro — só fica registrada como inconclusiva.

## Limitações

- O bloco de confirmação **nem chegou a ser baixado** — não existe nenhum
  dado de confirmação pra perder, então não há retrabalho desperdiçado.
- A causa raiz do critério de buckets (baseline morto vs. critério único
  de 95%) não foi corrigida retroativamente aqui — isso seria mudar regra
  depois de ver dado, proibido. Fica como achado para o operador decidir
  na volta.
- O artefato da métrica de reservas+fee também não foi corrigido agora,
  pelo mesmo motivo — mas está provado com números reais (100% de
  cobertura real) que não é um problema de dado.

## Próximo passo (decisão do operador, não tomada aqui)

Duas correções de protocolo — nenhuma aplicada nesta rodada, as duas
precisam de um pré-registro novo antes de qualquer nova coleta:

1. **Separar o critério de buckets resolvidos por grupo** (ex.: ≥95% só
   pra sobreviventes, um limite mais baixo e justificado pro baseline, já
   que baseline morto é uma propriedade esperada do desenho, não uma
   falha de cobertura).
2. **Corrigir a métrica de reservas+fee** pra só considerar os eventos que
   realmente foram decodificados (excluir do denominador os tokens que
   corretamente nunca tentaram), não diluir com zeros de não-tentativa.

Com essas duas correções pré-registradas, os MESMOS 202 candidatos e o
MESMO banco já selado desta rodada provavelmente passariam o gate sem
precisar baixar nada de novo — mas isso é uma decisão do operador, não
uma correção que eu deveria aplicar sozinho depois de ver o resultado.

**Vale ou não vale seguir pra paper ao vivo: ainda não se sabe — a
pergunta nem chegou a ser testada.** O que dá pra dizer com confiança: a
infraestrutura (Fases 0-3) funciona, os dados são bons (zero erro de
sistema, paridade exata na enumeração, 100% de cobertura real de
reservas+fee), e o único obstáculo é uma incompatibilidade de desenho
entre dois critérios de protocolo — corrigível, mas não sem uma decisão
humana primeiro.

# Rejection Intelligence v1

## Status

**IMPLEMENTADO como camada paralela de pesquisa.**

Esta camada não altera `wave_v3_volume_integrity`, não transforma rejeições em sinais e não executa ordens. O objetivo é medir o que acontece **depois** que o radar rejeita um token, para aprender se as barreiras estão evitando eventos ruins, descartando oportunidades ou apenas selecionando um regime diferente.

## Motivação

Avaliar somente os tokens aceitos cria uma visão incompleta do filtro. Também precisamos observar uma amostra dos tokens rejeitados.

Esse desenho é um contrafactual observacional: a pergunta não é "quanto teríamos lucrado com certeza?", mas sim "como o mercado evoluiu após a decisão de rejeitar, usando o estado que existia naquele momento?".

A inspiração metodológica vem de trabalhos públicos de **Post-Rejection Follow-up Sampling (PRFS)** no ecossistema Solana/pump.fun. O corpus RED-REJECT-2026-v1, publicado no Zenodo, registra 716.762 observações pós-rejeição de 4.635 tokens ao longo de 96 dias. Referências:

- https://zenodo.org/records/21402477
- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7129798

A ideia genérica de acompanhar rejeições é reaproveitável. O próprio depósito informa que existem pedidos de patente pendentes relacionados a metodologias específicas de trading/DEX. Portanto, este projeto **não copia filtros proprietários ou lógica específica alegadamente protegida**; aproveita apenas o desenho científico genérico de registrar a decisão e observar o desfecho.

## Integração com o Wave Funnel

Toda `record_discovery_run(...)` concluída agora chama o sidecar de Rejection Intelligence **depois** de persistir e confirmar `wave_discovery_runs` e `wave_discovery_candidates`.

Isso preserva duas propriedades:

1. o sidecar referencia um `run_id` já comprometido no SQLite;
2. nenhuma lógica de Rejection Intelligence participa da decisão `passed`, do Wave Score ou da criação do sinal.

Se a fonte de discovery falhar, não inventamos uma coorte de rejeição.

## O que é persistido

Toda nova rejeição produzida por uma discovery bem-sucedida passa a registrar, no instante da decisão:

- `run_id` da discovery;
- mint e símbolo;
- timestamp da decisão;
- preço observado naquele instante;
- Wave Score;
- se os dados básicos eram válidos;
- lista completa de barreiras;
- cautions;
- componentes do score;
- snapshot completo de mercado/risco usado pelo radar.

O snapshot é importante para preservar causalidade. Não reconstruímos um rejeitado histórico usando o estado atual do token.

## Amostra de follow-up

Persistir o snapshot é barato, então todas as rejeições novas são registradas. Consultar preços futuros tem custo de provider, então apenas uma amostra limitada é acompanhada automaticamente.

Padrão v1:

- no máximo 12 tokens por discovery run;
- somente rejeições com dados básicos válidos e preço de entrada positivo;
- primeiro, selecionar o melhor near miss de cada barreira única;
- depois preencher as vagas restantes priorizando menos barreiras e maior Wave Score;
- horizontes: 5, 15 e 60 minutos;
- o mesmo mint não é selecionado novamente por **6 horas** se já recebeu follow-up em outra run recente.

**Near miss** significa um token que ficou perto de passar, por exemplo por ter somente uma barreira. Ele é especialmente útil porque isola melhor a pergunta "o que acontece quando este gate rejeita?".

O cooldown de 6h por mint é uma proteção de **amostragem**, não um gate da estratégia. Ele evita gastar a cota de follow-ups várias vezes no mesmo token em discoveries próximas e reduz dependência artificial entre observações quase idênticas. A rejeição ainda é registrada em todas as runs; somente a seleção de novos preços futuros é temporariamente suprimida.

A amostra não é desenhada para maximizar retorno e não muda nenhum threshold da Wave.

## Settlement

`Settlement` significa resolver um follow-up cujo horário já chegou: consultar o preço histórico daquele alvo e calcular o retorno desde a rejeição.

Por segurança de orçamento do GeckoTerminal, isso é explícito e não roda escondido junto ao monitor principal:

```powershell
python rejection_lab.py --settle --max-checks 12
```

Sem `--settle`, o CLI não faz requests externos de preço. Novas discoveries já selecionam a amostra automaticamente. Para uma run antiga que já possua snapshots de Rejection Intelligence mas não tenha sido selecionada, existe um comando manual explícito:

```powershell
python rejection_lab.py --run-id <RUN_ID> --select --select-limit 12
```

Erros temporários continuam `pending` e podem ser tentados novamente. Erros permanentes ficam `failed`. A ausência de preço permanece visível e entra na análise de missingness; não é apagada.

## Métricas v1

Por horizonte, na amostra total:

- selecionados;
- completos, pendentes e falhos;
- cobertura;
- retorno médio;
- retorno mediano;
- proporção acima de 0%;
- proporção >= +20%;
- proporção <= -25%.

Além disso, o relatório cria uma seção **BARREIRA ÚNICA — OUTCOMES ISOLADOS**. Ela calcula as mesmas métricas somente para tokens rejeitados por exatamente uma barreira. Isso evita atribuir o desfecho a `liquidity_low`, por exemplo, quando o mesmo token também falhou em risco, concentração e volume.

Os cortes `+20%` e `-25%` são **descrições**, não novos filtros, take profits ou stop losses.

## Como interpretar

Um rejeitado subir depois não prova que o filtro é ruim. Um filtro pode trocar alguns vencedores perdidos por uma redução grande de cauda negativa. Por isso a avaliação precisa comparar distribuição, mediana, crashes, rallies, cobertura e motivo da rejeição.

Também não devemos concluir nada de uma amostra pequena. O principal uso inicial é descobrir quais barreiras merecem investigação posterior com amostra maior.

A comparação mais informativa no futuro será entre:

1. tokens aceitos pelo mesmo regime de discovery;
2. rejeitados near-miss;
3. rejeitados com múltiplas barreiras;
4. cada barreira individual com cobertura suficiente.

## Causalidade e limitações

- O snapshot da rejeição precisa ter sido capturado no momento da discovery.
- Rejeições antigas que só possuem `wave_discovery_candidates` não serão retroativamente reconstruídas com dados atuais.
- O preço pós-rejeição é observacional; não representa fill executável.
- Um token pode não ter preço futuro porque morreu, perdeu pool ou o provider não conseguiu observá-lo. Isso pode ser informativo e não deve ser silenciosamente removido.
- Não há correção causal automática para diferenças entre tokens aceitos/rejeitados.
- A seção por barreira única melhora atribuição descritiva, mas ainda não transforma a comparação em experimento randomizado.
- O cooldown de mint reduz repetição próxima, mas não torna as amostras independentes entre regimes/dias.
- O laboratório mede qualidade do filtro, não prova edge de execução.

## Fluxo

```text
Wave discovery
  -> decisão PASS/REJECT congelada
  -> PASS segue o paper existente
  -> REJECT salva snapshot
       -> amostra limitada/estratificada
       -> cooldown de follow-up por mint
       -> 5m / 15m / 60m follow-up
       -> relatório total
       -> relatório isolado por barreira única
```

## Guardrails

- `wave_v3_volume_integrity` permanece CONGELADA.
- Não afrouxar gate porque um ou poucos rejeitados subiram.
- Não otimizar thresholds sobre o próprio conjunto usado para descobrir o problema.
- Não tratar preço histórico como execução real.
- Não ocultar falhas/missingness.
- Não extrapolar a metodologia RED-REJECT como prova de que os filtros daquele trabalho são apropriados para este projeto.

## Próximo gate

Depois de acumular amostra suficiente, o Rejection Intelligence deverá responder:

- quais barreiras parecem evitar caudas negativas;
- quais parecem produzir muitos false negatives;
- quais têm evidência insuficiente;
- se combinações de barreiras são mais úteis que gates isolados;
- se qualquer revisão merece um teste prospectivo separado, sem retuning pós-hoc.

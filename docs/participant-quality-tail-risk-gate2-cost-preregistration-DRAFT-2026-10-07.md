# Participant Quality Tail-Risk Rejection — Gate 2 (custos) — Preregistration — DRAFT — 2026-10-07

Status: **DRAFT — aguarda sign-off do operador. Não autoriza nenhum cálculo. Escrito antes de
existir qualquer veredito da replicação (`docs/participant-quality-tail-risk-replication-v1-preregistration-2026-10-07.md`),
sem olhar nenhum episódio do holdout.** Commit precisa acontecer antes de você rodar a replicação.

Revisão (mesmo dia, antes de qualquer sign-off): varredura de custo pré-registrada, ATA + slippage de
execução incluídos no modelo, três classificações em vez de passa/falha, preço do SOL como regra em
vez de número — as quatro mudanças pedidas na revisão desta estrutura.

## Por que isso existe agora, antes do veredito

`docs/live-readiness-gates-v1.md`, Gate 2: "Uma estratégia candidata só avança se puder ser
reproduzida usando... slippage e fees contra o replay." A própria regra 2 do registro de hipóteses
("resultado positivo líquido de custos (Gate 2)") é o terceiro e último passo pra `VALIDADA` — depois
de PASS no teste pré-registrado e PASS na replicação. Escrever este Gate 2 agora, e não depois de ver
o resultado da replicação, é o que evita que o modelo de custo seja ajustado pra fazer o resultado
passar.

## Condição de aplicação (explícita, não implícita)

**Este documento só é aplicado se a replicação (PQ-TR-REPL-V1) classificar
`PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`.** Se o veredito for `FAIL` ou `INCONCLUSIVE`, este
Gate 2 fica parado, sem rodar — não há "resultado líquido de custo" pra calcular sobre um filtro que
já falhou ou que não teve suporte. Nenhuma versão deste documento autoriza recalcular nada se isso
acontecer.

## 1. População

Os mesmos episódios do holdout da replicação, run key
`participant-quality-tail-risk-replication-v1-20261007-01` (H1+H2 combinados, igual ao próprio
avaliador `participant_quality_tail_risk_rejection_v0.py` já faz: `high + low` da amostra pareada).
**Nenhuma coleta nova.** Mesmo relatório (`$HOLDOUT_REPORT`) que o passo 5 do runbook da replicação já
produz — este Gate 2 só lê `rows[].group`/`rows[].outcome_900_return_pct` dele, igual o avaliador já
faz.

## 2. Comparação

- **ALL**: todos os pares outcome-conhecidos da população (HIGH + LOW), líquido de custo.
- **ALL-sem-LOW**: só o subconjunto HIGH, líquido de custo (= a população depois de aplicar o filtro
  de rejeição).
- Horizonte: **900s**, o mesmo horizonte primário congelado desde o V0 — não se troca de horizonte
  aqui.
- Mesma regra de grupo: `group` já vem calculado no holdout report (HIGH se feature > cutoff fixo
  `-86.0484432047999`, LOW se não) — este Gate 2 não recalcula grupo, só aplica custo sobre o retorno
  já rotulado.

## 3. Modelo de custo explícito

A cotação route-only (`outcome_900_return_pct`) já inclui price impact de rota — o probe Jupiter já
usado roda com `research_slippage_bps=100` (1% configurado, já embutido na cotação de entrada e
saída). Este Gate 2 **não duplica esse price impact** — adiciona as camadas que a cotação route-only
não cobre: fee de rede, priority fee, custo de abertura de conta de token, e slippage de execução
(diferença entre cotação e execução real), ida e volta.

### 3.1 Verificação pedida: CU/prioritization fee reais da cotação Jupiter já gravada

**Verificado agora, não suposto: não existem.** `src/causal_quote_store.py` e
`src/jupiter_research_exit_route.py` foram lidos — nenhum dos dois campos (`computeUnitLimit`,
`prioritizationFeeLamports`, ou equivalente) é capturado ou persistido pelas cotações Jupiter já
gravadas neste projeto. A condição "usar o CU real se existir" não tem como ser satisfeita hoje — o
valor assumido abaixo permanece uma estimativa, não uma medição. Passar a capturar esses dois campos
na cotação (campo adicional, aditivo, sem mudar nenhum contrato existente) é uma melhoria de
observabilidade separada, fora do escopo deste pré-registro — fica anotada aqui para quando o
operador quiser abrir essa frente.

### 3.2 Componentes do custo base (multiplicador 1x)

| Componente | Valor proposto | Origem |
|---|---|---|
| Fee base por transação | 5.000 lamports (0,000005 SOL) | Documentação oficial Solana (fee fixo por assinatura) |
| Transações por episódio | 2 (compra + venda) | Definição do próprio replay route-only |
| Compute unit price (priority fee) | 5.000 microlamports/CU | Percentil "high" (~75º) de tabelas de estimador de priority fee de mercado — não o percentil de guerra de sniping, porque Gate 2 modela decisão pós-sinal, não corrida de slot |
| Compute units por transação | 200.000 CU | Assunção própria (seção 3.1 confirma: sem dado real pra substituir) — meio de faixa pra rota de 1-2 hops |
| Priority fee por transação | 5.000 × 200.000 / 1.000.000 = 1.000.000 lamports = 0,001 SOL | Fórmula oficial `priority_fee = cu_price × cu_limit / 1_000_000` |
| **Fee de rede total (2 transações)** | 2 × (5.000 + 1.000.000) lamports = 2.010.000 lamports ≈ **0,00201 SOL** | fee base + priority fee, ida e volta |
| Abertura de conta de token (ATA), não fechada/recuperada | **ver seção 3.3 — regra, não número fixo** | SIMD-0437 mudou esse valor em 2026 (abaixo) |
| Slippage de execução (cotação vs execução real) | **100 bps (1,0 pp), reutilizando a mesma ordem de grandeza do `research_slippage_bps` já configurado no probe** | **Não é dado medido** — este projeto não tem nenhum fill real capturado ainda pra medir o gap cotação-vs-execução diretamente; é a mesma lacuna que a revisão de evidência E9 do projeto já registrou (`docs/research-evidence-registry-v1-2026-09-02.md`). Reusar a mesma magnitude do slippage de rota é uma assunção conservadora razoável, não uma medição — Gates 4/5 (shadow/execução real) são onde isso se torna dado de verdade. |

### 3.3 ATA — regra, não número fixo (achado novo nesta revisão)

Pesquisa de mercado nesta sessão: o custo padrão de rent-exempt de uma conta de token SPL (165 bytes)
era ≈2.039.280 lamports (≈0,00204 SOL, o valor "~0,002 SOL" que você propôs) **antes** do SIMD-0437.
O SIMD-0437 corta `lamports_per_byte` em 5 passos com feature gates independentes; o passo 1 já
**ativou em mainnet em 3 de setembro de 2026** — antes de hoje. Depois do passo 1, o mesmo tipo de
conta custa ≈183.711 lamports (≈0,000184 SOL) — cerca de 10% do valor antigo. A própria documentação
do protocolo recomenda explicitamente ler o valor ao vivo do cluster (`getMinimumBalanceForRentExemption`),
não fixar um número, porque os próximos passos do rollout continuam saindo.

**Regra proposta (mesma lógica que você já pediu pro preço do SOL, aplicada aqui também):** o custo
de ATA não é um número congelado neste documento — é lido via RPC (`getMinimumBalanceForRentExemption`
para uma conta de token de 165 bytes) no momento em que o script do Gate 2 roda, não escolhido depois
de ver o resultado do filtro. Os dois valores de referência (0,00204 SOL pré-SIMD-0437; 0,000184 SOL
pós-passo-1) ficam registrados aqui só para dar ordem de grandeza — nenhum dos dois é usado como
constante no cálculo real.

### 3.4 Preço do SOL — regra, não número (mudança pedida)

**Fonte**: Jupiter Price API (mesmo provider já usado e confiado em toda esta pipeline para cotação
de rota — nenhuma dependência nova). **Momento**: lido ao vivo, no instante em que o script do Gate 2
roda — nunca um valor histórico, nunca escolhido depois de ver o resultado do filtro. O valor
efetivamente usado fica gravado no relatório de saída do Gate 2, para auditoria.

Valor ilustrativo usado só para mostrar a ordem de grandeza dos exemplos abaixo: US$150/SOL — **não é
o valor que será usado de verdade**, é só pra dar escala aos números desta seção.

### 3.5 Cálculo ilustrativo (1x), com os valores de referência acima

- Fee de rede ida/volta: 0,00201 SOL
- ATA (valor de referência pós-SIMD-0437, ilustrativo): 0,000184 SOL
- Total em SOL: ≈0,002194 SOL → ≈US$0,33 a US$150/SOL
- `cost_drag_pct` dos componentes em SOL: (0,33 / 25,00) × 100 ≈ 1,32 pontos percentuais
- + slippage de execução: 1,00 ponto percentual
- **`cost_drag_pct` total ilustrativo (1x) ≈ 2,32 pontos percentuais**

`net_return_pct(mult) = outcome_900_return_pct - (cost_drag_pct_base × mult)` — ver seção 3.6 pra
definição exata da varredura.

### 3.6 Varredura de custo pré-registrada (mudança pedida)

`cost_drag_pct_base` (seção 3.5, recalculado com os valores lidos ao vivo, não os ilustrativos) é
multiplicado por **1x, 2x e 4x** — os três níveis são calculados e reportados, nenhum é pulado. A
varredura escala o `cost_drag_pct_base` inteiro (fee de rede + ATA + slippage de execução juntos),
não só uma parte — é a leitura mais simples e também a mais conservadora de "estressar o custo base".

## 4. Métricas (lista do Gate 3, reusando `RobustReturnMetricsV47` sem código novo)

Pra ALL e pra ALL-sem-LOW, sobre `net_return_pct`, em cada um dos 3 níveis de custo (1x/2x/4x):

- `mean_return_pct`, `median_return_pct`, `profit_factor`, `mean_without_best_pct`, `best_return_pct`,
  `worst_return_pct`, `positive_share_pct`, `largest_winner_share_gross_profit_pct` — todos já existem
  em `src/route_research_feature_robustness_v47.py::robust_return_metrics_v47`, a mesma função que
  `participant_quality_tail_risk_rejection_v0.py`/`participant_quality_native_holdout_v1.py` já
  reusam via `_metrics_dict`. **Nenhuma métrica nova precisa ser implementada.**

## 5. Três classificações, não passa/falha (mudança pedida)

Calculadas em cada nível de custo (1x, 2x, 4x), sobre `net_return_pct` de ALL-sem-LOW vs ALL:

- **`FILTRO_LUCRATIVO`**: ALL-sem-LOW tem `profit_factor` > 1,0 **e** `median_return_pct` > 0 **e**
  `mean_without_best_pct` > 0 (sobrevive sem o maior vencedor — as três condições, não bastam duas).
- **`FILTRO_MELHORA_MAS_NAO_LUCRA`**: não bate `FILTRO_LUCRATIVO`, mas `median_return_pct` de
  ALL-sem-LOW > `median_return_pct` de ALL **e** `profit_factor` de ALL-sem-LOW > `profit_factor` de
  ALL (melhora relativa nos dois, sem cruzar a linha de lucro líquido real).
- **`FILTRO_NAO_AJUDA`**: nenhuma das duas condições acima se sustenta.

### Classificação oficial (barra "sobrevive a pelo menos 2x", mudança pedida)

A classificação oficial — a que vai pro registro — é a **pior entre a classificação em 1x e em 2x**
(ordem: `FILTRO_LUCRATIVO` > `FILTRO_MELHORA_MAS_NAO_LUCRA` > `FILTRO_NAO_AJUDA`). Se cair de
`FILTRO_LUCRATIVO` em 1x para `FILTRO_MELHORA_MAS_NAO_LUCRA` em 2x, a oficial é
`FILTRO_MELHORA_MAS_NAO_LUCRA` — não sobreviveu à varredura. **4x é só informativo**, reportado mas
não exigido pra nenhuma classificação oficial.

## 6. `FILTRO_LUCRATIVO` não é `VALIDADA` automática — é hipótese nova (mudança pedida)

Se a classificação oficial for `FILTRO_LUCRATIVO`, isso **não** promove PQ-TR-V0/PQ-TR-REPL-V1
diretamente a `VALIDADA`. A pergunta que PQ-TR-V0/REPL-V1 testaram sempre foi "LOW é pior que ALL"
(rejeição/risco, relativa) — "a população sem LOW dá lucro líquido" é uma afirmação diferente e mais
forte, que só aparece agora, depois de ver o resultado desta mesma amostra. Tratá-la como já validada
seria exatamente o problema de múltiplas comparações que o registro existe pra conter.

Portanto: `FILTRO_LUCRATIVO` oficial grava uma **hipótese nova**, com ID próprio a definir (proposta:
`PQ-TR-PROFIT-V0`), status `PRE-REGISTRADA`, pergunta congelada ("a população ALL-sem-LOW, filtrada
pelo cutoff `-86.0484432047999`, é líquida de custo positiva: PF>1, mediana>0, robusta sem o maior
vencedor"), e **exige sua própria replicação fresh** — amostra nova, não a mesma de H1+H2 desta
replicação (que já está queimada para a pergunta de rejeição; reusá-la de novo para a pergunta de
lucro seria o mesmo erro de amostra queimada já proibido em todo outro protocolo deste repo) — antes
de poder virar `VALIDADA` pela mesma régua de 3 passos do registro.

## 7. Proibido depois de ver o resultado da replicação ou deste próprio cálculo

- mudar qualquer componente do modelo de custo (seção 3) ou os multiplicadores da varredura (1x/2x/4x);
- mudar a fonte ou o momento de leitura do preço do SOL ou do custo de ATA;
- mudar as definições das três classificações ou a regra "pior entre 1x e 2x";
- trocar horizonte, grupo, ou população;
- rodar isto se a replicação não for PASS;
- pular a seção 6 e tratar `FILTRO_LUCRATIVO` como validação direta.

## 8. Execução (não autorizada ainda — precisa do sign-off E do PASS da replicação)

Script/implementação não escritos ainda — ficam para depois do sign-off, como o menor diff possível:
ler `$HOLDOUT_REPORT` (já existe), ler preço do SOL (Jupiter Price API) e custo de ATA
(`getMinimumBalanceForRentExemption`) ao vivo, montar `cost_drag_pct_base`, aplicar nos 3
multiplicadores, chamar `robust_return_metrics_v47` para ALL/ALL-sem-LOW em cada nível, aplicar as 3
classificações da seção 5, determinar a oficial pela regra da seção 5, e — se `FILTRO_LUCRATIVO` —
preparar o pré-registro da hipótese nova da seção 6 (não a hipótese em si, só a abertura da linha).
Nenhuma nova aquisição, nenhuma nova tabela de banco de dados.

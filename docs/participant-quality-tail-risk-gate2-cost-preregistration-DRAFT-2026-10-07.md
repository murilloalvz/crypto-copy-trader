# Participant Quality Tail-Risk Rejection — Gate 2 (custos) — Preregistration — DRAFT — 2026-10-07

Status: **DRAFT — aguarda sign-off do operador. Não autoriza nenhum cálculo. Escrito antes de
existir qualquer veredito da replicação (`docs/participant-quality-tail-risk-replication-v1-preregistration-2026-10-07.md`),
sem olhar nenhum episódio do holdout.** Commit precisa acontecer antes de você rodar a replicação.

## Por que isso existe agora, antes do veredito

`docs/live-readiness-gates-v1.md`, Gate 2: "Uma estratégia candidata só avança se puder ser
reproduzida usando... slippage e fees contra o replay." A própria regra 2 do registro de hipóteses
("resultado positivo líquido de custos (Gate 2)") é o terceiro e último passo pra `VALIDADA` — depois
de PASS no teste pré-registrado e PASS na replicação. Escrever este Gate 2 agora, e não depois de ver
o resultado da replicação, é o que evita que o corte/modelo de custo seja ajustado pra fazer o
resultado passar.

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

## 3. Modelo de custo explícito (número proposto, com origem)

A cotação route-only (`outcome_900_return_pct`) já inclui price impact — o probe Jupiter já usado
roda com `research_slippage_bps=100` (1% de slippage configurado, já embutido na cotação de entrada e
saída). Este Gate 2 **não adiciona slippage de novo** — só a camada de execução que a cotação
route-only não cobre: fee de rede + priority fee, ida e volta (compra + venda = 2 transações).

| Componente | Valor proposto | Origem |
|---|---|---|
| Fee base por transação | 5.000 lamports (0,000005 SOL) | Documentação oficial Solana (fee fixo por assinatura) |
| Transações por episódio | 2 (compra + venda) | Definição do próprio replay route-only (entrada + saída) |
| Compute unit price (priority fee) | 5.000 microlamports/CU | Percentil "high" (~75º) de tabelas de estimador de priority fee de mercado (ex. RPC/estimadores citados em pesquisa de mercado desta sessão) — **não** o percentil "veryHigh"/"max" usado em guerra de sniping no slot de criação, porque Gate 2 modela uma decisão pós-sinal (alguns segundos de latência já assumidos no pipeline), não uma corrida pelo mesmo slot |
| Compute units por transação (swap Jupiter) | 200.000 CU | **Assunção própria, não uma medição direta** — Jupiter não publica um número típico fixo; este valor é uma estimativa conservadora de meio-de-faixa pra uma rota de 1-2 hops. Precisa ser confirmado ou substituído pelo operador antes do sign-off, idealmente com CUs reais observados nas transações já simuladas pelo probe Jupiter deste projeto, se esse dado existir nos logs. |
| Priority fee por transação | 5.000 × 200.000 / 1.000.000 = 1.000.000 lamports = 0,001 SOL | Fórmula oficial: `priority_fee_lamports = cu_price_microlamports × cu_limit / 1_000_000` |
| Custo total por transação | 5.000 + 1.000.000 = 1.005.000 lamports ≈ 0,001005 SOL | fee base + priority fee |
| **Custo total ida e volta** | **≈ 0,00201 SOL** | 2 × 0,001005 SOL |
| Preço SOL assumido (ilustrativo) | US$150/SOL | **Assunção, não dado atual** — precisa ser atualizado pelo operador pro preço vigente no momento do sign-off, não no momento em que isto foi escrito |
| **Custo total ida e volta em USD** | **≈ US$0,30** | 0,00201 × 150 |
| Notional de referência | US$25,00 | `research_notional_usd=25.0`, já hardcoded em `participant_quality_native_holdout_v1.py`/`route_research_signal_plane_bridge_v0.py` — o mesmo notional que a própria replicação usa, não um número novo |
| **`cost_drag_pct` (aplicado a todo episódio, flat)** | **≈ 1,20 pontos percentuais** | (0,30 / 25,00) × 100 |

`net_return_pct = outcome_900_return_pct - cost_drag_pct`, aplicado uniformemente (o custo em SOL não
escala com o tamanho do trade — isso é reflexo real de como fee + priority fee funcionam no Solana,
não uma simplificação arbitrária).

**Isto é um modelo conservador de primeira passada para Gate 2, não um modelo de execução completo.**
A própria revisão de evidência deste projeto (`docs/research-evidence-registry-v1-2026-09-02.md`,
E9) já registrou que fee/priority fee "se torna uma superfície modelada, não uma assunção de fee
constante" — isso é verdade pros Gates 4/5 (shadow/execução real), não uma contradição com usar uma
constante explícita e sourced aqui, no primeiro corte Gate 2. Qualquer parâmetro desta tabela pode ser
corrigido pelo operador **antes** do sign-off — depois de ver o resultado, fica proibido pela mesma
regra 3 do registro.

## 4. Métricas (lista do Gate 3, reusando `RobustReturnMetricsV47` sem código novo)

Pra ALL e pra ALL-sem-LOW, sobre `net_return_pct`:

- `mean_return_pct`, `median_return_pct`, `profit_factor`, `mean_without_best_pct` (resultado sem o
  maior vencedor), `best_return_pct`, `worst_return_pct`, `positive_share_pct`,
  `largest_winner_share_gross_profit_pct` — todos já existem em
  `src/route_research_feature_robustness_v47.py::robust_return_metrics_v47`, a mesma função que
  `participant_quality_tail_risk_rejection_v0.py`/`participant_quality_native_holdout_v1.py` já
  reusam via `_metrics_dict`. **Nenhuma métrica nova precisa ser implementada** — só chamar a função
  já existente sobre `net_return_pct` em vez de `outcome_900_return_pct`.

## 5. Barra de aprovação proposta (só aplicável se a replicação for PASS)

PASS neste Gate 2 exige os três, todos líquidos de custo:

1. `median_return_pct` de ALL-sem-LOW > `median_return_pct` de ALL (o filtro precisa melhorar a
   mediana da população restante, não só "não piorar" — Gate 2 é sobre resultado positivo líquido de
   custo, uma barra mais alta que o Gate 3 original da V0/replicação, que só exigia "não piorar");
2. `profit_factor` de ALL-sem-LOW > 1,0 (lucratividade líquida real, não só comparação relativa);
3. `mean_without_best_pct` de ALL-sem-LOW > `mean_without_best_pct` de ALL (o resultado não pode
   depender só do maior vencedor isolado — mesma disciplina já usada em V48/V68/CD-PROMO-V0).

Classificações propostas: `PASS_PARTICIPANT_QUALITY_TAIL_RISK_GATE2_COST`,
`FAIL_PARTICIPANT_QUALITY_TAIL_RISK_GATE2_COST`.

`FAIL` aqui **não reabre nem reinterpreta** o PASS já obtido na replicação — PQ-TR-V0/PQ-TR-REPL-V1
continuam válidos como filtro de rejeição route-only; só significa que o Gate 2 (promoção pra
`VALIDADA`) não foi atingido ainda. Sem segunda tentativa de Gate 2 sobre a mesma amostra — um FAIL
aqui fecha esta tentativa específica de promoção, pela mesma disciplina de falha de todo protocolo
congelado deste repo.

## 6. Proibido depois de ver o resultado da replicação ou deste próprio cálculo

- mudar qualquer número da tabela de custo da seção 3;
- mudar a barra de aprovação da seção 5;
- trocar horizonte, grupo, ou população;
- rodar isto se a replicação não for PASS.

## 7. Execução (não autorizada ainda — precisa do sign-off E do PASS da replicação)

Script/implementação não escritos ainda — ficam para depois do sign-off, como o próprio menor diff
possível: ler `$HOLDOUT_REPORT` (já existe), aplicar `cost_drag_pct` fixo, chamar
`robust_return_metrics_v47` duas vezes (ALL, ALL-sem-LOW), aplicar os 3 gates da seção 5. Nenhuma
nova aquisição, nenhuma nova tabela de banco de dados.

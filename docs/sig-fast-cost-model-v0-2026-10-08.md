# SIG-FAST V0 — modelo de custo real (F4, 2026-10-08)

Pesquisa com fonte e data, para parametrizar `CostModel` em
`src/opportunity_path_metrics_v0.py` (F2). Nada inventado: todo número vem de uma
fonte citada; o que as fontes não resolvem fica marcado "não confirmado" — nunca
preenchido com um palpite. Pesquisa feita em 2026-10-08.

## 1. Fee da bonding curve do pump.fun (pré-graduação)

**Fonte primária, mais recente e mais autoritativa: a própria página de fees do
pump.fun** (`pump.fun/docs/fees`, lida diretamente em 2026-10-08; a página se
identifica como atualizada em **20 de maio de 2026**):

> Bonding curve (SOL e USDC): fee total **flat de 1,250%**, sem faixas por
> market cap. PumpSwap (pós-graduação) é que tem faixas por market cap (tabela
> completa na seção 2).

Isso **contradiz uma narrativa mais antiga** (Blockworks, "Pump.fun adopts
dynamic fee model", sem data de publicação visível no resultado de busca, e
Smithii, artigo datado da rollout de "Project Ascend" em 2025-09-02) que descreve
a fee da própria bonding curve como dinâmica por market cap (criador variando de
0,95% abaixo de US$300k até 0,05% acima de US$20M). O documento oficial do
protocolo (`pump-fun/pump-public-docs/docs/FEE_PROGRAM_README.md`, lido
diretamente em 2026-10-08) confirma que a bonding curve **ganhou capacidade**
de fee dinâmica por market cap a partir de 2025-09-01 ("a dynamic fee structure
depending on the current market cap of the coin in lamports", com fallback para
`feeBasisPoints`/`creatorFeeBasisPoints` globais se não houver config por
moeda) — ou seja, a infraestrutura dinâmica existe, mas **a página de fees atual
do próprio protocolo, mais recente, mostra o valor efetivo hoje como flat
1,250%**, sem tiers na bonding curve. Fica registrado como conflito de fontes
resolvido pela precedência de `CLAUDE.md` (fonte direta e mais recente do
próprio protocolo > artigo de terceiro sem data clara).

**Split protocolo/criador na bonding curve**: a documentação oficial (`FEE_PROGRAM_README.md`)
confirma que a fee se divide em `protocolFeeBps` e `creatorFeeBps`, mas **não
publica os valores exatos de cada fatia** no texto (só a estrutura de evento,
não a doc de fee em si). **Não confirmado**: a divisão exata protocolo/criador
dentro do 1,250% da bonding curve. O que é confirmado e mais importante pro
modelo de custo: a **fee real cobrada em cada trade específico já vem no
próprio evento on-chain** (`TradeEvent` do pump: campos `fee`/`fee_basis_points`/
`creator_fee`/`creator_fee_basis_points`, confirmados no IDL oficial `pump.json`,
mas ainda não lidos pelo decoder nem persistidos — ver F1b/F1a, seção "o que não
foi feito"). Ler o evento é a fonte de verdade por trade; a tabela é só
aproximação/cross-check.

**Valor a usar em `CostModel.venue_fee_pct` para bonding curve, nesta versão**:
**1,250%** (flat), com a ressalva documentada acima.

## 2. Fee do PumpSwap (pós-graduação) — tabela completa, lida diretamente da fonte oficial

Mesma fonte (`pump.fun/docs/fees`, lida 2026-10-08, página datada 2026-05-20).
Confirma e estende a tabela já citada em revisões anteriores do memo de
estratégia (`docs/strategy-options-move-first-2026-10-07.md`, Opção F) — agora
com todas as 25 faixas, não só os dois extremos.

### PumpSwap, pools canônicos denominados em SOL

Market cap = preço em SOL × 1 bilhão de tokens.

| Market cap (SOL) | Fee total |
|---|---|
| 0 – 420 | 1,250% |
| 420 – 1.470 | 1,200% |
| 1.470 – 2.460 | 1,150% |
| 2.460 – 3.440 | 1,100% |
| 3.440 – 4.420 | 1,050% |
| 4.420 – 9.820 | 1,000% |
| 9.820 – 14.740 | 0,950% |
| 14.740 – 19.650 | 0,900% |
| 19.650 – 24.560 | 0,850% |
| 24.560 – 29.470 | 0,800% |
| 29.470 – 34.380 | 0,750% |
| 34.380 – 39.300 | 0,700% |
| 39.300 – 44.210 | 0,650% |
| 44.210 – 49.120 | 0,600% |
| 49.120 – 54.030 | 0,550% |
| 54.030 – 58.940 | 0,525% |
| 58.940 – 63.860 | 0,500% |
| 63.860 – 68.770 | 0,475% |
| 68.770 – 73.681 | 0,450% |
| 73.681 – 78.590 | 0,425% |
| 78.590 – 83.500 | 0,400% |
| 83.500 – 88.400 | 0,375% |
| 88.400 – 93.330 | 0,350% |
| 93.330 – 98.240 | 0,325% |
| 98.240+ | 0,300% |

Pools PumpSwap **não-canônicos**: fee flat de **0,300%**, sem faixas.

**Split LP/protocolo/criador dentro do total**: confirmado em sessão anterior
via IDL oficial (`pump_amm.json`, campos `lp_fee_basis_points`/
`protocol_fee_basis_points`/`coin_creator_fee_basis_points` do `BuyEvent`/
`SellEvent`) — a fatia do **LP** é **0,020%** abaixo de 420 SOL de mcap e
**0,200%** a partir de 420 SOL (fonte: `madeonsol.com/blog/what-is-pumpswap`,
já citada no memo de estratégia; consistente com o artigo Smithii desta
pesquisa, que descreve a mesma mudança de 0,02%→0,2% no corte de 420 SOL,
efetiva 2025-09-02). O resto do total (criador + protocolo) preenche a
diferença. **Não confirmado nesta pesquisa**: o split exato criador-vs-protocolo
dentro dessa diferença, faixa a faixa — de novo, ler o evento por trade
(`lp_fee`/`protocol_fee`/`coin_creator_fee`, todos em lamports, já no payload)
é a fonte de verdade, a tabela é cross-check.

**Valor a usar em `CostModel.venue_fee_pct` para PumpSwap**: tabela acima,
indexada pela faixa de market cap do pool no momento do trade (não um número
fixo) — ou, preferencialmente, o campo `lp_fee + protocol_fee + coin_creator_fee`
do próprio evento, dividido pelo `quote_amount`, quando esses campos forem
persistidos (ainda não são — ver F1b).

## 3. Taxa por trade dos terminais

Nenhum terminal tem página oficial de fees acessível nesta pesquisa (todas as
fontes abaixo são guias/comparadores de terceiros — "confirmado" aqui significa
"≥2 fontes independentes convergem", não "fonte oficial do produto"). Toda
fee de terminal é **adicional** à fee do venue (seção 1-2) — um comparador do
BullX (`comparedge.com/tools/bullx/pricing`, verificado 2026-07-08) é
explícito: "+0,25% on Raydium and +1% on Pump.fun" por cima da fee do próprio
BullX, confirmando que `CostModel.terminal_fee_pct` deve somar, não substituir,
`venue_fee_pct` — exatamente como o F2 já modela.

| Terminal | Fee por perna (padrão) | Fee com referral | Fonte | Confiança |
|---|---|---|---|---|
| **Axiom** | 0,95% (tier "Wood", novo usuário) até 0,75% (tier "Champion", alto volume) | ~0,81-0,90% (fontes discordam sobre o %) | [Axiom Trade Fees — Medium](https://medium.com/@crypto-deploy/axiom-trade-fees-what-you-actually-pay-and-how-to-pay-less-0df290e57f7b); [madeonsol.com/blog/how-to-use-axiom-solana-trading](https://madeonsol.com/blog/how-to-use-axiom-solana-trading) | média — guias de terceiro, thresholds de volume não publicados |
| **Photon** | 1,0% | 0,9% | [uwuu.ai/blog/photon-review](https://uwuu.ai/blog/photon-review); [comparedge.com/tools/photon-sol/pricing](https://comparedge.com/tools/photon-sol/pricing) | média-alta — 2 fontes convergem |
| **GMGN** | 1,0% | 0,9% (uma fonte cita até 0,70% com código especial, não verificado) | [defillama.com/protocol/gmgn](https://defillama.com/protocol/gmgn); [solanacompass.com/projects/GMGN](https://solanacompass.com/projects/GMGN) | alta — DefiLlama trata 1% como receita de protocolo medida, não só marketing |
| **BullX** | 1,0% (+ fee do venue por cima, ex. +1% no pump.fun) | 0,9% | [comparedge.com/tools/bullx/pricing](https://comparedge.com/tools/bullx/pricing) (verificado 2026-07-08) | média — página de comparador, não a BullX oficial; uma fonte (madeonsol) afirma que o BullX "não é mais uma opção", não resolvido |
| **Trojan** | 1,0% (uma fonte cita 0,9% como base, não 1%) | 0,9% | [coin360.com/review/trojan](https://coin360.com/review/trojan); [madeonsol.com/blog/how-to-use-trojan-solana-trading](https://madeonsol.com/blog/how-to-use-trojan-solana-trading) | média — 2 valores-base conflitantes entre fontes |
| **Jupiter (direto)** | **Sem fee de protocolo obrigatória.** `feeBps` é opcional, definido por quem integra (ex. SDK usa 50bps de exemplo); Limit Order cobra 0,2% no taker (0,1% Jupiter + 0,1% referral); Perps: 0,1% taker/0,01% maker. **Não confirmado**: se o app de consumidor da própria Jupiter (modo "Ultra") aplica uma fee de plataforma própria por padrão — a doc lida é da seção legacy/API | [docs.jup.ag/docs/legacy/apis/adding-fees](https://docs.jup.ag/docs/legacy/apis/adding-fees); [defillama.com/protocol/jupiter-aggregator](https://defillama.com/protocol/jupiter-aggregator) | baixa-média para o modo Ultra; alta para swap via API/SDK puro (0% confirmado como padrão) |

**Round-trip (entrada+saída)**: para qualquer terminal ~1%/perna, o custo de
terminal do round-trip é ~2% (ou ~1,8% com referral) — já é assim que
`CostModel` soma (`total_fee_pct` por perna, aplicado separadamente em
`simulate_amm_buy_execution_price_sol`/`simulate_amm_sell_execution_price_sol`).

**Valor a usar em `CostModel.terminal_fee_pct`**: grade `{0%, 1%}` por perna
(conforme pedido no work order) — 1% cobre adequadamente Photon/GMGN/BullX/
Trojan no caso padrão (sem referral); Axiom tende a ficar um pouco abaixo
(0,75-0,95%) e Jupiter direto tende a ficar em 0% — a grade de 2 pontos é uma
simplificação deliberada do work order, não uma tentativa de capturar a
variação fina entre terminais.

## 4. Priority fee típica para entrar rápido em memecoin

**Não há uma fonte que dê um número "típico" único para 2026** — toda fonte
encontrada ou dá a fórmula (sem valor de mercado atual) ou um exemplo
ilustrativo/âncora, não uma leitura de mercado ao vivo:

- Mecânica: fee base fixa de 5.000 lamports/assinatura + fee de prioridade =
  unidades de computação consumidas × preço por unidade em microlamports
  ([Helius — Priority Fees](https://helius.dev/blog/priority-fees-understanding-solanas-transaction-fee-mechanics); [Solana Cookbook](https://solana.com/developers/cookbook/transactions/add-priority-fees)).
- Exemplo ilustrativo (não medição de mercado): 100 microlamports/CU em 200.000
  CU ≈ 0,00002 SOL ([madeonsol.com/blog/solana-priority-fees-guide](https://madeonsol.com/blog/solana-priority-fees-guide), 2026).
- Default de um terminal real: Photon usa 0,001 SOL (~US$0,19) como priority
  fee padrão (fee total, não por-CU) — citado no levantamento de GMGN desta
  pesquisa (configurações entre 0,002-0,006+ SOL, ver
  [solanacompass.com/projects/GMGN](https://solanacompass.com/projects/GMGN)).
- Extremo documentado (não representativo): um trader pagou 1.068 SOL
  (~US$207.000) de priority fee numa disputa de bloco 0 por um memecoin
  específico ([Decrypt](https://decrypt.co/300084/solana-trader-paid-200k-fee-didnt-end-well)) — isto é o oposto de "entrada manual típica" (é competição
  de bloco 0/MEV, fora do escopo read-only/manual do SIG-FAST) e não deve ser
  usado como referência de custo típico.

**Não confirmado**: uma faixa "típica" realista de priority fee para o caso de
uso do SIG-FAST (operador manual, ~segundos de atraso, sem brigar por bloco 0).
**Recomendação para F5/F7**: não fixar um número de priority fee nesta
pesquisa — ler `getRecentPrioritizationFees` via RPC no momento do discovery
real (dado de sistema, não economicamente sensível, não gasta tentativa) para
obter uma faixa empírica contemporânea, ou pedir ao operador a faixa que ele
de fato paga no terminal que usa (pergunta aberta, já prevista na seção F5/F7
do work order: "latência real dele, terminal usado, tamanho").

## 5. Custo de rede e ATA

Dados pelo próprio operador no work order, não pesquisados aqui: rede
0,0003 SOL/perna, ATA 0 — já são os defaults de `CostModel.network_fee_sol`/
`CostModel.ata_fee_sol` em `src/opportunity_path_metrics_v0.py`.

## Resumo para o `CostModel`

| Parâmetro | Valor(es) a usar | Fonte / confiança |
|---|---|---|
| `venue_fee_pct` (bonding curve) | 1,250% flat | pump.fun/docs/fees, oficial, lido 2026-10-08 |
| `venue_fee_pct` (PumpSwap) | tabela de 25 faixas (seção 2), por market cap do pool no momento do trade | pump.fun/docs/fees, oficial, lido 2026-10-08 |
| `terminal_fee_pct` | grade `{0%, 1%}` por perna (per work order) | convergência de 4-5 fontes de terceiro, sem página oficial de nenhum terminal |
| `network_fee_sol` | 0,0003 SOL/perna | dado pelo operador |
| `ata_fee_sol` | 0 | dado pelo operador |
| priority fee | sem valor fixo — ler ao vivo ou perguntar ao operador | nenhuma fonte dá um "típico" confiável |

## Fontes consultadas (2026-10-08)

- [pump.fun/docs/fees](https://pump.fun/docs/fees) — página oficial, datada 2026-05-20
- `pump-fun/pump-public-docs/docs/FEE_PROGRAM_README.md` (GitHub, lido via raw content)
- [Blockworks — Pump.fun adopts dynamic fee model](https://www.blockworks.co/news/pumpdotfun-fee-model)
- [Smithii — Project Ascend update](https://smithii.io/en/project-ascend-update/)
- [madeonsol.com/blog/what-is-pumpswap](https://madeonsol.com/blog/what-is-pumpswap) (já citado no memo de estratégia)
- [Axiom Trade Fees — Medium](https://medium.com/@crypto-deploy/axiom-trade-fees-what-you-actually-pay-and-how-to-pay-less-0df290e57f7b)
- [madeonsol.com/blog/how-to-use-axiom-solana-trading](https://madeonsol.com/blog/how-to-use-axiom-solana-trading)
- [uwuu.ai/blog/photon-review](https://uwuu.ai/blog/photon-review)
- [comparedge.com/tools/photon-sol/pricing](https://comparedge.com/tools/photon-sol/pricing)
- [defillama.com/protocol/gmgn](https://defillama.com/protocol/gmgn)
- [solanacompass.com/projects/GMGN](https://solanacompass.com/projects/GMGN)
- [comparedge.com/tools/bullx/pricing](https://comparedge.com/tools/bullx/pricing)
- [coin360.com/review/trojan](https://coin360.com/review/trojan)
- [madeonsol.com/blog/how-to-use-trojan-solana-trading](https://madeonsol.com/blog/how-to-use-trojan-solana-trading)
- [docs.jup.ag/docs/legacy/apis/adding-fees](https://docs.jup.ag/docs/legacy/apis/adding-fees)
- [defillama.com/protocol/jupiter-aggregator](https://defillama.com/protocol/jupiter-aggregator)
- [helius.dev — Priority Fees](https://helius.dev/blog/priority-fees-understanding-solanas-transaction-fee-mechanics)
- [Solana Cookbook — Add priority fees](https://solana.com/developers/cookbook/transactions/add-priority-fees)
- [madeonsol.com/blog/solana-priority-fees-guide](https://madeonsol.com/blog/solana-priority-fees-guide)
- [Decrypt — $200k priority fee](https://decrypt.co/300084/solana-trader-paid-200k-fee-didnt-end-well)

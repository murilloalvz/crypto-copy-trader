# Opção H — Memecoins Estabelecidas, Momentum — Discovery V0 — Preregistration — DRAFT — 2026-10-08 (rev. 4, autocontida)

Status: **DRAFT — sign-off parcial recebido em 2 rodadas (rev. 2 e rev. 3), com correções em
ambas. Ainda NÃO autoriza discovery, backtest, consulta a outcome ou execução do backfill.**
Esta revisão é **autocontida**: reintegra o protocolo inteiro (universo, sinal, comparações,
suporte mínimo, split, critério de lucro, escolha, classificação, risco de transferência,
proibições) num texto só, com todas as correções das revisões 2 e 3 já aplicadas — nenhuma seção
depende de "ver revisão anterior". Pesquisa adicional desta revisão: achado novo e potencialmente
bloqueante sobre `InitBoost` (seção "Investigação InitBoost" abaixo) e correções à seção de custo
(rede/priority em SOL, ATA explicitamente custo zero, tabela de fee literal da doc oficial, regra
de regime ambíguo). Nenhum retorno foi consultado em nenhum passo — só estrutura, cobertura e custo.

ID no registro: `MOVE-FIRST-H-DISC-V0`. Fonte da opção: `docs/strategy-options-move-first-2026-10-07.md`
(Opção H) e `docs/research-hypothesis-registry-v1-2026-10-04.md`.

---

## Investigação InitBoost (BLOQUEADOR da rev.3 — resolvido para o período recente, pendente para o período antigo)

**O que o BOOST é, confirmado contra fonte oficial-adjacente (cobertura de imprensa do anúncio do
próprio Pump.fun) e verificado ao vivo, estruturalmente, numa transação real desta sessão:**

- BOOST é "o novo mecanismo padrão de lançamento pra TODA moeda nova do pump.fun", ativo pra
  migrações **depois de 2026-07-21 10:23 ET**; migrações antes do corte e lançamentos via "Mayhem"
  não o recebem.
- Mecanismo: uma fração da própria liquidez da migração (no exemplo que verifiquei, **17,58 SOL**
  de um total que `CreatePool` tinha acabado de depositar) é **extraída da reserva do pool** por
  um agente automatizado, que gasta esse SOL num buyback fatiado em slices ao longo de ~5 minutos
  (reduz impacto de um lote único), **queimando** o que compra. O SOL não volta pro pool.
- **Isso acontece dentro da MESMA transação atômica de migração**, imediatamente depois do
  `CreatePool` — não é um evento separado, posterior, sobre um pool já assentado.
- **Verificado ao vivo nesta sessão** (transação real, `jsonParsed`, só estrutura — nenhum preço
  lido): na mesma transação, depois da extração de SOL, os tokens de LP recém-mintados por
  `CreatePool` são **queimados** (`burn` da quantidade inteira) e a conta de LP é **fechada**
  (`closeAccount`, aluguel devolvido pra conta de migração) — confirma estruturalmente, não só por
  citação de terceiro, que "LP queimado" é literal e acontece na própria transação de migração,
  não depois.

**Por que isso não quebra a regra de morte-vs-gap, pro período coberto por esta verificação**:
como tudo (extração de SOL do BOOST + queima do LP) acontece dentro da mesma transação atômica de
migração, **qualquer leitura de reservas feita depois que essa transação já foi confirmada já
reflete o estado final, pós-boost**. `k` derivado de qualquer ponto depois da migração (inclusive
imediatamente depois) já é o `k` certo — não precisa "descontar" o boost separadamente. A regra
"zero swap depois da migração ⇒ reservas paradas" continua válida pro período coberto.

**O que ainda NÃO está resolvido (pendência real, não fechada nesta revisão)**: BOOST só existe
desde 2026-07-21. O backfill cobre 2025-03-20 em diante — **~16 meses sem BOOST**, a maior parte
do período. Pergunta aberta: nesse período mais antigo, o LP de migração era **igualmente
queimado** (sem o passo de BOOST, mas ainda queimado por alguma outra instrução), ou ficava em
alguma conta que **não** era queimada (o que quebraria a premissa física "LP queimado" pra
praticamente toda a amostra antiga)? **Isso só se resolve lendo uma transação de migração real de
antes de 2025-05 ou similar** — é exatamente o que a amostragem da conta de migração (seção
"Amostragem da conta de migração" abaixo) está apurando; resultado consolidado nesta revisão onde
já disponível, e marcado como pendência restante onde não.

---

## 1. Universo ("estabelecida")

Um token entra no universo de uma data de rebalanceamento `t` se, **usando só dado anterior a `t`**:

1. já graduou da bonding curve para PumpSwap há **>= 7 dias de calendário** antes de `t` (margem
   larga sobre dois achados de risco de entrada precoce: MemeTrans — ~73% dos tokens caem para
   <40% do preço de migração em 20min — e E12 — >85% dos snipers saem em <5min);
2. teve volume 24h >= **US$5.000** (comparação de piso baixo) ou **US$20.000** (piso alto —
   comparação separada, seção 4) em pelo menos 5 dos 7 dias de calendário imediatamente antes de `t`;
3. tem preço resolvível em `t` **e** liquidez resolvível em `t+7` — se não tiver em `t+7`, não é
   excluído: vira retorno conforme a regra de morte-vs-gap (seção 8).

## 2. Sinal

Feature única: retorno acumulado nos **N dias anteriores a `t`** ("momentum"), mesma lógica de
Liu/Tsyvinski/Wu (JF 2022) — ordenação cruzada semanal, quintil de maior momentum vs quintil de
menor. **Long-only**: o programa não tem infraestrutura de short/borrow para memecoin; não
replicamos o lado short do paper — divergência de escopo registrada, não escondida.

## 3. Rótulo e horizonte

Retorno forward de **7 dias de calendário** a partir de `t` (próximo rebalanceamento semanal). Não
colide com nenhum horizonte congelado em segundos (`ROUTE_RESEARCH_HORIZONS_SECONDS` é outro
sistema, outra unidade, outra pergunta).

## 4. Comparações desta descoberta (pré-registradas, não escolhidas depois de ver o resultado)

Varredura de **4 combinações**:

| Lookback (N dias) | Piso de volume 24h |
|---|---|
| 7 | US$5.000 |
| 7 | US$20.000 |
| 14 | US$5.000 |
| 14 | US$20.000 |

Isso é **discovery** (regra 4 do registro de hipóteses): gera no máximo 1 candidato; não promove
nada a `VALIDADA` diretamente.

## 5. Suporte mínimo, split temporal e bloco de confirmação selado

- **Treino**: >= 15 datas de rebalanceamento válidas. **Retentor**: >= 6 datas de rebalanceamento
  válidas. Unidade é a **data de rebalanceamento** (semana), não token-semana — token-semanas da
  mesma semana não são observações independentes entre si.
- **Data pulada**: qualquer data de rebalanceamento cujo universo (seção 1) tenha **menos de 25
  tokens** é pulada inteira (não conta nem pro treino nem pro retentor) — decidido agora, não
  depois de ver quantos tokens cada data teria.
- Além disso, suporte mínimo em volume: **n >= 30 observações token-semana** no quintil de topo,
  somando treino + retentor.
- **Bloco de confirmação selado**: **12 semanas fixas**, as mais recentes disponíveis no backfill
  no momento do selamento. Hash do conteúdo (lista de episódios + valores) commitado antes de
  qualquer código de discovery rodar; o bloco **nunca** é lido pelo discovery, só por
  `MOVE-FIRST-H-CONF-V0` (a escrever depois), usando a mesma regra congelada que o discovery
  escolher.
- **Embargo**: **1 semana**. O último `t` do discovery, mais o horizonte de 7 dias
  (`t_último_discovery + 7d`), precisa terminar **antes** do primeiro `t` do bloco selado.
- **Mínimo total utilizável, checado antes de calcular qualquer retorno** (contagem só de
  cobertura):

  ```
  2 (lookback, pra ter N dias de momentum antes do 1º t)
  + 15 (treino) + 6 (retentor) + 1 (embargo) + 12 (bloco selado)
  = 36 semanas
  ```

  Abaixo de 36 semanas de histórico utilizável → `INCONCLUSIVE_SAMPLE`, antes de qualquer cálculo
  de retorno.

## 6. Candidato exige lucro absoluto (não só concordância de sinal)

Uma combinação (das 4 da seção 4) só é candidata se, **no treino**: retorno semanal líquido de
custo (sweep 1x, seção 8) do **quintil de topo** tiver **média E mediana > 0**. E, **no
retentor**: a **média líquida** do quintil de topo tem o **mesmo sinal** (positivo) da média do
treino — não precisa bater em magnitude. **Spread topo-fundo e retorno do universo equal-weight
são diagnóstico, não critério de escolha** — reportados, mas não decidem PASS/candidato.

## 7. Critério de escolha entre as 4 combinações

Entre as combinações que passam a regra 6 no treino: escolhe a de **maior média líquida do
quintil de topo**. Empate: **lookback menor** (7 dias antes de 14). Zero combinações passando a
regra 6 no treino → `INCONCLUSIVE_NO_CANDIDATE`, sem promover nenhuma.

## 8. Custo por perna, escalado por liquidez — seção revisada nesta rodada

**Impacto de preço:**

```
reserva_de_um_lado_usd ≈ liquidez_total_do_pool_usd / 2
impacto_pct ≈ (tamanho_posicao_usd / reserva_de_um_lado_usd) × 100      # = 2× tamanho / liquidez_total × 100
```

**Liquidez em `t` (o OHLCV não dá isso; é derivada):**

```
k ≈ reserva_SOL_inicial × reserva_token_inicial     # reservas no instante do CreatePool, pós-boost se houver (ver "Investigação InitBoost")
reserva_SOL(t) ≈ sqrt(k × preço_em_SOL_por_token(t))
```

`k` fixo desde a migração (não atualizado por LP de terceiros depois) é **conservador**: LP extra
só aumenta o `k` real, nunca diminui o piso — usar o `k` inicial subestima a reserva real quando
há LP extra, o que **sobre-estima** o impacto de preço (direção segura para um teste de custo).

**Fee de swap — tabela literal da doc oficial** (`pump.fun/docs/fees`, "Last Updated 20 May 2026";
confirmar se esta é também a tabela vigente desde o anúncio do Project Ascend em 2025-09-02/03, ou
se foi revisada entre essas duas datas — não confirmado nesta revisão). Pools canônicos, SOL:

| Market cap (SOL) | Criador | Protocolo | LP | **Total** |
|---|---|---|---|---|
| 0 – 420 | 0,300% | 0,930% | 0,020% | **1,250%** |
| 420 – 1.470 | 0,950% | 0,050% | 0,200% | **1,200%** |
| 1.470 – 2.460 | 0,900% | 0,050% | 0,200% | **1,150%** |
| 2.460 – 3.440 | 0,850% | 0,050% | 0,200% | **1,100%** |
| 3.440 – 4.420 | 0,800% | 0,050% | 0,200% | **1,050%** |
| 4.420 – 9.820 | 0,750% | 0,050% | 0,200% | **1,000%** |
| 9.820 – 14.740 | 0,700% | 0,050% | 0,200% | **0,950%** |
| 14.740 – 19.650 | 0,650% | 0,050% | 0,200% | **0,900%** |
| 19.650 – 24.560 | 0,600% | 0,050% | 0,200% | **0,850%** |
| 24.560 – 29.470 | 0,550% | 0,050% | 0,200% | **0,800%** |
| 29.470 – 34.380 | 0,500% | 0,050% | 0,200% | **0,750%** |
| 34.380 – 39.300 | 0,450% | 0,050% | 0,200% | **0,700%** |
| 39.300 – 44.210 | 0,400% | 0,050% | 0,200% | **0,650%** |
| 44.210 – 49.120 | 0,350% | 0,050% | 0,200% | **0,600%** |
| 49.120 – 54.030 | 0,300% | 0,050% | 0,200% | **0,550%** |
| 54.030 – 58.940 | 0,275% | 0,050% | 0,200% | **0,525%** |
| 58.940 – 63.860 | 0,250% | 0,050% | 0,200% | **0,500%** |
| 63.860 – 68.770 | 0,225% | 0,050% | 0,200% | **0,475%** |
| 68.770 – 73.681 | 0,200% | 0,050% | 0,200% | **0,450%** |
| 73.681 – 78.590 | 0,175% | 0,050% | 0,200% | **0,425%** |
| 78.590 – 83.500 | 0,150% | 0,050% | 0,200% | **0,400%** |
| 83.500 – 88.400 | 0,125% | 0,050% | 0,200% | **0,375%** |
| 88.400 – 93.330 | 0,100% | 0,050% | 0,200% | **0,350%** |
| 93.330 – 98.240 | 0,075% | 0,050% | 0,200% | **0,325%** |
| 98.240+ | 0,050% | 0,050% | 0,200% | **0,300%** |

Market cap = preço em SOL × 1 bilhão de tokens. **Correção à rev.3**: não havia contradição de
verdade — é formato corcova (sobe de 0,30% pra 0,95% em 420 SOL, depois decai tier a tier até o
piso de 0,05%); a rev.3 descreveu mal por citar só os dois extremos. **Correção mais importante**:
o total do swap **não é 0,25% fixo** como todo o resto deste memo vinha assumindo — varia de
0,300% (pools maduros, mcap alto) a 1,250% (pools novos/pequenos, mcap baixo). Pools recém-migrados
(mcap tipicamente baixo) pagam o total **mais alto** da tabela, não o mais baixo — isso é
conservador pra favor do teste de custo (mais fee assumida, não menos), mas é uma correção real a
propagar pra qualquer outro documento deste programa que ainda cite "0,25%" como fixo.

**Regimes históricos conhecidos, mais completos que a rev.3** (fonte por regime, nenhuma leitura
ao vivo num backtest):
1. **2025-03-20** (lançamento PumpSwap) até **2025-05-13**: sem fee de criador — só protocolo+LP
   (fonte: The Block, "PumpSwap revenue-tokens").
2. **2025-05-13** até **2025-09-02/03**: fee de criador **flat** introduzida (±0,05% por fonte
   anterior, não re-verificado nesta revisão) — "drew complaints that it did little for small
   creators" (Blockworks, cobertura do anúncio do Project Ascend).
3. **2025-09-02/03** (anúncio do Project Ascend, CryptoSlate/MEXC/PANews datam nesse dia) em
   diante: tabela por faixa de market cap acima — "reaches every PumpSwap listing", ou seja,
   aplica-se retroativamente a pools já existentes a partir dessa data, não só pools novos.
4. **Não confirmado**: se a tabela da doc oficial (datada 2026-05-20) é idêntica à introduzida em
   2025-09, ou foi revisada entre essas datas.
5. **Regra pra data de corte não confirmável (seu pedido)**: usar a fee **maior** entre os regimes
   candidatos na janela ambígua — nunca a menor. Aplica-se especificamente à incerteza do item 4.

**Rede/priority — corrigido pra SOL, não USD fixo:**

```
custo_rede_por_perna_sol = 0,0003 SOL
custo_rede_por_perna_usd(t) = 0,0003 × preço_histórico_do_SOL_em_USD(t)   # GeckoTerminal SOL/USDC, close diário em t
```

**ATA — custo zero, explícito (omitido por engano na rev.3):** abrir a conta associada ao token
pra comprar exige depósito de aluguel resgatável; ao vender e **fechar** a conta
(`closeAccount`), o aluguel **volta** — confirmado na prática: as transações de migração lidas
nesta sessão fecham contas e devolvem aluguel exatamente assim. Como a regra de saída desta
estratégia sempre vende a posição inteira (sem manter saldo residual), a ATA fecha a cada ciclo —
**custo líquido de ATA = 0**, não um número a somar.

**Fórmula final:**

```
custo_ida_volta_pct ≈ 2 × impacto_pct
                     + fee_swap_entrada(regime, mcap_em_t) + fee_swap_saída(regime, mcap_em_t+7)
                     + custo_rede_por_perna_usd(t)/tamanho_posicao_usd × 100 × 2
                     + 0   # ATA
```

Sweep 1x/2x mantido sobre o custo total, mesma disciplina do Gate 2 do PQ-TR.

## 9. Classificação final

- `INCONCLUSIVE_SAMPLE`: menos de 36 semanas utilizáveis (seção 5), checado antes de calcular
  qualquer retorno.
- `INCONCLUSIVE_DATA`: numa combinação, `missing_source` (seção "regra de morte-vs-gap") acima de
  5% das observações token-semana do quintil de topo.
- `DISCOVERY_MOVE_FIRST_H_V0_CANDIDATE`: exatamente 1 combinação passa a regra 6 no treino E no
  retentor (escolhida pela regra 7 em caso de múltiplas) — vai para `MOVE-FIRST-H-CONF-V0` sobre o
  bloco selado (seção 5).
- `INCONCLUSIVE_NO_CANDIDATE`: nenhuma combinação passa a regra 6 no treino, ou nenhuma mantém o
  sinal no retentor.

## 10. Regra de morte vs gap de fonte

Base física: LP de pool migrado é **queimado** (confirmado estruturalmente, ver "Investigação
InitBoost", pro período pós-2026-07-21; pendente pro período anterior) — sem swap novo, as
reservas não mudam, e o preço também não muda.

1. Sem candle de preço em `t+7` → checar assinaturas do **pool** via Helius entre o último candle
   conhecido e `t+7`.
2. **Zero swaps** no intervalo → preço(t+7) = **último close conhecido**, exato.
3. **Houve swap, mas falta candle** → `missing_source`, contado explícito e separado (invariante
   6, missingness explícita).
4. `missing_source` > 5% das observações token-semana do quintil de topo numa combinação →
   `INCONCLUSIVE_DATA` pra essa combinação (seção 9).
5. **-100% só quando o preço é de fato ~0**, confirmado por alguma fonte — nunca inferido da mera
   ausência de candle.
6. Captura causal própria deste repositório **não** serve de fonte cruzada aqui — não cobre o
   período do backfill (2025-03-20 em diante).

## 11. Risco de transferência

A evidência acadêmica mais forte citada pra H (Liu & Tsyvinski, RFS 2021; Liu/Tsyvinski/Wu, JF
2022) vem de BTC/XRP/ETH ou do top-1500 de criptomoedas por market cap, **2011-2018**,
rebalanceamento semanal — população, era de mercado e microestrutura diferentes de memecoins
Solana "estabelecidas" em 2025-2026. Mecanismo é o mesmo tipo de efeito; transferência não é
automática. Este discovery testa a transferência, não a prova.

## 12. Proibições explícitas desta V0

- não compara com nenhuma hipótese de minuto-inicial (CHURN/BUY-ACCEL/EARLY-BAL-CONC são outro
  mecanismo/população/horizonte — a razão exata pela qual H não é a mesma família);
- não troca lookback/piso de volume depois de ver a direção de nenhuma das 4 combinações;
- não estende a janela de captura com backfill no meio do protocolo;
- não promove mais de 1 combinação candidata;
- não lê o bloco de confirmação selado com código de discovery;
- na janela de regime de fee ambíguo, não usa a fee menor (regra fixa: usa a maior);
- não abre execução nem toca em capital.

---

## Apêndice — backfill (Pendência 3, read-only, nesta ordem) — estado desta sessão

### (a) Dune — achado, não executado

GeckoTerminal grátis só cobre ~26 semanas por chamada — não cobre as 36 mínimas. Dune tem
`dex_solana.trades` (curada, `block_month`-particionada, coluna `project`); literal exato pra
PumpSwap não confirmado. Query de 2 passos já escrita (descobrir o literal, depois puxar
volume/trade diário) — **você vai testar isso você mesmo**, por decisão sua desta rodada.

### (b) Custo CoinGecko Analyst — pesquisado, decisão sua

US$129/mês (ou US$103,20/mês anual), 500.000 créditos/mês, 1 crédito/requisição on-chain,
histórico desde set/2021 dependendo do pool.

**Estimativa de chamadas necessárias (pedida nesta rodada)**: total de migrações PumpSwap desde
2025-03-20 é incerto por uma ordem de grandeza — ancorando na taxa atual medida nesta sessão
(~1.500 assinaturas/dia na conta de migração, ~40% completam de verdade nesta amostra pequena →
~600 migrações novas/dia hoje) e assumindo que a média histórica dos 19 meses foi 1/3 a 1/2 da taxa
de hoje (ecossistema cresceu), **estimativa: ~100.000-400.000 migrações totais** — faixa larga,
não um número só.

"A maioria dos pools morre rápido" (premissa sua, consistente com MemeTrans e E12) permite uma
estratégia de 2 fases: (1) checagem de vida barata — **1 chamada por pool** (cobre semanas o
bastante pra aplicar o piso de volume da seção 1 e descartar os que não qualificam); (2) só os que
qualificam como "estabelecidos" recebem o pull completo da janela de 36 semanas — até **~2
chamadas por pool** (36 semanas ≈ 252 dias > 180 dias/chamada).

```
custo_estimado ≈ (todas as migrações × 1) + (sobreviventes × 2)
```

Com 150.000 migrações (meio da faixa) e uma taxa de sobrevivência generosa de 20% pra "vale a pena
olhar de novo" (30.000 pools): 150.000 + 60.000 = **~210.000 chamadas** — dentro dos 500.000
créditos/mês, com margem. **Se a estratégia fosse ingênua** (pull completo pra toda migração, sem
a checagem barata primeiro): 150.000 × 2 = 300.000 chamadas — ainda dentro de 500k, mas sem
margem pra mais nada no mês. Não assinar nada — decisão sua.

### (c) Amostragem da conta de migração — ampliada para 100, espalhada no tempo (pedido desta rodada)

Script: `benchmarks/move_first_h_coverage_audit_v0/sample_migration_account.py` (`--self-check`
OK). Caminhada histórica completa (2025-03 a hoje) iniciada nesta sessão, em segundo plano — **não
concluída a tempo de entrar nesta revisão**. Achado concreto e inesperado, útil por si só: a
contagem bruta de assinaturas **não é um proxy confiável de volume de migração** — a caminhada
(só contagem de assinaturas/timestamp, sem classificar conteúdo) encontrou picos extremos de
atividade concentrados em janelas de poucos minutos (ex.: ~90.000 assinaturas entre
2026-08-14T09:39 e 2026-08-14T11:13, ~1,5h reais; outro pico de ~90.000 em 2026-08-20, ~2h reais)
— consistente com tempestades de retry automatizado (a mesma assinatura "already migrated" vista
na amostra de n=5 da rev.3, repetida em massa), não com volume orgânico de migração real.
**Reforça, não enfraquece, a exigência de deduplicar por pool** antes de qualquer contagem — a
contagem bruta de tx superestima migrações únicas por uma margem desconhecida nesta sessão.
Reportado até aqui, classificado (não só contado): n=5 (amostra pequena, só período recente, já
na rev.3) — 5/5 `MigrateV2`, 3 "already migrated", 2 completando `CreatePool`+`InitBoost`.
**Amostra de 100, espalhada por trimestre incluindo mar-mai/2025 (e a verificação de LP-queimado
pré-BOOST que depende dela), fica pendente** — a caminhada de assinaturas brutas até lá levaria
mais tempo do que esta sessão permite dado o volume encontrado; próximo passo, não desta revisão.

### (d) Teste de sobrevivência com 50 migrações antigas — NÃO executado

Depende de (a) ou (c) trazerem enumeração real de migrações antigas. Não desta sessão.

## Pendências para o sign-off final (acumuladas)

1. Confirmar se a tabela de fee de 2026-05-20 é a mesma do lançamento do Project Ascend em
   2025-09 ou foi revisada — se incerto no momento do backfill, usar a fee maior (regra 12 já
   fixa isso, mas a pesquisa em si falta).
2. Resultado da amostra de 100 transações da conta de migração, espalhada por trimestre desde
   mar-mai/2025 — em andamento, não concluído.
3. Confirmar se LP era queimado também antes de 2026-07-21 (sem BOOST) — depende do item 2.
4. Decidir Dune (você vai testar) vs CoinGecko Analyst (pago, ~210k chamadas estimadas/mês numa
   estratégia de 2 fases) como fonte de preço/volume histórico.

Nenhum backtest, discovery, consulta a outcome ou backfill real foi executado nesta revisão — só
pesquisa, verificação ao vivo read-only (sem preço) e reorganização do documento.

# Opção H — Memecoins Estabelecidas, Momentum — Discovery V0 — Preregistration — PRE-REGISTRADA — 2026-10-08 (rev. 6)

Status: **PRE-REGISTRADA.** As 4 condições do sign-off condicional foram verificadas: (1) LP
queimado confirmado 10/10 em migrações espalhadas out/2025–jun/2026, pré-BOOST; (2) enumeração
resolvida pela via (a) — `getTransactionsForAddress` do Helius com filtro de `blockTime` é viável
(veja "Enumeração" abaixo) e está rodando desde 2025-03-20; (3) reservas confirmadas como campo
obrigatório de todo evento de swap, não aproximação; (4) fórmula de custo corrigida pra fee TOTAL
do swap, não só a fatia do LP. Protocolo congelado nesta revisão. **Autoriza**: o download único
da janela grátis do GeckoTerminal + a enumeração (em andamento) + o hash commitado descritos
abaixo. **Não autoriza** nenhum cálculo de retorno — isso só depois da sua revisão desta rev.6
congelada. Esta revisão é **autocontida** (protocolo inteiro num só texto).

ID no registro: `MOVE-FIRST-H-DISC-V0`. Fonte da opção: `docs/strategy-options-move-first-2026-10-07.md`
(Opção H) e `docs/research-hypothesis-registry-v1-2026-10-04.md`.

## Mudança de fonte de dado (decidida pelo operador, antes de qualquer dado)

**Dune descartado**: o trial da conta esgotou; a query só roda no plano pago. **Não pagar.**

**Novo desenho**, substitui o backfill profundo de 19 meses das revisões 2-4:

1. **Discovery** roda só na janela grátis do GeckoTerminal (OHLCV diário, ~6 meses rolantes a
   partir de hoje). Mínimo utilizável: **2 (lookback) + 15 (treino) + 6 (retentor) = 23 semanas**;
   abaixo disso, `INCONCLUSIVE_SAMPLE` antes de calcular qualquer retorno.
2. **Bloco de confirmação** = as **12 semanas imediatamente anteriores** ao início da janela de
   discovery, mais **1 semana de embargo** entre as duas. Isso é cronologicamente **antes** do
   discovery, não depois — inversão deliberada: como a API grátis só alcança ~6 meses pra trás a
   partir de agora, qualquer coisa mais antiga que isso **fica fisicamente fora do alcance** do
   código de discovery, mesmo por acidente. Só é baixado **se e quando** o discovery render um
   candidato, usando 1 mês de CoinGecko Analyst (US$129/mês) — decisão do operador *naquele
   momento*, não agora.
3. **Protocolo de integridade**: a janela grátis é rolante (o que é "últimos 6 meses" muda todo
   dia). No momento em que o discovery for autorizado: baixar a janela inteira **de uma vez**
   (não em pedaços ao longo de dias, o que deixaria a janela derivar durante a coleta), gravar o
   dado bruto, calcular um hash do conteúdo e **commitar o hash antes de calcular qualquer
   retorno**. Isso sela o dado de entrada contra qualquer "baixar de novo se o resultado não
   agradar".
4. **Enumeração — corrigido nesta revisão: viável desde 2025-03-20, não só ~7 meses.** A
   caminhada de assinaturas (`getSignaturesForAddress`, sequencial, sem filtro) não é viável —
   bateu 1.500.000 assinaturas sem sair dos últimos ~2 meses (achado da rev.5). Mas existe um
   método certo: `getTransactionsForAddress` (exclusivo Helius) aceita `filters.blockTime`,
   pulando direto pra qualquer data, sem caminhar a partir de agora. Testado ao vivo nesta
   revisão: ~1-5s por dia completo, com `transactionDetails=full`+`encoding=jsonParsed` (logs já
   vêm na mesma chamada, sem round-trip extra por assinatura). **Enumeração completa desde
   2025-03-20 lançada nesta sessão, em andamento** (ver "Enumeração via getTransactionsForAddress"
   abaixo) — cobre a janela inteira, não só os ~7 meses que a rev.5 propunha como atalho.

---

## 1. Universo ("estabelecida")

Um token entra no universo de uma data de rebalanceamento `t` se, **usando só dado anterior a `t`**:

1. já graduou da bonding curve para PumpSwap há **>= 7 dias de calendário** antes de `t` (margem
   larga sobre MemeTrans — ~73% dos tokens caem para <40% do preço de migração em 20min — e E12
   — >85% dos snipers saem em <5min);
2. teve volume 24h >= **US$5.000** (piso baixo) ou **US$20.000** (piso alto — comparação
   separada, seção 4) em pelo menos 5 dos 7 dias de calendário imediatamente antes de `t`;
3. tem preço resolvível em `t` **e** liquidez resolvível em `t+7` — se não tiver em `t+7`, não é
   excluído: vira retorno conforme a regra de morte-vs-gap (seção 10).

## 2. Sinal

Feature única: retorno acumulado nos **N dias anteriores a `t`** ("momentum"), mesma lógica de
Liu/Tsyvinski/Wu (JF 2022) — ordenação cruzada semanal, quintil de maior momentum vs quintil de
menor. **Long-only**: sem infraestrutura de short/borrow pra memecoin — divergência de escopo
registrada, não escondida.

## 3. Rótulo e horizonte

Retorno forward de **7 dias de calendário** a partir de `t`. Não colide com nenhum horizonte
congelado em segundos (`ROUTE_RESEARCH_HORIZONS_SECONDS` é outro sistema, outra unidade).

## 4. Comparações desta descoberta (pré-registradas, não escolhidas depois de ver o resultado)

| Lookback (N dias) | Piso de volume 24h |
|---|---|
| 7 | US$5.000 |
| 7 | US$20.000 |
| 14 | US$5.000 |
| 14 | US$20.000 |

Discovery (regra 4 do registro de hipóteses): gera no máximo 1 candidato; não promove nada a
`VALIDADA` diretamente.

## 5. Suporte mínimo, split temporal e bloco de confirmação selado (redesenhado)

- **Discovery**: >= 15 datas de rebalanceamento válidas de treino + >= 6 de retentor, dentro da
  janela grátis (~6 meses). Unidade é a **data de rebalanceamento** (semana), não token-semana.
- **Data pulada**: qualquer data com universo (seção 1) de **menos de 25 tokens** é pulada
  inteira — decidido agora, não depois de ver quantos tokens cada data teria.
- Suporte mínimo adicional em volume: **n >= 30 observações token-semana** no quintil de topo,
  somando treino + retentor.
- **Mínimo total pra autorizar o discovery**: **23 semanas** utilizáveis dentro da janela grátis
  (2 lookback + 15 treino + 6 retentor). Abaixo disso → `INCONCLUSIVE_SAMPLE`, antes de qualquer
  retorno.
- **Bloco de confirmação selado**: **12 semanas**, imediatamente **anteriores** ao início da
  janela de discovery (não posteriores — ver "Mudança de fonte de dado" acima), mais **1 semana
  de embargo** entre os dois blocos. Hash do bloco de discovery baixado commitado antes de
  qualquer cálculo (regra 3 acima); o bloco de confirmação só é baixado depois de um candidato
  existir, com seu próprio hash commitado antes de ler qualquer retorno dele.

## 6. Candidato exige lucro absoluto

Uma combinação (das 4 da seção 4) só é candidata se, **no treino**: retorno semanal líquido de
custo (sweep 1x, seção 8) do **quintil de topo** tiver **média E mediana > 0**. No **retentor**:
a **média líquida** do quintil de topo tem o **mesmo sinal** (positivo) da média do treino — não
precisa bater em magnitude. Spread topo-fundo e retorno do universo equal-weight são diagnóstico,
não critério de escolha.

## 7. Critério de escolha entre as 4 combinações

Entre as que passam a regra 6 no treino: escolhe a de **maior média líquida do quintil de topo**.
Empate: **lookback menor** (7 antes de 14). Zero combinações passando → `INCONCLUSIVE_NO_CANDIDATE`.

## 8. Custo por perna, escalado por liquidez (simplificado nesta revisão)

**Impacto de preço:**

```
reserva_de_um_lado_usd ≈ liquidez_total_do_pool_usd / 2
impacto_pct ≈ (tamanho_posicao_usd / reserva_de_um_lado_usd) × 100
```

**Reservas em `t` — confirmado nesta revisão: direto do evento de swap, campo oficial, sem
derivação.** Busquei o IDL oficial do PumpSwap
(`github.com/pump-fun/pump-public-docs/idl/pump_amm.json`) e confirmei: **todo** `BuyEvent` e
`SellEvent` carrega `pool_base_token_reserves` e `pool_quote_token_reserves` como campos `u64`
simples, **nunca opcionais** (não estão dentro de nenhum wrapper `Option`). Não é aproximação, não
é um campo às vezes presente — é parte obrigatória do evento, em todo swap, por desenho do
programa. Isso já é modelado no próprio código deste repositório
(`src/market_protocol_facts.py`, campos `pool_base_token_reserves`/`pool_quote_token_reserves`,
mesmos nomes). Método: ler o **último swap antes de `t`** do pool (1 transação por token-data,
não uma caminhada por todos os swaps — pool ativo pode ter milhares/dia) e usar as reservas
diretas desse evento. O `k`/`sqrt` das revisões anteriores fica só como *fallback* pra quando não
houver swap algum no histórico disponível (`missing_source`, seção 10).

**Fee de swap — achado mais importante desta revisão: não precisa de tabela nem de regime, o
evento já grava a fee realmente aplicada.** O mesmo IDL mostra que `BuyEvent`/`SellEvent` também
carregam `lp_fee`, `lp_fee_basis_points`, `protocol_fee`, `protocol_fee_basis_points`,
`coin_creator_fee` e `coin_creator_fee_basis_points` — a fee **de fato cobrada naquele swap
específico**, já somada e já na faixa certa, sem precisar reconstruir qual faixa de market cap
valia naquela data nem qual regime histórico estava ativo. **Isso substitui a tabela de faixas
como método primário**: ler a fee do último swap real antes de `t` (mesma transação que já dá a
reserva, acima) é mais simples E mais correto que calcular por tabela — elimina de uma vez a
necessidade de confirmar regimes históricos. A tabela literal de `pump.fun/docs/fees` (25 faixas,
0,300% a 1,250% total — ver `docs/strategy-options-move-first-2026-10-07.md`, Opção F) fica só
como *cross-check* de sanidade, não como fonte primária de cálculo.

Verificação adicional desta revisão, via histórico de commits do GitHub
(`pump-fun/pump-public-docs`, `docs/FEE_PROGRAM_README.md`): **exatamente 1 commit**, `f9bb0be`,
2025-08-29, "Publish fee program README" — **nenhuma alteração desde então**. Como a janela de
discovery+confirmação inteira (~7 meses, 2026) é muito posterior a 2025-08-29, **a tabela é a
mesma em toda a janela que importa** — não precisa mais da regra "regime ambíguo, usa a fee
maior" das revisões anteriores; essa regra fica só como salvaguarda teórica, não algo que se
espera acionar aqui. Ressalva honesta: histórico de commits do GitHub confirma quando o *arquivo*
mudou, não prova com 100% de certeza que o conteúdo publicado em `pump.fun/docs/fees` nunca
divergiu do arquivo do repositório — é a melhor evidência disponível, não uma certeza absoluta.

**Rede/priority — SOL, não USD fixo:**

```
custo_rede_por_perna_sol = 0,0003 SOL
custo_rede_por_perna_usd(t) = 0,0003 × preço_histórico_do_SOL_em_USD(t)
```

**ATA — custo zero, explícito**: aluguel devolvido ao fechar a conta na venda (confirmado na
prática por `closeAccount` em transações reais lidas nesta sessão) — a regra de saída desta
estratégia sempre vende a posição inteira, então a ATA sempre fecha. Custo líquido = 0.

**Fórmula final — correção desta revisão (item 4): fee TOTAL, não só a fatia do LP.** Quem paga o
swap paga `lp_fee + protocol_fee + coin_creator_fee` juntos (0,300%–1,250% conforme a faixa) — a
fatia do LP isolada (0,020%–0,200%) subestimaria o custo real do trade. Lido direto do evento de
swap (`lp_fee`, `protocol_fee`, `coin_creator_fee`, já somados no evento, seção acima), não da
tabela por faixa:

```
custo_ida_volta_pct ≈ 2 × impacto_pct
                     + fee_TOTAL_swap(último swap antes de t) + fee_TOTAL_swap(último swap antes de t+7)
                     + custo_rede_por_perna_usd(t)/tamanho_posicao_usd × 100 × 2
                     + 0   # ATA
```

onde `fee_TOTAL_swap = (lp_fee + protocol_fee + coin_creator_fee) / quote_amount` do evento de
swap real mais próximo — não um valor de tabela. Sweep 1x/2x mantido, mesma disciplina do Gate 2
do PQ-TR.

## 9. Classificação final

- `INCONCLUSIVE_SAMPLE`: menos de 23 semanas utilizáveis na janela de discovery (seção 5).
- `INCONCLUSIVE_DATA`: `missing_source` (seção 10) acima de 5% das observações token-semana do
  quintil de topo, numa combinação.
- `DISCOVERY_MOVE_FIRST_H_V0_CANDIDATE`: exatamente 1 combinação passa a regra 6 no treino E no
  retentor (escolhida pela regra 7 em caso de múltiplas) — vai para `MOVE-FIRST-H-CONF-V0` sobre
  o bloco selado (seção 5), que só então é baixado.
- `INCONCLUSIVE_NO_CANDIDATE`: nenhuma combinação passa a regra 6, ou nenhuma mantém o sinal no
  retentor.

## 10. Regra de morte vs gap de fonte (ampliada nesta revisão: qualquer tx, não só swap)

Base física: LP de pool migrado é **queimado** — confirmado estruturalmente (ver "Investigação
InitBoost" abaixo) pro período pós-2026-07-21; pendente, mas plausível, pro período anterior
(ainda não verificado com uma transação real de antes dessa data). Sem swap novo, as reservas não
mudam, e o preço também não muda.

1. Sem candle de preço em `t+7` → checar **toda transação** (não só as que parecem swap de
   antemão) envolvendo a **conta do pool** via Helius, no intervalo entre o último candle
   conhecido e `t+7`. **Correção desta revisão**: checar qualquer tx, não pré-filtrar só por
   "parece swap" — a investigação do InitBoost mostrou que uma tx de aparência administrativa
   (migração) pode mover reserva sem ser um swap tradicional; não dá pra assumir que só
   instruções rotuladas "swap" afetam reserva.
2. **Zero transações afetando reserva** no intervalo → preço(t+7) = **último close conhecido**,
   exato.
3. **Houve transação afetando reserva, mas falta candle** → `missing_source`, contado explícito
   e separado (invariante 6).
4. `missing_source` > 5% das observações token-semana do quintil de topo numa combinação →
   `INCONCLUSIVE_DATA` pra essa combinação.
5. **-100% só quando o preço é de fato ~0**, confirmado por alguma fonte — nunca inferido da mera
   ausência de candle.
6. Captura causal própria deste repositório **não** serve de fonte cruzada — não cobre o período.

## 11. Risco de transferência

Liu & Tsyvinski (RFS 2021) e Liu/Tsyvinski/Wu (JF 2022): BTC/XRP/ETH ou top-1500 por market cap,
**2011-2018**, rebalanceamento semanal — população, era de mercado e microestrutura diferentes de
memecoins Solana "estabelecidas" em 2026. Mecanismo é o mesmo tipo de efeito; transferência não é
automática. Este discovery testa a transferência, não a prova.

## 12. Proibições explícitas desta V0

- não compara com nenhuma hipótese de minuto-inicial;
- não troca lookback/piso de volume depois de ver a direção de nenhuma das 4 combinações;
- não baixa a janela de discovery em pedaços ao longo de dias (regra 3 do redesenho) nem a
  reabre depois de calcular um resultado que não agradou;
- não lê o bloco de confirmação selado antes de um candidato existir;
- não promove mais de 1 combinação candidata;
- não abre execução nem toca em capital;
- não assina nenhum plano pago sem autorização explícita do operador.

---

## Investigação InitBoost — resolvida nesta revisão (era bloqueador)

**Erro de aritmética da rev.5, corrigido (item 1 do operador).** Eu tinha escrito que a janela de
discovery+confirmação "já cai inteiramente depois de 2026-07-21" — **errado**, e eu não tinha
feito a conta de verdade. Com hoje = 2026-10-08: janela de discovery ≈ 2026-04-08..2026-10-08;
bloco de confirmação (12 semanas + 1 de embargo antes disso) ≈ 2026-01-07..2026-04-01. **A
confirmação inteira, e ~57% da janela de discovery (de 2026-04-08 a 2026-07-21), são
pré-BOOST.** LP queimado pré-BOOST voltou a ser bloqueante, exatamente como o operador apontou.

**Verificação pedida: 10 pools PumpSwap migrados entre out/2025 e jun/2026, espalhados — ler a
transação de migração de cada um e checar se o mint de LP é mintado, queimado (`burn`) e fechado
(`closeAccount`) na mesma transação (mesmo padrão já confirmado pro período pós-BOOST).**

**Resultado: 10/10.** Para cada uma das 10 datas (2025-10-01, 10-25, 11-20, 12-15, 2026-01-10,
02-05, 03-01, 04-01, 05-15, 06-20), a primeira migração completa do dia tem exatamente 1 conta
que recebe `mintTo`, depois `burn` da quantidade inteira, depois `closeAccount` — todas dentro da
mesma transação de migração, igual ao padrão pós-BOOST. **A base física da regra de
morte-vs-gap (seção 10: LP queimado ⇒ reservas paradas sem swap) vale pro período inteiro da
janela de discovery+confirmação, não só pós-2026-07-21.** Nenhuma das 10 falhou — a condição de
parada do operador ("se algum não for queimado, PARAR e me trazer") não foi acionada.

BOOST em si (quando existe, migrações pós-2026-07-21) extrai SOL da reserva do pool e queima o LP
**dentro da mesma transação atômica de migração** — verificado ao vivo numa transação real.
Qualquer leitura de reservas feita depois dessa transação já reflete o estado final, pós-boost.

**Correção sobre o texto oficial do BOOST**: a rev.5 disse "não existe doc oficial no GitHub,
busquei por 'boost', zero arquivos" — **isso estava errado**, eu só tinha buscado a documentação
em markdown, não o IDL. O IDL oficial (`pump-fun/pump-public-docs/idl/pump_amm.json`) **tem**
definições formais de BOOST: instrução `toggle_boost`, eventos `InitBoostEvent`,
`SetBoostAuthorityEvent`, `BoostBuyAndBurnEvent`, conta `boost_authority`/`boost_enabled` em
`GlobalConfig`, códigos de erro 6063-6067 prefixados "BOOST:". O que **não** consegui acessar foi
o texto do anúncio original (`x.com/Pumpfun/status/...` retornou HTTP 402) — mas a especificação
técnica é oficial e encontrada, não só a verificação estrutural que eu já tinha feito.

## E11 / Opção G — já verificado, sem trabalho novo nesta revisão

Leitura completa do paper (arXiv 2601.08641v3) já feita numa revisão anterior deste programa:
confirmado que o retorno de 3% do copiador é derivado assumindo "immediate copier" (atraso ~zero,
Lema 1), não medido sob latência real — ver `docs/strategy-options-move-first-2026-10-07.md`,
seção da Opção G, pra detalhe completo. Mantido como está; nada a refazer aqui.

---

## Apêndice — estado da pesquisa de backfill desta sessão

### Dune — descartado

Trial encerrado; query só no plano pago. Não pagar. Query dos 2 passos permanece documentada em
revisões anteriores deste arquivo (histórico git), caso o operador reconsidere mais tarde.

### CoinGecko Analyst — só pro bloco de confirmação, só se houver candidato

US$129/mês (ou US$103,20/mês anual), 500.000 créditos/mês. Sob o redesenho desta revisão, o uso
cai drasticamente: só as 12 semanas do bloco de confirmação, só pros tokens que já qualificaram
como candidato — não mais um backfill de centenas de milhares de pools. Estimativa de chamadas:
irrelevante frente ao limite de 500k/mês nesse uso restrito. Decisão de assinar: do operador, e
só no momento em que (se) houver candidato.

### Enumeração via `getTransactionsForAddress` — resolvida nesta revisão (era item 2)

A caminhada sequencial de assinaturas (`getSignaturesForAddress`) não é viável — confirmado na
rev.5 (1.500.000 assinaturas, sem sair de ~2 meses). **Testado nesta revisão**: `filters.status:
"succeeded"` **não resolve** a deduplicação — confirmado ao vivo, as chamadas "already migrated"
têm `err: null` (são tecnicamente bem-sucedidas, só não fazem nada) — classificação ainda precisa
olhar o conteúdo do log, não só o status. **O que resolve**: `filters.blockTime` do
`getTransactionsForAddress` pula direto pra qualquer data, sem caminhar a partir de agora —
testado em 3 dias espalhados (2025-04-15, 2025-10-15, 2026-04-15): **0,8 a 4,8 segundos por dia
completo**, com `transactionDetails=full` já trazendo os logs na mesma chamada.

**Achados ao longo do caminho**: (1) a instrução histórica se chama **"Migrate"** (não
"MigrateV2") em abr/2025 — confirma a suspeita do operador de que existia uma versão anterior,
só que o nome não é literalmente "V1"; a conta também processa **"SetCreator"** (cadastro de
criador pra fee-sharing, consistente com a linha do tempo já registrada) e, numa fração dos dias
mais antigos, tem **ruído de um programa totalmente não relacionado** (`PEPPER3dYQpY2TTqHp3XinzRu519X7GswmVNb5tqK8L`,
confirmado numa transação que falhou) — por isso o filtro certo exige checar se o programa
bonding-curve (`6EF8rrecth...`) ou PumpSwap (`pAMMBay...`) aparece na lista de contas da
transação, não só "qualquer tx que toque esta conta".

**Enumeração completa desde 2025-03-20, lançada nesta sessão, em andamento** — resolve o item 2
pela via (a), como pedido. Script: `benchmarks/move_first_h_coverage_audit_v0/sample_migration_account.py`,
função `enumerate_date_range` / flag `--enumerate-from`, grava uma linha JSON por dia (sobrevive
interrupção). Resultado parcial até o momento deste commit, dia a dia: migrações completas por
dia variam de ~10 (jul/2025, baixa de atividade coincidente com a "rápida queda de graduações" já
documentada no memo de opções) a ~540 (picos), dezenas a centenas de pools distintos por dia na
maior parte do período. Será concluída e usada pra montar o universo real da janela de
discovery+confirmação, não só os ~7 meses que a rev.5 propunha como atalho.

## Pendências — só execução, não mais desenho

O protocolo está congelado (PRE-REGISTRADA). O que falta é só executar o que esta revisão já
autorizou: (1) terminar a enumeração em andamento até cobrir 2026-10-08; (2) baixar a janela
grátis do GeckoTerminal de uma vez; (3) montar o universo (seção 1) com as duas fontes; (4)
calcular hash do dado bruto e commitá-lo; (5) reportar só contagem de cobertura (semanas
utilizáveis, tokens por data, % `missing_source`) — **nenhum retorno calculado** até você revisar
esta rev.6 congelada.

Nenhum backtest, discovery, consulta a outcome ou pagamento foi executado nesta revisão — a
enumeração em si (contagem/estrutura de transação, sem preço) já está em andamento, autorizada
pelo sign-off condicional.

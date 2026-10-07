# Opções de estratégia — "move first" — 2026-10-07 (revisão 2)

## Status

RESEARCH / PAPER / READ ONLY. Documento de pesquisa. Nenhum pré-registro aberto por este memo, nenhuma coleta de produção rodada, nenhum threshold congelado alterado, nenhum resultado fechado reaberto. O diagnóstico read-only de `benchmarks/move_first_long_horizon_baseline_v0/baseline.py` (ver seção "Diagnóstico de viés de sobrevivência") também não abre pré-registro nem gasta tentativa (regra 5 do registro).

## Histórico desta revisão

Revisão 1 (commit `927d844`) recomendava só a Opção B. O operador rejeitou B com 4 críticas específicas (régua desigual: B também tem evidência própria zero e a mesma evidência externa contrária de A; pergunta 1 sem resposta — B diz quem sai, não quem paga a gente; viés de sobrevivência no desenho do coletor de 3600s; o marcador proposto é a mesma família de breadth/concentração/churn já fechada). As 4 críticas procedem e estão incorporadas abaixo. Esta revisão também adiciona 3 opções novas (F, G, H) pedidas pelo operador, aplica a mesma régua a todas, adiciona custo (dias de engenharia + dias até veredito) e o primeiro teste pré-registrável de cada uma, e adiciona a seção "Composição" para os caminhos escolhidos.

## Diagnóstico que motiva o memo (recap)

Registro de hipóteses: ~15 veredictos econômicos, 0 `VALIDADA`. No memecoin Solana, quem ganha nos primeiros minutos ganha por **posição** (deployer/insider/MEV/KOL), não por padrão replicável depois do fato. Read-only, segundos atrasado, ~US$25, sem MEV: copiar o gatilho de entrada desse grupo é apostar do lado de quem fornece liquidez de saída pra eles. E11 (copier ~3% vs smart money ~14% sob fricções realistas) e E12 (>55% dos snipers saem em <1min, >85% em <5min) dão a forma exata do problema. Prioridade: achar a fonte de lucro antes de empilhar mais filtro.

## Regra de qualificação para a recomendação (inalterada)

Só entra na recomendação a opção que responder, com evidência e com a **mesma régua para todas**, às 5 perguntas:

1. De quem vem o dinheiro — contraparte que perde e por quê.
2. Por que conseguimos capturar sendo read-only, segundos atrasados, ordens de ~US$25, sem MEV.
3. Qual evidência (nossa ou externa séria) mostra que essa sobra existe.
4. Qual o teste mais barato e decisivo.
5. Qual o critério de morte, escrito antes.

Opção que não responde fica **DESCARTADA**, com o motivo. Opção que responde mas não é escolhida por causa do limite de caminhos fica **QUALIFICADA, NÃO ESCOLHIDA NESTA RODADA** (não é descarte — é fila). No máximo **2 caminhos** são recomendados. Cada recomendado terá exatamente **1 discovery + 1 confirmação**. Regra de parada: **se nenhum dos caminhos recomendados der resultado positivo líquido de custos (Gate 2), o programa de memecoin é encerrado.** Esta regra está escrita também em `docs/research-hypothesis-registry-v1-2026-10-04.md`.

---

## Opção A — Post-Transition Pullback-Reacceleration V1

1. **Fonte**: vendedores de pânico no fundo do recuo; compradores de momentum na reaceleração.
2. **Desvantagem de velocidade**: geometria em segundos-minutos, não em bloco 0 — em tese tolera atraso.
3. **Evidência**: **nenhuma própria** (V0 queimou com `conditional_economic_n=0`); a evidência externa mais próxima do domínio ("Midsummer Meme's Dream": 82,89% dos tokens >100% de retorno mostram mecanismo de crescimento artificial) **corta contra** a leitura de reversão orgânica.
4. **Teste mais barato**: retomar o protocolo V0 corrigindo a semântica de price-impact — não resolve o problema da evidência.
5. **Critério de morte**: moot.

**Veredito: DESCARTADA** (mantido da revisão 1). Custo se fosse tentada: engenharia ~2-3 dias (corrigir semântica + resolver gap de cobertura causal Pump→PumpSwap), calendário até veredito ~5-7 dias de coleta nova — não estimado com confiança porque a pergunta 3 falha antes de chegar lá.

---

## Opção B — Descoberta "movement first" em horizontes longos (1h/4h/24h)

**Veredito da revisão 1: SOBREVIVE. Veredito desta revisão: DESCARTADA**, pelas 4 razões do operador, aplicadas com a mesma régua usada em A:

1. **Pergunta 3 falha, mesma régua de A.** B também tem **zero evidência própria** — nunca foi coletada. A E12 (>55% dos snipers saem em <1min) mostra só que o grupo sniper **sai**; não mostra que existe *drift positivo* depois — isso era uma inferência minha, não um dado medido. E a evidência do Midsummer Meme's Dream (82,89% dos tokens de alto retorno com mecanismo de crescimento artificial) pesa **igualmente contra B**: se o que sobrevive até +1h/+4h/+24h é, em boa parte, continuação de pump artificial, "sobrevivente" não é sinônimo de "oportunidade orgânica" — é o mesmo problema que matou A.
2. **Pergunta 1 nunca foi respondida.** B descreve quem sai (snipers via E12) mas não descreve quem paga a gente no outro lado da negociação em +1h/+4h/+24h. "Quem sai primeiro" não é uma contraparte para o nosso lucro — é só a ausência de um competidor.
3. **Viés de sobrevivência confirmado no próprio desenho do coletor.** Lido `src/route_research_evaluation.py::_metrics`: UNAVAILABLE/PROVIDER_ERROR são **excluídos** da amostra de retorno ("dado ausente"). Em horizonte longo isso descarta exatamente os episódios onde o token ficou tão ilíquido que nem cotação de saída existia — economicamente uma perda total pra um BUY route-only, não uma observação ausente. Qualquer leitura "B parece promissora" feita sobre esse evaluator estaria inflada por este viés.
4. **O marcador proposto (fluxo ainda ativo / sem dominância de carteira) é a mesma família de breadth/concentração/churn já fechada** — `CD-V0`/`CD-PROMO-V0` (concentração, INCONCLUSIVE fechada), `CHURN-V0`/`CHURN-PROSP-V1` (churn, PASS retrospectivo mas INCONCLUSIVE prospectivo), `BUY-ACCEL` (FAIL como alpha), `EARLY-BAL-CONC-V0` (FAIL de direção). Nenhuma variante dessa família produziu edge até hoje.

**Diagnóstico de viés de sobrevivência (task separada, entregue com este memo).** Antes de descartar B eu quis medir o tamanho do viés do item 3, não só apontá-lo. Escrevi `benchmarks/move_first_long_horizon_baseline_v0/baseline.py` — script read-only, diagnóstico (não validação, não gasta tentativa), que recalcula a população "viva em +5min" (cotação de saída AVAILABLE em 300s) e compara, em 3600s, a visão do evaluator atual (rota faltante excluída) contra a visão com rota faltante = -100%, sem fatiar por marcador. `--self-check` passa (`python3 -m benchmarks.move_first_long_horizon_baseline_v0.baseline --self-check`). **Não consegui rodar contra dado real**: toda linha de 3600s no `data/copytrader.db` local desta sessão está `PENDING` em todas as `acquisition_run_key` existentes (`--all` confirma: 297 episódios vivos em +5min, 0 resolvidos em 3600s) — esperado, porque esse `.db` é local/gitignored desta sandbox e o coletor ativo (`route_research_forward_collection_900_v0.py`) só drena (300,900), nunca 3600. O script está pronto pra você rodar no seu `data/copytrader.db`, se e quando houver linhas de 3600s resolvidas lá.

Custo se B fosse revivida: engenharia ~4-6 dias (habilitar polling de 3600s, que já é suportado pelo contrato `ROUTE_RESEARCH_HORIZONS_SECONDS`, mais corrigir o viés do item 3 no evaluator ou tratá-lo no script separado), calendário ~7-14 dias de coleta nova para ter amostra viva em +5min com 3600s resolvido. Não recomendado iniciar sem resolver a pergunta 1 primeiro, o que B por definição não responde.

---

## Opção C — Stack de filtros como camada sobre A/B

**Veredito: DESCARTADA** (mantido). C não tem fonte própria — filtra a cauda de outra coisa, falha a pergunta 1 por construção. Custo/teste: moot, contingente a uma entrada existir primeiro.

---

## Opção D — Robinhood Chain / Pons

**Veredito: DESCARTADA** (mantido). Zero evidência própria (branches só têm plumbing/adapter) e zero evidência externa séria encontrada para essa chain especificamente. Custo se fosse tentada: construir coletor econômico causal do zero, ~10-15 dias de engenharia antes de qualquer dado — alto e sem justificativa de evidência prévia.

---

## Opção E — Parar o programa, só acumular dados baratos

Não é hipótese de lucro, não compete pelas 5 perguntas. É a consequência automática da regra de parada se nenhum caminho escolhido fechar líquido de custos. Custo: zero (é a ausência de nova tentativa).

---

## Opção F — Prover liquidez (LP) em pools PumpSwap filtrados por rug

1. **De quem vem o dinheiro.** Toda troca num pool PumpSwap paga uma taxa de 0,25%; **0,20% vai para os LPs do pool** e 0,05% para o protocolo (confirmado em múltiplas fontes independentes: BlockEden abr/2026, MadeOnSol, Benzinga — ver fontes no fim do memo). Quem paga é todo trader que troca no pool — não é preciso vencer ninguém em velocidade ou informação; é remuneração mecânica de AMM por fornecer a contraparte da troca.
2. **Por que read-only/segundos atrasado/sem MEV ainda captura.** Depositar como LP não compete em velocidade: a posição é aberta uma vez e rende taxa proporcional ao volume enquanto for mantida. A única decisão de timing é *em qual pool entrar* (aplicando os vetos abaixo) e *quando sair* — nenhuma corrida de bloco 0.
3. **Evidência.** Mecanismo de taxa: sólido e verificado externamente (fonte oficial do protocolo não encontrada, mas 3 fontes independentes concordam em 0,20%/0,05%; a fee de criador por cima disso mudou em 2026 e está mal documentada — tratar como desconhecida até confirmar). Confirmado também: **terceiros podem depositar em qualquer pool PumpSwap, incluindo os migrados da curva** — LP de migração queimado trava só a liquidez que entrou na migração, não impede novo depósito próprio (MadeOnSol marca acesso de LP como "aberto a qualquer um"). Risco concreto e quantificado: o próprio Pump.fun relatou que **cerca de 20% da liquidez de cada token migrado fica "encalhada"** nos pools (consistente com IL catastrófico quando o token desaba) — esse é exatamente o cenário que os filtros de rejeição (PQ-TR/Bundle) deveriam reduzir. **Não temos dado próprio**: nunca simulamos LP (taxa − IL − custo) para um subconjunto filtrado por PQ-TR/Bundle. Isso é precisamente o que o discovery abaixo mede.
4. **Teste mais barato e decisivo.** Simulação read-only a partir de reservas e volume do pool (sem execução, sem ordem nova): para uma amostra de pools graduados que passam os vetos, reconstruir valor de LP via fórmula de produto constante e comparar com taxa acumulada (0,20% × volume × participação do LP) menos impermanent loss. Barreira real: `token_pool_cache` hoje guarda só um snapshot atual por `token_mint` (PRIMARY KEY), não uma série temporal — é preciso uma janela nova de observação passiva (ler estado público do pool, sem executar nada) por alguns dias antes de poder simular.
5. **Critério de morte.** Se a mediana/média do retorno simulado de LP (taxa − IL), líquido do sweep de custo (1x/2x, mesma disciplina do Gate 2), não for positiva no grupo filtrado, ou a amostra não atingir o mínimo (n≥10, mesma régua da CD-V0) — fecha, sem reabrir com outro horizonte de retenção ou outro filtro.

**Veredito: QUALIFICADA.** Custo estimado: engenharia ~5-7 dias (simulador de valor de LP + reaproveitar PQ-TR/Bundle, que precisa de merge do branch `bundle-bot-detection-v0-plumbing`), calendário até veredito ~7-14 dias (precisa de uma janela real de observação passiva para a série temporal de reservas/volume existir).

---

## Opção G — Copy-trading com filtro anti-bot, universo amplo (desenho E11)

1. **De quem vem o dinheiro.** O próprio paper (E11, arXiv 2601.08641, WWW'26, peer-reviewed, domínio Pump.fun) já mede isso: carteiras "smart money" têm retorno médio de 14%; a contraparte é quem compra depois delas e vende pra elas (ou vende antes que elas, dependendo do lado) — a vantagem é posicional/informacional da carteira copiada, exatamente nomeada no diagnóstico do programa.
2. **Por que read-only/segundos atrasado/sem MEV ainda captura.** Este é o ponto central de G: o paper não mede só a smart money — ele mede especificamente o retorno de quem **copia** essas carteiras (read-only, com atraso, sob fricções realistas) e reporta **~3% de retorno positivo**, não zero, não negativo. Esse já é um resultado publicado de que copiar (não ser o insider) pode funcionar sob fricção real — diferente de V48/V55/V68/PQ-V1, que buscavam alpha de features de fluxo genéricas, não a receita exata de smart-money + filtro anti-bot do paper.
3. **Evidência.** A melhor desta lista: peer-reviewed, mesmo domínio (Pump.fun), já classificada Grade A/B no nosso próprio `docs/research-evidence-registry-v1-2026-09-02.md` (via branch com E10-E12). Ressalva que o próprio registro já aponta: o modelo de fricção do paper não é detalhado no que foi lido, e o split de avaliação (temporal ou não) não foi confirmado — preciso ler o paper completo antes do pré-registro, não só o abstract. Ressalva adicional já registrada (RED-COHORT-2026-v1): compra no mesmo bloco pode refletir popularidade, não coordenação — um placebo pareado por atividade já é exigido antes de confiar em bundle/sniper/bump.
4. **Teste mais barato e decisivo.** Universo de smart money **selecionado por critério de dados sobre histórico já capturado** (ex.: profit factor/retorno mediano em holdout temporal — mesma disciplina do pipeline PQ), não lista fixa — WFWD-V2 (Run 2: 0 BUYs) e v60 (parado) já mostraram que lista fixa de poucas carteiras falha por amostra. Filtro bundle/sniper/bump exige os campos `slot`/`creator`/`creation_slot` já implementados (não mergeados) no branch `bundle-bot-detection-v0-plumbing`.
5. **Critério de morte.** Se o cohort smart-money filtrado, depois de bundle/sniper/bump, não superar (a) um placebo pareado por atividade e (b) a mesma barra de PF/suporte que já matou PQ-V1 (PF do grupo favorável > desfavorável, n≥30) sob o mesmo sweep de custo do Gate 2 — fecha, sem reabrir trocando a lista de carteiras.

**Veredito: QUALIFICADA.** Custo estimado: engenharia ~8-13 dias (seleção de universo por critério de dados + merge e extensão do Bundle plumbing para as 3 definições de bot do E11 + desenho de placebo pareado) — a mais cara das três. Calendário até veredito: se o discovery reusar histórico de transações já capturado (`transactions`, mesmo caminho do WFWD-v2), pode ser retrospectivo em ~3-5 dias; a confirmação prospectiva precisa de uma janela nova de ~5-10 dias.

---

## Opção H — Memecoins estabelecidas, momentum/atenção em horizonte de dias/semanas

1. **De quem vem o dinheiro.** Mesmo mecanismo da literatura de momentum cripto: quem vende cedo demais ou compra tarde demais numa tendência que persiste por dias/semanas.
2. **Por que read-only/segundos atrasado/sem MEV ainda captura.** Rebalanceamento em dias/semanas — atraso de segundos é irrelevante por construção, igual ao argumento (agora descartado) de B, mas aqui a evidência é melhor.
3. **Evidência — confirmada e lida, não só citada de memória.** Busquei e confirmei as duas referências que você pediu: **Liu & Tsyvinski, "Risks and Returns of Cryptocurrency", Review of Financial Studies 34(6):2689-2727, 2021 (DOI 10.1093/rfs/hhaa113)** — amostra BTC/XRP/ETH, 2011-2018, acha momentum de série temporal forte e atenção do investidor prevendo retorno futuro. **Liu, Tsyvinski & Wu, "Common Risk Factors in Cryptocurrency", Journal of Finance, 2022, pp. 1133-1177 (DOI 10.1111/jofi.13119)** — moedas com market cap >US$1M, cresceu de 109 (2014) a 1.583 (2018) moedas, rebalanceamento **semanal**, modelo de 3 fatores (mercado, tamanho, momentum) explica o cross-section. Ambos peer-reviewed em revistas de primeira linha (RFS/JF) — evidência mais forte, academicamente, que qualquer preprint usado neste memo. **O que não transfere automaticamente**: a amostra são moedas estabelecidas 2011-2018 (BTC/XRP/ETH ou top-1500 por market cap), horizonte semanal, não memecoins Solana lançadas em 2026 com horizonte de dias — a mesma ressalva de transferência que o nosso próprio registro já aplica a E2-E6. Risco do Midsummer Meme's Dream pesa menos aqui que em A/B porque H exige piso de liquidez e sobrevivência prolongada (não é "sobreviveu 5 minutos", é "sobreviveu o suficiente pra ter liquidez real") — mas não é zero.
4. **Teste mais barato e decisivo.** Backtest histórico puro, sem coleta nova: `src/prices.py` já tem cliente GeckoTerminal usado pelo `exit_engine.py`. Universo com piso de liquidez (ex.: volume 24h sustentado por N dias) **incluindo moedas que morreram** (sem viés de sobrevivência — exigência que você já colocou) via histórico, não lista atual de sobreviventes.
5. **Critério de morte.** Se o momentum/atenção não separar retorno futuro líquido de slippage escalado por liquidez no backtest, ou a confirmação paper forward (dias/semanas reais) não replicar — fecha, sem trocar horizonte/universo depois de ver o dado.

**Veredito: QUALIFICADA.** Custo estimado: engenharia ~5-7 dias (universo com piso de liquidez + não-sobrevivente, reaproveitando o cliente GeckoTerminal já existente), calendário até veredito: discovery retrospectivo ~2-3 dias (é backtest puro); confirmação prospectiva real precisa de ~14-28 dias porque o horizonte é de dias/semanas — não dá pra apressar isso sem violar a própria lógica do horizonte.

---

## Recomendação final (decisão é minha, do operador)

F, G e H **todas respondem às 5 perguntas** com evidência — nenhuma das três é descartada pela régua. O limite de 2 caminhos obriga escolher.

**Escolho G e F:**

- **G** porque é a evidência mais direta e no mesmo domínio que existe neste memo inteiro (peer-reviewed, Pump.fun, com um número de copiador já medido e positivo) — se G falhar mesmo seguindo a receita exata do paper, isso é quase definitivo contra copy-trading pra nós.
- **F** porque é a única fonte de dinheiro **não adversarial** da lista — não compete em informação nem velocidade com ninguém, é remuneração mecânica de AMM — e reaproveita o engenho já construído (PQ-TR, Bundle) numa função nova (escolher onde prover liquidez) em vez de só rejeitar entrada.

**H fica QUALIFICADA, NÃO ESCOLHIDA NESTA RODADA** — não por falha de evidência (é, academicamente, a mais bem credenciada das três), mas porque mecanicamente ela ainda é uma variante de momentum/atenção, a mesma família que já fechou sem edge várias vezes no registro (CHURN, BUY-ACCEL, EARLY-BAL-CONC), mesmo que população e horizonte sejam diferentes o bastante para não ser o mesmo teste. Fica na fila: se G e F fecharem o programa pela regra de parada, H é a próxima candidata natural a reabrir uma rodada nova (fora da regra de parada desta rodada, que é só sobre G e F).

### Composição — Opção G (copy-trading com filtro anti-bot)

Escrita inteira agora, como **uma hipótese única**, testada uma vez — não é busca de combinação sobre dado.

1. **Universo**: tokens Pump.fun/PumpSwap em que pelo menos 1 carteira do cohort smart-money (selecionado por critério de dados em holdout, não lista fixa) compra.
2. **Gatilho de entrada (fonte de lucro)**: BUY no instante em que detectarmos on-chain a compra de uma carteira do cohort, tamanho fixo (item 5). A fonte é a vantagem posicional/informacional da carteira copiada (E11).
3. **Vetos reaproveitáveis, computáveis neste universo**:
   - **PQ-TR** (corte −86,05, LOW vs ALL): computável se a memória de qualidade de participantes (`participant_quality_native_memory_v1`) cobrir os mesmos tokens — confirmar cobertura antes, não depende de slot/creator.
   - **Bundle/sniper/bump (E11, Algoritmos 1-3)**: precisa de `slot` (trade) e `creator`/`creation_slot` (lifecycle) — já implementado, não mergeado, no branch `bundle-bot-detection-v0-plumbing`.
   - **Freeze authority (E10)**: **já capturado hoje**, de graça — `freeze_authority_present` existe em `src/opportunity_onchain_hazard.py` (o mesmo probe de hazard que já alimenta a admissão do V68), sem custo adicional de engenharia.
   - **Concentração** (`mf_top_wallet_gross_share_delta...`): computável, já está no feature matrix, mas é `diagnostic_only` (CD-V0/CD-PROMO-V0 fecharam sem edge) — entra como veto (rejeita se concentração piorando), nunca como parte do gatilho de entrada.
4. **Regra de saída (mais simples defensável, não "saída melhor")**: reaproveitar `src/exit_engine.py::EXIT_POLICIES` — combinar uma política `fixed_time` (prazo máximo igual ao horizonte de confirmação) com `trailing_stop_10_v1` (trail 10%, já definido, `max_duration_seconds` já parametrizado). Nenhum código novo de política — é composição do que já existe. "Saída melhor" (ex.: `wallet_exit_sizing.py`-informed, trailing dinâmico) é hipótese futura separada, com pré-registro próprio.
5. **Tamanho de posição fixo**: ~US$25 por entrada, igual ao resto do programa.

### Composição — Opção F (LP filtrado em pools graduados)

1. **Universo**: pools PumpSwap recém-graduados que passam os vetos abaixo.
2. **Gatilho de entrada (fonte de lucro)**: depositar como LP (não comprar o token) no instante em que o pool gradua **e** passa os vetos, tamanho fixo (item 5). A fonte é a taxa de 0,20% por swap pago pelo volume de troca no pool.
3. **Vetos reaproveitáveis, computáveis neste universo**: os mesmos 4 do item G acima (PQ-TR, Bundle/sniper/bump, freeze authority — já capturado — e concentração), na mesma condição de disponibilidade.
4. **Regra de saída (mais simples defensável)**: aqui "saída" é retirar a posição de LP, não vender o token. Composição: `fixed_time` (prazo máximo de permanência) + `trailing_stop` sobre o **valor simulado da posição de LP** (reservas × preço), não sobre o preço do token isolado — é a mesma mecânica de `trailing_stop_10_v1` de `exit_engine.py`, com a métrica observada trocada; não é política nova, é a política existente lendo outra série. "Saída melhor" (ex.: retirar antes se IL cruzar um limiar separado do preço) é hipótese futura separada.
5. **Tamanho de posição fixo**: ~US$25 nominal por posição de LP, pra manter comparabilidade de custo com o resto do programa.

**Regra de combinação**: cada composição acima (G e F) é escrita inteira, é UMA hipótese no registro, testada uma vez. Nenhuma busca de combinação sobre dado — se a composição fechar como está escrita aqui, fecha; não se troca veto, horizonte de saída ou tamanho depois de ver o resultado.

---

## Regra de parada (repetida, já também em `docs/research-hypothesis-registry-v1-2026-10-04.md`)

G e F recebem exatamente 1 discovery + 1 confirmação cada. **Se nenhuma das duas fechar líquida de custos (Gate 2), o programa de memecoin é encerrado.**

Nenhum pré-registro foi aberto por este memo. Nenhuma coleta de produção foi rodada. Nenhum threshold congelado foi alterado. Nenhum resultado fechado foi reaberto.

## Fontes externas usadas nesta revisão

- [What Is PumpSwap? How Pump.fun's DEX Works After Bonding (2026)](https://madeonsol.com/blog/what-is-pumpswap)
- [pumpswap 16b volume pumpfun amm raydium solana dex (BlockEden, abr/2026)](https://blockeden.xyz/blog/2026/04/12/pumpswap-16b-volume-pumpfun-amm-raydium-solana-dex/)
- [Pump.fun Launches PumpSwap DEX to Rival Solana's AMMs (Benzinga)](https://benzinga.com/content/44428583/pump-fun-launches-pumpswap-dex-to-rival-solanas-amms)
- [Pump.Fun's DEX PumpSwap introduces revenue-sharing for token creators (The Block)](https://www.theblock.co/news/defi/2025-05-13-pumpswap-revenue-tokens-354038)
- Liu, Yukun; Tsyvinski, Aleh. "Risks and Returns of Cryptocurrency." *Review of Financial Studies* 34(6):2689-2727, 2021. DOI 10.1093/rfs/hhaa113.
- Liu, Yukun; Tsyvinski, Aleh; Wu, Xi. "Common Risk Factors in Cryptocurrency." *Journal of Finance*, 2022, pp. 1133-1177. DOI 10.1111/jofi.13119.

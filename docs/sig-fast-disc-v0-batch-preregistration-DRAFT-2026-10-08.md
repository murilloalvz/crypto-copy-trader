# Pré-registro em lote — SIG-FAST-DISC-V0 — 2026-10-08 (RASCUNHO, rev. 4 2026-10-08)

Status: **RASCUNHO, aguardando sign-off do operador.** Nenhuma coleta foi rodada
para julgar este lote. Segue o formato de
`docs/templates/batch-preregistration-template-v1.md`, adaptado à régua nova do
SIG-FAST (caminho de preço, não retorno de horizonte fixo — ver
`docs/strategy-options-move-first-2026-10-07.md`, "Revisão 4"/"Opção SIG-FAST").

**Rev. 2 (2026-10-09): revisão do operador aplicada integralmente.** Mudanças
principais desta revisão, detalhadas abaixo: (1) discovery deixa de ser
retrospectivo — exige coleta nova com o motor corrigido (ver
`docs/sig-fast-live-engine-wiring-v0-2026-10-09.md`); (2) Δ primário passa a
ser fixo em 30s (os outros valores da grade ficam só diagnóstico); (3)
multiplicidade recontada: 2 famílias × 6 saídas no treino = 12 comparações de
decisão; (4) as 6 perguntas abertas da rev. 1 estão respondidas e aplicadas.
Nada da rev. 1 foi apagado silenciosamente — este documento substitui a rev. 1
por completo, autocontido.

**Rev. 3 (2026-10-09): segunda revisão do operador aplicada, itens (a)/(a2)/
(b)/(c)/(d).** Relevante a este documento: (d) o veto "histórico do criador"
é **removido** de H1/H2 (não existia definição nem histórico implementado) —
H1/H2 passam de 4 para 3 vetos; a contagem de 14 leituras decisórias não
muda, vetos não participam dela (ver "Multiplicidade"). (b) o stall guard de
`run_live_shadow_v0` (pendência da rev. 2) está implementado, e o Passo 0
ganha uma terceira métrica de sistema (continuidade pós-graduação,
`audit_graduation_continuity`). (a)/(a2) e (c) não alteram este documento
diretamente — ver `docs/sig-fast-live-engine-wiring-v0-2026-10-09.md` e o
runbook do Passo 0.

**Rev. 4 (2026-10-08): aceleração — H2 pivota de coleta ao vivo pra discovery
histórico on-chain selado, antes de qualquer coleta ao vivo longa.** Decisão
do operador: H1 (SIG-FAST-COPY-G) **não muda** — continua dependente de
cohort formado ao vivo (seção 2, H1, inalterada). H2 (SIG-FAST-POSTMIG) muda
de fonte de dado: em vez de esperar sessões de horas/dias do motor ao vivo,
roda discovery+confirmação sobre migrações pump→PumpSwap **já aconteceram**,
buscadas via RPC (Helius) e decodificadas pelo mesmo decoder Carbon já
estendido no item (a) (`benchmarks/carbon_decoder_parity_v1/rust_runner`).
Motivo: dado já existe on-chain, não precisa esperar nenhuma sessão rodar.
Oito regras anti-viés (seção dedicada abaixo) entram no congelamento do
protocolo **antes de qualquer download** — nenhuma foi violada ainda porque
nenhum download aconteceu. Passo 0 ao vivo (runbook
`docs/sig-fast-passo-0-calibration-runbook-v0-2026-10-09.md`) **deixa de ser
fonte de teste de H2** e vira checagem final de sistema/latência do motor ao
vivo (ainda relevante pra H1 e para a eventual automação futura, nunca pra
julgar H2). Execução em 3 passos, cada um com seu próprio gate de OK do
operador: (A) piloto de custo/cobertura (sem retorno); (B) download selado
dos 2 blocos congelados (sem retorno até o operador aprovar a cobertura);
(C) investigação (sem código, sem download) de uma fonte sem viés de
sobrevivência pra H1 no histórico — não autoriza coleta de H1 ainda.

## Regras anti-viés do discovery histórico de H2 (rev. 4, congeladas antes de qualquer download)

1. **Universo**: migrações pump→PumpSwap **sorteadas ao acaso** (seed fixa
   `20261008` — a data de hoje como inteiro, documentada aqui antes de ver
   qualquer dado) da enumeração on-chain da conta de migração
   (`39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg`, mesmo mecanismo de
   `benchmarks/move_first_h_coverage_audit_v0/sample_migration_account.py`,
   função `fetch_day_classified`). Só transações **bem-sucedidas** que de
   fato completam `CreatePool` (`completed_create_pool=True` — "already
   migrated" tem `err: null` e não conta, mesmo achado já confirmado em
   MOVE-FIRST-H-DISC-V0), dedup por `pool_mint`. Inclui migrações que
   morreram depois — nunca uma lista de tokens "conhecidos" ou vivos hoje
   (isso seria viés de sobrevivência por construção).
2. **Período — 2 blocos de calendário fixados agora (2026-10-08), sem olhar
   nenhum dado**:
   - **Discovery**: `2026-08-20` a `2026-09-17` (4 semanas = 28 dias), split
     70/30 temporal fixo em dias de calendário (não por sorteio): treino
     `2026-08-20`–`2026-09-09` (20 dias, ~71%), holdout `2026-09-09`–`2026-09-17`
     (8 dias, ~29%).
   - **Embargo**: `2026-09-17` a `2026-09-24` (1 semana), sem nenhuma migração
     deste intervalo em discovery ou confirmação.
   - **Confirmação selada**: `2026-09-24` a `2026-10-08` (2 semanas MAIS
     RECENTES), baixada **em separado** do discovery, hash commitado antes de
     qualquer cálculo, **nunca lida pelo código de discovery** (import/arquivo
     separado, sem caminho de código compartilhado que leia os dois blocos ao
     mesmo tempo).
   - Todo o intervalo (`2026-08-20`..`2026-10-08`) é **pós-BOOST**
     (`>=2026-07-21`, confirmado em `docs/strategy-h-established-memecoin-
     momentum-discovery-v0-preregistration-DRAFT-2026-10-08.md`) — um único
     regime de fee/BOOST em toda a janela, sem mistura de regimes.
3. **Por token sorteado**: todos os trades do pool PumpSwap, da migração até
   migração+20min (marco do sinal MemeTrans) + 60min (W máximo da métrica
   primária). Reservas (`pool_base_token_reserves`/`pool_quote_token_reserves`)
   e fee (`lp_fee`/`protocol_fee`/`coin_creator_fee` + basis points) lidas do
   próprio evento `BuyEvent`/`SellEvent` (decoder Carbon, item (a) desta
   sessão — já expõe esses campos). Tempo = `block_time` da transação; ordem
   dentro do mesmo `block_time` = `slot` + índice da transação no bloco.
4. **Causalidade**: o sinal (marco dos 20min, preço, contagem de trades) usa
   só trades com `block_time <= T`. Entrada = 1º trade com
   `block_time >= T + Δ`, **Δ primário = 30s + 2s de atraso de detecção
   assumido = 32s** (grade diagnóstica de Δ continua só diagnóstico, igual
   rev. 2/3). Nenhum trade depois de `T + Δ` influencia a decisão de entrar
   — mesmo teste de causalidade já existente em
   `tests/test_opportunity_path_metrics_v0.py` (`CausalEntryTests`) se aplica
   aqui sem modificação, porque consome a mesma interface `PathTrade`/
   `find_causal_entry` do F2 congelado.
5. **Selagem**: baixar → gravar o dado bruto (resposta RPC completa, não só
   os campos decodificados) → hash commitado → só então calcular qualquer
   métrica. Cobertura (% de trades com reservas+fee decodificados, nº de
   migrações sorteadas que renderam dado utilizável) é reportada **antes** de
   qualquer resultado — mesmo padrão já usado em F1c/F7 desta linha de
   trabalho.
6. **Proveniência**: tabela própria de backfill, schema dedicado (ver item
   (19) do work order desta rodada) com `source`, `fetched_at` real (quando
   a chamada RPC de fato aconteceu, não um valor inventado) e `block_time`
   (tempo on-chain real do trade). **Nunca** em `market_trade_observations`
   (essa tabela é do caminho ao vivo/batch, schema já tem um contrato
   diferente) e **nunca** com um `observed_at` falso — isso violaria o
   invariante 11 de `CLAUDE.md` ("historical data may not receive fake
   historical `observed_at`"). O backfill histórico não tem e não precisa de
   `observed_at` no sentido do invariante (que é sobre o momento em que ESTE
   repositório observou algo ao vivo); ele tem `fetched_at` (quando a chamada
   RPC aconteceu, hoje) e `block_time` (quando o trade aconteceu on-chain,
   no passado) — dois campos reais, nunca um substituindo o outro.
7. **Baseline (F3)**: do mesmo universo sorteado (regra 1), mesma idade
   pós-migração que o sinal — reusa `opportunity_path_baseline_v0.py` sem
   modificação, só troca de onde vêm os `TokenCandidate` (histórico em vez de
   live).
8. **Status**: H2 passa a ser discovery histórico + confirmação histórica
   selada (regras 1-7); Passo 0 ao vivo deixa de julgar H2, vira checagem de
   sistema/latência (ver "Rev. 4" acima). Registrado em
   `docs/research-hypothesis-registry-v1-2026-10-04.md` (linha
   `SIG-FAST-DISC-V0`, mesmo commit desta atualização).

**Addendum Fase E (2026-10-08): fonte de RPC do backfill, congelado antes de
rodar o piloto de novo.** O operador configurou um segundo provedor
(QuickNode grátis, `H2_BACKFILL_RPC_URLS`) e pediu que o backfill passe a
usar só `getSignaturesForAddress` + `getTransaction` (não o método exclusivo
da Helius) em rodízio de endpoints, pra reduzir a dependência de um único
provedor. Decisão registrada aqui, não decidida em silêncio:

- **Estágio 1 (enumeração das migrações)** continua na Helius via
  `getTransactionsForAddress` com filtro `blockTime` (mesmo mecanismo de
  `fetch_day_classified`, agora aplicado só à janela sorteada, não ao dia
  inteiro — ver addendum Fase E parte 2 abaixo). Motivo de continuar na
  Helius: MOVE-FIRST-H-DISC-V0 já achou que caminhar
  `getSignaturesForAddress` sequencialmente na conta de migração
  (`MIGRATION_AUTHORITY`, alto volume compartilhado) bate ~1.500.000
  assinaturas sem saído dos últimos ~2 meses — inviável pro lookback de 7-11
  semanas do piloto/discovery. Isso não muda a regra 1 (universo/sorteio),
  só o transporte.
- **Estágio 2 (trades de cada pool sorteado)** usa o método de 2 chamadas
  (`getSignaturesForAddress` paginado por `before`, parando quando a página
  mais antiga já está no ou antes de `window_start`, seguido de
  `getTransaction` por assinatura mantida) em **prioridade fixa** (não
  round-robin) entre `H2_BACKFILL_RPC_URLS` + o endpoint público
  (`https://api.mainnet-beta.solana.com`) + Helius **por último** —
  `EndpointRotator` em `benchmarks/sig_fast_v0/h2_historical_backfill_v0.py`
  sempre tenta na ordem dada, caindo pro próximo só numa falha; só levanta
  erro se todos falharem na mesma chamada. Corrigido na Fase E parte 2
  (abaixo): a ordem original desta revisão era round-robin (uso igual entre
  os três); o operador pediu poupar a Helius pro Estágio 1 especificamente,
  então a ordem agora é prioridade, com Helius por último.
- Diagnóstico do 429 da Helius (pedido do operador): confirmado que vinha da
  própria Helius (headers `Server: cloudflare`/`CF-Ray` genuínos tanto na
  falha quanto no sucesso seguinte), não do proxy do sandbox (`status` do
  proxy sem `recentRelayFailures`). Era rate-limit transitório — já havia
  voltado a responder 200 antes deste addendum ser escrito (mas voltou a
  aparecer na prática ao rodar o piloto de verdade, ver addendum Fase E
  parte 2).
- Nenhuma URL de RPC (Helius ou QuickNode) é impressa, logada ou commitada em
  nenhum lugar deste pipeline — só host/índice quando algo precisa ser
  identificado.

**Addendum Fase E parte 2 (2026-10-08, mesmo dia): amostragem por janelas +
429 tolerante, congelado antes de rodar o piloto de novo.** O piloto real
(Fase E parte 1) bateu 429 de novo no Estágio 1 logo na segunda chamada
(paginação do mesmo dia), mesmo a 5 req/s — caminhar o dia inteiro na conta
de migração é caro demais pra essa conta mesmo com rate limit conservador.
Duas mudanças, nenhuma delas afeta a régua de H2 (regras 1-8 acima), só o
transporte:

1. **Enumeração por janelas sorteadas, não por dia inteiro.** Por bloco
   (piloto, discovery ou confirmação), sorteiam-se (seed `20261008`, mesma
   seed de sempre) K janelas de 10 minutos, de um grid não-sobreposto sobre
   o calendário do bloco, sem reposição
   (`sample_calendar_windows` em `h2_historical_backfill_v0.py`). Pra cada
   janela sorteada, busca-se **toda** migração bem-sucedida dentro dela
   (`getTransactionsForAddress` com filtro `blockTime`, exige
   `completed_create_pool=True` **e** `meta.err is None` —
   `fetch_migrations_in_windows`). A **janela** é a unidade de amostra
   (conglomerado): toda migração bem-sucedida dentro dela entra, nunca só
   "a próxima depois de um horário sorteado" (isso enviesaria pra migrações
   que vêm depois de períodos mais calmos — regra explícita do operador).
   `migration_block_time` agora vem direto do próprio evento de enumeração
   (`blockTime` real da resposta), não mais um placeholder por dia — então
   `run_pilot_token` não precisa mais de uma chamada `getTransaction`
   separada só pra resolver esse instante.
   - Piloto: `K=3` janelas de 10min no lookback (`2026-07-21`..
     `2026-08-20`), suficiente pra ~10 migrações esperadas à taxa observada
     de ~40/h (2-3 janelas, conforme estimativa do operador). **K final por
     bloco** (discovery/confirmação) fica pendente do resultado real do
     piloto — ver "K proposto" abaixo.
2. **429 desacelera, não aborta.** Helius a 1 req/s (limiter próprio,
   independente do limiter dos outros endpoints); em 429, respeita
   `Retry-After` quando presente, senão backoff exponencial dobrando a cada
   tentativa até 60s; só aborta se passar ~10 minutos **sem nenhum sucesso**
   — nunca na primeira falha isolada. O circuit breaker de 3 falhas
   consecutivas continua existindo, mas só conta erros que **não** são 429
   (5xx, timeout, resposta inválida) — um 429 nunca incrementa esse
   contador. Implementado em `install_rate_limited_rpc`
   (`benchmarks/sig_fast_v0/h2_pilot_v0.py`).
3. **Checkpoint em disco por janela/pool**
   (`artifacts/sig_fast_h2_pilot_v0/checkpoint.json`, fora do git): cada
   janela enumerada e cada token processado são salvos assim que terminam;
   um re-run do piloto pula o que já está no checkpoint em vez de refazer.
4. Estágio 2 (trades por pool) continua no rodízio de prioridade fixa
   (ver bullet acima), poupando a Helius pro Estágio 1.

**Addendum Fase E parte 3 (2026-10-08, mesmo dia): achado de custo real do
Estágio 2 — volume de trade na janela muito maior que o modelo assumia,
piloto parado antes de gastar nenhuma chamada `getTransaction`.** Rodando o
piloto com o método novo: Estágio 1 (janela sorteada) funcionou bem — janela
1 achou as 7 migrações reais em 1 chamada, rápido. Testei o Estágio 2 pra 1
dessas 7 migrações (diagnóstico isolado, só `getSignaturesForAddress`
paginado, sem chamar `getTransaction` nenhuma vez): QuickNode/público
responderam rápido e sem erro (21 páginas, ~0,25s/chamada, 5,5s no total) —
mas a janela de 80min desse pool teve **16.473 transações**, não as
dezenas/centenas assumidas implicitamente no modelo de custo (F4). O método
de 2 chamadas pede 1 `getTransaction` por assinatura mantida — pra só esse
1 pool, seriam ~16.500 chamadas, que a 5 req/s (não-Helius) levam ~55
minutos **só de uma migração**, antes mesmo de decodificar. É isso que
travou o piloto rodando em background por 30min sem terminar nem 1 token —
não é 429, é volume real de trade pós-migração (atividade de bot/sniper
intensa nos primeiros minutos é plausível e não deveria ter sido
surpreendente, mas o modelo de custo não contava com isso). Parei aqui —
nenhuma chamada `getTransaction` foi feita pra essas 16.473 assinaturas,
sem martelar. **Isso é um problema de arquitetura, não de rede**: o método
de 2 chamadas tem custo por-transação (1 chamada por trade), enquanto o
método exclusivo da Helius (`getTransactionsForAddress`, usado no Estágio 1
e no antigo `fetch_pool_trades_raw`, removido) batcha até 1000
transações completas por chamada — ordens de magnitude mais barato pra
pools de alto volume. Opções que não decidi sozinho, pendentes do operador:
(a) usar JSON-RPC batch request (várias chamadas `getTransaction` num só
POST HTTP) se QuickNode/público suportarem — reduziria round-trips, não
necessariamente o número de chamadas cobradas; (b) usar o método em lote da
Helius (`getTransactionsForAddress`) também no Estágio 2 quando ela estiver
saudável, aceitando a dependência que o pedido desta rodada queria evitar;
(c) outra estratégia de amostragem/cobertura dentro da janela, o que
tensiona com a regra 5 (cobertura completa reportada antes do resultado).
K/N continuam **não fixados** — faltam dados de Estágio 2 de qualquer
migração ainda.

**Addendum Fase E parte 4 (2026-10-09): grade de preço de 5s — decisão do
operador, congelada antes de qualquer download, substitui as 3 opções
puras da parte 3.** Nenhuma das opções (a)/(b)/(c) isoladas resolvia bem:
(a) depende de suporte a batch JSON-RPC ainda não confirmado; (b)
reintroduz a dependência exclusiva da Helius que esta rodada queria evitar;
(c) pura tensiona com a regra 5 (cobertura completa). A decisão é uma
variante de (c) com regras fixas, igual para sinal e baseline, sem viés
introduzido por amostragem seletiva:

1. **Lista de assinaturas, completa e barata.** Por pool, todas as
   assinaturas da janela via `getSignaturesForAddress` (1 crédito flat,
   sem `getTransaction` nenhum) — `block_time` e `err` **já vêm na própria
   resposta**, sem precisar resolver a transação. Descarta-se `err != null`
   (não decodificável como trade bem-sucedido); a % de falha é reportada
   como contagem de sistema, nunca descartada em silêncio.
2. **Grade de 5s a partir da migração.** Em cada bucket de 5s: pega a
   **última** transação bem-sucedida do bucket; chama `getTransaction`
   nela; se não tiver evento de swap PumpSwap (`pumpswap_buy`/
   `pumpswap_sell`) decodificado, tenta a transação anterior dentro do
   mesmo bucket (limite de tentativas por bucket, pra não martelar um
   bucket anômalo cheio de instruções não-swap). Reservas pós-trade do
   swap achado = preço no fim do bucket. Bucket sem transação bem-sucedida,
   ou sem nenhum swap resolvível dentro dele → preço **carregado do bucket
   anterior** (sem swap o pool não muda de reservas). Preço em T0
   (migração) = o mesmo procedimento aplicado a partir do bucket 0, andando
   pra **frente** até achar o primeiro swap (não há bucket anterior pra
   carregar). Entrada (quando o cálculo de sinal real for autorizado) = 1ª
   transação bem-sucedida com `block_time >= T + Δ`, buscada
   especificamente (não é parte do piloto, que nunca calcula entrada/
   retorno).
3. **Estágio 1 barato, para TODO token sorteado (piloto e discovery/
   confirmação futuros).** Preço em T0 + preço no marco de 20min (regra 2,
   tipicamente 2 chamadas `getTransaction` no caso otimista — mais se a
   busca por bucket precisar andar pra trás) + contagem de trades
   bem-sucedidos nos últimos 5 minutos antes do marco (da própria lista da
   regra 1, sem chamada nova) → classifica sobrevivente pela regra já
   pré-registrada de H2 (razão de preço marco/T0 >= 0,40, inalterada —
   este addendum troca só a FONTE do preço, nunca a régua de decisão). A
   contagem de trades nos últimos 5min é reportada como diagnóstico
   adicional de sistema, não substitui nem pondera a régua pré-registrada.
4. **Estágio 2 (grade completa, migração até +80min) — só pra discovery/
   confirmação reais, não pro piloto de custo.** Todos os sobreviventes +
   amostra aleatória (seed fixa `20261008`) de não-sobreviventes do mesmo
   tamanho, para o baseline (F3). Proporção exata (1:1 sobrevivente:
   não-sobrevivente) fixada aqui; nenhuma mudança de proporção depois de
   ver dado.
5. **Limitação documentada:** a grade de 5s não resolve picos de preço
   mais curtos que 5s — um pico que sobe e desce dentro do mesmo bucket
   nunca aparece, só o preço no fim do bucket (= o último swap resolvido).
   Essa subestimação é **simétrica entre sinal e baseline** (mesma grade,
   mesma regra, nos dois grupos) — não introduz viés direcional a favor ou
   contra H2. Um operador humano real executando manualmente com Δ=30s
   (a latência de decisão primária desta rodada) também não capturaria
   picos sub-5s — a grade não é menos realista que a execução que o
   produto pretende viabilizar.
6. **Batch JSON-RPC é só otimização de velocidade, nunca de medida.** Se
   QuickNode/público suportarem enviar várias requisições num único POST
   HTTP, usar isso pra reduzir round-trips/tempo de parede — mas o que é
   contado (nº de chamadas lógicas, créditos, cobertura) não muda. Testar
   antes de assumir suporte; cair pra chamadas sequenciais se não suportar.
   A Helius continua restrita ao Estágio 1 (enumeração) nesta grade também.

Custo esperado (vs. o achado da parte 3): pra um pool de ~16.500
transações em 80min (≈960 buckets de 5s), o Estágio 2 completo (regra 4)
custa na ordem de ~1 `getTransaction` por bucket não-vazio no caso
otimista — uma redução de ordem de grandeza frente a 1-por-transação,
medida empiricamente abaixo antes de qualquer download dos 2 blocos. O
Estágio 1 barato (regra 3) é independente do volume de trade do pool (só
2+ chamadas por token), então escala bem pra qualquer K.

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`.

Instrumento de medida (congelado para este lote, trocar exige lote novo):
`src/opportunity_path_metrics_v0.py` (F2) + `src/opportunity_path_baseline_v0.py`
(F3) + modelo de custo em `docs/sig-fast-cost-model-v0-2026-10-08.md` (F4).
Persistência de caminho de preço: F1b + wiring do motor ao vivo (F1b +
`docs/sig-fast-live-engine-wiring-v0-2026-10-09.md`), branch
`sig-fast-price-path-persistence-v0`, ainda não mergeada na autoridade —
aguarda replicação do PQ-TR.

## Item (c) da métrica primária — resolvido pelo operador

Resposta do operador, substitui a nota de interpretação da rev. 1: **(c) = os
dois, não um ou outro.** (i) Retenção de 30%: o resultado de (a) e (b) no
holdout de 30% dentro do discovery precisa se sustentar, com o MESMO sinal, o
mesmo Δ e a mesma regra de saída escolhidos nos 70% de treino — nada
reajustado ao ver o holdout. (ii) Separadamente, depois do discovery+holdout
congelados e commitados, uma confirmação prospectiva fresca (coleta nova, sem
overlap com o discovery) precisa repetir o mesmo resultado, com a regra
idêntica. As duas etapas são exigidas, em sequência — isso é a disciplina de
3 passos do registro (PASS no pré-registrado → PASS na replicação fresca →
Gate 2) aplicada à régua de caminho de preço.

## 1. Coleta que julga este lote

**Rev. 4: as duas hipóteses não compartilham mais uma única coleta.** H1
continua na coleta ao vivo (seção 1a, inalterada desde a rev. 3). H2 passa a
usar um discovery+confirmação histórico selado, sem motor ao vivo (seção 1b,
nova nesta revisão — ver também "Regras anti-viés do discovery histórico de
H2" acima).

### 1a. Coleta de H1 (ao vivo, inalterada)

**Discovery NÃO é retrospectivo.** Os trades já capturados antes de
2026-10-09 não têm reservas (`base_reserves_raw`/`quote_reserves_raw`
nulos — confirmado em F1c contra o sandbox, 100% de cobertura faltante). O
motor ao vivo só passou a gravar esses campos a partir do commit `fd87939`
(`docs/sig-fast-live-engine-wiring-v0-2026-10-09.md`). **O discovery exige
coleta nova**, rodando o motor corrigido, em sessões longas e contínuas — ver
"Plano de coleta" abaixo.

- Run key(s): `<a definir no sign-off — chaves frescas, nunca usadas>`
- Caminho de aquisição: `run_live_shadow_v0` (motor corrigido, commit `fd87939`
  ou posterior) → `market_trade_observations` com `base_amount_raw`/
  `quote_amount_raw`/`base_reserves_raw`/`quote_reserves_raw` populados
  (PumpSwap completo; Pump sem `base_reserves_raw` até o bloqueador do Rust
  não-congelado ser resolvido pelo operador — ver doc de wiring).
- Janela e cohorts: split temporal **70/30 dentro do discovery**; confirmação
  prospectiva fresca **depois**, em coleta separada, sem overlap temporal com
  o discovery.
- Instrumento de medida: `opportunity_path_metrics_v0` + `opportunity_path_baseline_v0`,
  **tamanho fixo de 0,15 SOL por posição** (confirmado pelo operador — nada de
  US$, nada de cotação SOL/USD necessária; `size_sol=0.15` direto no
  `CostModel`/`find_causal_entry`).
- **Δ primário = 30s, fixo** (confirmado pelo operador — provisório até ele
  medir a latência real dele). Δ ∈ {5, 15, 60, 120}s continuam na grade, mas
  só como **diagnóstico** — nunca contam para o veredito PASS/FAIL, só servem
  pra calibrar quando o operador souber a latência real dele.
- **Terminal primário = 1%/perna** (confirmado pelo operador). A grade
  {0%, 1%} de F4 permanece como sensibilidade diagnóstica, não como parte da
  decisão.
- Gates de sistema que precisam passar antes de qualquer número econômico:
  cobertura de preço derivável (`benchmarks/sig_fast_v0/path_coverage_audit.py`,
  F1c) **>=95%** dos trades no caminho com preço derivável (confirmado pelo
  operador); nenhum worker/traceback error na coleta; missingness explícita
  onde a cobertura falhar (nunca tratada como 0).
- Condições operacionais: saída redirecionada para arquivo, hash dos dados
  commitado antes de qualquer cálculo (ver F7), PC sem suspensão durante toda
  a coleta (sessões de horas, não minutos).

### 1b. Coleta de H2 (histórica, selada, rev. 4)

- Run key(s): `<a definir no sign-off da rev. 4 — chaves frescas, nunca
  usadas, uma por bloco (discovery/confirmação) pra manter a separação física
  exigida pela regra 2>`.
- Caminho de aquisição: enumeração da conta de migração (regra 1) → sorteio
  (seed `20261008`) → busca de trades do pool via RPC (`getTransactionsForAddress`
  filtrado por `blockTime`, mesma chamada já provada em
  `sample_migration_account.py`) → decodificação pelo decoder Carbon (item
  (a) desta sessão, `benchmarks/carbon_decoder_parity_v1/rust_runner`) →
  tabela própria de backfill (regra 6) → `PathTrade` (F2) sem passar por
  `market_trade_observations`.
- Janela e cohorts: discovery = treino 70% + holdout 30% (datas fixas, regra
  2); confirmação selada = bloco separado, 1 semana de embargo, nunca lida
  pelo código de discovery (regra 2).
- Instrumento de medida: o mesmo F2/F3/F4 de H1 — nenhuma mudança no
  instrumento, só na fonte do `PathTrade`/`CostModel.venue_fee_pct` (agora
  lido do evento histórico, não do live capture).
- **Δ primário = 32s fixo** (30s + 2s de atraso de detecção assumido, regra
  4) — distinto do Δ=30s de H1 porque H2 não tem motor ao vivo cujo atraso
  real ele vá medir; os outros valores da grade continuam diagnóstico.
- Gates de sistema antes de qualquer número econômico: cobertura de preço
  derivável **>=95%** (mesmo piso de H1/F1c, agora medido sobre o backfill
  histórico); piloto (passo A) aprovado antes do download dos blocos (passo
  B); cobertura do download aprovada pelo operador antes de qualquer cálculo
  de retorno (passo B, "NÃO calcular retorno até eu dar OK").
- Condições operacionais: mesma disciplina de selagem da regra 5 — sem
  suspensão de energia não é necessário aqui (chamadas RPC pontuais, não uma
  sessão contínua de horas), mas hash commitado antes de qualquer cálculo é
  obrigatório do mesmo jeito.

### Plano de coleta (H1, ao vivo — rev. 4: Passo 0 deixa de julgar H2)

**Passo 0 — rev. 4: deixa de julgar H2, vira checagem final de sistema/
latência (nunca fonte do teste de nenhuma hipótese).** Sessão curta (2-4h)
pra medir, com dado real, a cobertura de preço (`path_coverage_audit.py`) e
a continuidade pós-graduação sob o motor corrigido, relevante pra H1 (que
continua dependendo do motor ao vivo) e pra validar o motor antes de uma
eventual automação futura. `audit_graduation_continuity` (mesmo arquivo,
item (b)) reporta, por token graduado pra PumpSwap, se o motor continua
persistindo trades por >=60min depois da graduação
(`meets_60min_floor` / `dropped_before_60min_floor` /
`run_ended_before_60min_floor`) -- contagem/duração, nunca preço ou retorno.
**Essa métrica não decide mais nada sobre H2** (rev. 4): H2 agora lê
continuidade do próprio backfill histórico (regra 3 das regras anti-viés),
não do motor ao vivo -- runbook
`docs/sig-fast-passo-0-calibration-runbook-v0-2026-10-09.md`.

**Estimativa de taxa de sinal de H1 (de systems data já coletado, não é
outcome)**: a taxa de sinal de H1 depende do cohort de carteiras, que só
existe depois do bloco 1 (abaixo) — **não estimável antes da primeira sessão
real**. (A estimativa de taxa de graduação pump→PumpSwap que vivia aqui
antes da rev. 4 -- ~950/dia, MemeTrans ~27% sobrevivente -- era sobre H2;
H2 saiu deste plano ao vivo, ver "Regras anti-viés do discovery histórico de
H2" acima, onde a taxa real agora é medida pelo piloto, não estimada.)

**Bloco 1 — formação do cohort H1 (bloco temporal inicial, congelado depois).**
Proposta: 48-72h contínuas de coleta antes de qualquer avaliação de sinal de
H1 — tempo suficiente pra algumas carteiras acumularem round-trips realizados
com preço (compra+venda, ambas com preço derivável nesta mesma coleta nova).
**Não confirmado com dado real** quantas carteiras atingem round-trips
suficientes nesse intervalo — o Passo 0 não mede isso (é outcome de lucro
realizado, ainda que sem ser o veredito da hipótese); a calibração real desse
bloco só acontece rodando-o.

**Discovery de H1 (rev. 4: só H1 — H2 saiu deste plano ao vivo).** O
dimensionamento desta janela (quantos dias de coleta ao vivo) depende só do
cohort que emergir do bloco 1 -- não há mais estimativa de taxa H2 puxando
este número. **Proposta conservadora, ainda provisória**: uma janela
contínua única de **5-7 dias** (cobre o bloco 1 inteiro + folga para H1
atingir n>=30, considerando vetos que reduzem a amostra elegível — PQ-TR
ainda fora, bundle/sniper já mergeado nesta revisão). Dividir em 70/30 por
ordem temporal dentro dessa janela. Como H2 não depende mais desta coleta,
este plano ao vivo passa a ser **secundário** no cronograma -- a prioridade
imediata é o discovery histórico de H2 (regras anti-viés acima).

**Confirmação prospectiva fresca (H1).** Nova janela contínua, iniciada só
depois do discovery de H1 (regra+Δ+saída) estar congelada e commitada — sem
overlap. Mesma ordem de grandeza de dias que o discovery, para ter suporte
comparável.

**Stall guard.** O motor de discovery (`benchmarks/sig_fast_v0/discovery_v0.py`,
F7) já tem `StallGuard`. A **coleta em si** (`run_live_shadow_v0`) **agora
também tem** (rev. 3, item (b) do operador, 2026-10-09): gap > 30s entre
ticks monotônicos consecutivos do loop consumidor principal → `break`
explícito, reportado em `consumer_stall_detected`/`consumer_stall_gap_seconds`
no relatório final e como gate `no_consumer_loop_stall` (falha fechada,
mesmo padrão de `FORWARD_COLLECTION_V43_STALL_GAP_SECONDS`/
`FORWARD_COLLECTION_900_STALL_GAP_SECONDS`). Distinto do
`SURFACE_IDLE_TIMEOUT_SECONDS` já existente, que cobre "a conexão WS calou",
não "o loop do processo travou".

**Custo de créditos Helius da coleta contínua (H1, ao vivo).** **Não
confirmado nesta revisão** — recomendo o operador checar o uso do plano
Helius dele depois do Passo 0 (2-4h), que já vai dar uma amostra real de
consumo pra extrapolar pros 5-7 dias propostos. (Distinto do custo de H2,
que agora é RPC pontual por chamada, não uma sessão WS contínua — medido
pelo piloto, não estimado aqui; ver "Regras anti-viés do discovery histórico
de H2".)

**Os números de duração acima (Passo 0, bloco 1 de 48-72h, janela de
discovery de 5-7 dias, H1) são estimativas derivadas de taxa de migração
observada, não medição direta de taxa de sinal — ainda não confirmados pelo
operador.** Recomendo rodar o Passo 0 primeiro e só então fixar os números
maiores; isso vai para as perguntas abertas no fim deste documento, não foi
decidido aqui.

## 2. Hipóteses (K = 2)

### H1 — SIG-FAST-COPY-G (copy-trading filtrado, desenho E11)

- **Família**: coordenação / qualidade de wallet.
- **Tipo**: entrada (família candidata dentro do caminho SIG-FAST).
- **Origem**: nova — primeira vez que o desenho do E11 é testado com dado
  próprio sob a régua de caminho de preço; não é resgate de V48/V55/V68/PQ-V1
  (features de fluxo genérico, não smart-money). **Aprovado pelo operador
  como hipótese nova** (mecanismo ≠ PQ-V1).
- **As 5 perguntas**:
  1. De quem vem o dinheiro: vantagem posicional/informacional da carteira
     smart-money copiada (E11, arXiv 2601.08641v3) — quem compra depois dela,
     ou vende antes dela, paga a diferença.
  2. Por que read-only/30s atrasado ainda captura: **não está respondido pelo
     paper** (achado da revisão 3 do memo — o +3% do E11 assume atraso
     ~zero). É a pergunta central que este discovery mede empiricamente, no
     Δ primário fixo de 30s (grade {5,15,60,120}s só diagnóstico).
  3. Evidência: E11, peer-reviewed, mesmo domínio (Pump.fun); Grade A/B no
     `docs/research-evidence-registry-v1-2026-09-02.md`.
  4. Teste mais barato: **coleta nova** (não retrospectivo, ver seção 1) —
     mais barato que alternativas porque reusa o mesmo motor/coleta de H2.
  5. Critério de morte: ver "PASS exige" abaixo.
- **Gatilho de entrada (sinal)**: BUY detectado on-chain de uma carteira do
  cohort smart-money. **Formação do cohort (resolvido pelo operador)**: lucro
  realizado calculado **só nos dados novos desta coleta, com preço
  derivável** (nunca na memória do PQ-V1, nunca em dado antigo sem reservas)
  — o cohort é formado no **bloco 1** (primeiro bloco temporal da coleta, ver
  "Plano de coleta") e **congelado** a partir daí; sinais de H1 só são
  avaliados nos blocos temporais seguintes ao bloco 1, nunca dentro dele.
  `signal_time` = `chain_time` do trade da carteira copiada.
- **Dependências de observabilidade**: `slot`/`creator`/`creation_slot` (branch
  `bundle-bot-detection-v0-plumbing`, não mergeada) para os filtros
  bundle/sniper/bump do E11 (Algoritmos 1-3). Sem esses campos, os filtros
  bundle/sniper/bump ficam **INCONCLUSIVE por cobertura**, não pulados
  silenciosamente.
- **Vetos (rejeição)**:
  - PQ-TR (LOW vs ALL, corte `-86.0484432047999` congelado) — **aguarda
    replicação do PQ-TR** antes de entrar como veto ativo; sem ela, fica fora
    do veto set desta rodada (não substituído por outro corte).
  - Freeze authority (`src/opportunity_onchain_hazard.py::freeze_authority_present`)
    — disponível hoje, sem custo.
  - Bundle/sniper/bump (E11 Algoritmos 1-3) — depende do merge do plumbing
    acima.
- **Janela primária**: W=900s (15min), alvo +50%/stop −30% para a métrica (a),
  **Δ=30s fixo**. Outras janelas (60/300/3600s), barreiras (±20/100/200%) e
  Δ∈{5,15,60,120}s são diagnóstico.
- **Suporte mínimo**: n>=30 pares primários (no Δ primário fixo; mesma régua
  da CHURN-V0/EBPQ-REPL-V0).
- **PASS exige todos**:
  1. P(+50% antes de −30% em 15min) do sinal − baseline (F3) >= 10pp, no
     Δ primário (30s);
  2. EV líquido > 0 **e** PF líquido > 1, sob a melhor das 6 regras de saída
     (`EXIT_RULE_IDS`) escolhida nos 70% de treino, Δ=30s, terminal 1%/perna
     (custos do sweep 1x/2x só como diagnóstico adicional, disciplina do
     Gate 2);
  3. (1)+(2) se sustentam no holdout de 30% (mesmo Δ, mesma saída, nada
     reajustado) **e** na confirmação prospectiva fresca separada (ver "Item
     (c)" acima).
- **FAIL**: qualquer um dos 3 falha no holdout ou na confirmação fresca, ou o
  edge (1) não aparece no Δ primário.
- **INCONCLUSIVE**: suporte < n mínimo, ou cobertura de preço derivável abaixo
  de 95%.
- **Controles/placebo**: baseline pareado (F3) — K tokens elegíveis no mesmo
  `signal_time`, mesma venue, mesma faixa de idade, mesma atividade mínima,
  seed fixa. MFE reportado só como teto teórico, nunca somado ao EV/PF.
- **O que um PASS não prova**: fill real, latência além da simulada (30s é a
  do treino, não necessariamente a real do operador — grade diagnóstica serve
  pra isso), execução automatizada, shadow, live. Execução continua manual
  (CLAUDE.md).

### H2 — SIG-FAST-POSTMIG (sobreviventes pós-migração, desenho MemeTrans)

- **Família**: metadado do token / momentum de sobrevivência.
- **Tipo**: entrada (família candidata dentro do caminho SIG-FAST).
- **Origem**: nova — usa a semântica de timing do MemeTrans (quando NÃO
  entrar), nunca testada aqui como gatilho positivo de entrada; não toca
  nenhuma feature de hipótese fechada deste programa.
- **As 5 perguntas**:
  1. De quem vem o dinheiro: MemeTrans (arXiv 2602.13480, n=41.470) mede que
     ~72,96% dos tokens caem para <40% do preço de migração em 20min — quem
     compra no instante da graduação, às cegas, paga a maioria desse colapso.
     A minoria que sobrevive esse intervalo já filtrou boa parte do pânico de
     venda inicial; o lado comprador que entra depois herda uma população com
     menos vendedores de pânico ainda por vir.
  2. Por que read-only/30s atrasado ainda captura: o próprio desenho exige
     esperar 20 minutos pós-graduação antes de entrar — atraso de segundos é
     irrelevante por construção.
  3. Evidência: MemeTrans, mesma fonte já verificada diretamente na Tabela 6 do
     paper (citada em `docs/strategy-options-move-first-2026-10-07.md`, Opção F).
  4. Teste mais barato (rev. 4): discovery+confirmação **histórico selado**
     (ver seção 1b e "Regras anti-viés do discovery histórico de H2") — dado
     já existe on-chain, não precisa esperar nenhuma sessão ao vivo rodar;
     mais barato que a coleta ao vivo de H1 porque não depende de duração de
     sessão nem de energia da máquina ligada.
  5. Critério de morte: ver "PASS exige" abaixo.
- **Gatilho de entrada (sinal) — definição única, resolvida pelo operador (não
  é mais grade de X)**: `idade_pos_graduacao == 20 minutos` **e** preço no
  marco de 20min >= 40% do preço de migração (definição exata do MemeTrans)
  **e** >=20 trades nos últimos 5 minutos antes do marco (15-20min
  pós-graduação). `signal_time` = o instante do marco dos 20 minutos.
- **Fonte de dado (rev. 4)**: discovery+confirmação histórico selado sobre
  migrações sorteadas, não coleta ao vivo — ver "1b. Coleta de H2" e "Regras
  anti-viés do discovery histórico de H2" acima.
- **Dependências de observabilidade (rev. 4: tabela de backfill histórico,
  não mais `market_trade_observations`/`market_lifecycle_observations`)**:
  migração detectada via `CreatePool` na enumeração (regra 1); reservas
  (`pool_base_token_reserves`/`pool_quote_token_reserves`) e fee (`lp_fee`/
  `protocol_fee`/`coin_creator_fee` + basis points) lidas do evento
  `BuyEvent`/`SellEvent` decodificado pelo Carbon (regra 3); `base_amount_raw`/
  `quote_amount_raw` do mesmo evento pra contar os >=20 trades e derivar o
  preço no marco.
- **Vetos (rejeição)**: os mesmos 3 de H1 (PQ-TR aguardando replicação, freeze
  authority disponível, bundle/sniper/bump dependente do merge) — pouco
  relevante numa moeda já sobrevivente 20min, mas ainda computável se os
  campos existirem **e** se a tabela de backfill histórico também carregar
  `creator`/`creation_slot` (a confirmar quando o fetcher histórico for
  implementado — ver item (19) do work order desta rodada).
- **Janela primária**: W=900s, alvo +50%/stop −30%, mesma métrica (a) de H1,
  **Δ=32s fixo (rev. 4: 30s + 2s de atraso de detecção assumido — distinto
  do Δ=30s de H1, que não tem esse componente porque mede atraso real do
  motor ao vivo)**.
- **Suporte mínimo**: n>=30 pares primários (Δ=32s fixo).
- **PASS exige todos**: os mesmos 3 itens de H1 (edge >=10pp no Δ primário de
  H2, 32s; EV líquido>0 e PF>1 sob a melhor das 6 saídas; sustenta no holdout
  de 30% E na confirmação histórica selada — ver "Item (c)").
- **FAIL**: mesmos critérios de H1.
- **INCONCLUSIVE**: suporte insuficiente, ou cobertura de preço/graduação
  abaixo de 95%.
- **Controles/placebo**: baseline pareado (F3), mesmo universo sorteado da
  regra 1 (nunca lista de tokens vivos hoje), mesma faixa de
  `idade_pos_graduacao` (20min ± tolerância), mesma atividade mínima. MFE só
  descritivo.
- **O que um PASS não prova (rev. 4, acrescenta ao de H1)**: fill real,
  latência além da simulada, execução automatizada, shadow, live (mesmo de
  H1) **e, por ser histórico**: que o motor ao vivo (`run_live_shadow_v0`)
  de fato captura este sinal em tempo real com latência <=32s — isso só o
  Passo 0 ao vivo (agora checagem de sistema, não de hipótese) e uma eventual
  coleta ao vivo futura de H2 poderiam mostrar.

## Candidatas consideradas e deixadas de fora (registro da triagem, não é descarte formal)

- **Aceleração de fluxo de compra nos primeiros segundos** (mecanismo do
  `BUY-ACCEL`/`mf_buy_event_rate_acceleration_per_s2`): deixada de fora desta
  rodada. `BUY-ACCEL` já é uma família FECHADA (FAIL como alpha, retida só
  como evidência de tail-risk) — qualquer família aqui que reusasse esse
  mecanismo contaria como hipótese nova em dado novo, exigindo OK explícito do
  operador por essa regra do work order. Na dúvida ("se usa feature de
  hipótese fechada, na dúvida deixar de fora"), não entrou nesta rodada.
- Nenhuma terceira família com evidência própria/externa limpa e não
  sobreposta a hipótese fechada foi encontrada nesta pesquisa — K=2 ficou
  abaixo do teto de 5 por falta de candidata adicional qualificada, não por
  limite artificial.

## 3. Multiplicidade e próximos passos

- Este lote julga **K = 2** hipóteses, cada uma com discovery + holdout 70/30
  + confirmação separada (rev. 4: **não mais a mesma coleta** — H1 ao vivo,
  H2 histórico selado, ver seção 1).
- **Comparações de decisão, recontadas (rev. 2)**: 2 famílias × 6 regras de
  saída (seleção da melhor em treino, no Δ primário de cada família) =
  **12 comparações**. Métrica (a) é lida uma vez por família no respectivo
  Δ primário (+2), totalizando **14 leituras que entram na decisão**. A
  grade diagnóstica (Δ∈{5,15,60,120}s, janelas 60/300/3600s, barreiras
  ±20/100/200%) é computada e reportada, mas **nenhuma delas conta para
  PASS/FAIL** — são só calibração. **Rev. 4**: a contagem de 12+2=14 não
  muda com o pivô de fonte de dado de H2 — é sobre seleção de regra/Δ por
  família, não sobre de onde vêm os trades; só o Δ primário de H2 mudou de
  valor (30s→32s, regra 4 das regras anti-viés), não o número de
  comparações.
- **Recontagem pós-remoção do veto "histórico do criador" (rev. 3, item (d)
  do operador)**: o veto removido **não participava** da contagem de 14
  leituras acima — vetos (PQ-TR, freeze authority, bundle/sniper/bump) são
  filtros de elegibilidade da amostra, não comparações de seleção de regra/Δ.
  A contagem de **12 comparações + 2 leituras de métrica (a) = 14** permanece
  exatamente a mesma. O que muda é só o número de vetos ativos: **3**, não 4
  (PQ-TR aguardando replicação, freeze authority, bundle/sniper/bump
  dependente do merge).
- Hipótese com PASS → status `PASS (aguarda replicação)` no registro →
  replicação sozinha, regra congelada, chave nova, pré-registro próprio
  (nota: a confirmação prospectiva fresca exigida pelo item (c) **já cobre**
  essa replicação — um PASS que já passou pelas duas etapas desta própria
  rodada vai direto pro Gate 2, não precisa de uma 3ª coleta redundante,
  salvo decisão em contrário do operador).
- Hipótese com FAIL/KILL → fecha. Nenhuma variação é testada de novo nesta
  amostra.
- Falha de sistema da coleta → nenhuma hipótese recebe veredito; o lote pode
  ser reaproveitado numa coleta nova sem mudança de regra.
- **Critério de morte do caminho inteiro (não só de uma família)**: se o edge
  (métrica a) some no Δ primário de cada família (30s pra H1, 32s pra H2)
  para AMBAS as famílias, o caminho manual SIG-FAST morre — automação
  continua bloqueada pelo modo atual de qualquer forma, então isso não abre
  uma porta de automação, só encerra o programa de memecoin pela regra de
  parada já registrada (nenhum caminho 2 reservado foi ocupado). A grade
  diagnóstica informa esse veredito mas não o decide isoladamente.

## 4. Proibido depois de ver dado

Mudar corte, direção, horizonte, suporte, gates ou controles; incluir ou
remover hipóteses do lote; olhar só um subgrupo; combinar as duas famílias num
score; trocar a regra de saída ou o Δ escolhidos no treino depois de ver o
holdout ou a confirmação; reabrir `BUY-ACCEL` ou qualquer outra família
fechada para "salvar" um resultado fraco; promover um valor da grade
diagnóstica (Δ≠30s pra H1, Δ≠32s pra H2) a decisório depois de ver que ele
teria passado; mudar as datas dos 2 blocos de calendário de H2 (regra 2) ou
o universo sorteado (regra 1, seed `20261008`) depois de ver qualquer dado —
inclusive depois do piloto (passo A), que só mede sistema/custo, nunca
sinal ou retorno.

## 5. Atualização do registro

Depois do resultado: uma linha por hipótese em
`docs/research-hypothesis-registry-v1-2026-10-04.md` e os contadores
atualizados, no mesmo commit que registra o resultado. Esta linha de
RASCUNHO não conta como `PRE-REGISTRADA` até o sign-off do operador.

## Perguntas abertas — todas as 6 da rev. 1 respondidas pelo operador

1. ~~Confirmar a leitura do item (c).~~ Resolvido: "os dois" (ver seção
   dedicada acima).
2. ~~Latência real / terminal.~~ Resolvido: Δ=30s e terminal 1% como
   primários provisórios, até o operador medir a latência real dele.
3. ~~Tamanho de posição.~~ Resolvido: 0,15 SOL fixo.
4. ~~Cotação SOL/USD.~~ Resolvido: desnecessária, tudo em SOL.
5. ~~Piso de cobertura / grade de X do H2.~~ Resolvido: piso=95%; H2 usa X=20min
   único (não é mais grade).
6. ~~Grade de X reduzida a valor único ou mantida como grade.~~ Resolvido:
   reduzida a valor único (20min), conforme item 5.

### Novas perguntas abertas (desta revisão, ainda sem resposta)

1. **(Rev. 4: escopo agora é só H1)** Confirmar a duração/sessões do "Plano
   de coleta (H1, ao vivo)" acima (Passo 0 de calibração, bloco 1 de 48-72h,
   janela de discovery de 5-7 dias) — são estimativas a partir de taxa de
   migração observada (dado de sistema já coletado), não medição direta de
   taxa de sinal. H2 não depende mais desta resposta.
2. ~~Métrica exata do veto "histórico do criador".~~ Resolvido (rev. 3, item
   (d) do operador, 2026-10-09): veto **REMOVIDO** da V0, não "a definir" --
   não existe definição nem histórico implementado nesta rodada. H1/H2 ficam
   com 3 vetos (PQ-TR, freeze authority, bundle/sniper/bump), não 4; a
   contagem de 14 leituras decisórias (seção "Multiplicidade") não muda.
3. ~~Checar/implementar stall guard próprio pra sessões de coleta de
   horas/dias em `run_live_shadow_v0`.~~ Resolvido (rev. 3, item (b) do
   operador, 2026-10-09): implementado -- ver parágrafo "Stall guard" acima.
4. Custo de créditos Helius da coleta contínua de dias **(H1)** — não
   confirmado, proposta é calibrar no Passo 0 antes de comprometer a janela
   de dias.

### Novas perguntas abertas (rev. 4, ainda sem resposta)

5. Os 2 blocos de calendário fixados (regra 2) rendem n>=30 sinais H2
   elegíveis no treino? Não assumido — é exatamente o que o piloto (passo A)
   mede antes do download dos blocos (passo B).
6. **Bloqueador de execução — diagnosticado nesta revisão (terceira rodada,
   Fase E), mas ainda sem N fixado.** Diagnóstico do 429 pedido pelo
   operador: confirmado que vinha da própria Helius (headers `Server:
   cloudflare`/`CF-Ray` genuínos tanto na falha quanto no sucesso seguinte)
   e não do proxy do sandbox (`status` do proxy limpo, sem
   `recentRelayFailures`) — não um bloqueio de rede do ambiente. QuickNode
   (`H2_BACKFILL_RPC_URLS`) e o endpoint público testados e saudáveis nesse
   momento (sem 403 "CONNECT tunnel failed"). Em resposta, implementado o
   método de 2 estágios com rodízio de endpoints (ver "Addendum Fase E"
   acima, `EndpointRotator` em `h2_historical_backfill_v0.py`). **Mas o
   piloto de verdade rodado com o rodízio (mesmo a 5 req/s) ainda bateu 429
   na Estágio 1 (Helius, `getTransactionsForAddress`) logo na segunda
   chamada** — a primeira chamada (dia 1 do lookback) teve sucesso (~901-
   1000 tx, 100 créditos; coerente com "alto volume" já achado em
   MOVE-FIRST-H-DISC-V0 pra esta conta), a seguinte voltou 429 e interrompeu
   a enumeração (sem ponto de retomada parcial — limitação já documentada).
   Não insisti de novo na mesma sessão (CLAUDE.md: não martelar uma chamada
   externa que já falhou) — Estágio 1 continua restrito à Helius (rodízio
   não ajuda aqui, é só pra Estágio 2) e parece ter um teto de taxa mais
   baixo que 5 req/s pra esta conta/plano, mesmo com rajadas curtas. Em
   resposta (addendum Fase E parte 2, mesma revisão): enumeração passa a
   ser por K janelas sorteadas de 10min (não mais o dia inteiro) e 429
   passa a desacelerar em vez de abortar (Retry-After, backoff até 60s,
   só aborta após ~10min sem nenhum sucesso). **N (agora K por janela)
   continua não fixado** — ainda não há um piloto completo rodado com o
   novo método; fixar K fica para a próxima tentativa, com seu resultado
   real.
7. **H1 no histórico (step C): respondido, achado NEGATIVO.** Não existe
   hoje um atalho barato equivalente ao `MIGRATION_AUTHORITY` das
   migrações. A conta `global` (PDA fixo, seed `"global"`) é só config
   (authority/fee recipient/reservas-padrão/supply/fee rates) -- não é um
   registro de tokens e, pelas fontes consultadas, é tocada também por
   trades, não só por `create`, então não isola o volume. O único método
   correto (sem viés) seria varrer o PROGRAMA bonding-curve inteiro
   (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) via
   `getTransactionsForAddress`, filtrando pelo discriminador de
   `create`/`create_v2` -- mas esse programa recebe TODA a atividade de
   trade de TODOS os tokens (criados ou não, graduados ou não), um volume
   muitas ordens de magnitude maior que o da conta de migração (terceiros
   relatam >11 milhões de criações historicamente). Dado o 429 observado
   nesta mesma sessão com uma chave que nem chegou a tentar esse volume,
   este caminho não é praticamente viável com o plano atual. **Conclusão:
   H1 histórico sem viés de sobrevivência NÃO está desbloqueado por esta
   investigação** -- precisaria de uma fonte paga/indexador de terceiros
   (Dune já descartado por exigir plano pago) ou de evidência nova. H1
   continua só ao vivo (seção 1a, inalterada); isso não afeta H2.

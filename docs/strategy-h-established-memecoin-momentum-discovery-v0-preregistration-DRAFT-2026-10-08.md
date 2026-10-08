# Opção H — Memecoins Estabelecidas, Momentum — Discovery V0 — Preregistration — DRAFT — 2026-10-08 (rev. 2)

Status: **DRAFT — sign-off PARCIAL recebido (seção 11 da rev. 1 respondida). Ainda não autoriza
backtest, consulta a outcome, ou coleta.** O operador pediu primeiro o Passo 0 (auditoria de
cobertura local) e o Passo 1 (spike de fonte histórica) antes do sign-off final sobre o protocolo
em si. Esta revisão reporta os dois passos e reescreve as seções afetadas. Nenhum backtest foi
rodado; nenhum retorno/direção foi consultado em nenhum passo abaixo.

ID no registro: `MOVE-FIRST-H-DISC-V0`. Fonte da opção: `docs/strategy-options-move-first-2026-10-07.md`,
Opção H, revisão 3.

## Sign-off recebido (respostas às pendências da rev. 1)

1. Pisos de volume US$5k/US$20k ficam como estavam.
2. **Backfill AUTORIZADO** como tarefa de engenharia separada, read-only, **antes** do discovery
   (corrige a rev. 1, que tratava backfill como fora de escopo — ver seção 1 revisada).
3. Tamanho de posição simulada: US$25.

Erro da rev. 1, corrigido: "captura própria desde 2026-08-20" vinha da data do primeiro commit no
`git log`, não de cobertura real de dado. Os coletores rodam em sessões limitadas, não 24/7. Isso
foi auditado no Passo 0 abaixo, não só corrigido de palavra.

---

## Passo 0 — Auditoria de cobertura local (read-only, SQLite, sem rede) — REPORTADO

Script: `benchmarks/move_first_h_coverage_audit_v0/audit.py` (`--self-check` cobre a lógica;
reusável para auditar qualquer `data/copytrader.db`, inclusive o seu, fora desta sandbox).
Resultado rodado contra o `data/copytrader.db` **desta sandbox** (não é a base de produção do
operador — ver aviso abaixo):

```
janela de captura observada: 2026-09-28 .. 2026-09-29   (≈ 25 horas, não 7 semanas)
pools graduados (>=1 trade lifecycle venue=pumpswap): 84
pools com graduação observada na própria janela (pump E pumpswap): 15
linhas de trade pumpswap: 416.631 (com price_usd: 0, com notional_usd: 0)
pools com pelo menos 1 dia com preço E volume: 0
pools com série diária contínua (preço+volume): 0
% contínuo sobre graduados: 0,0%
```

**Dois achados, não um:**

1. **A janela real desta sandbox é ~1 dia, não 7 semanas.** Confirma exatamente o seu ponto: a
   data do `git log` é a idade do *código*, não prova de cobertura de *dado*. Este `.db` local é
   gitignored e específico desta sessão de container — não é a base de produção do operador, que
   roda em sessões limitadas no computador dele. Esta auditoria precisa ser repetida lá para saber
   a cobertura real.
2. **Achado estrutural, mais sério que o tamanho da janela: `price_usd` e `notional_usd` são
   `None` em 100% das linhas de `market_trade_observations` para `venue='pumpswap'` (e também
   para `venue='pump'`), em qualquer janela.** Não é falta de dado por pouco tempo de captura — é
   o pipeline de ingestão que grava assim por desenho: `src/pumpswap_stream.py:501` e
   `src/pumpswap_normalized_persistence.py:98` escrevem `price_usd=None` explicitamente. Preço
   causal hoje só existe em `causal_quote_observations` (1.049 linhas nesta sandbox), que é
   disparado por episódio de rota de pesquisa (Jupiter quote), não é uma série diária contínua por
   pool. **Conclusão honesta: mesmo com 7 semanas reais de captura rodando 24/7, a captura própria
   deste repositório, como está hoje, não dá uma série diária de preço+volume por pool — dá só
   identidade/timing de graduação.** Isso muda a seção 1 abaixo: captura própria nunca poderia ter
   sido a fonte de preço/volume da seção 2-7; só pode ser (no melhor caso) fonte da *lista* de
   quais tokens graduaram e quando, não dos seus preços diários.

---

## Passo 1 — Spike de fonte histórica (desk research + 2 testes mecânicos ao vivo, sem olhar retorno)

**Enumeração de migrações (universo "todas desde o lançamento do PumpSwap, incluindo mortas")**

PumpSwap lançou em **2025-03-20** (The Block, data mais confiável encontrada; memo anterior tinha
19/20 em conflito entre fontes — 20/03 é a data citada pela cobertura mais específica). Comparação
de fontes para enumerar `create_pool` desde então:

| Fonte | Completude | Custo | Observação |
|---|---|---|---|
| **Helius `getTransactionsForAddress`** no programa PumpSwap (`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`), `sortOrder=asc` | Completa por construção (é o próprio ledger) | Credits Helius — fontes conflitam entre si sobre o preço exato (10 créditos/100 tx vs 100 créditos/request); ordem de grandeza: varrer ~1M tx custaria ~1-10% de um plano Developer (10M créditos/mês) | **Já temos `SOLANA_RPC_URL` configurado neste repo** (confirmei: não vazio). Precisa decodificar `create_pool` no client — **já temos o decoder Carbon-based de PumpSwap** usado em `benchmarks/carbon_decoder_parity_v1` e `live_shadow.py` — reuso direto, não é código novo do zero. Sem filtro server-side por nome de instrução; decodificação é client-side. |
| **Solscan** (filtro de instrução `create_pool` na página do programa) | Provavelmente completa (indexador dedicado) | Não confirmado nesta sessão (não testado ao vivo) | Mais simples que Helius se a API pública permitir o mesmo filtro da UI — não verificado. |
| **Bitquery** (API PumpSwap dedicada) | Marketing próprio diz servir "dado histórico de PumpSwap mais antigo que ~30 dias" — ou seja, se vende exatamente para este problema | Pago, valor não confirmado nesta sessão | Turnkey, mas terceiro pago; não testado. |
| **Dune** | Incerta para a era PumpSwap — só confirmei uma query comunitária cobrindo a era pré-PumpSwap (graduação direto pra Raydium); tabelas/colunas exatas para `create_pool` do PumpSwap não confirmadas | Grátis (camada free) | Precisaria de engenharia de query própria e validação contra amostra conhecida antes de confiar. |

**Recomendação deste spike**: Helius via `SOLANA_RPC_URL` já configurado + decoder Carbon já
existente é a opção que reusa mais infraestrutura já paga/construída (ladder de "reusar antes de
construir"). Bitquery é o fallback turnkey se o custo de engenharia do decode client-side não
valer a pena. Dune fica descartado para esta tarefa até alguém confirmar as tabelas certas.

**Preço/volume diário por pool (depois de ter a lista de pools)**

- **GeckoTerminal `/ohlcv/day`**: testado ao vivo nesta sessão (ver abaixo), sem chave. Limite
  documentado: até 6 meses por chamada, mais que isso exige plano pago (Analyst+); profundidade
  depende de quando o GeckoTerminal passou a rastrear aquele pool especificamente, não da idade do
  pool.
- **Birdeye / Solana Tracker** (já integrados em `src/discovery/`): **não testáveis nesta sandbox**
  — `BIRDEYE_API_KEY` e `SOLANA_TRACKER_API_KEY` estão **vazios** no `.env` local. Pela
  documentação (não testada ao vivo), os endpoints de listagem de ambos são só forward-looking
  (~3 dias), não servem pra enumerar migrações antigas — mas o endpoint de OHLCV histórico do
  Birdeye pode servir pra preço/volume uma vez que já se tenha o endereço do pool; não verificado
  aqui por falta de chave.

**Dois testes mecânicos reais, feitos nesta sessão (sem ler nenhum valor de preço/retorno, só
estrutura):**

1. Peguei um `token_mint` real do `data/copytrader.db` desta sandbox
   (`MsV1fcepUo4xAN5jC6vv47X6dn1pkDwEaVbC25Upump`) e chamei
   `GET /networks/solana/tokens/{mint}/pools` (API pública do GeckoTerminal, sem chave). **Resultado:
   encontrou os 2 pools do token** (PumpSwap e pump.fun) — confirma que o GeckoTerminal indexa até
   token pequeno/recente, não só os grandes.
2. Chamei `GET /networks/solana/pools/{pool}/ohlcv/day` pro pool PumpSwap encontrado acima.
   **Resultado: só 3 candles diários**, do dia seguinte à primeira observação nossa
   (2026-09-29) até 2026-10-04 — **um gap de 4 dias até hoje (2026-10-08)**. Não sei, sem olhar o
   valor, se o gap é o pool secando (sem trade = sem candle) ou um limite da API gratuita para
   pool de baixo volume — **isso é uma lacuna real de completude, não resolvida por esta sessão**,
   e é exatamente o tipo de coisa que o teste de sobrevivência da seção seguinte precisaria
   diferenciar.

**Teste de sobrevivência com amostra de 50 migrações antigas: NÃO EXECUTADO.** Motivo honesto, não
contornado: pra testar 50 migrações *antigas* (~2025) preciso primeiro de uma lista de endereços
de pool antigos — e esse é exatamente o problema de enumeração que este Passo 1 está avaliando
(circular: não dá pra testar sobrevivência de retenção de dado antes de resolver a enumeração).
Com Birdeye/SolanaTracker sem chave nesta sandbox e sem a enumeração via Helius ainda construída,
o teste de 50 fica como **primeiro item da tarefa de engenharia do backfill** (autorizada no
sign-off), não algo que esta sessão de pesquisa resolve sozinha.

**Proveniência honesta (desenho para quando o backfill for implementado, não implementado ainda):**
cada linha backfilled vai pra uma tabela própria, **nunca** para `market_trade_observations`/
`market_lifecycle_observations` nem usando `observed_at` (invariante 11 — "historical data may not
receive fake historical `observed_at`"). Campos mínimos: `source` (ex.: `helius_backfill_v0`),
`fetched_at` (quando ESTE backfill realmente rodou, não uma data histórica), `as_of_date` (a data
histórica que o dado descreve). Nenhum campo causal existente é reaproveitado para isso.

**Fee de criador do PumpSwap — verificado contra doc oficial, não blog de terceiro.** Fonte:
`pump.fun/docs/fees` (atualizado 2026-05-20) e `github.com/pump-fun/pump-public-docs` (`FEE_PROGRAM_README.md`)
— confirmei que ambos existem e tratam disso. "Dynamic Fees V1"/"Project Ascend" aplica-se a
**todos** os pools PumpSwap (novos e existentes), com taxa de criador por faixa de market cap em
**SOL** (não USD). **O que está confirmado com confiança**: a parcela de 0,20% pros LPs não muda
com o Dynamic Fees V1 (a doc oficial diz explicitamente que as alocações de protocolo/LP
"continuam as mesmas" na migração para o novo esquema). **O que NÃO está confirmado com confiança
suficiente pra virar número fixo**: os percentuais exatos de criador por faixa (fontes secundárias
discordam entre si sobre os números — algumas reportam em USD, a doc oficial usa SOL, e uma delas
tem uma inconsistência aritmética óbvia). Por isso, a seção 7 revisada abaixo trata a fee de
criador como **regra** (ler a faixa atual da pool nas thresholds de `pump-public-docs` no momento
de `t`), não como número fixo — mesmo padrão já usado pro preço do SOL/ATA no Gate 2 do PQ-TR.

---

## 1. Fonte do universo (revisada — backfill autorizado, não mais "fora de escopo")

Com o achado estrutural do Passo 0 (captura própria nunca teve preço/volume, em nenhuma janela) e
a autorização do sign-off, a fonte fica assim:

1. **Lista de migrações (enumeração)**: backfill via Helius `getTransactionsForAddress` sobre o
   programa PumpSwap, decodificando `create_pool` com o decoder Carbon já existente no repo —
   tarefa de engenharia separada, read-only, **a fazer antes do discovery rodar** (autorizada,
   não executada ainda).
2. **Preço/volume diário por pool**: GeckoTerminal `/ohlcv/day` (testado, funciona, sem chave) como
   fonte primária; gaps de cobertura (como o de 4 dias encontrado no teste mecânico) tratados pela
   regra (d) da seção 8 — mas só depois de confirmar que o gap é o pool secando, não a API
   falhando (ver nota na seção 8).
3. **Captura própria desta repo**: rebaixada a fonte auxiliar/cruzamento (pode confirmar que um
   token realmente existiu e graduou numa data, já que tem `source_provider`/`event_key` causal
   próprio), nunca fonte de preço.

## 2. Universo ("estabelecida", critérios candidatos — inalterados do sign-off)

Um token entra no universo de uma data de rebalanceamento `t` se, **usando só dado anterior a `t`**:

1. já graduou da bonding curve para PumpSwap há **>= 7 dias de calendário** antes de `t`;
2. teve volume 24h >= **US$5.000** (tier baixo) ou **US$20.000** (tier alto, comparação separada —
   ver seção 5) em pelo menos 5 dos 7 dias de calendário imediatamente antes de `t`;
3. tem preço resolvível em `t` **E** liquidez resolvível em `t+7` — se não tiver em `t+7`, não é
   excluído, vira retorno -100% (regra (d) nova, seção 8).

## 3. Sinal (inalterado — só momentum na V0)

Feature única: retorno acumulado nos **N dias anteriores a `t`**, mesma lógica de
Liu/Tsyvinski/Wu (JF 2022) — ordenação cruzada semanal, quintil de maior momentum. Long-only.

## 4. Rótulo e horizonte (inalterado)

Retorno forward de **7 dias de calendário** a partir de `t`.

## 5. Comparações desta descoberta (inalterado — 4 combinações pré-registradas)

| Lookback (N dias) | Piso de volume 24h |
|---|---|
| 7 | US$5.000 |
| 7 | US$20.000 |
| 14 | US$5.000 |
| 14 | US$20.000 |

## 6. Suporte mínimo em semanas (regra b — nova, substitui o critério antigo de só token-semana)

- **Treino**: >= **15 datas de rebalanceamento** (semanas) com universo válido.
- **Retentor**: >= **6 datas de rebalanceamento**.
- **Além disso**, suporte mínimo em volume: **n >= 30 observações token-semana** no quintil de topo,
  somando treino+retentor (mantido da rev. 1).
- **Data pulada, regra fixada agora**: qualquer data de rebalanceamento cujo universo (seção 2)
  tenha **menos de 25 tokens** é **pulada** inteira (não conta nem pro treino nem pro retentor) —
  decidido antes de rodar, não depois de ver quantos tokens cada data teria.
- Split treino/retentor permanece 70/30 por calendário (seção 7), mas agora medido em **datas de
  rebalanceamento válidas** (pós-exclusão), não em dias corridos — correção direta do seu ponto: a
  unidade independente é a semana, não o token-semana, e token-semanas da mesma semana não são
  observações independentes entre si.

## 7. Split temporal (mantido 70/30, unidade corrigida para semana — regra a, bloco de confirmação selado)

Mesma disciplina do E11 (calendário, não aleatório), unidade agora é **data de rebalanceamento
válida** (seção 6), não dia corrido. **Regra (a), nova**: antes do discovery rodar, as **~20
semanas mais recentes** do backfill (contagem exata depende de quantas semanas o backfill cobrir —
"mais recentes" fixado por data de calendário, não por contagem de observações) são **seladas como
bloco de confirmação**: hash do conteúdo (lista de episódios + valores) commitado nesta revisão
*antes* de qualquer código de discovery rodar, e esse bloco **nunca é lido pelo código do
discovery** — só pelo código de `MOVE-FIRST-H-CONF-V0` (a escrever depois), usando a mesma regra
congelada que o discovery escolher aqui. O split 70/30 do discovery em si acontece **dentro** do
restante do backfill (a parte não selada), não sobre o bloco de confirmação.

## 8. Custo por perna, escalado por liquidez (regra e — revisada)

```
reserva_de_um_lado_usd ≈ liquidez_total_do_pool_usd / 2
impacto_pct ≈ (tamanho_posicao_usd / (2 × reserva_de_um_lado_usd)) × 100
custo_ida_volta_pct ≈ 2 × impacto_pct
                     + 0,50%                         # 0,25% por perna × 2 pernas (fee de swap, LP 0,20% + protocolo, confirmado estável)
                     + fee_de_criador(t)              # REGRA, não número: ler a faixa atual de pump-public-docs/FEE_PROGRAM_README.md pro market cap do pool em t
                     + rede/priority                   # mesma leitura ao vivo já usada no Gate 2 do PQ-TR
                     + ATA/SOL                          # mesma regra do Gate 2 do PQ-TR (SIMD-0437, preço do SOL via Jupiter Price API)
```

Sweep 1x/2x mantido, mesma disciplina do Gate 2.

**Nota operacional sobre a regra (d)** (token sem preço/liquidez em `t+7` = -100%, nunca excluído):
antes de aplicar -100%, o discovery precisa diferenciar "o pool realmente secou" de "a fonte de
preço (GeckoTerminal) tem um gap que não é morte real" — o teste mecânico desta sessão (3 candles,
gap de 4 dias) mostra que esse gap existe e sua causa não foi determinada aqui. Proposta (pendente
de sign-off explícito, não decidida por mim): tratar como morte real (-100%) só se **nenhuma** das
fontes disponíveis (GeckoTerminal **e** a captura/cruzamento próprio da seção 1.3) mostrar
liquidez em `t+7`; se só uma fonte tiver gap e a outra confirmar liquidez viva, usar a que confirma
liquidez. Se nenhuma fonte cobrir `t+7` de forma confiável, essa observação individual fica como
`missing_source`, contada separadamente do -100% — mantém "missingness stays explicit" (invariante
6) em vez de confundir ausência de dado com morte confirmada.

## 9. Candidato exige lucro absoluto (regra c — nova, substitui "concorda em sinal" como critério único)

Uma combinação (das 4 da seção 5) só é candidata se, **no treino**:

- retorno semanal líquido de custo (sweep 1x, seção 8) do **quintil de topo** tiver **média E
  mediana > 0**.

E, **no retentor**:

- a **média líquida** do quintil de topo tem o **mesmo sinal** (positivo) da média do treino — não
  precisa bater em magnitude.

**Spread topo-fundo e retorno do universo equal-weight são diagnóstico, não critério de escolha**
— reportados no resultado, mas não decidem PASS/candidato.

## 10. Critério de escolha entre as 4 combinações (regra f — nova, fixada antes de rodar)

Entre as combinações que passam a regra 9 no treino: escolhe a de **maior média líquida do
quintil de topo**. Empate: **lookback menor** (7 dias antes de 14). Zero combinações passando a
regra 9 no treino → `INCONCLUSIVE_NO_CANDIDATE`, sem promover nenhuma.

## 11. Classificação final

- `INCONCLUSIVE_SAMPLE_NO_EXTENSION`: menos de 15 datas válidas no treino ou menos de 6 no
  retentor, ou n<30 token-semanas — sem esticar a janela nem importar mais backfill no meio do
  protocolo.
- `DISCOVERY_MOVE_FIRST_H_V0_CANDIDATE`: exatamente 1 combinação passa a regra 9 no treino E no
  retentor (escolhida pela regra 10 em caso de múltiplas) — vai para `MOVE-FIRST-H-CONF-V0` sobre
  o bloco de confirmação selado (seção 7).
- `INCONCLUSIVE_NO_CANDIDATE`: nenhuma combinação passa a regra 9 no treino, ou nenhuma mantém o
  sinal no retentor.

## 12. Risco de transferência (inalterado)

A evidência acadêmica mais forte citada no memo para H (Liu & Tsyvinski, RFS 2021; Liu/Tsyvinski/Wu,
JF 2022) vem de BTC/XRP/ETH ou do top-1500 de criptomoedas por market cap, **2011-2018**, com
rebalanceamento semanal — população, era de mercado e microestrutura diferentes de memecoins
Solana "estabelecidas" em 2026. Mecanismo é o mesmo tipo de efeito; transferência não é automática.

## 13. Proibições explícitas desta V0 (inalterado, mais uma)

- não compara com nenhuma hipótese de minuto-inicial;
- não troca lookback/piso de volume depois de ver a direção de nenhuma das 4 combinações;
- não estende a janela de captura além do que o backfill autorizado trouxer, no meio do protocolo;
- não promove mais de 1 combinação candidata;
- não lê o bloco de confirmação selado (seção 7) com código de discovery;
- não abre execução nem toca em capital.

## 14. Pendências para o sign-off final (atualizadas)

1. A nota operacional da seção 8 (diferenciar morte real de gap de fonte) — confirmar a proposta
   ou decidir outra.
2. Quantas semanas exatas selar como bloco de confirmação (seção 7 propõe "~20 semanas mais
   recentes" — número exato depende do que o backfill trouxer).
3. Autorização para a tarefa de engenharia do backfill em si rodar (ler histórico via Helius +
   decoder Carbon existente) — read-only, sem tocar capital, mas é a primeira coisa a executar de
   fato depois desta revisão.

Nenhum backtest, nenhuma consulta a outcome, nenhum backfill foi executado nesta revisão — só a
auditoria local (Passo 0) e os 2 testes mecânicos read-only do Passo 1 (estrutura, não retorno).

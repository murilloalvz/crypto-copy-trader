# Opção H — Memecoins Estabelecidas, Momentum — Discovery V0 — Preregistration — DRAFT — 2026-10-08 (rev. 3)

Status: **DRAFT — sign-off da rev. 2 recebido, com 3 correções. Ainda NÃO autoriza discovery,
backtest, consulta a outcome ou execução do backfill.** Esta revisão reescreve a regra de
morte-vs-gap (pendência 1), fixa o tamanho exato do bloco selado (pendência 2) e corrige o modelo
de custo (seção 8), além de reportar cobertura/custo da ordem de backfill da pendência 3. Nenhum
retorno foi consultado em nenhum passo abaixo — só estrutura, cobertura e custo.

ID no registro: `MOVE-FIRST-H-DISC-V0`. Fonte da opção: `docs/strategy-options-move-first-2026-10-07.md`
(Opção H) e `docs/research-hypothesis-registry-v1-2026-10-04.md`.

---

## Pendência 1 — regra de morte vs gap de fonte (substitui a nota operacional da rev. 2)

Base física: LP de pool migrado é **queimado** — sem swap novo, as reservas do pool não mudam, e
portanto o preço também não muda (produto constante não se move sem troca). "Sem candle" não é
"preço indeterminado"; é informação.

**Regra, nessa ordem:**

1. Sem candle de preço em `t+7` → checar assinaturas do **endereço do pool** via Helius no
   intervalo entre o último candle conhecido e `t+7`.
2. **Zero swaps nesse intervalo** → preço(t+7) = **último close conhecido**, exato (não
   aproximação) — decorre direto da física do AMM, não de uma suposição.
3. **Houve swaps, mas a fonte de preço não tem candle** → `missing_source` — contado
   explicitamente, separado de qualquer retorno calculado (invariante 6, missingness explícita).
4. `missing_source` acima de **5% das observações token-semana do quintil de topo** (numa
   combinação) → essa combinação vira `INCONCLUSIVE_DATA`, não entra na escolha da seção 10.
5. **-100% só quando o preço é de fato ~0** (confirmado por alguma fonte, não inferido da
   ausência de candle).
6. **Correção à rev. 2**: removida a frase "captura própria rebaixada a fonte auxiliar/cruzamento"
   — **errada**. A captura causal própria desta repo (quando rodando) não cobre o período
   histórico que este backfill precisa alcançar (2025-03-20 em diante); não serve de segunda
   fonte pra nada aqui. As únicas fontes possíveis de cruzamento são a checagem de assinaturas do
   próprio pool (passo 1 acima) e, se necessário, uma segunda fonte comercial (seção "Pendência 3b").

## Pendência 2 — tamanho exato do bloco selado e mínimo utilizável

- **Bloco de confirmação selado**: **12 semanas fixas**, as mais recentes disponíveis no backfill
  no momento do selamento. Hash do conteúdo (lista de episódios + valores) commitado antes de
  qualquer código de discovery rodar; o bloco nunca é lido pelo discovery.
- **Embargo**: **1 semana**. O último `t` do discovery, mais o horizonte de 7 dias
  (`t_último_discovery + 7d`), precisa terminar **antes** do primeiro `t` do bloco selado — sem
  overlap entre o rótulo forward de uma observação de discovery e o início do bloco de confirmação.
- **Mínimo total utilizável, antes de calcular qualquer retorno** (contagem só de cobertura):

  ```
  2 (lookback, pra ter N dias de momentum antes do 1º t)
  + 15 (treino)
  + 6 (retentor)
  + 1 (embargo)
  + 12 (bloco selado)
  = 36 semanas
  ```

  **Abaixo de 36 semanas de histórico utilizável → `INCONCLUSIVE_SAMPLE` antes de qualquer cálculo
  de retorno.** Esta contagem é feita primeiro, com os dados de cobertura do backfill (Pendência
  3), antes de decidir se vale a pena sequer montar o pipeline de retorno.

---

## Pendência 3 — backfill, read-only, nesta ordem — reportado até onde esta sessão alcança

### (a) Checagem no Dune — achado, não executado (sem conta Dune nesta sessão)

**Bloqueio confirmado primeiro**: GeckoTerminal grátis só dá OHLCV diário dos **últimos ~6 meses**
(~26 semanas) por chamada — não cobre as 36 semanas mínimas por si só, mesmo que o pool exista
desde o início do PumpSwap.

Dune tem a tabela curada `dex_solana.trades` (`docs.dune.com/data-catalog/curated/dex-trades/solana`),
particionada por `block_month`, com coluna `project` que identifica a exchange, e `trade_source`
que distingue troca direta de troca roteada (ex.: via Jupiter). **Não confirmei o literal exato**
que o Dune usa pra PumpSwap na coluna `project` (candidato mais provável: `'pumpswap'`, minúsculo
— não verificado). Se confirmado, esta tabela resolveria enumeração **e** OHLCV-equivalente
(volume/contagem de trade por dia) juntos, de graça, exatamente como você propôs.

**Não executei a query** — preciso de uma conta Dune (não tenho credencial nesta sandbox). Query
pronta pra rodar, em duas etapas (a 1ª descobre o literal certo, a 2ª usa-o):

```sql
-- 1) descobrir o literal exato do project para PumpSwap
SELECT project, version, version_name, COUNT(*) AS trades
FROM dex_solana.trades
WHERE block_month >= DATE_TRUNC('month', current_date - INTERVAL '30' day)
  AND block_date >= current_date - INTERVAL '30' day
  AND LOWER(project) LIKE '%pump%'
GROUP BY 1, 2, 3
ORDER BY 4 DESC;

-- 2) volume/trade diário, usando o literal confirmado no passo 1
SELECT block_date, COUNT(*) AS trades, SUM(amount_usd) AS volume_usd
FROM dex_solana.trades
WHERE project = '<literal confirmado>'
  AND block_month >= DATE_TRUNC('month', '2025-03-20'::date)
GROUP BY 1 ORDER BY 1;
```

**Comparação contra 20 pools conhecidos (pedida por você)**: não fiz ainda — precisaria rodar a
query acima primeiro. Proponho usar os 84 tokens graduados já vistos no `data/copytrader.db` desta
sandbox (recentes, 2026-09-28/29) como a amostra de verificação mais barata disponível — não são
"antigos" (não testam profundidade histórica), mas testam se o Dune cobre pelo menos o que a gente
já sabe que existiu. Pendente de conta Dune pra executar.

### (b) Custo CoinGecko Analyst (decisão sua) — pesquisado

- **US$129/mês** (cobrança mensal) ou **US$103,20/mês** (cobrança anual, US$1.238,40/ano) —
  fonte: página oficial de preços da CoinGecko API.
- 500.000 créditos/mês, 500 requisições/min, overage US$250 por 500k chamadas extras.
- Dados on-chain (pool OHLCV, o que precisamos) incluídos nesse plano, 1 crédito/requisição.
- Profundidade histórica on-chain: confirmei (sessão anterior, changelog oficial da CoinGecko)
  que o endpoint de OHLCV on-chain foi estendido pra cobrir **desde setembro de 2021**, dependendo
  de quando aquele pool específico passou a ser rastreado — não é garantia de profundidade pra
  todo pool, é o teto do que é possível.
- Decisão de assinar ou não: **sua**, não decidida aqui.

### (c) Enumeração via Helius — achado e **verificado ao vivo nesta sessão**, com ressalva honesta

**Correção ao seu ponto**: você está certo — não dá pra varrer o programa PumpSwap inteiro (são
todos os swaps, não só criações de pool). A pesquisa achou um candidato a "conta de migração do
pump.fun": `39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg` (citado por um guia de terceiro, não por
doc oficial — precisava de verificação antes de confiar).

**Verifiquei ao vivo**, via o `SOLANA_RPC_URL` já configurado neste repo (`getSignaturesForAddress`
+ `getTransaction`, read-only, sem olhar preço nenhum): puxei 20 assinaturas recentes dessa conta
e decodifiquei os logs de 5 transações completas. **Resultado: 5 de 5 (100% da amostra) são a
instrução `MigrateV2`** do programa bonding-curve (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`):

- 3 de 5 terminam em `"Bonding curve already migrated"` — chamada redundante/retry, não chega a
  criar pool (explica por que nem toda tx desta conta invoca o PumpSwap diretamente — não é uma
  conta "suja" com outro uso, é a mesma instrução de migração batendo numa curva já migrada).
- 2 de 5 completam a migração de verdade, com a sequência exata esperada nos logs: `MigrateV2` →
  ... → **`Instruction: CreatePool`** (dentro do programa PumpSwap, confirma o discriminador de
  `create_pool` que a pesquisa achou) → `MintTo` → `InitBoost` (o modo BOOST de reciclagem de
  liquidez morta, achado lateral confirmando que o PumpSwap atual já embute essa feature na
  própria migração).

**Ressalva honesta**: n=5 é uma amostra pequena pra confirmar "100%" com confiança estatística — é
suficiente pra validar que o candidato é a conta certa (consistente demais pra ser coincidência:
mesma instrução 5/5 vezes), não suficiente pra garantir que não existe nenhum outro tipo de tx
dessa conta em 19 meses de histórico (2025-03-20 até hoje). Antes do backfill rodar de verdade,
puxar uma amostra maior (50-100, espalhada no tempo, não só as 20 mais recentes) é o passo certo —
não feito aqui.

### (d) Teste de sobrevivência com 50 migrações antigas — NÃO executado

Depende de (a) ou (c) já estarem rodando de verdade (enumeração real de migrações antigas, não só
a conta verificada). Próximo passo depois de (a)/(c) serem decididos e executados, não desta
sessão.

---

## Seção 8 revisada — custo por perna (3 correções)

**Correção 1 — fórmula de impacto estava errada (dava a metade):**

```
reserva_de_um_lado_usd ≈ liquidez_total_do_pool_usd / 2
impacto_pct ≈ (tamanho_posicao_usd / reserva_de_um_lado_usd) × 100      # = 2× tamanho / liquidez_total × 100
```

(a versão da rev. 2 tinha um `× 2` extra no denominador, subestimando o impacto pela metade.)

**Correção 2 — liquidez em `t` não vem do OHLCV; precisa ser derivada:**

```
k ≈ reserva_SOL_inicial × reserva_token_inicial     # das reservas no instante do CreatePool (decodificável, confirmado seção (c))
reserva_SOL(t) ≈ sqrt(k × preço_em_SOL_por_token(t))
```

`k` fixo desde o `CreatePool` (não atualizado por depósitos de LP de terceiros depois) é
**conservador**: LP extra de terceiros só aumenta o `k` real, nunca diminui o `k` do piso
queimado — usar o `k` inicial subestima a reserva real quando há LP extra, o que **sobre-estima**
o impacto de preço (direção seguramente conservadora para um teste de custo).

**Correção 3 — fee de criador por perna, e nada de "leitura ao vivo" num backtest histórico:**

```
custo_ida_volta_pct ≈ 2 × impacto_pct
                     + 0,25%(entrada, fee de swap) + 0,25%(saída, fee de swap)
                     + fee_criador(mcap_em_t)       # entrada — faixa oficial pump-public-docs/FEE_PROGRAM_README.md pro market cap EM t
                     + fee_criador(mcap_em_t+7)      # saída — faixa pro market cap EM t+7, pode ser outra faixa
                     + rede_e_priority_constante      # fixada agora nesta revisão, não lida ao vivo — ver abaixo
```

**Por que nada de "ler ao vivo"**: a disciplina "regra, não número" do Gate 2 do PQ-TR fazia
sentido pra um contexto prospectivo (lê o valor real no momento da decisão real). Aqui é um
**backtest histórico** — não existe "agora" na data `t` de 2025 ou 2026 que este backtest
processa; o que existe é o registro histórico. Cada custo precisa vir de um dos dois lugares:

1. **O regime histórico vigente na data `t`** (não o regime de hoje). Já encontrei, sem fechar a
   lista completa, pelo menos 2 cortes de regime conhecidos no período do backfill (2025-03-20 até
   hoje): (i) lançamento do PumpSwap sem fee de criador — fee de criador introduzida só em
   2025-05-13 (fonte: The Block, "PumpSwap revenue-tokens", já citada no memo); (ii) "Dynamic Fees
   V1"/"Project Ascend" (faixas por market cap em SOL, 0,30% até 420 SOL, sobe conforme o mcap
   cresce, piso de 0,05% acima de ~98.240 SOL) — doc oficial `pump.fun/docs/fees` datada
   "Last Updated 2026-05-20", mas não confirmei a data exata de ativação (pode ter sido antes de
   20/05, essa é só a data da doc). **Pendente**: fechar a lista completa de regimes e datas de
   corte antes do backfill calcular custo de qualquer data — não resolvido nesta sessão, fica
   como item de engenharia da própria tarefa de backfill.
2. **Preço histórico do SOL em `t`**: usar o close diário do pool canônico SOL/USDC no
   GeckoTerminal (mesmo endpoint já testado ao vivo nesta sessão) pra aquela data histórica
   específica — não o preço de agora.
3. **Rede/priority — constante conservadora, fixada agora, não decidida por mim sozinho**:
   proposta (pendente de confirmação sua): **US$0,02 por perna** (US$0,04 ida+volta) — fee base
   Solana (5.000 lamports/assinatura, ~US$0,001 ao preço atual do SOL, desprezível) mais uma
   margem de priority fee deliberadamente alta pra ser conservadora em período de congestionamento.
   Pra uma posição de US$25, isso é ~0,16% ida+volta — pequeno comparado ao impacto de preço
   esperado pra pools pequenos, mas não zero. **Não decidido unilateralmente — fica para
   confirmação no sign-off**, mesmo padrão dos outros números desta seção.

Sweep 1x/2x mantido sobre o custo total, mesma disciplina do Gate 2.

---

## Resumo do que mudou nesta revisão (demais seções do protocolo ficam como na rev. 2, exceto onde listado)

- Regra de morte-vs-gap: substituída pela física do AMM (Pendência 1 acima) — mais simples e mais
  correta que a proposta da rev. 2, que exigia "duas fontes confirmando" sem necessidade.
  `missing_source > 5%` numa combinação vira `INCONCLUSIVE_DATA` pra aquela combinação.
- Bloco selado: exatamente 12 semanas + 1 semana de embargo (rev. 2 tinha "~20 semanas", não
  fixado). Mínimo total utilizável: 36 semanas, checado antes de qualquer retorno.
- Seção 8 (custo): 3 correções — fórmula de impacto, derivação de liquidez via `k` do
  `CreatePool`, fee de criador por perna com regime histórico citado por fonte (não leitura ao
  vivo), rede/priority como constante proposta e pendente de confirmação.
- "Captura própria como cruzamento" removido — não cobre o período do backfill.

## Pendências para o sign-off final (atualizadas desta revisão)

1. Confirmar (ou ajustar) a constante de rede/priority proposta (US$0,02/perna).
2. Fechar a lista completa de regimes de fee históricos do PumpSwap (datas de corte + fonte por
   regime) — trabalho de engenharia ainda não feito, não só uma confirmação rápida.
3. Decidir entre (a) Dune [grátis, não confirmado se cobre PumpSwap] e (b) CoinGecko Analyst
   [US$103-129/mês, confirmado que cobre, mas pago] como fonte de preço/volume histórico — ou
   autorizar abrir uma conta Dune primeiro pra testar (a) antes de decidir sobre (b).
4. Autorizar uma amostra maior (50-100 assinaturas, espalhada no tempo) da conta de migração
   `39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg` antes de confiar nela como filtro único do
   backfill.

Nenhum backtest, discovery, consulta a outcome ou backfill real foi executado nesta revisão — só
a verificação ao vivo da conta de migração (passo (c), read-only, sem preço) e pesquisa/custo.

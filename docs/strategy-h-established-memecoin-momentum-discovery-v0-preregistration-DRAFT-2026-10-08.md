# Opção H — Memecoins Estabelecidas, Momentum — Discovery V0 — Preregistration — DRAFT — 2026-10-08 (rev. 5, autocontida)

Status: **DRAFT — redesenho de janela recebido, decidido ANTES de qualquer dado. Ainda NÃO
autoriza discovery, backtest, consulta a outcome, backfill ou qualquer pagamento.** Esta revisão
é **autocontida** (protocolo inteiro num só texto) e substitui a estratégia de fonte de dado: em
vez de um backfill profundo até 2025-03-20, usa a janela grátis rolante do GeckoTerminal pro
discovery e um bloco pago, selado e cronologicamente **anterior**, só pra confirmação. Nenhum
retorno foi consultado em nenhum passo — só estrutura, cobertura, custo e pesquisa documental.

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
4. **Enumeração**: só migrações dos **últimos ~7 meses** (janela de discovery + lookback, não os
   19 meses desde o lançamento do PumpSwap). Via Helius, com amostragem por tempo, deduplicando
   por pool — não uma caminhada completa de assinaturas (a tentativa de caminhada completa desde
   2025-03 nesta sessão bateu no limite de 1.500.000 assinaturas sem sair dos últimos ~2 meses;
   ver "Amostragem da conta de migração" abaixo). ~7 meses é uma fração pequena o bastante desse
   volume pra ser tratável dentro de uma sessão.

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

**Reservas em `t` — correção desta revisão: pelo evento de swap, não só pela fórmula de `k`.**
Revisões anteriores propunham `k` fixo desde o `CreatePool` e derivar a reserva de `t` por
`sqrt(k × preço(t))`. Essa é uma aproximação que assume ausência de LP de terceiros entre a
migração e `t`. Mais correto, e mais barato agora que a janela é só ~7 meses: **reconstruir a
reserva real andando pelos eventos de swap** do pool (cada swap emite as quantidades trocadas —
dado causal, não aproximado) desde a migração (ou desde o início da janela de discovery, se a
migração for anterior a ela) até `t`. O `k`/`sqrt` da rev.4 fica como *fallback* só pra quando o
histórico de swaps estiver incompleto (`missing_source`, seção 10), não como método primário.

**Fee de swap — tabela confirmada estável no período que importa.** Tabela literal de
`pump.fun/docs/fees` (25 faixas por market cap em SOL, 0,300% a 1,250% total; LP 0,020% abaixo de
420 SOL, 0,200% acima — tabela completa em `docs/strategy-options-move-first-2026-10-07.md`,
Opção F). **Verificação desta revisão, via histórico de commits do GitHub**
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

**Fórmula final:**

```
custo_ida_volta_pct ≈ 2 × impacto_pct
                     + fee_LP_swap(mcap_em_t) + fee_LP_swap(mcap_em_t+7)
                     + custo_rede_por_perna_usd(t)/tamanho_posicao_usd × 100 × 2
                     + 0   # ATA
```

Sweep 1x/2x mantido, mesma disciplina do Gate 2 do PQ-TR.

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

## Investigação InitBoost (herdada da rev.4, ainda válida)

BOOST (ativo só pra migrações depois de 2026-07-21 10:23 ET) extrai SOL da reserva do pool e
queima o LP recém-mintado **dentro da mesma transação atômica de migração** — verificado ao vivo,
estruturalmente, numa transação real (sem preço lido). Qualquer leitura de reservas feita depois
dessa transação já reflete o estado final, pós-boost; não quebra a regra de morte-vs-gap pro
período coberto. **Pendente**: confirmar se o LP também era queimado antes do BOOST existir
(2025-03 a 2026-07) — com a janela agora limitada a ~7 meses de 2026, **isso deixa de ser
bloqueante**: a janela de discovery+confirmação inteira já cai inteiramente depois de
2026-07-21 (confirmar a aritmética exata quando as datas de corte forem fixadas), então o período
sem BOOST pode nem entrar na amostra usada por este protocolo.

**Texto oficial do BOOST — não consegui acessar.** O post original (`x.com/Pumpfun/status/...`)
retornou HTTP 402 (paywall/autenticação do X) nesta sessão. Não existe doc oficial no GitHub
(`pump-fun/pump-public-docs`) — busquei por "boost" no repositório inteiro, zero arquivos. A
melhor evidência disponível continua sendo a verificação estrutural direta que fiz numa
transação real (mais forte que qualquer paráfrase de imprensa), não o texto literal do anúncio.

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

### Amostragem da conta de migração — achado desta sessão, escopo revisado

Caminhada completa de assinaturas (`39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg`) tentada nesta
sessão: **1.500.000 assinaturas, limite de segurança atingido, sem sair de 2026-08-05** —
confirma que uma caminhada completa até 2025-03-20 não é tratável no tempo desta sessão. Achado
lateral: picos de atividade extremos (~90.000 assinaturas em janelas de ~2h), consistente com
tempestades de retry automatizado, não volume orgânico — reforça a exigência de deduplicar por
pool. **Sob o redesenho desta revisão, isso deixa de ser um problema**: a enumeração agora só
precisa cobrir ~7 meses (item 4 de "Mudança de fonte de dado"), não 19 — ainda não tentado nesse
escopo menor nesta sessão, mas a ordem de grandeza (uma fração de ~7/19 do volume total,
provavelmente ainda não trivial dado os picos observados) é bem mais tratável. Script reusável:
`benchmarks/move_first_h_coverage_audit_v0/sample_migration_account.py` (`--self-check` OK),
aceita `--until-date` pra limitar o alcance.

## Pendências para o sign-off final

1. Rodar a amostragem da conta de migração com `--until-date` fixado em ~7 meses atrás (não os
   19 meses completos) — não feito nesta revisão.
2. Confirmar se o LP era queimado antes do BOOST existir — só relevante se a aritmética exata das
   datas da janela de discovery+confirmação tocar o período anterior a 2026-07-21 (a verificar
   quando as datas forem fixadas, não feito ainda).
3. Decidir o momento exato de "autorizar o discovery" pra disparar o download único e hash da
   janela grátis (regra 3) — depende do seu sign-off final sobre o protocolo inteiro acima.

Nenhum backtest, discovery, consulta a outcome, backfill ou pagamento foi executado nesta
revisão — só pesquisa documental (GitHub, X bloqueado), correção de fórmula e reorganização do
protocolo.

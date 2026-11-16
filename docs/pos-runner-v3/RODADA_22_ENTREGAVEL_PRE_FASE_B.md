# Rodada 22 — entregável só-leitura antes da Fase B

PAPER/READ-ONLY. Nenhum detector, parâmetro, H1, sinal ou critério alterado. Hashes recomputados:
V1 `279b79ffa3f0`, V2 `d57b4331d51d`, V3 `56762db29cd6`, plano `2bc8e32a0663`. **Nenhum
pré-registro aqui.** Nenhum R, P&L ou desfecho foi calculado no piloto.

**F** = fato verificado; **H** = hipótese. IC = Clopper-Pearson 95% exato.

## 1) `signals_mvp/scripts/fase_a_vm.py`

Executa todas as consultas [VM] de `RODADA_22_FASE_A_AUDITORIA_EXECUCAO_E_VIABILIDADE.md`.

Garantias (**F**, testadas em `signals_mvp/tests/test_fase_a_vm.py`, 6 testes):
- banco aberto com `mode=ro` + `PRAGMA query_only=1`; o `Storage` é montado **sem `__init__`**
  (sem criar tabela, migrar ou regenerar CSV). Teste: o arquivo do banco fica byte a byte igual, e
  `set_meta` levanta `OperationalError`;
- reusa as funções oficiais sem cópia: `analise.condicional.carregar_sinais_e_excluidos`/`rodar_h1`
  (seção c) e `simular_v3_carteira.carregar_ao_vivo` (seção b);
- **nunca registra** o hash do plano: sem registro em `meta`, a seção (c) recusa;
- `os.nice(19)`; zero rede, exceto a seção (d), que é opt-in (`--carteiras`).

Seções:

| | o que imprime |
|---|---|
| (a) | stops ao vivo V1/V2/V3: n sinais/tokens, R < −1,2R / −1,5R / −2R, quantis de R, R − piso do modelo offline, quantos candles de stop abriram abaixo do stop (gap) e o tamanho do gap em R |
| (b) | todo sinal `perdido_offline` ou não fechado com pool fora de `ativo`: H1 legado (pr_baseline), horizonte fixo (valor **persistido**), `simular_v3_carteira` (recalculado; marca **AUSENTE** quando os candles foram podados) e motivo/data da saída do pool. `--simbolos PEAK,WASTED` filtra |
| (c) | V1/V2: `rodar_h1` no modo legado (default do relatório) e no horizonte fixo 72h (diagnóstico), com n tokens, média, limites e critérios (a)–(d) |
| (d) | por carteira "pro": transações **bem-sucedidas** antes/depois de 2026-10-27 19:09:46 UTC (commit `ac4ff4c`), janela pré **simétrica** à pós. Só `getSignaturesForAddress`; **conta transações, não compras** (compra exige `getTransaction`). 30 s entre chamadas (2/min); **aborta no 1º 429** (HTTP ou JSON-RPC) e guarda checkpoint em arquivo próprio; teto de 240 chamadas por execução e 20 páginas por carteira (marca TRUNCADO). Endpoint próprio (`--rpc-url`/`FASE_A_RPC_URL`, padrão o público); **nunca** lê `POS_RUNNER_RPC_URLS`/`CARTEIRAS_RPC_URL`. Endereços aparecem só com 4 caracteres |
| (e) | MIN/MAX(`grad_ts`) de `pr_pools` por status, `pr_retro_candidatos`, nº de mints distintos em **qualquer** tabela com coluna `mint`, e a graduação mais antiga entre eles (= fim da janela limpa). `--exportar-vistos ARQ` grava a lista num arquivo próprio. Também conta `pr3_filtrados` por motivo (portão de qualidade no universo real) |
| (f) | rendimento ao vivo da V3: dos pools que viraram runner sob rastreio (`pr_funil_marcos`), quantos tiveram ≥1 ENTRADA (IC95%) — insumo do N do B2 (item 2) |

Comandos na VM (a partir da raiz do repo; sem restart):

```bash
git pull origin signals-mvp
```

```bash
python -m signals_mvp.scripts.fase_a_vm --db signals_mvp/dados/estado.sqlite --exportar-vistos ~/mints_vistos.txt
```

```bash
python -m signals_mvp.scripts.fase_a_vm --db signals_mvp/dados/estado.sqlite --simbolos PEAK,WASTED
```

Seção (d), demorada (~1 h por 120 chamadas; retomável):

```bash
nohup python -m signals_mvp.scripts.fase_a_vm --db signals_mvp/dados/estado.sqlite --so-carteiras --carteiras --checkpoint ~/fase_a_carteiras.json > ~/fase_a_carteiras.log 2>&1 &
```

Custo de (d): ≥1 chamada por carteira (121) ⇒ ≥61 min a 2/min; carteiras com >1.000 transações na
janela custam 1 chamada a mais por 1.000. Se o bot também usa o RPC público no mesmo IP, 2/min é
desprezível frente ao limite por IP. O mais seguro é passar uma chave própria em `FASE_A_RPC_URL`.

## 2) Piloto de rendimento do B2 (`signals_mvp/scripts/piloto_rendimento_b2.py`)

**Método (F):**
- **Universo:** todas as graduações enumeradas on-chain (mesma `enumerate_window` da Parte A).
- **Janelas:** de 30 min, sorteadas com semente `20261117` em **2026-10-16 → 2026-11-01** — fora do
  holdout do V0, da semana de embargo e da janela limpa candidata (o script recusa sortear nelas).
  Nenhum pool cai em `holdout_selado.json`; isso é checado a cada janela.
- **Candles:** 1h em MC, pela mesma conversão da Parte A (`_mc_bars`), por 14 dias desde a
  graduação (`idade_max_dias` do bot).
- **Filtro e detector:** portão `avaliar_qualidade` (o mesmo do ao vivo, `live.py:2151`) e
  `DetectorV1` com `ParamsV3` congelado. **Só conta eventos**: nunca chama `simulate`, custo ou
  horizonte.
- **Simplificação declarada:** `created_ts = grad_ts`. Para a emissão de ENTRADA é equivalente, só
  porque a janela de idade da V3 é [0, 36500] d.

**Resultado parcial (F; congelado em 2026-11-17 13:03 UTC):**
- **Cobertura:** 8 de 36 pares janela×launchpad concluídos, das 4 primeiras janelas; 2 pares falharam
  por `RateLimited` no RPC público e ficam para a retomada. Unidade = graduação (token).

| | n | fração | IC95% |
|---|---|---|---|
| graduações processadas | **139** (pump.fun 48, DBC 91, LaunchLab 0) | | |
| barradas pelo portão de qualidade | 113 (pavio do 1º candle ≥ 3×: 110; `l_bc_floor`: 3) | 81% | 73,8%–87,4% |
| sem referência USD da cotação | 4 | 3% | |
| válidas | 22 | 16% | |
| viraram runner (pico ≥ US$300k em 14 d) | 11 (pump.fun 10, DBC 1) | **7,9%** | 4,0%–13,7% |
| runner → caixa (FASE2) | 11 | | |
| caixa → ONDA_INVALIDA | **11 (todas)** | | |
| tokens com ≥ 1 ENTRADA V3 | **0** | **0,0 por 1.000** | **0–26,2 por 1.000** |

**N a sortear para ≥ 200 tokens sinalizados:**
- **Não estimável pelo ponto** (0 sinais).
- **Limite inferior de N:** mesmo no topo do IC (26,2/1.000), seriam precisos **≥ 7,6 mil** graduações.
- **Limite da janela limpa:** ela tem ≈ 112,7 mil graduações (item 3). Logo, se o rendimento real for
  **< 1,8 por 1.000**, a janela limpa inteira **não alcança 200 tokens sinalizados**.
- **Hipótese:** pelos 0/139 e pelo portão de qualidade que corta 81% antes do detector, esse cenário
  é plausível.

**Como estreitar sem baixar dezenas de milhares de pools:**
- `fase_a_vm.py` seção (f) mede, no bot ao vivo, P(≥1 ENTRADA V3 | pool virou runner sob rastreio).
- Multiplicado pela fração de runners por graduação medida aqui (7,9%; IC 4,0–13,7%), dá a estimativa
  de rendimento por 1.000 graduações.

**Custo/ritmo medido (F):**
- **Ritmo:** ≈ 0,8 graduação/min.
- **Gargalos:** `getTransaction` no RPC público (janelas inteiras falham com `RateLimited`) e 429 da
  GT, com pausas de 30–60 s.
- **Chamadas:** ≈ 5–7 RPC e ≈ 1–2 GT por graduação (enumeração incluída).
- **Para 1.000 graduações**, com chave RPC própria: ≈ 1–2 h de GT.

**Retomar** (mesma semente, sem repetir o que já foi feito; fora da VM):

```bash
PILOTO_RPC_URL="<endpoint próprio>" python -m signals_mvp.scripts.piloto_rendimento_b2 --trabalho ~/piloto_b2 --janelas 12
```

O checkpoint desta sessão está no container (efêmero), então a retomada noutra máquina recomeça do
zero. O sorteio é determinístico: as mesmas 12 janelas.

## 4) Calibração de custo real — cotação Jupiter ida e volta (`signals_mvp/scripts/calibrar_custo_jupiter.py`)

**O que mede (F):** para US$10 e US$25, cota SOL→token e depois token→SOL da quantidade recebida
(Jupiter `swap/v1/quote`, só leitura, sem chave nem assinatura). Custo por perna =
1 − √(1 − ida_e_volta) = **fee de pool + impacto de preço no instante**.
- **Não inclui:** terminal, rede, priority fee/Jito, MEV, latência, ATA, tx falha.
- **Parte comparável do `costs.py`:** 1,25% fee + 1,0% slippage = **2,25%/perna**. O total offline é
  3,45%/perna (`costs.py:56-75`).
- **Liquidez:** `liquidity` do `price/v3` da Jupiter, por token (soma dos pools).
- **Sem concorrência com o bot:** zero GT e zero RPC Solana, então pode rodar na VM.

**Na VM (amostra real de `pr_pools`, estratificada por idade, semente fixa):**

```bash
python -m signals_mvp.scripts.calibrar_custo_jupiter --db signals_mvp/dados/estado.sqlite --exportar-amostra ~/amostra_custo.csv --n 120
```

```bash
python -m signals_mvp.scripts.calibrar_custo_jupiter --cotar ~/amostra_custo.csv --saida ~/cotacoes_jupiter.jsonl
```

**Corrida desta sessão (F; 2026-11-17, SOL/USD = 70,68; 142 cotações, 71 tokens):**
- **Ressalva (amostra ≠ `pr_pools`, que não está aqui):**
  - 56 tokens são graduados de pump.fun/DBC/LaunchLab tirados das listas *top trending/traded/organic*
    da Jupiter. Viés para tokens vivos e líquidos; nenhum caiu em < US$5k.
  - os outros 15 são graduações pump.fun de 10–12/11 (amostra de viabilidade da Fase A), que cobrem
    a faixa morta.

| tamanho | liquidez atual | n tokens | sem rota | mediana/perna | p90/perna | máx/perna |
|---|---|---|---|---|---|---|
| US$10 | < 5k | 13 | 1 | **28,3%** | **78,2%** | 90,4% |
| US$10 | 5k–20k | 17 | 0 | 1,25% | 1,74% | 2,05% |
| US$10 | 20k–100k | 15 | 0 | 0,87% | 3,28% | 4,30% |
| US$10 | 100k–1M | 15 | 0 | 0,86% | 1,17% | 1,32% |
| US$10 | ≥ 1M | 11 | 0 | 0,19% | 0,25% | 0,25% |
| US$25 | < 5k | 13 | 2 | **69,3%** | **87,0%** | 93,9% |
| US$25 | 5k–20k | 17 | 0 | 1,34% | 2,16% | 3,03% |
| US$25 | 20k–100k | 15 | 0 | 1,06% | 3,42% | 4,31% |
| US$25 | 100k–1M | 15 | 0 | 0,87% | 1,22% | 1,40% |
| US$25 | ≥ 1M | 11 | 0 | 0,20% | 0,25% | 0,25% |

**Leitura:**
- **F:** com liquidez ≥ US$5k, fee + impacto cotados ficam **abaixo** dos 2,25% do `costs.py` na
  mediana (0,2–1,3%), e o p90 vai a 3,4% na faixa 20k–100k.
- **F:** com liquidez < US$5k o custo é de outra ordem: mediana 28%/perna (US$10) e 69%/perna
  (US$25). O `costs.py` não tem esse regime — usa 1% fixo offline. São tokens mortos: sair custa
  quase tudo.
- **H:** o regime que importa para a V3 é justamente o baixo. A entrada acontece depois de queda de
  80–96% de um pico ≥ US$300k, ou seja MC da base ≲ US$60k. Pela fórmula do próprio `costs.py`
  (reserva ≈ 0,207·√(L_bc·MC)), uma base de MC US$30k com L_bc US$50k dá reserva ≈ US$8k: perto da
  borda de 5k. O desfecho pior que −1,2R e os ~0,5R de custo da Fase A podem estar **subestimados**
  para os tokens que morrem depois da entrada.
- **Falta (F):** liquidez histórica no instante da entrada não existe nos candles. A tabela usa
  liquidez **atual**.

**Proposta de custo pessimista para os pré-registros (H; não adotado aqui):**
1. **Perna com liquidez ≥ US$5k:** 3,5% (≈ p90 cotado nas faixas 5k–100k) + 1,0% terminal +
   **US$0,30 fixo** (priority/rede, o cenário alto que `simular_v3_carteira` já tem) = 4,5% +
   US$0,30/perna. Isso dá **7,5%/perna em US$10** e **5,7%/perna em US$25**.
2. **Perna com liquidez < US$5k** (estimada ex-ante pela fórmula de reserva, ou medida ao vivo):
   custo de **50%/perna**, ou o sinal é declarado **não executável** e contado como perda total do
   risco. A escolha entre os dois fica para o pré-registro, nunca depois de ver o dado.
3. **Sensibilidade obrigatória:** 2× o item 1 (Gate 2).

Em R, por ida e volta:

| custo | stop 15% | stop 22% |
|---|---|---|
| `costs.py` offline (6,8%) | 0,45R | 0,31R |
| proposta, US$25 (11,1%) | 0,74R | 0,50R |
| proposta, US$10 (14,4%) | 0,96R | 0,66R |

## 3) Baixar e guardar os candles de 1h da janela limpa

**Janela limpa candidata (H até rodar a seção (e)):** 2026-09-22 → início do que o bot já viu.
Limite conservador usado aqui: 2026-10-16 (24 dias). O fim exato é a graduação mais antiga em
`pr_pools`; se for anterior a 16/10, a janela encolhe.

**Tamanho (medido, F):** transações sem erro nas contas de migração em 22/09–16/10, contadas só
por `getSignaturesForAddress` (383 chamadas):

| launchpad | tx sem erro | fração migração (Parte A, ago–set) | graduações estimadas |
|---|---|---|---|
| pump.fun | 40.173 | 0,838 | ≈33,7 mil |
| Meteora DBC | 82.304 | 0,939 | ≈77,3 mil |
| Raydium LaunchLab | 1.904 | 0,910 | ≈1,7 mil |
| **total** | 124.381 | | **≈112,7 mil** |

**Custo (estimativa a partir de medições desta sessão; H):**

| etapa | chamadas | ritmo | tempo |
|---|---|---|---|
| enumeração (pool/mint) | ≈124 mil `getTransaction` + ~400 de assinaturas + âncoras | RPC público ≈40/min (acima disso tomou `RateLimited`); chave própria grátis ≈100/min | ≈52 h / ≈21 h |
| candles 1h (moeda do token) | 1 GT por pool (1.000 candles = 41 dias por chamada) ≈113 mil | GT grátis 24–26/min (ritmo da Parte A) | **≈72–78 h** |
| supply + série USD da cotação | ≈113 mil RPC + poucas GT | sem prazo (on-chain é permanente) | depois |
| disco | ≈2,8 KB/pool em JSON (n=20 pools, 14 d) | | ≈315 MB bruto, ~40–60 MB gzip |

**Prazo (F, `signals_mvp/CLAUDE.md`):** o OHLCV grátis da GT cobre ~180 dias. O 1º dia da janela
(22/09) sai por volta de **2027-03-21**: ~4 meses de folga. Só os candles têm prazo; enumeração,
supply e USD podem vir depois.

**Plano de download retomável, fora do orçamento do bot (proposta, não implementada):**
1. **Onde:** PC do operador ou outra máquina com disco persistente; **nunca a VM** (1 GB, mesmo IP da
   GT/RPC do bot). Container de nuvem não serve para guardar: é efêmero.
2. **Chaves:** RPC próprio (chave grátis nova, não `POS_RUNNER_RPC_URLS`/`CARTEIRAS_RPC_URL`); GT
   grátis com limitador próprio a 24/min (limite por IP).
3. **Banco/cache separados:** reusar o `Store` da Parte A (`windows`/`graduations`, `window_done`
   torna a enumeração retomável) num diretório próprio, e o `OhlcvStore` (checkpoint por arquivo,
   `pending`).
4. **Ordem:** dia mais antigo primeiro, primeiro enumerar o dia e depois baixar os candles do dia
   (mesma regra §8 da Parte A, pois a borda dos 180 dias anda todo dia).
5. **Sem desfecho:** só candles brutos em moeda do token (`currency=token`), sem conversão nem
   detector. Rodar regra e desfecho fica para depois do pré-registro.
6. **Antes de baixar candles:** gravar e commitar a lista de pools enumerados com sha256 (como
   `holdout_selado.json`). É recomendação para a Fase B, não pré-registro.
7. **Exclusões:** tirar os mints de `--exportar-vistos` (seção e) e as 15 graduações da amostra de
   viabilidade de 10–12/11 (já fora da janela). Conferir que nenhum pool cai no holdout selado do V0.

O que falta para executar: um CLI pequeno que aponte o `pipeline` da Parte A para uma janela
arbitrária (hoje ele está preso ao `PeriodPlan` do V0) — código novo, não escrito nesta entrega.

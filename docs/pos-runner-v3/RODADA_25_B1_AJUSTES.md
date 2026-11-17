# Rodada 25 — ajustes no desenho do B1 (copy-wallet) + proposta RpcError → adiamento

Só documento: nenhum código, banco ou pré-registro. **Substitui as §3.1 (saída), §3.2 (custo) e
§3.3 (critério) de `RODADA_24_HORIZONTE_FIXO_RPC_DESENHO_B1.md`.** O resto daquela seção continua valendo:
amostra pós-congelamento, entrada t + 2 min, placebo e controles.

**F** = fato (código ou medição citada); **H** = hipótese ou proposta.

Fechado na Rodada 24, conforme o operador: não rodar `horizonte_fixo` na VM. As rejeições por `getSlot`
foram **57**, todas descobertas em 09–12/11.

## 1) Custo e enriquecimento exigido

**Correção da minha leitura.** "1,2–1,95×" não é multiplicador de custo. Minha leitura anterior **não
veio de texto nenhum do repositório** (busca por "hurdle" e "1,95" em `docs/` e `signals_mvp/` não acha
nada além de um 1,95% sem relação em `RODADA_19_ITEM3_MODELO_CUSTO_STOP_CURTO.md:32`). Foi minha
interpretação errada da frase do pedido.

**Definição (operador):** fator de enriquecimento exigido sobre o acaso = **1 + RT/stop**, onde
RT = custo de ida e volta e stop = largura do stop em % do preço de entrada.

**Por que essa é a régua (F, conta):**
- Aposta com alvo +k·stop e perda −1·stop. A taxa de acerto do acaso, sem custo, é p0 = 1/(k+1).
- Com custo RT, o equilíbrio exige p·k·stop − (1−p)·stop − RT = 0. Daí
  **p\* = (1 + RT/stop)/(k + 1) = p0 · (1 + RT/stop)**.
- O fator vale para qualquer k, e só é atingível se 1 + RT/stop ≤ k + 1.

**Cenários de custo (ida e volta, da Rodada 22):**

| cenário | perna | RT | origem |
|---|---|---|---|
| offline (`costs.py`, sol_usd=None) | 3,45% | **6,9%** (2 × 3,45%) | `pos_runner/costs.py:56-75` (**F**) |
| pessimista US$25 | 4,5% + US$0,30 = 5,7% | **11,1%** | calibração Jupiter, Rodada 22 §4 (**H**, proposta) |
| pessimista US$10 | 4,5% + US$0,30 = 7,5% | **14,4%** | idem |

**Enriquecimento exigido por largura de stop.** Entre parênteses, a taxa de acerto de equilíbrio para
alvo simétrico (k=1, p0=50%) e para alvo +2R (k=2, p0=33,3%):

| stop | offline 6,9% | pessimista US$25 11,1% | pessimista US$10 14,4% |
|---|---|---|---|
| 12% | 1,58× (78,8% / 52,5%) | **1,92×** (96,2% / 64,2%) | 2,20× (**inviável** em k=1 / 73,3%) |
| 15% | 1,46× (73,0% / 48,7%) | 1,74× (87,0% / 58,0%) | 1,96× (98,0% / 65,3%) |
| 20% | 1,35× (67,3% / 44,8%) | 1,56× (77,8% / 51,8%) | 1,72× (86,0% / 57,3%) |
| 22% | 1,31× (65,7% / 43,8%) | 1,50× (75,2% / 50,2%) | 1,65× (82,7% / 55,2%) |
| 25% | 1,28× (63,8% / 42,5%) | 1,44× (72,2% / 48,1%) | 1,58× (78,8% / 52,5%) |
| 33% | **1,21×** (60,5% / 40,3%) | 1,34× (66,8% / 44,5%) | 1,44× (71,8% / 47,9%) |

Os dois extremos da régua do operador conferem: offline + stop 33% → **1,21×**; pessimista + stop 12% →
**≈1,93×** (US$25: 1,925).

**Onde entra no B1 (H):** o desfecho primário (espelho, §2) **não tem stop**: o custo é descontado em
cada braço e o teste é a diferença pareada líquida. O fator exigido vale para o **secundário por evento**
(tocar +k·s antes de −1·s, com s declarado antes). Nele a razão P(evento | pro) / P(evento | acaso) tem
de passar de 1 + RT/s no cenário de custo declarado.
- **Proposta:** s = 25% e k = 2, nos cenários offline e pessimista US$25.
- **Pendente:** escolha do operador antes do pré-registro.

## 2) Saída: um primário, secundários declarados antes

| | definição |
|---|---|
| **primário: espelho** | saída a 100% na **1ª venda** de qualquer carteira da **mesma pessoa** naquele token depois da compra. Execução no `open` do 1º candle de 1 min que começa ≥ t_venda + **2 min**, com custo de venda (perna do cenário). **Teto de 72 h:** sem venda até t_compra + 72 h, sai no `close` do último candle com negócio ≤ 72 h, mais custo de venda. Pool morto (sem negócio ≥ 24 h antes da saída) também leva a sensibilidade −100% |
| secundário 1 h / 6 h / 24 h | marcado a mercado no `close` do último candle negociado ≤ t_entrada + h, com custo de ida e volta; sem venda espelhada |
| diagnóstico (fora da decisão) | espelho **proporcional** (vende a mesma fração que a pessoa vendeu, a cada venda) |

Venda parcial da pessoa dispara a saída total no primário. É uma simplificação declarada; o diagnóstico
proporcional mostra quanto ela pesa.

## 3) Filtros: o que reportar

Para todas as compras pós-congelamento (unidade = token, 1ª compra da lista), contagem e fração com
IC95% Clopper-Pearson de cada exclusão, na ordem:

1. token **ainda na curva de bonding** em t + 2 min (sem pool graduado);
2. pool sem cofre identificável no tx de compra (`sem_dado` de liquidez);
3. **liquidez < US$5k** no tx de compra;
4. sem candle de 1 min na GT após t + 2 min;
5. compra que é recompra ou de outra pessoa no mesmo token (vai para diagnóstico).

**Secundário sem o filtro de liquidez:**
- **Viável (H)** para tokens já graduados: o preço da GT existe.
- **Custo:** compras com liquidez < US$5k recebem **50%/perna** (regime medido: mediana 28–69%/perna,
  Rodada 22 §4), não o custo de ≥ US$5k. Sem isso o secundário sairia otimista por construção.
- **Leitura:** reportado ao lado do primário, nunca decide.
- **Fora dos dois:** compras na curva, que só entram se um dia houver reconstrução on-chain.

## 4) RPC: créditos Helius

**Premissa (H, a conferir no painel/documentação da Helius):** `getSignaturesForAddress` e
`getTransaction` custam **1 crédito** cada (chamada RPC padrão). Plano informado: 1M créditos/mês,
10 req/s.

| etapa | chamadas | créditos | tempo a 5 req/s (metade do teto) |
|---|---|---|---|
| **piloto** (~200 tx parseadas) | 121 páginas de assinaturas (1 por carteira) + 200 `getTransaction` | **≈ 320** | ≈ 1 min |
| **backfill** das 121 carteiras desde 27/10 | Σ ceil(n_w/1000) + Σ n_w | ≈ **TX_pos + 121** | TX_pos / 5 s |
| placebo (§3.4 da Rodada 24) | assinaturas do pool ±10 min (1–3 por compra pro) + histórico de 3 placebos por pessoa | ≈ **2–3 × TX_pos** (H) | — |

TX_pos = transações bem-sucedidas pós-congelamento somadas, coluna `pos` da seção (d) de
`fase_a_vm.py`.

| TX_pos (121 carteiras) | backfill pro | com placebo (×3–4) | cabe em 1M/mês? |
|---|---|---|---|
| 50 mil | ≈ 50 mil | 150–200 mil | sim |
| 150 mil | ≈ 150 mil | 450–600 mil | sim, se o bot não gastar o resto |
| 300 mil | ≈ 300 mil | 0,9–1,2 M | **no limite / estoura** |

- **Bot:** se a chave Helius for a mesma do bot (trocada em 12/11), o consumo dele sai do mesmo milhão.
  Usar chave separada ou medir o consumo do bot no painel antes.
- **Taxa:** 10 req/s só limita o tempo. 300 mil chamadas a 5 req/s ≈ 17 h.

## 5) Critério de parada numérico do B1 (B4)

**N mínimo** (d = 0,3; α = 0,05 unilateral; 80% de poder; pareado; folga 1,5× por cauda pesada, Rodada
24 §3.3): **N_min = ⌈69 × 1,5⌉ = 104 tokens.** Se o B1 for julgado com α/2: ⌈88 × 1,5⌉ = 132.

**N projetado até o limite do OHLCV grátis:**

```
N_proj = λ_ef × D
λ_ef   = (TX_pos / D_obs) × f_compra × f_novo × (1 − f_curva) × (1 − f_sem_dado) × (1 − f_liq<5k) × f_gt
D      = dias de 2026-10-27 até 2027-04-25 = 180
```

| termo | o que é | de onde |
|---|---|---|
| TX_pos / D_obs | transações/dia da lista após o congelamento | seção (d) de `fase_a_vm.py` |
| f_compra | fração dessas transações que são compras | piloto (~200 tx parseadas) |
| f_novo | fração das compras que são a 1ª da lista naquele token | piloto |
| f_curva, f_sem_dado, f_liq<5k | exclusões do §3, na ordem | piloto |
| f_gt | cobertura de candle na GT | 0,87 (Rodada 22, n=15, IC95% 0,60–0,98) até o piloto medir |

**Regra (fixada antes do piloto):**
- Calcular N_proj com a estimativa pontual **e** com o produto dos limites inferiores de IC95% das
  frações do piloto.
- **N_proj pontual < 104** ⇒ o B1 **não roda**. Ele é redesenhado (ex.: unidade pessoa × token, janela
  maior, curva via on-chain) ou encerrado. Qualquer redesenho é hipótese nova, com pré-registro novo.
- **Pontual ≥ 104, mas pessimista < 104** ⇒ zona cinzenta: só roda por decisão explícita do operador,
  registrada antes de coletar preços.
- **Pessimista ≥ 104** ⇒ segue para o pré-registro.
- **Equivalente em taxa:** λ_ef ≥ **0,58 token/dia** (104/180). Com α/2: 0,73/dia.

Nenhum preço ou retorno é lido nessa decisão: só contagens.

## Item à parte — proposta (não implementada): RpcError vira adiamento na linhagem

**Problema (F, Rodada 24 §2):**
- `verify_lineage` converte `RpcError` em `Lineage("erro")` (`pos_runner/live.py:306-307`).
- `step()` conta isso como tentativa (`:373`) e, na 8ª (`VERIFY_MAX_ATTEMPTS`, `:151`), rejeita para
  sempre (`:393-394`).
- Uma queda de RPC de ~2,5 h vira exclusão permanente de token. Foram 57 assim, em 09–12/11.

**Proposta mínima:**
1. **Distinguir a classe do erro:** `solana_rpc.classificar_erro` já existe. `Lineage` ganha um status
   novo **`adiado`** para erro de transporte, rate limit, conexão ou `exhausted`. Erro de **dado**
   (migração não encontrada, mint divergente, criação desconhecida) continua `rejeitado`.
2. **`adiado` não consome tentativa:** não incrementa `tentativas`. Grava `adiado_ate` com espera
   crescente, limitada a 30 min, e um contador **separado** `adiamentos`, só para diagnóstico.
3. **Teto por idade, não por tentativas:** o pool só sai da fila quando passar de `idade_max_dias`, que
   `_promote` já aplica (`live.py` "passou da idade máxima na fila"). O motivo fica explícito:
   "sem linhagem por indisponibilidade de RPC", **nunca** `rejeitado`.
4. **Visibilidade:** `saude.py` mostra quantos pools estão `adiado` e há quanto tempo.
5. **Os 57 já rejeitados:** reabri-los muda a amostragem retroativamente. Por isso **não** entram
   automaticamente: decisão do operador, numa emenda de amostragem datada. A fila e a idade já os
   tirariam, porque passaram de 14 d.

**O que não muda:** detector, parâmetros, H1, hashes. É só operação de admissão (amostragem). Exige
restart e um teste: RpcError repetido 20× → pool continua na fila como `adiado`; erro de dado → continua
`rejeitado`.

---

## Adendo — decisões do operador e ajustes (antes de qualquer preço)

**Decisão:** secundário por evento com **s = 25%, k = 2** (tocar +50% antes de −25%; acaso p0 = 33,3%).

### A1) Preenchimento do stop no cenário pessimista = meio entre stop e low

- **Dado de origem:** a reconciliação ao vivo (VM, 16/11, informada pelo operador) mediu a venda no meio
  stop–low **0,10–0,25R pior** que no stop.
- **Como entra:** no cenário pessimista, a perda de quem bate o stop passa a ser s + δ, com δ = ΔR · s
  em % do preço. O ganho continua k·s.
- **Equilíbrio:** **p\* = (s + δ + RT) / ((k+1)·s + δ)**; fator exigido = p\* / p0.

Para s = 25%, k = 2:

| cenário de custo | stop no nível (δ=0) | meio, ΔR=0,10 (δ=2,5%) | meio, ΔR=0,25 (δ=6,25%) |
|---|---|---|---|
| offline (RT 6,9%) | p\*=42,5% · **1,28×** | 44,4% · 1,33× (custo efetivo no stop 9,4%) | 47,0% · 1,41× (13,2%) |
| pessimista US$25 (11,1%) | 48,1% · **1,44×** | 49,8% · **1,49×** (13,6%) | 52,1% · **1,56×** (17,4%) |
| pessimista US$10 (14,4%) | 52,5% · 1,58× | 54,1% · 1,62× (16,9%) | 56,2% · 1,69× (20,7%) |

"Custo efetivo no stop" = RT + δ: o que um trade perdedor paga além dos −25%.

- **Pré-registro:** usar o **pessimista US$25 com ΔR = 0,25**, ou seja exigir razão de acerto ≥ **1,56×**
  o acaso. O offline sem δ (1,28×) fica como referência.

### A2) Ambiguidade dentro do candle (declarado antes de olhar preço)

- Se um mesmo candle de 1 min tem `low ≤ entrada·(1−s)` **e** `high ≥ entrada·(1+k·s)`, conta-se o
  **stop primeiro** (perda). É a mesma convenção conservadora de `simulate_v1.py:147-165`.
- O candle de entrada (o do `open` usado como preço) já conta. Nenhum candle anterior à entrada conta.

### A3) Limiar de fração vendida que dispara a saída espelho

- **Regra:** a 1ª venda dispara a saída total só se vender **≥ 50%** do saldo do token que **aquela
  carteira** tinha imediatamente antes da venda: `(pre − post) / pre`, lido nos `pre/postTokenBalances`
  do próprio tx de venda.
- **Vendas abaixo de 50%:** não disparam; ficam registradas.
- **Vendas acumuladas da mesma carteira:** somam até cruzar 50% do maior saldo observado desde a
  compra; o instante do cruzamento é o gatilho.
- **Por que 50%, sem olhar preço:** é o menor corte com significado estrutural — a carteira passa a
  ter **menos da metade** da exposição, ou seja a maior parte da posição saiu. Abaixo disso a venda pode
  ser realização parcial, ajuste de tamanho, taxa ou "pó", que não indicam saída.
- **Sensibilidade (diagnóstico, nunca decide):** 25% e 75%.
- O piloto mede **só a distribuição da fração vendida** (sem preço) para mostrar quanto cada corte
  muda a contagem de saídas.

### A4) Créditos Helius por método (documentação lida em 2026-11-16)

- **Fontes:** `https://www.helius.dev/docs/billing/credits` e `/docs/billing/rate-limits`.

| método | créditos | uso |
|---|---|---|
| `getSignaturesForAddress` | **1** | **usado** (piloto e backfill) |
| `getTransaction` | **1** | **usado** (piloto e backfill) |
| demais RPC padrão (ex. `getTokenAccountsByOwner`) | 1 (linha "Standard RPC Calls") | não usado |
| `getTransactionsForAddress` | 10 por 100 tx completas (mínimo 10) | não usado |
| Enhanced Transactions (parse) | **100** | **não usado** |
| Parsed Events | 10 por requisição | não usado |

- **Plano Free:** 1M créditos/mês; RPC 10 req/s; APIs enriquecidas 2 req/s.
- **Decisão:** só RPC padrão. O parse é feito localmente, com o mesmo `jsonParsed` já usado pelo projeto.
- **Medição:** o piloto conta chamadas por método × tabela acima e imprime o total. Conferir contra o
  delta do painel da Helius antes e depois do piloto.
- **Chaves e consumo do bot:**
  - Pela taxa informada de ~10 chamadas/min, o bot gasta ≈ 14,4 mil créditos/dia ≈ **432 mil/mês**:
    ~43% do plano, antes do B1.
  - **Piloto (~320 créditos):** pode usar a chave do bot.
  - **Backfill:** **chave própria**, diferente da do bot.

### A5) D = 180 dias é conservador se o B1 salvar candles na coleta

- O limite de ~180 dias do OHLCV gratuito vale para dado **baixado depois**. Se o B1 salvar os candles
  de 1 min de cada token **à medida que coleta** (forward, logo após cada compra mais 72 h), nenhum
  candle envelhece fora do alcance. O horizonte deixa de ser 25/04/2027 e passa a ser a data de corte
  que o operador escolher.
- **Consequência:** a projeção N_proj = λ_ef × 180 é **conservadora** nesse modo; com coleta forward
  contínua, N cresce com o tempo de coleta.
- **A regra do B4 continua:** decide com D = 180. Um D maior só vale se for declarado antes, junto com o
  compromisso de coleta forward.

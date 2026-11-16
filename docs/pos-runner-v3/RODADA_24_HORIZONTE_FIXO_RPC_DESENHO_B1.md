# Rodada 24 — horizonte fixo vazio, rejeições por RPC e desenho do B1 (copy-wallet)

PAPER/READ-ONLY. Nenhum código alterado, nada rodado no banco. **F** = fato (código); **H** = hipótese
ou proposta.

## 1) Por que `pr_horizonte_fixo` tem 0 linhas para os 58 sinais

**F — o único escritor é um script manual que nunca é chamado pelo bot:**
- `storage.pr_horizonte_fixo_upsert` é chamado em um só lugar: `signals_mvp/scripts/horizonte_fixo.py:109`,
  dentro de `calcular_e_persistir_ao_vivo` (`:68-115`).
- Esse código só roda por `executar()` (`:136-145`), a partir do CLI
  `python -m signals_mvp.scripts.horizonte_fixo --db …` (`:148-154`).
- Nenhum código do bot chama isso. Busquei por `pr_horizonte_fixo_upsert`, `calcular_e_persistir_ao_vivo`
  e `scripts.horizonte_fixo` em `live.py`, `worker.py` e `supervisor.py`, e não há agendamento em
  `scripts/linux/` (`iniciar.sh`, `parar.sh`, `signals-mvp.service`).
- **Conclusão:** não é bug de gravação nem gravação condicionada a uma versão. O motor de horizonte fixo
  (criado em `4da2a4a`, 2026-11-05, "R primário em 72h/7d") virou desfecho primário autorizado **sem um
  job que o rode**. 0 linhas = o CLI nunca rodou contra este banco.
- **Primeira data de escrita esperada:** não existe uma automática. Seria a 1ª execução manual do CLI,
  possível desde 2026-11-05.
- **Confirmação na VM:** se o CLI nunca rodou, `meta['emenda_horizonte_fixo_hash']` também está vazio,
  porque `garantir_emenda_registrada` só é chamado nesse mesmo `executar`
  (`pos_runner/horizonte_fixo.py:51-66`):

  ```bash
  sqlite3 -readonly signals_mvp/dados/estado.sqlite "SELECT key, value FROM meta WHERE key IN ('emenda_horizonte_fixo_hash','plano_analise_hash');"
  ```

- **Detalhe que não muda a conclusão:** mesmo rodando, o script pula sinais sem `pr_trajetoria`, sem o
  candle de `t_entrada` em `pr_bars` ou com candles já podados (`scripts/horizonte_fixo.py:78-92`).
- **O que fazer (decisão sua, é escrita em produção):** rodar o CLI uma vez grava `pr_horizonte_fixo` e
  registra o hash da emenda. Enquanto isso, a reconciliação (`reconciliacao_ao_vivo.py`) já dá os mesmos
  valores recalculados, só lendo.

## 2) Pools rejeitados por "RpcError: exhausted … getSlot"

**F — mecanismo:**
1. A verificação de linhagem converte qualquer `RpcError`/`RuntimeError` em `Lineage("erro", …)`
   (`pos_runner/live.py:306-307`). O `getSlot` vem da busca da âncora (`solana_rpc.py:343`, chamada por
   `anchor_at_or_after`).
2. Cada passo soma 1 em `info["tentativas"]` (`live.py:373`).
3. Na 8ª tentativa (`VERIFY_MAX_ATTEMPTS = 8`, `live.py:151`) o pool vira **`rejeitado` para sempre**,
   com o último erro como motivo (`live.py:393-394`).
4. A espera entre tentativas é `min(30 min, 2 min × 2^tentativas)` (`live.py:331-335`): 4, 8, 16, 30,
   30, 30, 30 min. Da 1ª à 8ª tentativa passam ≈ **2 h 28 min**.

**F — consequência:** qualquer queda do RPC de ~2,5 h ou mais rejeita **permanentemente** todo candidato
que estava na fila. É uma falha de sistema virando exclusão de token. Contraria a regra do
`signals_mvp/CLAUDE.md`: "rate-limit … is not a property of the token: postpone, don't decide on missing
data". Também reduz a amostra de forma não aleatória: some quem foi descoberto durante a queda. Não
corrigi (escopo só leitura).

**Datas e contagem depois de 12/11: [VM].** O checkout não tem o banco. Consulta só leitura, por dia de
descoberta e de rejeição:

```bash
sqlite3 -readonly signals_mvp/dados/estado.sqlite "SELECT date(found_ts,'unixepoch') AS descoberto, date(checked_ts,'unixepoch') AS rejeitado_em, COUNT(*) AS n FROM pr_pools WHERE status='rejeitado' AND motivo LIKE '%exhausted%getSlot%' GROUP BY 1,2 ORDER BY 1,2;"
```

```bash
sqlite3 -readonly signals_mvp/dados/estado.sqlite "SELECT SUM(checked_ts >= strftime('%s','2026-11-12')) AS rejeitados_apos_12nov, SUM(found_ts >= strftime('%s','2026-11-12')) AS descobertos_apos_12nov, COUNT(*) AS total FROM pr_pools WHERE status='rejeitado' AND motivo LIKE '%exhausted%getSlot%';"
```

- Use o horário exato da troca para Helius, se souber; acima usei 2026-11-12 00:00 UTC.
- Rejeições **depois** da troca significam que o endpoint novo também ficou ≥ ~2,5 h sem responder ao
  `getSlot` em algum momento, ou que o pool já vinha acumulando tentativas.

## 3) Desenho do backtest B1 (copy-wallet) — proposta, não implementada

**Pergunta (H):** copiar as compras da lista "pro" congelada, com atraso realista e custo pessimista,
rende mais que copiar carteiras comuns pareadas por atividade nas mesmas condições?

### 3.1 Amostra e fontes

| item | proposta |
|---|---|
| carteiras | lista congelada `carteiras_pro_papodefi.json` (121 endereços, 79 pessoas, sha256 `71d6ee62a458…`); **unidade de decisão = pessoa** (grupo), nunca endereço |
| período de teste | **só compras depois de 2026-10-27 19:09:46 UTC** (commit `ac4ff4c`). Compras anteriores servem apenas para parear o placebo (§3.4) — a lista foi escolhida por desempenho passado |
| compras | `getSignaturesForAddress` por carteira até o congelamento + `getTransaction` (`jsonParsed`, **`maxSupportedTransactionVersion: 1`**); compra = saldo do token ↑ e SOL/WSOL ↓ no mesmo tx. Venda, o inverso |
| unidade estatística | **token**: a 1ª compra de qualquer pessoa da lista naquele token depois do congelamento. Recompras e outras pessoas no mesmo token entram só como diagnóstico |
| preço de entrada | GT OHLCV **1 min** (`currency=usd`): `open` do 1º candle que **começa** ≥ t_compra + Δ. Causal; nunca o preço do próprio tx da carteira |
| atraso Δ | primário **2 min**; diagnósticos 30 s e 5 min |
| token na curva (antes da graduação) em t+Δ | fora da análise primária, com motivo explícito. A GT tem em mediana só 2 candles de 1 min na curva antes da graduação (Rodada 22, n=13), então não há preço confiável. Reconstrução on-chain fica como secundário futuro |
| liquidez ≥ US$5k | medida **no próprio tx de compra da carteira**: `pre/postTokenBalances` trazem os cofres do pool, então a reserva em SOL × SOL/USD × 2 dá a liquidez no instante t (ex-ante, sem dado posterior). Abaixo de US$5k: excluído e contado. Sem cofre identificável: `sem_dado`, nunca liberado |
| saída primária | **espelhar** a 1ª venda da mesma pessoa naquele token, executada em t_venda + Δ, com teto de 72 h. Sem venda até 72 h: marca no último candle negociado ≤ 72 h |
| saídas secundárias | retorno marcado em 24 h e 72 h |
| pool morto | sem negócio ≥ 24 h antes da saída: também sensibilidade −100% |

**N esperado (H, a medir):** N_tokens ≈ (tokens distintos comprados pela lista após 27/10) ×
f_graduado(t+Δ) × 0,87 (cobertura de candles GT, Rodada 22: 13/15, IC95% 0,60–0,98) × f_liq≥5k.
- O primeiro fator sai da seção (d) do `fase_a_vm.py`. Hoje ela conta transações, não compras: falta o
  parse com `getTransaction`.
- `f_graduado` e `f_liq` são desconhecidos. Um piloto de ~200 transações (parse apenas, sem preço)
  mede os três fatores sem olhar desfecho.

### 3.2 Custo (pessimista) e a régua de 1,2–1,95×

- Por perna, da calibração Jupiter (Rodada 22): **4,5% + US$0,30**. Isso dá 5,7%/perna em US$25 e
  7,5%/perna em US$10. Ida e volta = **11,1% (US$25)** e **14,4% (US$10)**. Esse é o *hurdle* h.
- **Leitura que assumi** (confirme): o resultado líquido precisa ficar positivo com o custo multiplicado
  por **1,2 (primário)**, e é reportado também com **1,5 e 1,95 (estresse)**.

  | tamanho | 1,0× | 1,2× (primário) | 1,95× (estresse) |
  |---|---|---|---|
  | US$25 | 11,1% | 13,3% | 21,6% |
  | US$10 | 14,4% | 17,3% | 28,2% |

- O custo é **igual nos dois braços** (pro e placebo). O teste compara líquido contra líquido.

### 3.3 Teste primário (um só) e poder

- **Métrica:** diferença pareada por token, d_i = r_líq(pro) − média de r_líq(placebos do mesmo token e
  da mesma janela).
- **Escala (H, escolher antes):** log(1 + r), com r ≥ −99%. Retorno de memecoin tem cauda pesada; a
  média crua vira diagnóstico.
- **Teste:** unilateral, α = 0,05 (α/2 se o B1 for julgado junto com outra hipótese primária). IC por
  bootstrap **por token**, 10.000 réplicas, semente fixa. Permutação de sinais como confirmação. Um único
  Δ e uma única saída no primário: os demais ficam fora da decisão.
- **N mínimo para 80% de poder** (aproximação normal, delineamento pareado: N = (z_{1−α} + z_{0,8})² / d²,
  com d = efeito / DP da diferença pareada):

  | d (efeito padronizado) | α = 0,05 | α = 0,025 |
  |---|---|---|
  | 0,15 | 275 tokens | 349 |
  | 0,20 | **155** | 197 |
  | 0,30 | 69 | 88 |
  | 0,50 | 25 | 32 |

  - Sem pareamento (pro e placebo em tokens diferentes), o N **por braço** dobra (ex.: d=0,2 → 310).
  - Com cauda pesada, bootstrap e permutação perdem eficiência. **H:** planejar com folga de 1,5–2×
    (ex.: d=0,2 → 230–310 tokens).
- **Como fixar d sem queimar dado (H):** estimar só o **DP** da diferença usando compras pré-congelamento
  de **placebos contra placebos** (nunca pro contra placebo). Isso dimensiona a amostra sem olhar o
  efeito.

### 3.4 Placebo pareado por atividade (lição RED-COHORT)

- **Candidatos:** compradores do **mesmo pool** em ±10 min da compra pro (assinaturas do pool nessa
  janela), menos as carteiras da lista, programas/PDAs e bots de alta frequência (corte de tx/dia fixado
  antes).
- **Pareamento:** só com o período **pré-congelamento**: compras/dia, tamanho mediano em SOL, idade
  mediana do token na compra, mix de launchpad. K = 3 vizinhos por pessoa pro, com caliper e semente
  fixa.
- **Mesma regra:** os placebos seguem a mesma regra de cópia, o mesmo Δ, a mesma saída espelhada (a venda
  do próprio placebo) e o mesmo custo e filtro de liquidez.
- **Regra de descarte:** se o lift do placebo for ≥ o lift do pro, a hipótese cai como
  `DESCARTADA_CONFUNDIMENTO`. Mesma regra do pré-registro de carteiras forward (§4).

### 3.5 Controles

- **Negativo — série embaralhada:** para cada token, embaralhar em blocos de 15 e 60 min os retornos
  1 min (preservando volatilidade e caudas), mantendo os instantes de compra. Rodar o pipeline inteiro.
  Espera-se "positivo" em ≈ α das 200 reamostragens de tokens. Junto: série invertida no tempo.
- **Positivo — efeito plantado:** a mesma especificação de `RODADA_22_ESPEC_TESTE_EFEITO_PLANTADO.md`,
  aplicada aos retornos de cópia (recuperar d conhecido de 0,2/0,3/0,5). Só em dados que não julgam o B1:
  placebos pré-congelamento.
- **Timing dentro do token:** entrada sorteada no mesmo token em ±6 h, com o mesmo filtro de liquidez.
  Diz se o ganho vem do token ou do momento.

### 3.6 Custo de coleta e onde roda (H)

- **RPC:**
  - por carteira, `ceil(n_tx/1000)` páginas + 1 `getTransaction` por tx desde 27/10;
  - para o placebo, mais assinaturas do pool em ±10 min por compra pro (1–3 páginas em pool quente) e o
    histórico pré-congelamento de cada candidato.
  - Com **chave própria** (não `POS_RUNNER_RPC_URLS`/`CARTEIRAS_RPC_URL`), fora da VM, num banco separado
    e retomável.
- **GT:**
  - ~5 chamadas por token para 72 h de candles de 1 min (1.000 por chamada);
  - para 300 tokens × (1 pro + 3 placebos no mesmo token) ≈ 1,5 mil chamadas, ≈ 1 h a 24/min.
- **Prazo:** o OHLCV grátis da GT cobre ~180 dias. As compras de 27/10 começam a sair por volta de
  **2027-04-25**.

### 3.7 O que congelar antes de qualquer cálculo de retorno (vai para o pré-registro em lote)

- Δ e saída primária.
- Escala da métrica, α, N alvo (ou data de corte) e semente.
- Piso de liquidez e como medi-lo.
- Custo e multiplicadores.
- Regra de pareamento e K.
- Controles e critério de aceite (FP no nulo dentro da faixa binomial).
- Número de comparações (1 primária; diagnósticos listados).
- Exclusões: curva, `sem_dado` e liquidez.

Nada de retorno é calculado antes desse commit.

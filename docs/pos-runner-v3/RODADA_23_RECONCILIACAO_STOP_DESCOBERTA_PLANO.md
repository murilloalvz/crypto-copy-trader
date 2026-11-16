# Rodada 23 — reconciliação ao vivo, profundidade do stop, cobertura da descoberta e plano não registrado

PAPER/READ-ONLY. Nada entrou em produção; nenhum detector, parâmetro, H1 ou hash alterado (recomputados:
V1 `279b79ffa3f0`, V2 `d57b4331d51d`, V3 `56762db29cd6`, plano `2bc8e32a0663`).

**F** = fato verificado (código/medição); **H** = hipótese. Os números de banco saem do script novo
rodado na VM; este documento explica o que cada coluna significa e por que ela pode divergir.

## Script novo: `signals_mvp/scripts/reconciliacao_ao_vivo.py`

- **Só leitura:** abre o banco com `mode=ro` + `query_only` e monta o `Storage` sem `__init__`. É o
  mesmo mecanismo do `fase_a_vm.py`. O teste confere que o banco fica byte a byte igual.
- **Sem rede**, com `nice`.
- **Testes:** `signals_mvp/tests/test_reconciliacao_ao_vivo.py`. A suíte completa passou: 1.440 testes,
  6 pulados.

```bash
python -m signals_mvp.scripts.reconciliacao_ao_vivo --db signals_mvp/dados/estado.sqlite --csv ~/reconciliacao.csv
```

### 1) Reconciliação ao vivo

**O que faz (F).** Para **todo** sinal ENTRADA de V1/V2/V3, de qualquer status:
1. Localiza o candle de entrada em `pr_bars`, onde `ts == ts_fechamento`. Isso vale porque o
   `decision_ts` do detector é o início do candle de decisão + 1 passo (`detector_v1.py:115`).
2. Recalcula R@72h e R@7d com a função oficial `horizonte_fixo.calcular_r_horizonte`: custo offline e
   veto amplo, iguais aos do motor persistido.
3. Coloca lado a lado:
   - H1 legado: `pr_baseline.r_sinal`/`dif_pareada`;
   - horizonte fixo persistido: `pr_horizonte_fixo`;
   - R da regra ao vivo: `result_net / risco`;
   - R da regra **sem corte e com custo offline** (`simulate_v1` na série inteira). Essa coluna
     separa o efeito de custo/veto do efeito do horizonte.

**Agregados (F).**
- **Unidade:** por token, na 1ª tentativa (menor `ts_fechamento` por mint, por versão).
- **Estatísticas:** média, mediana, IC bootstrap por token (10.000 réplicas, semente e nível do H1),
  leave-one-token-out (mínimo e máximo da média) e a média sem o melhor token.

**Pool morto vs censurado (F, regra do script).**
- **morto:** o restante foi marcado num preço **sem negócio havia ≥ 24 h** no fim dos dados. É o mesmo
  limiar de `RETIRADA_SEM_CANDLE_H`. Para esses o script reporta também a **sensibilidade −100%**: a
  fração ainda aberta vale zero e as pernas já realizadas (stop, TP1) são mantidas.
- **censurado:** o rastreio parou antes do corte (pool saiu de `ativo`, por exemplo por idade máxima)
  **com o pool ainda negociando**. O valor é só marcado no último preço; sem −100%, porque não há
  evidência de morte. É contado à parte.

**Categorias de divergência recalculado × persistido (coluna `divergencia`):**

| categoria | o que significa | qual vale |
|---|---|---|
| `igual` | mesmo status e mesmo R | — |
| `nao_persistido` | `scripts/horizonte_fixo.py` nunca calculou o sinal: não rodou depois do sinal, ou o sinal não tinha trajetória | o recalculado |
| `persistido_desatualizado` | estava `pendente` quando foi calculado; o horizonte venceu depois | o recalculado |
| `candles_novos_apos_o_calculo` | a série cresceu depois do cálculo e a marca andou | o recalculado |
| `regra_fechou_depois_do_calculo` | era `marcado`; a regra fechou depois com candles novos | o recalculado |
| `sem_candles_hoje` | `pr_bars` podado | o persistido, sem como reproduzir |
| `outro` | ver valores lado a lado no relatório/CSV | manual |

**Por que H1 legado ≠ horizonte fixo (F, mecanismo):**
1. O legado só tem `dif_pareada` para `status=='fechado'` (`live.py:3684`). Logo `aberto`,
   `perdido_offline` e `descontinuado` ficam fora.
2. O legado usa a **saída pela regra sem limite de tempo**: `simulate_v1` só sai por stop, EXIT FULL
   ou TP1 (`simulate_v1.py:141-186`). O horizonte fixo marca a mercado no corte.
3. O custo do legado usa a cotação SOL/USD cacheada (`live.py:4370`); o recalculado usa o teto
   offline. A coluna "R regra offline" mostra quanto dessa diferença é custo e veto.
4. O veto ao vivo cruza com o DexPaprika; o offline não.

**Os 13 `perdido_offline` por idade máxima (PEAK, MOGZ, WASTED, McRib, Kimchi…).**
- **Mecanismo (F):**
  - `_retire` (`live.py:1082-1091`) aposenta todo pool `ativo` com mais de 14 d desde a graduação e
    só poupa sinais **V0** abertos (`pr_signals`). V1, V2 e V3 abertos não são protegidos.
  - O detector é descartado; o sinal fica `aberto` congelado até o próximo restart, que o marca como
    `perdido_offline` (`live.py:899-947`).
  - Ele estava aberto aos 14 d porque a regra **nunca tocou o stop nem fechou abaixo de S** nesse
    tempo; a regra não tem prazo.
- **H:** são trades que sobreviveram dias sem stop. Excluí-los do H1 legado tende a deixar a amostra
  **mais perdedora**, a mesma direção já descrita na Rodada 17 item 6. O script mostra o valor real
  de cada um.
- **Censura no horizonte fixo (F):**
  - entrada V1 entre 2 e 7 d de idade ⇒ o corte de 72h cai antes dos 14 d, então não há censura;
  - o corte de 7d pode passar dos 14 d, e aí fica censurado;
  - a V3 não tem janela de idade, então censura é possível nos dois horizontes.
- **Poda (F):** 21 d depois de `checked_ts`, `pr_prune` apaga os candles (`storage.py:1293-1300`). A
  partir daí o caso só existe pelo valor persistido; o script marca `sem_candles`.

### 2) Profundidade do stop

**O que faz (F):**
1. Para cada sinal ao vivo `fechado` por `stop`, reexecuta `simulate_v1` (veto amplo) sobre `pr_bars`
   para achar o candle do stop.
2. Mede **(stop − low)/stop** e se houve gap (`open < stop`).
3. Recalcula o R vendendo em três pontos, mantendo as outras pernas e o custo:

   | ponto | preço |
   |---|---|
   | oficial | `min(open, stop)`, a convenção atual (`simulate_v1.py:155`) |
   | meio | média entre o fill oficial e o low |
   | low | pior caso dentro do candle |

4. Reporta mediana, p90 e máximo para todos os stops e para a 1ª tentativa por token. A quarta linha,
   "R ao vivo", vem de `result_net`.

**Limite (F):** se o veto ou o custo offline divergirem do ao vivo e a simulação offline **não**
terminar em stop, o caso aparece como "não reproduzido", com o motivo — nunca é inventado.

**Leitura (H):** a profundidade mede quanto o low passou do stop dentro da hora. Com velas de 1h e um
token ilíquido, "meio" é um palpite razoável para uma ordem a mercado disparada no meio da queda. A
convenção oficial preenche no stop sempre que o candle abre acima dele.

### 3) Cobertura da descoberta

**Como o bot descobre (F):**
- **Fontes:** uma lista do GeckoTerminal a cada 3 min (`descoberta_min`), em rodízio entre quatro
  (`live.py:165-170`, `config.yaml`):
  - `trending_pools`;
  - top por volume 24h de `pumpswap`;
  - top por volume 24h de `meteora-damm-v2`;
  - top por volume 24h de `raydium`.
- **Só a página 1**, que tem **20 pools** (medido agora). Isso dá 480 leituras/dia: cada lista é lida
  a cada 12 min e mostra sempre os mesmos líderes de volume.
- **Filtro do candidato** (`offer`, `live.py:978-1011`): DEX de graduação, **MC ≥ US$300k** (o piso de
  runner), MC ≤ US$50M, idade ≤ 14 d, ainda não visto.
  - Na leitura de agora: 6/20 no *trending* e 6/20 no top-volume da PumpSwap.
- **Fila:** `offer()` **para de aceitar candidatos** quando pendente+verificado ≥ `QUEUE_MAX = 60`
  (`live.py:153`, `995`).
- **Vaga:** a promoção a `ativo` depende de vaga (`max_pools`, 45 na VM) e vai do **maior MC
  primeiro** (`_prioridade_espera`, `live.py:1095-1100`).
- **Saída da fila:** quem fica mais de 14 d na fila sai como `encerrado` ("passou da idade máxima na
  fila").

**Por que ~16 pools/dia (H, a confirmar com a seção (3) do script).** A entrada é limitada na origem:
- as listas mostram poucos pools novos e elegíveis por dia;
- com as vagas cheias, a fila de 60 encosta e a entrada vira **rotatividade da fila**, não taxa de
  graduação.

A seção (3) mostra, do banco: candidatos por dia e por lista, a ocupação atual da fila, os motivos de
saída, a espera até a vaga, os barrados por vaga e as chamadas de descoberta com 429.

**Fração das graduações reais:**

| | taxa | origem |
|---|---|---|
| graduações (janela 22/09–16/10) | ≈ 4.700/dia (pump.fun ≈ 1.400, DBC ≈ 3.220, LaunchLab ≈ 70) | **F**, medido |
| graduações que viram runner ≥ US$300k em 14 d | 7,9% (IC95% 4,0–13,7%) ⇒ **≈ 370/dia** (190–640) | **F**, piloto, n=139; limite inferior, porque 81% nem passaram pelo detector |
| candidatos do bot | ~16/dia ≈ **0,3% das graduações** e **≤ 4% dos runners** (≈ 2,5–8% pelo IC) | **H**, usando a taxa informada da VM |

**Viés (H):** o bot só estuda runners que estavam **entre os 20 de maior volume 24h** (ou em
trending) num dos instantes de leitura, já acima de US$300k. Sob escassez de vaga, vêm primeiro os de
maior MC.
- **Efeito sobre a amostra:** ela sobre-representa os runners mais populares e líquidos. Tudo que sai
  dela (ao vivo, `retro_lote1`, `replay_v3`) **não generaliza** para "runners em geral".
- **Direção:** desconhecida. Popularidade pode trazer mais segunda corrida ou mais despejo.
- **O B2 por enumeração on-chain não tem esse viés.**

**Quanto custaria ampliar (estimativas; H):**

| opção | o que muda | custo extra | viável na VM de 1 GB? |
|---|---|---|---|
| A. páginas 1–10 das mesmas listas | mais candidatos do mesmo tipo (volume) | GT ≈ 4.800/dia (≈ 3,3/min), dividindo a fatia de GT do bot | rede sim, mas não resolve: o gargalo é a vaga e a fila de 60; só aumenta barrados |
| B. radar on-chain de **todas** as graduações + checagem de MC barata | universo completo de candidatos | RPC ≈ 4.700 `getTransaction`/dia (≈ 3,3/min, chave própria); MC via Jupiter `price/v3` em lote de 50: ~66 mil mints vivos em 14 d ⇒ ≈ 1.300 chamadas por varredura (1×/h ≈ 22/min; 1×/6h ≈ 3,7/min); registro em SQLite ≈ dezenas de MB | **sim** (registro leve). Precisaria de sorteio **ex-ante** entre os elegíveis no lugar de "maior MC primeiro" para tirar o viés |
| C. **acompanhar com candles** todos os runners | sem seleção | ~370/dia × 14 d ≈ 5.200 pools simultâneos × 1,9 MB/pool (RSS medido, emenda 2026-11-05) ≈ **9,9 GB de RAM**; GT ≈ 87 chamadas/min só de candle 1h | **não**: RAM ~10× a VM e GT acima do gratuito |

B muda a regra de amostragem do bot (sorteio e radar). Isso exige emenda datada e restart, **não
feito**. Para medir seleção de token, o caminho barato continua sendo o B2 offline.

### 4) "plano não registrado em meta (atual 2bc8e32a0663)"

**Por que (F):**
- O bot **não** registra o hash do plano na inicialização. No startup ele só congela os hashes de
  saída fiel, suporte forward e carteiras forward (`live.py:747`, `759`, `796`).
- O hash do plano (`meta['plano_analise_hash']`, `analise/condicional.py:31`) só é gravado
  **preguiçosamente**, na **1ª** chamada de `condicional.executar` (`condicional.py:1053` →
  `garantir_plano_registrado`, `:65-79`). Isso acontece pelo `/analise` no Telegram
  (`live.py:4007`, `telegram.py:318`) ou pelo CLI `python -m signals_mvp.analise.condicional`.
- Portanto, **ninguém rodou `/analise` nem o CLI contra este arquivo de banco**. Outra possibilidade:
  rodaram contra outro arquivo. O CLI **não tem `--db`**; usa `make_paths()`, que é
  `signals_mvp/dados/estado.sqlite` ou `$SIGNALS_MVP_HOME/dados/estado.sqlite`.
- O `fase_a_vm.py` recusa de propósito: só lê.

**Procedimento oficial** (há dois no código; recomendo o explícito):
1. Confirmar que o texto em disco é o commitado:

   ```bash
   git status --short docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md
   ```

   Saída vazia = sem edição local. A última mudança do texto é o commit `ec70b4b`, de 2026-11-10
   (EMENDA 4, opção A).
2. Registrar explicitamente, a partir da raiz do repo e apontando para o mesmo banco do bot:

   ```bash
   python -m signals_mvp.analise.condicional --registrar-emenda
   ```

   Isso grava `plano_analise_hash` **e** uma entrada com data em `meta['plano_analise_emendas']`
   (histórico só de acréscimo). É o único caminho que deixa data registrada.
   - A alternativa implícita (o 1º `/analise`) grava só o hash, sem data.
   - **Isto é uma escrita no banco de produção:** em `meta`, mais o `Storage(paths)` do CLI, que roda
     o schema e migrações idempotentes. O CLI não pega o lock de instância (só o `worker.py` pega).
     A escrita é concorrente com o bot via WAL, com `busy_timeout` de 30 s. Fica para você decidir
     quando; não fiz.

**O que o registro congela (F):**
- Congela **só o texto** de `docs/pos-runner-v1/PLANO_ANALISE_PREREGISTRADO.md` (hash curto de 12
  caracteres). Isso inclui H1–H14 de V1/V2, a EMENDA 1 (critérios a–d) e o resumo normativo da opção A
  da V3.
- Depois do registro, qualquer edição do arquivo faz `/analise` recusar (`PlanoAlteradoError`) até um
  novo `--registrar-emenda`.
- **Não congela** dados, amostra, detector, parâmetros (que têm hash próprio) nem custo.
- **Não torna nada retroativamente pré-registrado:** a data científica do texto é o commit no git; o
  `meta` só impede edição silenciosa daqui para frente.
- Registrar agora **não muda nenhum número**; só libera `rodar_h1` no `/analise` e no `fase_a_vm`.

## O que não foi verificado nesta sessão

- Todos os números de banco (seções 1–3 do script): este checkout não tem `estado.sqlite`. O script
  foi testado em banco sintético.
- Os ~16 pools/dia, que tomei do seu relatório da VM.
- O custo das opções A e B, que é estimativa a partir de taxas medidas na Rodada 22.

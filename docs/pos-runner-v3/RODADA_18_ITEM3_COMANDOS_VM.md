# Rodada 18, item 3 — comando de VM (`avaliar_entrada_suporte.py`) e tempo estimado

PAPER/READ-ONLY, zero chamada de rede, zero escrita fora de `meta` (hash do pré-registro). Mesma
limitação de sempre: esta sessão não tem acesso ao banco real da VM — tempo abaixo é estimativa por
complexidade algorítmica, nunca medição.

```bash
nice -n 19 tmux new-session -d -s avaliar_entrada_suporte \
    'python -m signals_mvp.scripts.avaliar_entrada_suporte --db signals_mvp/dados/estado.sqlite \
     --veto amplo \
     2>&1 | tee avaliar_entrada_suporte.log'
```

**Tempo estimado**: replay de base (ordem de grandeza de `varredura_v3.py`, mesmos 3 loaders) + **1
replay extra de `DetectorV1` por sinal** (`entrada_suporte.localizar_revisitas_suporte` reexecuta o
detector do zero, 0..gatilho_idx, pra cada sinal — zero chamada de rede, mas custo O(sinais ×
candles_até_o_gatilho), tipicamente bem menor que o replay completo do pool já que para no gatilho)
+ comparador aleatório K=20/sinal (reusa `_r72h_de_indices`, já pago no resto do projeto) + bootstrap
10k por horizonte(2)×origem(3). Esperado próximo da ordem de `retrospectivo_saida_fiel.py`
(rodada 17/18) — nunca o mais caro dos scripts desta linha, mas **a elegibilidade reduz N** (sinais
sem revisita pós-`WATCHLIST` e antes do gatilho ficam fora), então o N efetivamente agregado deve ser
menor que os `n_sinais` totais reportados.

| comando | tempo estimado (sem medição) | tempo real medido |
|---|---|---|
| `avaliar_entrada_suporte --veto amplo` | ordem de `retrospectivo_saida_fiel` | _(preencher)_ |

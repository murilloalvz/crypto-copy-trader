# Emenda 2026-11-03 — auditoria de negociação (ANT/CHICO) e proposta de critério de incapacidade

PEDIDO 2026-11-03 (rotação/capacidade). **Não altera V1/V2/V3 nem hashes**
(`ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6`) — item 1 é medição nova;
item 2 é SÓ proposta (não implementada); item 3 fixa a disciplina para quando (e se) for adotado.

## 1) `scripts/auditar_negociacao.py` (novo, SOMENTE LEITURA)

Para todo pool `ativo`/`dormente`: volume USD 24h/72h (`pr_bars.v`, já em USD por `to_mc_bars` — soma
direta), nº de candles 1h com volume exatamente 0 nas últimas 24h, liquidez (`pr_pools.info.liq_usd`,
snapshot da descoberta — "s/d" explícito quando faltar, nunca 0), MC atual e horas em `sem_fase`.
Destaca ANT, CHICO e todo `dormente` (aposentado pela rotação atual). Nenhum limiar é escolhido —
só a medição, para decidir o critério depois com dado real da VM.

## 2) Critério proposto para "incapaz por falta de negociação" (NÃO IMPLEMENTADO)

A rotação atual (`live.py: _rotacionar_vagas`) já aposenta por MC<piso OU queda>96%, com sem_fase
>24-72h — mas nunca por volume. Caso relatado (ANT/CHICO com MC>=100k, dias em sem_fase): o critério
de MC passa, mas não há negociação real.

Derivado dos próprios parâmetros (nunca um número arbitrário): o gatilho `rompimento_volume` exige
`bar.volume >= vol_mult(2.0) × média de volume da caixa`. Numa caixa com volume médio ≈0, essa
condição vira `0 >= 0` (trivialmente satisfeita por qualquer ruído, nunca por negociação real) — ou
seja, o próprio gatilho perde o significado quando não há volume de verdade para servir de
referência. Proposta: medir, dentro da janela `sem_fase` já em curso, quantos candles consecutivos
têm volume exatamente 0 (o piso natural em que `vol_mult × média` deixa de representar qualquer coisa
real — "zero" não é uma fração escolhida, é o ponto em que a própria fórmula do gatilho se torna
vazia). Um pool cuja caixa inteira (ou quase) tem volume zero nunca teria uma `rompimento_volume`
genuína, nem um `power_candle_rompimento` real com amplitude de preço, já que sem negociação não há
movimento de preço para gerar ATR — o sintoma observado (sem_fase prolongado) é consequência
estrutural, não coincidência. Holders: covariável apenas (nunca critério), conforme pedido.

Isto é SÓ a proposta — nenhum limiar exato de candles/horas foi escolhido, e nada foi ligado em
`_rotacionar_vagas`. Decisão fica para depois de olhar o relatório do item 1 na VM.

## 3) Disciplina para quando (e se) for adotado

Qualquer critério novo de rotação é AMOSTRAGEM (decide só quem fica sob observação, nunca
detecção/entrada/saída/banca) — igual à rotação atual e à emenda 2026-10-30
(`EMENDA_2026-10-30_AMOSTRAGEM_ROTACAO_VAGAS.md`). Quando implementado: emenda datada própria,
`regime_amostragem` explícito e datado (mesmo padrão já usado em `pr1_signals.regime_amostragem`),
reversível pela lista `dormente` (nunca `encerrado`), e NUNCA aplicado a runner/pullback/posição
aberta — exatamente as mesmas garantias que `_rotacionar_vagas` já tem hoje.

## Testes e hashes

5 testes novos (`test_auditar_negociacao.py`). Suíte completa: 1002 passed. Hashes
`ParamsV1=279b79ffa3f0`/`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` intactos.

## Comandos na VM

```
git pull origin signals-mvp
# RESTART NAO necessario (script offline novo, zero mudanca de codigo ao vivo).
python -m signals_mvp.scripts.auditar_negociacao --db dados/estado.sqlite
```

# SIG-FAST V0 — spec do cartão de sinal (F6, 2026-10-08)

Só especificação de formato. Nenhum sistema ao vivo é ligado por este
documento — nenhum sinal real é gerado, nenhuma UI é construída, nenhum dado é
lido. Isto descreve o que um cartão de sinal MOSTRARIA para o operador, se e
quando `SIG-FAST-DISC-V0` (F5) passar por discovery + confirmação e virar algo
que o operador queira operar manualmente.

## Propósito

O operador decide TAKE/SKIP e executa manualmente (caminho `signal → TAKE/SKIP
humano → execução manual` do `CLAUDE.md`). O cartão existe pra dar a ele, no
momento do sinal, o que precisa pra decidir tamanho e planejar a saída — não
pra decidir por ele.

## Campos do cartão

1. **Token**: mint, venue (`pump_bonding_curve` | `pumpswap`), idade do token
   (ou idade pós-graduação, se aplicável à família).
2. **Família**: qual família do lote disparou o sinal (`SIG-FAST-COPY-G` |
   `SIG-FAST-POSTMIG`, ou as que vierem a ser validadas depois). Um token só
   gera um cartão por família por sinal — famílias não são combinadas num
   score (regra 4 do pré-registro em lote).
3. **Flags de filtro** (vetos computados no momento do sinal, cada um com 3
   estados possíveis — nunca um booleano que esconda ausência de dado):
   - `PASSOU` — filtro computado, token não rejeitado.
   - `REJEITOU` — filtro computado, token rejeitado (o cartão não deveria
     nem ser exibido neste caso — listado aqui só pra completude do formato).
   - `INCONCLUSIVE_SEM_DADO` — filtro não computável agora (ex.: PQ-TR
     aguardando replicação; bundle/sniper/bump aguardando merge do plumbing
     de slot/creator). Nunca tratado como "passou".
   - Lista de filtros: PQ-TR, freeze authority, bundle/sniper/bump, histórico
     do criador (mesma lista do pré-registro em lote).
4. **Perfil histórico da família** (vem do resultado **validado/confirmado**
   da família, nunca do discovery isolado — se a família ainda não passou da
   confirmação prospectiva, o cartão não existe, porque a família não é
   operável ainda):
   - P(+X% antes de −Y%) no Δ e W congelados da regra validada, **menos** a
     mesma probabilidade do baseline pareado (F3) — o número a mostrar é o
     edge, não a probabilidade bruta do sinal isolada (evita o operador ler
     "70% de chance de +50%" sem saber que o placebo já tinha 65%).
   - Mediana do tempo até o pico (MFE) — **só descritivo**, rotulado
     explicitamente "teto teórico (hindsight) — não é o que a regra de saída
     valida captura". Nunca mostrado sem esse rótulo ao lado.
   - MAE típica (mediana/percentil, a definir qual no sign-off da família) —
     também descritivo, dá ao operador uma ideia de quanto o preço costuma
     cair no caminho antes de qualquer recuperação.
   - EV líquido e PF da regra de saída congelada (a mesma que passou no PASS
     validado) — este é o número que carrega a validação, não o MFE.
5. **Grade de latência usada na validação**: qual Δ (entre
   `ENTRY_LATENCY_GRID_SECONDS`) foi o que validou — pra ele saber se a
   latência dele bate com a que foi testada (ver "Perguntas abertas" do F5:
   latência real dele é informação que falta pra isso ficar preciso).
6. **Timestamp do sinal** (`chain_time` do trade que disparou) e timestamp de
   geração do cartão — pra ele avaliar quanto atraso já teria ao agir.

## O que o cartão NÃO mostra (deliberado)

- Não mostra um "preço-alvo de saída" calculado pra agora — mostra o PERFIL
  histórico da regra de saída validada, pro operador comparar com o que ele
  decidir fazer.
- Não mostra nenhuma recomendação de tamanho de posição em valor absoluto além
  do tamanho ~US$25 já usado na validação — mudar o tamanho muda o slippage
  (ver `simulate_amm_buy_execution_price_sol`/`simulate_amm_sell_execution_price_sol`
  em `src/opportunity_path_metrics_v0.py`), então o perfil histórico só vale
  pro tamanho em que foi medido.

## Aviso obrigatório no cartão (texto fixo, não editorializado por sinal)

> "A saída discricionária sua não é validada por este programa — só a regra de
> saída fixa (listada acima) tem PASS validado. Se você sair diferente da
> regra (antes, depois, parcial, por instinto), o resultado passa a ser seu,
> não um dado que entra de volta no registro de hipóteses. Isso não é uma
> recomendação pra seguir a regra à risca — é só a distinção entre o que foi
> medido e o que você decide fazer."

Este aviso existe porque a disciplina do registro (CLAUDE.md, regra 3 do
`research-hypothesis-registry-v1-2026-10-04.md`) só vale pra regra congelada;
a discrição do operador fica por cima da validação, nunca dentro dela.

## Exemplo de layout (ilustrativo, dado 100% fictício)

```
┌─────────────────────────────────────────────────────────┐
│ SIG-FAST — cartão de sinal (ILUSTRATIVO, sem dado real)  │
├─────────────────────────────────────────────────────────┤
│ Token: <mint> · pumpswap · idade pós-graduação: 22min    │
│ Família: SIG-FAST-POSTMIG                                │
│                                                           │
│ Filtros:                                                 │
│   PQ-TR ................ INCONCLUSIVE_SEM_DADO           │
│   freeze authority ..... PASSOU                          │
│   bundle/sniper/bump .... INCONCLUSIVE_SEM_DADO           │
│   histórico do criador .. PASSOU                          │
│                                                           │
│ Perfil histórico (Δ=15s, W=900s, regra validada):        │
│   Edge P(+50% antes de −30%) vs. baseline: +<X>pp         │
│   EV líquido / PF (regra de saída congelada): <...>       │
│   Mediana tempo-até-pico (MFE, TETO TEÓRICO, hindsight):  │
│     <...>s — não é o que a regra de saída captura         │
│   MAE típica: <...>%                                      │
│                                                           │
│ Sinal em: <chain_time> · cartão gerado em: <agora>        │
│                                                           │
│ [aviso fixo de discrição, ver seção acima]                │
└─────────────────────────────────────────────────────────┘
```

## Pré-condição pra este cartão existir de verdade

Nenhuma família tem resultado validado ainda (F5 é RASCUNHO, nenhuma coleta
rodou). Este spec existe pra já ter o formato pronto quando/se uma família
passar a validação — não antecipa nenhum número.

# V68 Jupiter Retry/Backoff — Nota de Conformidade de Protocolo (2026-10-04)

## Escopo

Verifica, item a item e com referência de código exata, se os três commits que
alteraram o caminho de captura SELL da pesquisa route-only (`2e847c7`, `5ead9ee`,
`f865745`) respeitam os invariantes congelados do protocolo V68:

- mesmo pacing do provider (`hazard_start_interval_ms=650`, `entry_start_interval_ms=1000`,
  `exit_start_interval_ms=250`);
- semântica de missingness "at-most-once" (um outcome por target);
- "sem retry/backfill para melhorar a economia" (o retry não pode ser condicionado a
  preço/resultado).

Escrita antes do resultado do v68-09 existir.

## Diffs reais inspecionados

```
2e847c79  src/jupiter_research_exit_route.py (+41/-13), tests (+78)
5ead9ee4  src/jupiter_research_exit_route.py (+15/-1), src/jupiter_swap_v2.py (+6/-2), tests (+42)
f865745   docs ledger (+8), src/jupiter_research_exit_route.py (+21/-1), tests (+2/-1)
```

Nenhum dos três toca `src/signal_plane_forward_cohort_v0.py`,
`src/route_research_evaluation.py`, ou qualquer arquivo de threshold/gate — confirmado
por `git show --stat` nos três commits.

## Item (a) — retry é cego a preço/resultado?

**Sustenta-se o espírito (cego a preço), mas a frase literal "só por classe de erro
HTTP" é mais estreita do que o código real.**

O laço de retry em `capture()` (`jupiter_research_exit_route.py:244-266`) é:

```python
for retry_index in range(JUPITER_RESEARCH_EXIT_ORDER_MAX_ATTEMPTS):
    try:
        order = JupiterSwapV2Client(...).order(...)
        last_exc = None
        break
    except JupiterOrderError as exc:
        last_exc = exc
        if retry_index + 1 < JUPITER_RESEARCH_EXIT_ORDER_MAX_ATTEMPTS:
            backoff = (RATE_LIMIT_BACKOFF if exc.status_code == 429 else GENERIC_BACKOFF)
            time.sleep(backoff)
```

`JupiterOrderError` é levantado em `jupiter_swap_v2.py` por quatro famílias de causa,
não só por status HTTP:

1. `HTTPError` real (linha 115-122) → `status_code=exc.code` (ex.: 429, 5xx).
2. Erro de transporte (`URLError`, `TimeoutError`, `OSError`, `HTTPException`,
   decode/JSON) (linha 123-131) → `status_code=None`.
3. Payload 200 com `error` e sem `inAmount` (linha 136-137) → `status_code=None`,
   rejeição a nível de aplicação (ex.: "no route found"), **não** um erro HTTP.
4. Falha de normalização (`parse_jupiter_order`, campos ausentes/valores inválidos,
   linhas 160-174) → propagada como `JupiterOrderError`, `status_code=None`.

O retry genérico (`0.5s`) cobre as famílias 2, 3 e 4 também — não apenas falha de
transporte/HTTP. Nenhuma dessas quatro famílias inspeciona preço, `priceImpact`,
tamanho de saída ou qualquer campo econômico antes de decidir retry: a decisão é
inteiramente sobre o tipo da exceção levantada, nunca sobre o conteúdo de uma
resposta bem-sucedida. **Conclusão: cego a preço/resultado = sustenta. "Só classe de
erro HTTP" = impreciso; é "qualquer `JupiterOrderError`", um conjunto mais amplo que
ainda assim nunca olha para economia.**

O backoff 429-específico (`exc.status_code == JUPITER_RESEARCH_EXIT_RATE_LIMIT_STATUS_CODE`,
linha 263) É exatamente e apenas o código de status HTTP 429 — essa parte é exata.

## Item (b) — nunca escreve mais de um outcome por target?

**Sustenta-se.**

`complete_route_research_outcome` é chamado exatamente uma vez por invocação de
`capture()`, sempre após o laço de retry já ter terminado (sucesso via `break`, ou
exaustão das `MAX_ATTEMPTS` tentativas): ver os quatro pontos de retorno terminais em
`capture()` — `CONFIG_MISSING` (linha 233-239), `PROVIDER_ERROR` por exaustão
(linha 284-290), `NORMALIZATION_ERROR`/`PROVIDER_ERROR` por falha de normalização
(linha 322-328), `AVAILABLE` (linha 355-360). O laço de retry em si nunca chama
`complete_route_research_outcome` ou `complete_provider_attempt` — só `time.sleep`.

De-duplicação entre chamadas separadas de `capture()` é garantida por
`begin_provider_attempt` (chave `attempt_key`) mais o guard `if outcome.status !=
"PENDING": raise` (linha 199-200) e o caminho idempotente `_existing()` (linha 169-196),
que nunca dispara uma nova chamada ao provider. Nenhuma trajetória do código produz
duas escritas de outcome para o mesmo target.

## Item (c) — pacing do provider não foi alterado?

**Sustenta-se, com evidência direta.**

`hazard_start_interval_ms=650`, `entry_start_interval_ms=1000`, `exit_start_interval_ms=250`
são argumentos default congelados em `src/signal_plane_forward_cohort_v0.py:88-90`,
usados pelos pacers (`ProviderStartPacerV44`, linha 204 e análogas) que controlam
quando cada probe agendado é *disparado*. Confirmado via `git show --stat` nos três
commits: nenhum toca esse arquivo. O retry/backoff dos três commits só atua **depois**
que um probe já disparado chama `capture()` — ele afeta quanto tempo uma tentativa já
em curso pode demorar para terminar, nunca a cadência entre o início de probes
agendados distintos. Pacing (cadência de início) e latência de conclusão de uma
tentativa individual são eixos diferentes; só o segundo foi tocado.

## Item (d) — fica limitado pelo gate de lateness?

**NÃO se sustenta como garantia. Para e aviso, como instruído — não é algo escondido:
o próprio comentário do commit `f865745` (linhas 42-65 do arquivo) já documentava
esse risco residual explicitamente antes desta nota.**

O que é verdadeiramente limitado: o atraso adicional **máximo por outcome** é
determinístico, porque `JUPITER_RESEARCH_EXIT_ORDER_MAX_ATTEMPTS=3` fixa exatamente 2
janelas de backoff. Com o valor atual (`1.5s`), o atraso adicional de um único outcome
está em `{0, 1.5, 3.0}` segundos (mais o tempo real de rede/API em cada tentativa).

O que **não** é garantido: que esse atraso determinístico fique dentro do
`target_lateness_p95_max_seconds=2` congelado em
`src/signal_plane_forward_cohort_v0.py:82`. Qualquer outcome que precise de 2 retries
já soma pelo menos `3.0s` de backoff puro (antes de qualquer latência de rede) — acima
do próprio limite do gate. Isso não é hipotético: é exatamente o mecanismo que já
quebrou o gate em v68-08 com backoff=3.0s (`lateness_p95=6s` vs. limite `2s`). O
valor `1.5s` foi escolhido por dominância matemática sobre `1.0s` (cobre com certeza o
grupo "precisa de ≤3.0s de espera real" que o esquema anterior provou existir), não
porque alguma prova garanta `lateness_p95 <= 2s` no v68-09. A nota em `f865745` já
dizia isso ("Known residual risk, not claimed to be fully solved... lateness_p95 could
still exceed 2s").

**Consequência prática para a leitura do v68-09:** se v68-09 passar no gate de
lateness, isso é um fato empírico sobre a distribuição real de retries daquela coleta
específica — não uma propriedade provada do código. Se v68-09 falhar de novo no mesmo
gate, a causa raiz permanece a mesma identificada em `f865745`: o código não persiste
timestamp por tentativa, então não é possível, a partir do histórico, separar quanto
do atraso veio da rede vs. do backoff — exatamente o que a A4 (branch separada, não
mergeada) se propõe a resolver com medição real, em vez de mais uma constante
chutada.

## Veredito consolidado

| Item | Sustenta? | Observação |
|---|---|---|
| (a) cego a preço/resultado | Sim, em espírito | "só classe de erro HTTP" é descrição estreita; o gatilho real é qualquer `JupiterOrderError` (HTTP, transporte, ou payload de erro a nível de app), sempre cego a economia |
| (b) um outcome por target | Sim | confirmado por rastreamento de todos os `complete_route_research_outcome` em `capture()` |
| (c) pacing intocado | Sim | confirmado por `git show --stat`; nenhum dos 3 commits toca `signal_plane_forward_cohort_v0.py` |
| (d) limitado pelo gate de lateness | **Não, como garantia** | limitado pelas próprias constantes (`MAX_ATTEMPTS`, backoff), não provadamente dentro do gate — já era risco residual documentado, não uma violação nova introduzida agora |

Nenhum item encontrado aqui implica reabrir um resultado fechado, tocar um threshold
congelado, ou alterar a amostra/sequência do v68-09 em curso. O ponto (d) é uma
característica honesta e já conhecida do fix, não uma falha escondida — mas como
instruído, está sendo reportado explicitamente em vez de suavizado.

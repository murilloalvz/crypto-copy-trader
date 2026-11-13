# V68-10 — autorização pré-registrada — 2026-10-05

Modo: PAPER / RESEARCH / READ ONLY. Escrito e commitado antes do resultado do
v68-10 existir, pra ficar provado que foi escrito às cegas (mesmo padrão de
anteriores da V68 — ver `docs/v68-09-preregistered-decision-tree-2026-10-04.md`,
em `research/v68-09-fase-a-prereg`).

## Decisão do operador

`v68-10` é autorizado como o **único ciclo restante** do orçamento de infra da V68
definido na decisão-tree do v68-09 ("no máximo mais 1 ciclo, e só se o fix vier de
medição"). Se `v68-10` falhar por sistema de novo, **não há `v68-11`** até um sprint
de hardening dedicado — essa condição é fixada aqui, antes do resultado existir, não
decidida depois de olhar o dado.

## Causa raiz do v68-09, medida (não suposta)

- `v68-09-A` agendou a cohort completa (`decision_count=40`, `scheduled_count=120`)
  mas todos os 120 outcomes, nos 3 horizontes, ficaram `PENDING` pra sempre —
  `available=0` e `unavailable_or_error=0` em todo lugar.
- `Get-History` do operador: o comando real (`--run-key v68-09`) rodou das 17:31:48
  às 19:36:06 — 7458s de relógio, contra um esperado de ~3693s (120s de bridge +
  3573s de janela de coleta, pelo próprio `derived_runtime_seconds` impresso) sem
  travamento. Excesso de ~3765s, da mesma ordem da janela de ~59,6 minutos.
- `QuickEdit = 1` confirmado no console do operador.
- Caminho do código (`src/route_research_forward_collection_v43.py`, antes do fix):
  `deadline = time.monotonic() + runtime_seconds` é calculado imediatamente antes
  do único `print()` da função que roda antes de qualquer trabalho real; o loop de
  poll só checa `time.monotonic() < deadline` depois que esse print retorna. Um
  `print()` bloqueado pelo modo "QuickEdit" do console do Windows (seleção de
  texto trava `WriteConsole` até ser liberada) por mais tempo que a janela
  derivada faz o loop nunca executar nem uma iteração — exatamente a assinatura
  observada: zero submissões, zero capturas, zero erros.
- Conclusão: causa raiz é ambiental/operacional (console, não dado, não corte, não
  horizonte, não feature). Confirmado por código e pela aritmética do
  `Get-History`, não suposto.

## Fix autorizado para v68-10 (operacional + código, ambos já aplicados)

1. **Saída redirecionada para arquivo**: o comando real roda com a saída
   redirecionada para `logs\v68-10.log` (ex.: `... | Tee-Object -FilePath
   logs\v68-10.log` ou `*> logs\v68-10.log`), nunca escrevendo direto no console —
   elimina o mecanismo de travamento por `WriteConsole`/QuickEdit na raiz, não só
   detecta o sintoma.
2. **Stall guard mesclado** (`src/route_research_forward_collection_v43.py`, commit
   `e4e95e8`): se, ainda assim, algo travar o processo por mais de
   `FORWARD_COLLECTION_V43_STALL_GAP_SECONDS=30s` entre checagens, o coletor falha
   fechado com `FAIL_ROUTE_ONLY_FORWARD_COLLECTION_STALL_DETECTED` — explícito e
   distinto, não mais um `INCONCLUSIVE_NO_AVAILABLE_ROUTE_OUTCOME` indistinguível
   de uma queda real de provider.
3. **Telemetria por tentativa mesclada** (`src/jupiter_research_exit_route.py`,
   commit `6c8d47e`, A4): se `v68-10` falhar de novo por 429/lateness em vez de
   travamento, o `details` de cada outcome agora carrega `try`/`started_at`/
   `ended_at`/`status_code`/`backoff_seconds` por tentativa real — dado medido pra
   um próximo ajuste de hardening, não mais uma constante de backoff chutada.
4. **Sem suspensão de energia** durante a janela completa do run (plano de energia
   do Windows ajustado antes de iniciar).
5. **Janela 12h-19h BRT**, mesma recomendação que já funcionou para o gate de
   decision-count em `v68-08`/`v68-09`.
6. **Nenhum outro uso da chave Jupiter** durante a janela — nenhum outro processo,
   script ou sessão deste operador chamando a mesma `JUPITER_API_KEY` ao mesmo
   tempo.

Nenhum destes fixes toca `SUBCOHORT_MIN_DECISIONS`, `SUBCOHORT_CAP`,
`target_lateness_p95_max_seconds`, o contrato econômico da V68, ou qualquer outro
threshold congelado.

## O que acontece com o resultado

- **Falha de sistema** (inclusive um novo `FAIL_ROUTE_ONLY_FORWARD_COLLECTION_STALL_DETECTED`
  ou qualquer outro `FAIL_V68_SIGNAL_PLANE_SUBCOHORT`): logado no ledger, chaves
  `v68-10-A`/`v68-10-B` queimadas, causa raiz medida antes de qualquer proposta de
  fix. **Sem `v68-11`** — sprint de hardening dedicado é o próximo passo, decisão
  do operador sobre quando.
- **Chega ao gate econômico primário** (`PASS` ou `FAIL`/`INCONCLUSIVE` em
  `primary_gate_v68`): aplica-se exatamente a árvore de
  `docs/v68-09-preregistered-decision-tree-2026-10-04.md` (branches 2-4), sem
  modificação — nenhum threshold, corte, horizonte ou amostra é tocado por este
  documento.

## Guardrails (inalterados)

- Nenhum resultado FAIL/KILL/INCONCLUSIVE fechado é reaberto.
- Nenhum threshold econômico congelado é tocado.
- Nada vai para o signal plane ao vivo ou shadow sem veredito econômico escrito.

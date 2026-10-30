# Bundle Bot Detection V0 — escopo do encanamento (slot + creator) — 2026-10-07

Status: **documento de escopo. Não implementa nada, não autoriza nenhuma coleta, não congela
parâmetro nenhum.** Responde só "o que precisaria mudar e quanto custaria", para o operador decidir
se e quando abrir essa frente. Lido o pré-registro RASCUNHO completo
(`docs/bundle-bot-detection-v0-preregistration-DRAFT-2026-10-04.md`, ainda só na branch
`research/v68-09-fase-a-prereg`) e o código real desta checkout antes de escrever qualquer linha
abaixo.

## 1. Campos a persistir

- `slot` (inteiro, por trade) — o slot Solana em que a transação do trade foi incluída.
- `creator` (string, por token) — a wallet que criou o token (evento Pump `create`).
- `creation_slot` (inteiro, por token) — o slot em que a transação de criação foi incluída.

`bundle_flag` em si (`1` se alguma wallet != creator comprou no mesmo slot da criação) é **derivado**
destes três campos — não precisa de coluna própria, é calculado na hora da análise, não na hora da
persistência.

## 2. Onde isso já é decodificado hoje (confirmado por leitura direta, não por suposição)

- `src/pump_bonding_stream.py`:
  - `PumpLogNotification.slot: int` (linha 43) — já decodificado para TODA notificação de log, trade
    ou create.
  - `PumpCreateEvent.creator: str` (linha 36) — já decodificado para todo evento de criação.
  - `parse_logs_notification()` (linhas 232-285) já tem os dois em escopo simultaneamente: monta
    `PumpLogNotification(slot=slot, ..., lifecycle_events=tuple(lifecycle_events))` onde cada item de
    `lifecycle_events` já é um `PumpCreateEvent` com `.creator` preenchido.
- `benchmarks/integrated_market_signal_plane_v1/live_shadow.py` (o bridge que alimenta o Signal
  Plane promovido, usado por V68/PQ-V1/PQ-TR-V0):
  - `slot = normalized.get("slot")` (linha 568) — disponível para todo evento Carbon decodificado.
  - `row_slot = _nonnegative_int(row, "slot")` (linha 1431) — já extraído e usado para construir
    `PumpSwapPoolIdentityObservation(..., observed_slot=int(row_slot), ...)` (linha 1440) no MESMO
    bloco onde, poucas linhas depois (linha 1453), uma `MarketLifecycleObservation` é construída SEM
    slot nem creator.

Conclusão direta: **o dado não está perdido em Rust.** Em ambos os pontos verificados, `slot` (e,
para create events, `creator`) já existe em escopo Python exatamente no lugar onde
`MarketTradeObservation`/`MarketLifecycleObservation` são construídos — só não é passado pro
construtor porque o dataclass não tem campo pra receber. Isso não toca o hot path Rust, detector
semantics, trigger identity, ordering ou queue architecture (regra do CLAUDE.md sobre o Rust Signal
Plane) — fica inteiramente na camada de ingestão/persistência Python.

## 3. Onde falta hoje (o buraco exato)

- `MarketTradeObservation` (`src/market_opportunity_radar.py`, linhas 22-31): tem `chain_time`
  (segundos), não tem `slot`.
- `MarketLifecycleObservation` (mesma linha 35-39): não tem `creator` nem `creation_slot`.
- `record_market_trade`/`record_market_lifecycle` (`src/market_observation_store.py`, linhas 187 e
  274): os tuples `identity_values`/`INSERT`/`UPDATE`/`SELECT` não incluem esses campos — são
  extensões mecânicas das mesmas tuplas já existentes, não lógica nova.
- Tabelas SQLite `market_trade_observations`/`market_lifecycle_observations` (mesmo arquivo, linhas
  ~29-63): sem as colunas.

### Inventário de chamadas que precisam ser auditadas (não confirmadas uma a uma nesta passada)

Além dos dois pontos verificados na seção 2, mais **17 arquivos de produção** chamam
`MarketTradeObservation(...)` ou `MarketLifecycleObservation(...)` diretamente: `pumpswap_stream.py`,
`pumpswap_normalized_persistence.py`/`_v2`/`_v3`, `pumpswap_causal_normalization_v5.py`,
`carbon_market_trade_adapter.py`, `route_research_v68_release.py`, e as pipelines em
`benchmarks/{launch_burst_replay_v0,market_first_live_discovery_v0,commodity_signal_plane_v0,
market_first_live_smoke_v0,market_first_signal_plane_v0,market_first_capacity_harness_v0}`. Cada um
precisaria ser confirmado individualmente antes da implementação — o padrão observado nos dois
pontos verificados (slot disponível em escopo, só não passado) é consistente com a arquitetura
(toda notificação RPC Solana carrega `context.slot` por protocolo), mas **não foi verificado arquivo
por arquivo nesta passada**. Isso é o primeiro passo real de implementação, não um passo de escopo.

## 4. Migração de schema (padrão já existente neste mesmo arquivo, sem invenção)

`src/market_observation_store.py:97-116` (`ensure_market_observation_schema`) já resolve exatamente
este problema para a coluna `transaction_key`: adiciona a coluna ao `_SCHEMA` base (serve DBs novos)
e faz `ALTER TABLE market_trade_observations ADD COLUMN transaction_key TEXT` guardado por
`if "transaction_key" not in _column_names(conn, "market_trade_observations")` (serve DBs locais já
existentes, sem apagar nada). A extensão para `slot`/`creator`/`creation_slot` seguiria o mesmo
padrão, nullable, sem default mágico — três `ALTER TABLE ADD COLUMN` guardados da mesma forma, um
por coluna nova.

## 5. `observed_at` causal

Nenhuma mudança de semântica: `observed_at` já é o relógio causal de todo observation
(`notification.observed_at`/`learned_at`, nunca derivado do dado em si). `slot`/`creation_slot` são
fatos do dado (quando a transação foi incluída na chain), `observed_at` continua sendo quando o
processo *descobriu* isso — as duas coisas não se confundem, igual já acontece hoje com
`chain_time` vs `observed_at`.

## 6. Sem backfill

Regra do CLAUDE.md ("historical data may not receive fake historical `observed_at`") aplica-se
diretamente: linhas já persistidas sem `slot`/`creator` ficam `NULL` para sempre — não se decodifica
`raw_json` histórico pra preencher essas colunas retroativamente com um `observed_at` de hoje. A
cobertura começa em zero no momento do deploy e cresce só com captura nova.

## 7. Testes

Mínimo, seguindo a disciplina de "teste mais estreito relevante" do CLAUDE.md:

- `tests/test_market_observation_store.py`: round-trip de `record_market_trade`/`record_market_lifecycle`
  com `slot`/`creator`/`creation_slot` presentes e ausentes (`None`); confirmar que o `ALTER TABLE`
  guardado não quebra um DB criado antes da migração (teste de upgrade, não só de DB novo).
- `tests/test_pump_bonding_stream.py`: confirmar que `persist_pump_notification` agora passa
  `notification.slot` e `event.creator` pros dois construtores, sem mudar nenhum outro campo.
- Os outros ~17 call sites (seção 3) ficam fora do escopo mínimo até serem auditados individualmente
  — ponytail: não escrever teste para código que ainda não foi tocado.

Não existe hoje nenhum teste que dependa da AUSÊNCIA de `slot`/`creator` (confirmado: são campos
novos, opcionais, sem default não-`None`) — não se espera quebra de teste existente, só extensão.

## 8. Fora da linhagem congelada do V68

V68 roda por `route_research_signal_plane_bridge_v0.py` → `SignalPlaneRouteResearchCoordinatorV0` →
Rust hot path (`benchmarks/integrated_market_signal_plane_v1`) — nenhuma linha desse caminho muda
aqui. O risco real de contaminação está nos testes que hoje cobrem especificamente
V68/Signal-Plane-promoted (`test_integrated_market_signal_plane_v1.py`,
`test_rust_signal_plane_live_shadow_v0.py`, `test_signal_plane_v68_feature_bridge_v0.py`,
`test_signal_plane_episode_admission_v0.py`, `test_signal_plane_episode_bridge_v0.py`,
`test_signal_plane_research_persistence_v0.py`) — esses precisam continuar passando *sem
modificação de asserção*, só aceitando os dois dataclasses com campos novos opcionais. Se qualquer um
desses exigir mudança de asserção para passar, isso é o sinal de alerta que o CLAUDE.md pede:
documentar e não prosseguir sem revisão, porque indicaria que o V68 lineage dependia implicitamente
da forma antiga do dataclass.

## 9. Estimativa de captura nova para a discovery (não medível hoje, é por isso que step 0 existe)

A proposta do RASCUNHO é 40 episódios com bundle pareados por atividade. Não há como medir a taxa
real de `bundle_flag=1` hoje — é exatamente o dado que falta persistir. Dá pra colocar uma faixa,
não um número:

- Capturas já observadas nesta sessão (mesmo radar market-first, janelas de 900s): entre ~75 e ~145
  episódios admitidos por janela (`baseline_selected_count` 76 e 142, CD-PROMO-V0 2026-10-06/07).
- Se a taxa real de bundle (pelo menos uma wallet != creator comprando no slot exato da criação) for
  de ordem alta (10-20% dos lançamentos — plausível dado o quanto bots de sniping saturam pump.fun,
  por evidência externa coletada nesta sessão), 40 episódios pareados seriam alcançáveis em ~2-4
  janelas de 900s, ou seja, possivelmente **1 dia** de captura repetida.
- Se a taxa real for próxima da fração estritamente insider-financiada medida externamente (~1,75%
  dos lançamentos, Mobula/pesquisa externa), o mesmo alvo poderia levar **mais de uma semana**,
  porque o pareamento por atividade (exigir um episódio sem-bundle comparável na mesma janela de
  horário/venue) reduz ainda mais o rendimento por janela.
- Não dá pra saber qual faixa é real sem rodar step 0 primeiro — essa é a resposta honesta, não um
  número inventado.

## 10. Mesmo encanamento que destrava o v61

`docs/direct-funding-link-v61-protocol-2026-09-08.md` exige saber o `creator` de cada token e cruzar
com transferências SOL anteriores ao lançamento — a mesma lacuna de `creator` nomeada na seção 3
acima bloqueia os dois. `creation_slot`/`slot` de trade não é necessário pro v61 em si (v61 usa
`chain_time` de transferência vs lançamento, não slot), mas como os dois bloqueiam no mesmo PASSO 0
de observabilidade de `creator`, resolver esta migração para o Bundle Bot Detection V0 libera o v61
também, sem trabalho extra de schema.

## 11. O que este documento não decide

- se vale a pena abrir esta frente agora (comparado a priorizar a replicação do PQ-TR-V0, já em
  andamento nesta mesma sessão);
- o tamanho exato da auditoria dos ~17 call sites restantes;
- qualquer parâmetro do discovery do Bundle Bot Detection V0 em si (isso é do pré-registro
  RASCUNHO, que continua RASCUNHO).

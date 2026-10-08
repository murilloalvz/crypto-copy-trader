# SIG-FAST V0 — motor ao vivo: wiring de reservas + bloqueadores (2026-10-09)

Resposta ao item 1 da revisão do operador (handoff `f00a19a`/`9d4a526`). Investigação
completa, correção do que não precisa de Rust, e tudo que precisa parado aqui para
decisão do operador.

## Cadeia real confirmada (não suposta)

`benchmarks/integrated_market_signal_plane_v1/live_shadow.py` (`run_live_shadow_v0`, o
motor que V68/PQ-V1/PQ-TR de fato usam) spawna via `subprocess`
`benchmarks/carbon_decoder_parity_v1/rust_runner` (confirmado: import direto de
`benchmarks.carbon_decoder_parity_v1.parity` e referência de path na linha 76) para
decodificar payloads Pump/PumpSwap, depois chama
`src/carbon_matched_unit_adapter.py::adapt_carbon_pump_trade_v0`/
`adapt_carbon_pumpswap_trade_v0` → `src/carbon_market_trade_adapter.py::adapt_carbon_matched_unit_to_market_trade_v0`
para construir `MarketTradeObservation`, injeta `slot` via `dataclasses.replace`
(plumbing já existente, `bundle-bot-detection-v0-plumbing`), monta `signal_record` e manda
pro kernel Rust de detecção (`benchmarks/integrated_market_signal_plane_v1/rust_runner`,
**este sim é o hot path congelado** nomeado no CLAUDE.md). A persistência real passa por
`src/signal_plane_research_persistence_v0.py::persist_signal_plane_research_batch` →
`src/market_observation_batch_v0.py::record_market_observations_batch_v0` — **não** pelo
`record_market_trade` de linha única que os testes de F1b exercitaram.

Dois Rust diferentes, só um é congelado:

- `carbon_decoder_parity_v1/rust_runner` — decodifica bytes de payload em JSON. Cargo
  crate separado, usado como ferramenta de decodificação/parity, **não é** "o hot path
  Rust" nomeado em `CLAUDE.md` (que cita especificamente
  `benchmarks/integrated_market_signal_plane_v1/rust_runner/Cargo.toml`).
- `integrated_market_signal_plane_v1/rust_runner` — o kernel de detecção/trigger
  (fresh_market_burst, activity_acceleration). **Este é o congelado.** Confirmei que seu
  `struct Trade` (Rust, `#[derive(Deserialize)]`, sem `deny_unknown_fields`) ignora
  silenciosamente qualquer campo JSON que não conhece — então adicionar campos novos ao
  lado Python nunca quebra nem precisa alterar este arquivo. `slot` já prova isso: foi
  adicionado ao dataclass e ao payload sem o kernel notar.

## (a) O que o Carbon já traz — campo e arquivo

Fonte: `benchmarks/carbon_decoder_parity_v1/rust_runner/src/main.rs`, função
`decode_event` (linhas ~88-176), confirmada por leitura direta (não por teste de parity,
que não compara reservas).

| Evento | Campo no JSON do Carbon | Linha | Confirmado? |
|---|---|---|---|
| `pump_trade` | `sol_amount_raw` (quote) | 102 | sim |
| `pump_trade` | `token_amount_raw` (base) | 103 | sim |
| `pump_trade` | `virtual_quote_reserves_raw` | 111-113 | sim |
| `pump_trade` | `virtual_token_reserves_raw` (base/reserva do token) | — | **NÃO existe** |
| `pump_trade` | `fee`/`fee_basis_points`/`creator_fee`/`creator_fee_basis_points` | — | **NÃO existem** |
| `pumpswap_buy`/`sell` | `base_amount_raw` | 145/166 | sim |
| `pumpswap_buy`/`sell` | `quote_amount_raw` | 146/167 | sim |
| `pumpswap_buy`/`sell` | `pool_base_token_reserves_raw` | 148-150/169-171 | sim |
| `pumpswap_buy`/`sell` | `pool_quote_token_reserves_raw` | 151-153/172-174 | sim |
| `pumpswap_buy`/`sell` | `lp_fee`/`protocol_fee`/`coin_creator_fee` (e seus `*_basis_points`) | — | **NÃO existem** |

PumpSwap: **completo** (base+quote, amounts+reservas). Pump: **parcial** — quote
completo (amount+reserva), base só tem o amount, falta a reserva.

## (b) Wiring feito — sem tocar nenhum Rust

- `benchmarks/integrated_market_signal_plane_v1/live_shadow.py`: nova função pura
  `_raw_price_path_fields_from_row(row, event_type=...)`, chamada no mesmo ponto onde
  `slot` já era injetado (`dataclasses.replace`). PumpSwap recebe os 4 campos completos;
  Pump recebe 3 (`base_amount_raw`, `quote_amount_raw`, `quote_reserves_raw`),
  `base_reserves_raw` fica `None` (não disponível, não inventado).
- `src/market_observation_batch_v0.py`: **achado crítico separado** — este arquivo tem
  SQL duplicada própria (`_record_trade_conn`) que **nunca carregava nem `slot`** (gap do
  próprio `bundle-bot-detection-v0-plumbing`, não pego pelos testes daquele commit porque
  eles não exercitam o caminho de batch) **nem os 4 campos novos do F1b**. É este caminho
  de batch, não `record_market_trade`, que `persist_signal_plane_research_batch` de fato
  chama. Sem esta correção, nada do wiring acima chegaria no banco. Estendido: schema de
  identidade, SELECT, INSERT, UPDATE agora incluem `slot` + os 4 campos.
  - **Não corrigido (fora do escopo desta revisão)**: `_record_lifecycle_conn` no mesmo
    arquivo tem o mesmo gap para `creator`/`creation_slot` (campos do
    `bundle-bot-detection-v0-plumbing`, não do SIG-FAST). Flagado aqui, não tocado — o
    operador não pediu isso nesta revisão e corrigir sem pedido seria escopo além do
    evidenciado.

## (c)/(d) BLOQUEADO — precisa de decisão do operador

Dois gaps exigem editar `benchmarks/carbon_decoder_parity_v1/rust_runner/src/main.rs`
(Rust, mas **não** o hot path congelado nomeado no CLAUDE.md):

1. **`virtual_token_reserves_raw` do pump_trade não é serializado para JSON.** O decoder
   Carbon (`TradeEventEvent`, da crate `carbon-pumpfun-decoder`) decodifica o payload
   completo via IDL — o campo quase certamente existe na struct Rust decodificada, só não
   é escrito no `object.insert(...)` da linha ~103-118. Se existir, expor custa 1 linha
   Rust. Sem isso, a bonding curve do pump nunca terá `base_reserves_raw`, e todo o
   caminho de preço do pump (slippage AMM de `simulate_amm_buy_execution_price_sol`)
   fica sem par de reservas — PumpSwap não tem esse problema.
2. **Nenhuma fee real (pump: `fee`/`creator_fee`; PumpSwap: `lp_fee`/`protocol_fee`/
   `coin_creator_fee`) é serializada para JSON em nenhum dos dois eventos.** Mesma
   situação: os campos são padrão do IDL oficial (confirmado em sessão anterior,
   `pump.json`/`pump_amm.json`), quase certamente já decodificados pela struct Rust, só
   não expostos. Bloqueia o item (d) do pedido do operador por completo — não dá pra
   "aproveitar e persistir as fees reais" sem essa edição Rust primeiro.

**Por que parei em vez de decidir sozinho**: a instrução foi explícita ("se exigir mexer
no hot path Rust → PARAR e me trazer"). Mesmo não sendo *o* hot path congelado do
CLAUDE.md, é Rust de produção, e a prudência de "não mexer em Rust casualmente" se aplica.
Não editei `carbon_decoder_parity_v1/rust_runner/src/main.rs`.

**Se o operador autorizar**, a mudança é pequena e isolada: confirmar que
`TradeEventEvent`/`BuyEventEvent`/`SellEventEvent` (as structs geradas pelas crates
`carbon-pumpfun-decoder`/`carbon-pump-swap-decoder`) já têm os campos
(`virtual_token_reserves`, `fee`, `creator_fee`, `lp_fee`, `protocol_fee`,
`coin_creator_fee`) acessíveis, e adicionar um `object.insert(...)` por campo — sem mudar
discriminador, parsing, nem o conjunto de 150 eventos congelado da parity suite (mesmo
padrão das linhas 105-107: "Extra research fields are intentionally outside the frozen
parity field set").

## (e) Teste de ponta a ponta

`tests/test_rust_signal_plane_live_shadow_v0.py::test_live_adapter_chain_threads_price_path_fields_into_persisted_observation`:
row sintético de `pump_trade` → `adapt_carbon_pump_trade_v0` → `adapt_carbon_matched_unit_to_market_trade_v0`
→ injeção de `slot` + `_raw_price_path_fields_from_row` (exatamente a sequência do loop
real) → `record_market_observations_batch_v0` (o caminho de batch real, não o de linha
única) → `load_market_trades`. Confirma que `base_amount_raw`/`quote_amount_raw`/
`quote_reserves_raw` chegam no banco; `base_reserves_raw` fica `None` (esperado, ver
bloqueador 1 acima). Mais 3 testes unitários da função pura nova. 59 testes totais
rodados neste arquivo+arquivos relacionados, todos passando. Suíte completa do repo:
1926 testes, 1 falha isolada e não relacionada (`test_pumpswap_demoted_audit_lane_v9`,
sensível a timing/carga, passa isoladamente, não tocada nesta sessão).

### Runbook de smoke test (2 min, operador roda em casa)

1. Rodar `run_live_shadow_v0` por uma janela curta (ex. 60-120s) contra um `acquisition_run_key`
   novo e descartável, com o feed real (ou um fixture de WS, se preferir não gastar
   créditos Helius por esse teste).
2. Parar a run.
3. Rodar `benchmarks/sig_fast_v0/path_coverage_audit.py --acquisition-run-key <chave> --limit 5`
   (F1c, já existente) sobre o mesmo banco.
4. Esperado agora: `n_price_from_amounts` > 0 para tokens PumpSwap (e para pump, via
   `sol_amount_raw`/`token_amount_raw`); `n_price_from_reserves` > 0 só para PumpSwap até
   o bloqueador 1 acima ser resolvido (pump ainda fica 0, por falta de
   `base_reserves_raw`). Isso é esperado e não é bug.
5. Reportar as contagens — não reportar nenhum preço/retorno (regra de todas as fases).

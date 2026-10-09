# SIG-FAST price-path persistence V0 — auditoria (F1a) + design (F1b) — 2026-10-08

Branch: `sig-fast-price-path-persistence-v0`, baseada em `bundle-bot-detection-v0-plumbing`
(commit `7f72804`), não na branch de autoridade (`research/rust-signal-plane-live-shadow-v0`).
Motivo: essa branch já implementa o plumbing de `slot`/`creator`/`creation_slot` em
`MarketTradeObservation`/`MarketLifecycleObservation` e `market_observation_store.py`
(commit `367ed12`), que F1b reaproveita em vez de reimplementar (regra do work order
2026-10-08: "Reaproveitar o slot/creator do branch bundle-bot-detection-v0-plumbing se
fizer sentido, e documentar"). Consequência: esta branch **herda a mesma dependência não
mergeada** — não mergear nenhuma das duas na autoridade antes da replicação do PQ-TR.

Nenhum dado de outcome foi lido. Nenhum hot path Rust foi tocado — toda mudança é na
camada de persistência/decoders Python (`src/pump_bonding_stream.py`,
`src/pumpswap_stream.py`, `src/market_opportunity_radar.py`,
`src/market_observation_store.py`).

## F1a — o que já era decodificado e descartado

### Pump TradeEvent (`src/pump_bonding_stream.py::decode_pump_trade_event_payload`, linha ~129-170 antes desta mudança)

IDL oficial confirmado (`pump-fun/pump-public-docs`, `idl/pump.json`, tipo `TradeEvent`,
35 campos): `mint, sol_amount, token_amount, is_buy, user, timestamp,
virtual_sol_reserves, virtual_token_reserves, real_sol_reserves, real_token_reserves,
fee_recipient, fee_basis_points, fee, creator, creator_fee_basis_points, ...`.

- **Decodificado e mantido** (linhas antigas 146/148/150/154/156, guardado no retorno
  146→165, 148→166, 150→167, 154→168, 156→169): `mint`, `sol_amount`, `token_amount`,
  `is_buy`, `user`, `timestamp`.
- **Não decodificado** (nunca lido, não é "decodificado e descartado" — a função
  retornava assim que lia `timestamp`; docstring antiga dizia explicitamente "Later
  fields are intentionally ignored"): `virtual_sol_reserves`, `virtual_token_reserves`,
  `real_sol_reserves`, `real_token_reserves` e tudo depois.
- Na persistência (`persist_pump_notification`, linhas antigas 327-328):
  `notional_usd=None, price_usd=None` hardcoded; `sol_amount`/`token_amount` eram usados
  só pelo filtro `event.sol_amount <= 0` (linha 319), nunca persistidos.

### PumpSwap Buy/SellEvent (`src/pumpswap_stream.py::_decode_trade_event_payload`, linha ~286-316 antes desta mudança)

IDL oficial confirmado (`idl/pump_amm.json`): `BuyEvent` (40 campos) e `SellEvent` (33
campos) compartilham os mesmos 13 campos `u64` consecutivos logo depois de `timestamp`
e antes dos pubkeys `pool`/`user`, na mesma ordem relativa:

| índice em `amounts` (`struct.unpack_from("<13Q", ...)`, linha antiga 299) | BuyEvent | SellEvent |
|---|---|---|
| 0 | `base_amount_out` | `base_amount_in` |
| 1 | `max_quote_amount_in` | `min_quote_amount_out` |
| 2 | `user_base_token_reserves` | `user_base_token_reserves` |
| 3 | `user_quote_token_reserves` | `user_quote_token_reserves` |
| 4 | **`pool_base_token_reserves`** | **`pool_base_token_reserves`** |
| 5 | **`pool_quote_token_reserves`** | **`pool_quote_token_reserves`** |
| 6 | `quote_amount_in` | `quote_amount_out` |
| 7 | `lp_fee_basis_points` | `lp_fee_basis_points` |
| 8 | `lp_fee` | `lp_fee` |
| 9 | `protocol_fee_basis_points` | `protocol_fee_basis_points` |
| 10 | `protocol_fee` | `protocol_fee` |
| 11 | `quote_amount_in_with_lp_fee` | `quote_amount_out_without_lp_fee` |
| 12 | `user_quote_amount_in` | `user_quote_amount_out` |

- **Decodificado e mantido** (linha antiga 299 lê tudo, linhas 314/315 guardam só 2):
  `amounts[0]` → `base_amount_raw`, `amounts[6]` → `quote_amount_raw`.
- **Decodificado e DESCARTADO** (lido em `amounts`, nunca guardado): índices 1,2,3,**4,5**
  ,7,8,9,10,11,12 — em especial **4 e 5 (reservas pós-trade do pool)**, que é exatamente o
  que F1b precisa para derivar preço.
- **Não decodificado** (a checagem de tamanho mínimo da linha antiga 293-294 parava
  exatamente em `user`): `coin_creator`, `coin_creator_fee_basis_points`,
  `coin_creator_fee`, `cashback*`, `buyback*`, `virtual_quote_reserves` (i128),
  `can_boost`, e tudo depois.
- Na persistência (linhas antigas 500-501): `notional_usd=None, price_usd=None`
  hardcoded, mesmo padrão do Pump.

## F1b — persistência mínima implementada

Reaproveita o contrato existente (`market_trade_observations`, mesmo padrão de
`ALTER TABLE` guardado já usado para `transaction_key`/`slot`) em vez de criar tabela
nova — ladder do Ponytail, rung 2 ("já existe no código? reusa").

4 colunas novas, todas `INTEGER NULL`, genéricas o bastante pra cobrir os dois venues
sem inventar uma segunda convenção de nomes:

- `base_amount_raw` — quantidade do lado base (token) do trade, em unidades on-chain
  cruas (sem ajuste de decimais). Pump: `token_amount`. PumpSwap: `base_amount_out`/
  `base_amount_in`.
- `quote_amount_raw` — quantidade do lado quote, em unidades cruas. Pump: `sol_amount`
  (sempre SOL nesse adapter v1). PumpSwap: `quote_amount_in`/`quote_amount_out` (SOL/WSOL
  na prática atual dos pools PumpSwap, não verificado caso a caso aqui).
- `base_reserves_raw` — reservas do pool **pós-trade**, lado base. Pump:
  `virtual_token_reserves` (agora decodificado, ver abaixo). PumpSwap:
  `pool_base_token_reserves` (já decodificado, só não persistido).
- `quote_reserves_raw` — reservas do pool pós-trade, lado quote. Pump:
  `virtual_sol_reserves`. PumpSwap: `pool_quote_token_reserves`.

**Decisão deliberada: preço NÃO é persistido nesta tabela.** "Preço por trade = derivado
das reservas/amounts em SOL" (instrução do operador) é tratado como uma função pura sobre
`(base_amount_raw, quote_amount_raw, base_reserves_raw, quote_reserves_raw)`, implementada
em F2 (`src/opportunity_path_metrics_v0.py`), não como coluna armazenada — evita decidir
agora, na camada de persistência, uma convenção de decimais de token que pode variar
(pump.fun tokens são tipicamente 6 decimais, mas isso não é verificado aqui campo a campo
e não deve ser assumido silenciosamente num INSERT). Mantém a tabela como fato bruto,
auditável, sem conversão aplicada.

### Mudanças de código

- `src/market_opportunity_radar.py`: `MarketTradeObservation` ganha os 4 campos opcionais
  acima (default `None`, aditivo, não quebra nenhum call site existente).
- `src/market_observation_store.py`: schema + `ensure_market_observation_schema` (ALTER
  TABLE guardado) + `_validate_trade` (checagem não-negativa) + `record_market_trade`
  (identity tuple, SELECT, INSERT, UPDATE) + `load_market_trades` (SELECT, construção do
  dataclass) estendidos para as 4 colunas.
- `src/pump_bonding_stream.py`: `PumpTradeEvent` ganha `virtual_sol_reserves`/
  `virtual_token_reserves` (opcionais). `decode_pump_trade_event_payload` agora lê esses
  2 campos `u64` adicionais **de forma oportunista** — só se o payload tiver bytes
  suficientes (`len(payload) >= offset + 16`), senão fica `None`. Isso preserva
  compatibilidade com payloads mais curtos (ex.: versão antiga do programa) sem quebrar
  nada, e mantém a missingness explícita (invariante 6 do CLAUDE.md) em vez de assumir
  zero. `persist_pump_notification` agora passa
  `base_amount_raw=token_amount, quote_amount_raw=sol_amount,
  base_reserves_raw=virtual_token_reserves, quote_reserves_raw=virtual_sol_reserves`.
- `src/pumpswap_stream.py`: `PumpSwapTradeEvent` ganha `pool_base_token_reserves`/
  `pool_quote_token_reserves` (opcionais, mas sempre preenchidos quando o evento decodifica
  — já estavam dentro do `amounts` lido). `_decode_trade_event_payload` passa a guardar
  `amounts[4]`/`amounts[5]`. A persistência (`persist_pumpswap_notification`) passa
  `base_amount_raw`, `quote_amount_raw`, `base_reserves_raw=pool_base_token_reserves`,
  `quote_reserves_raw=pool_quote_token_reserves`.

### O que NÃO foi feito nesta passada (limite de escopo deliberado)

Outros pontos de ingestão que também constroem `MarketTradeObservation` — citados no
commit `367ed12` desta mesma branch (`pumpswap_normalized_persistence.py`/`_v2`/`_v3`,
`pumpswap_causal_normalization_v5.py`,
`integrated_market_signal_plane_v1/live_shadow.py`, este último o motor ao vivo que
V68/PQ-V1/PQ-TR de fato usam) — **não foram threadados com os 4 campos novos nesta
passada**. F1a cobriu só os dois decoders que o work order nomeou explicitamente
("TradeEvent do pump" e "Buy/SellEvent do PumpSwap"); estender os outros pontos de
ingestão é trabalho futuro, não incluído aqui, para não alargar o escopo desta fase
("Do not perform broad cleanup/refactors while fixing a scoped issue", CLAUDE.md).
Qualquer coleta via `live_shadow.py` hoje continua sem essas 4 colunas preenchidas.

`real_sol_reserves`/`real_token_reserves` (Pump) e os campos de fee por trade
(`lp_fee`, `protocol_fee`, `coin_creator_fee`, já confirmados no IDL do PumpSwap) também
não foram persistidos nesta passada — não são necessários para o caminho de preço (F2),
só para custo real (relevante a F4), e persisti-los exigiria mais 2-6 colunas que não
foram pedidas por F1b. Podem ser adicionados depois, no mesmo padrão de ALTER TABLE
guardado, sem migração custosa.

## Testes

`tests/test_pump_bonding_stream.py` e `tests/test_pumpswap_stream.py` estendidos (não
reescritos): decode com/sem reservas presentes, e persistência end-to-end confirmando que
`base_amount_raw`/`quote_amount_raw`/`base_reserves_raw`/`quote_reserves_raw` sobrevivem
ida (`persist_*_notification`) e volta (`load_market_trades`). `python3 -m unittest
tests.test_pump_bonding_stream tests.test_pumpswap_stream tests.test_market_observation_store`
— 33 testes, todos passando.

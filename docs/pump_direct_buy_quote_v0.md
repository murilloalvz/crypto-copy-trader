# Pump Direct Bonding-Curve BUY Quote V0

Status: read-only execution research primitive. This is **not** a trading provider and does not alter any frozen Launch Burst contract.

## Purpose

Separate two questions that must not be conflated:

1. Can a third-party router/provider expose a route for a very early Pump launch?
2. Given a causal Pump bonding-curve state and fee schedule, what does Pump's own documented curve math quote for the BUY?

V0 addresses only the second question for BUYs.

## Canonical math source

The implementation follows Pump's current public protocol documentation for `buy_exact_quote_in_v2` in:

- `pump-fun/pump-public-docs/idl/pump.json`
- `pump-fun/pump-public-docs/idl/pump.ts`
- `pump-fun/pump-public-docs/docs/PUMP_PROGRAM_README.md`

The documented exact-quote-in sequence is:

1. `net_quote = floor(spendable_quote * 10_000 / (10_000 + total_fee_bps))`
2. protocol and creator fees are each rounded up from `net_quote`
3. if `net_quote + fees` exceeds the spendable budget because of rounding, reduce `net_quote` by the overrun
4. `tokens_out = floor((net_quote - 1) * virtual_token_reserves / (virtual_quote_reserves + net_quote - 1))`

The documented reverse BUY quote for desired tokens is also implemented:

1. `net_quote = ceil(tokens * virtual_quote_reserves / (virtual_token_reserves - tokens)) + 1`
2. `spendable_quote = ceil(net_quote * (10_000 + total_fee_bps) / 10_000)`

All arithmetic is integer/raw-unit arithmetic.

### Split-fee rounding nuance

V0 intentionally preserves both the documented reverse budget and the sum obtained by separately rounding protocol and creator fees.

Because:

`ceil(protocol_fee) + ceil(creator_fee)`

can be one raw quote unit larger than:

`ceil(total_fee)`

the documented reverse `spendable_quote` can occasionally be one raw unit below `net_quote + protocol_fee + creator_fee`. The forward exact-input formula then performs its documented overrun correction and may return slightly fewer tokens than the requested reverse amount.

V0 exposes:

- `documented_spendable_quote_raw` — the canonical reverse formula result;
- `computed_total_quote_raw` — `net_quote + separately_rounded_protocol_fee + separately_rounded_creator_fee`.

Downstream execution research must preserve this distinction rather than silently modifying the canonical formula. If a fee-exact conservative max-cost is required, `computed_total_quote_raw` is the safer raw-unit budget to test, subject to later validation against the actual Pump instruction/runtime.

## Fee policy

V0 **does not derive fee tiers**.

Pump's fee schedule can depend on current protocol configuration / fee tiers. Therefore `protocol_fee_bps` and `creator_fee_bps` are explicit inputs. A later causal adapter may populate those from observed on-chain/config evidence.

Hard-coding today's headline fee into historical or prospective evidence would be scientifically wrong.

## Real reserve policy

The public exact-input formula is applied to virtual reserves. V0 additionally checks the result against observed `real_token_reserves_raw`.

If the formula's output exceeds real token reserves, V0 returns:

`REAL_TOKEN_RESERVE_LIMIT`

and does **not** claim an executable amount. It deliberately does not invent a partial-spend rule without an equally explicit canonical specification.

## Graduation

If `complete == true`, V0 refuses to produce a bonding-curve BUY execution claim. Post-graduation execution belongs to PumpSwap and remains a separate stratum/path.

## Explicit non-goals

V0 does not:

- fetch bonding-curve accounts;
- fetch fee config;
- derive current tiered fee rates;
- build instructions;
- sign transactions;
- submit transactions;
- claim landed fills;
- model priority fees/rent;
- implement SELL quoting;
- merge Pump with PumpSwap;
- replace Jupiter in the frozen Route-Paper V2 experiment.

SELL math will only be added after its current rounding/fee semantics are pinned to an equally authoritative source.

# Launch Burst V4 — Funded Taker Gate V0

## Status

This is an operational execution-fixture gate for the frozen Solana Launch Burst V4 prospective route-paper experiment.

It does **not** modify the economic hypothesis, selector, feature window, costs, notional, or exit policy.

Current scientific state before this gate:

- systems/timing: **PASS / CLOSED**;
- selector: `pump_launch`, 5s, `signed_flow_over_event_reserve >= 0.08`, no confirmation;
- route contract hash: `3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d`;
- first V4 economic acquisition: **INCONCLUSIVE** because 57/57 admitted entries were `ROUTE_ONLY_UNEXPECTED`;
- representative Jupiter diagnostic: valid ~$25 pricing, `router=okx`, `mode=manual`, `transaction_present=false`, `error_code=1`, `Insufficient funds`;
- taker balance at diagnosis: 0 USDC and 0 SOL.

Therefore the current blocker is an **unfunded execution fixture**, not timing, route absence, or negative signal economics.

## Frozen operational fixture

File:

`benchmarks/launch_burst_prospective_route_live_v4/funded_taker_fixture_v0.frozen.json`

The fixture freezes before the next acquisition:

- the route-contract hash;
- the taker identity by SHA-256 of its public key;
- USDC as the input asset;
- minimum USDC balance = `25_000_000` raw units = the already-frozen US$25 notional;
- minimum SOL balance = `10_000_000` lamports = 0.01 SOL operational floor;
- entry slippage = the already-frozen 100 bps;
- one known-liquid control output (wrapped SOL);
- one representative Burst output mint;
- no adaptive top-up after acquisition starts;
- read-only assembly probes only.

The 0.01 SOL threshold is an operational assembly floor, not a modeled trade cost or economic parameter. Trade costs remain exclusively defined by the frozen route-paper contract.

## Fail-closed preflight

Command module:

`benchmarks.launch_burst_prospective_route_live_v4.funded_taker_preflight`

PASS classification:

`PASS_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT`

The preflight fails closed unless all of the following hold:

1. fixture schema/status/hash are valid;
2. route-contract hash is unchanged;
3. input mint/decimals/notional/slippage still match the frozen contract;
4. `JUPITER_TAKER_PUBLIC_KEY` hashes to the frozen taker identity;
5. USDC balance is at least the frozen US$25 input amount;
6. SOL balance is at least the predeclared 0.01 SOL operational floor;
7. a read-only Jupiter `/order` probe for USDC -> wrapped SOL returns an assembled candidate transaction;
8. a read-only Jupiter `/order` probe for USDC -> representative Burst token returns an assembled candidate transaction.

If balance checks fail, Jupiter probes are not run.

The report records router/mode/error metadata and whether a transaction was present, but never stores the serialized candidate transaction. The preflight never signs or submits a transaction and opens no economic outcome.

## Funding rule

Funding is allowed only before acquisition and only for a wallet controlled by the researcher.

Do not fund an address unless ownership/control is independently known.

After the fixture is funded and frozen:

- no adaptive top-up after a signal;
- no changing taker identity mid-run;
- no changing the US$25 economic notional;
- no changing selector/threshold/window/costs to obtain PASS.

A balance above the minimum is allowed as static operational margin; the prospective trade notional remains exactly US$25.

## Next gate

Only after the funded-taker preflight PASS may the V4 prospective economic live be repeated, unchanged.

If either assembly probe fails, classify the result as a new execution-fixture/provider blocker, preserve the error evidence, and do not start the 900s live.

If the funded-taker preflight passes, send the result to the alignment chat before starting the next material prospective acquisition.

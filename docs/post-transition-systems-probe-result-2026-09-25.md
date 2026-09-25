# Post-Transition Pullback / Reacceleration V0 — Systems Probe Result — 2026-09-25

Status: PASS SYSTEMS / NO ECONOMIC OUTCOME / NO LIVE MONEY

## Frozen code identity

Branch:

`research/post-transition-pullback-reacceleration-v0`

Probe HEAD:

`6aebd3063063da89c30bdf7c6c523c5ec30c0019`

## Result

Classification:

`PASS_POST_TRANSITION_REACCELERATION_SYSTEMS_PROBE_V0`

Observed during the 120-second systems-only probe:

- notifications: 41,313;
- PumpSwap trade events: 27,495;
- direct CreatePool events: 3;
- role-valid transition states: 3;
- trades anchored to those direct transition states: 3,248;
- causal snapshots produced: 3,248;
- trades whose pool transition predated the probe window: 24,247;
- active transition states at completion: 3;
- structural-reacceleration pools observed: 0;
- transport error: none;
- economic outcomes opened: false;
- provider economic calls used: false.

Transport selection:

- configured Alchemy endpoint did not expose `logsSubscribe`;
- public Solana mainnet WSS accepted the PumpSwap subscription and completed the probe.

## Interpretation

This PASS proves only the real-market plumbing:

`direct PumpSwap CreatePool -> normalized asset role -> anchored Buy/Sell events -> causal research state`.

It does not prove economic edge or the frequency of the pullback/reacceleration pattern.

The observed structural-reacceleration count of zero is descriptive only. There were only three
direct transition states and this probe did not require prior Pump-origin lineage. No threshold,
window or feature may be changed from this systems result.

## Next gate

Before economic discovery:

1. require causally known prior Pump birth for the opportunity token;
2. distinguish lineage FOUND / MISSING / AMBIGUOUS;
3. freeze exactly one decision snapshot at transition-observed +30 seconds;
4. persist that snapshot immutably with a hash chain;
5. validate missingness/accounting;
6. keep Jupiter/outcomes disabled during readiness.

Fresh economic discovery remains unauthorized until that readiness gate passes.

# Market Opportunity Radar v1.1 — Live Smoke Validation

Date: 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**

## Completed validation run

Run key:

`market-radar-smoke-20260903-03`

Command:

```text
python market_radar_smoke.py --run-key market-radar-smoke-20260903-03 --duration-seconds 120 --commitment confirmed
```

The bounded Pump -> Market Radar -> Opportunity Episode path completed its full 120-second window on the user's local Windows machine with no traceback.

## Observed totals

```text
elapsed=120.0s
notifications=2034
decoded_trades=2111
lifecycle_events=27
sol_eligible=2037
persisted=2037
filtered_non_sol_prefix=74
duplicate_or_replayed_eligible=0
evaluated_tokens=156
raw_radar_hits=738
continuation_hits=707
continuation_share=95.8%
unique_hit_tokens=29
unique_episodes=31
repeated_episode_tokens=2
opened_trigger_kinds={'activity_acceleration': 24, 'fresh_market_burst': 7}
opened_directions={'downward_pressure': 7, 'upward_pressure': 12, 'mixed_pressure': 12}
raw_trigger_kinds={'activity_acceleration': 622, 'fresh_market_burst': 116}
raw_directions={'downward_pressure': 97, 'upward_pressure': 294, 'mixed_pressure': 347}
```

## Operational interpretation

### Acquisition

The stream sustained approximately:

- 16.95 notifications/s;
- 17.59 decoded Pump TradeEvents/s;
- 16.98 persisted SOL-eligible observations/s.

All 2,037 SOL-eligible events were persisted during this run. The 74 remaining decoded events were explicitly classified as unsupported non-SOL-prefix events by the current v1 adapter rather than being silently misclassified.

`duplicate_or_replayed_eligible=0` means this particular 120-second window did not contain an eligible provider replay. It does **not** weaken the replay fix validation: replay semantics are covered by regression tests, including the exact Pump same-signature/later-WebSocket-delivery path. This smoke establishes that the fix did not regress live acquisition and that the full bounded collection completed normally.

### Radar -> episode accounting

The detector generated 738 qualifying raw radar hits, but only 31 independent 60-second opportunity episodes were opened.

Therefore:

- 707 / 738 hits were continuations;
- continuation share = 95.8%;
- mean raw qualifying hits per opened episode ~= 23.8.

This confirms that raw radar hits are a high-frequency state signal, **not independent economic opportunities**. Expensive enrichment must be scheduled per new episode, never per raw hit.

### Diversity

The 31 episodes covered 29 unique hit tokens. Only two episode openings were repeats of tokens already opened earlier in the same run, and the visible run output showed the two repeated tokens each opening twice. The maximum observed token share was therefore 2/31 ~= 6.5%, well below the future 20% concentration ceiling.

This is encouraging acquisition diversity, but the 120-second smoke is operational evidence only and must not be treated as the future economic DATA-READY sample.

### Trigger composition

Episode openings:

- `activity_acceleration`: 24 / 31 = 77.4%;
- `fresh_market_burst`: 7 / 31 = 22.6%.

Directions at episode open:

- upward pressure: 12 / 31 = 38.7%;
- mixed pressure: 12 / 31 = 38.7%;
- downward pressure: 7 / 31 = 22.6%.

The detector is therefore not simply selecting price-up narratives or positive-pressure-only states. Direction remains descriptive and no direction has been promoted to a trading rule.

## Gate decision

**PUMP BONDING STREAM -> MARKET RADAR -> OPPORTUNITY EPISODE: LIVE OPERATIONAL PASS.**

Validated in the local real environment:

- live Pump WebSocket acquisition;
- causal trade/lifecycle persistence;
- transaction-aware activity detection;
- bounded burst handling;
- raw-hit persistence;
- 60-second episode accounting;
- first-episode console policy;
- high continuation compression;
- token diversity under live traffic;
- no runtime failure across the complete smoke window.

Not validated by this smoke:

- predictive edge;
- profitability;
- Jupiter route/execution quality;
- hazard/risk rejection;
- wallet-intelligence incremental value;
- PumpSwap coverage;
- finality audit of every observed signature;
- production thresholds;
- shadow/live execution.

## Threshold policy

No Market Opportunity Radar threshold is changed from this run.

The run contains no economic outcome labels and is used to validate acquisition/accounting mechanics only. Detector retuning remains forbidden until a preregistered outcome-aware research stage provides enough independent evidence.

## Next gate

The Pump bonding acquisition/radar plumbing is no longer the immediate blocker.

Before any 12-hour acquisition window:

1. implement and validate PumpSwap as a separate native adapter using its official IDL and causal pool -> base-mint resolution;
2. design bounded episode-scoped enrichment admission so expensive Jupiter/wallet/risk/regime work cannot execute on every raw continuation hit;
3. wire `episode -> wallet intelligence -> Opportunity Core -> Jupiter/risk/regime -> final decision_as_of`;
4. run a short end-to-end evidence smoke;
5. audit provider/RPC load, missingness, latency and finality semantics;
6. freeze the runnable protocol;
7. only then start the first preregistered long acquisition window.

The project remains **PAPER / RESEARCH / READ ONLY**.

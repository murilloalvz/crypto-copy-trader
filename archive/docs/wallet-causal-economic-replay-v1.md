# Causal Economic Replay v1

`wallet_causal_economic_replay.py` is a research/read-only diagnostic. It matches a
forward BUY to a later SELL from the same wallet and token, using only event-scoped
Jupiter quotes observed after detection plus the configured delay.

There is no fill or live-order claim. A missing SELL, missing quote, pre-existing
inventory, or right-censored run never becomes realized PnL. The current action schema
does not contain token quantities, so the implementation uses one event-lot per BUY and
reports return percentages (the optional notional is only a transparent stress estimate).
Repeated BUYs are retained and clustered by wallet/token; they are not independent
opportunities. Costs are configurable stress assumptions, not observed execution fees.

Run with `python wallet_causal_economic_replay.py --json`. The default delays are
0/15/30/60/120 seconds and executable quotes are required. `--allow-proxy-quotes` is
diagnostic only and must not be used for live conclusions.

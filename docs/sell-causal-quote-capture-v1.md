# SELL causal quote capture v1

The forward wallet quote watcher now accepts BUY and SELL events. SELL attempts are
event-scoped by the exact `observation_key` and use the real Jupiter direction
`token -> USDC`.

Because the source wallet schema has no token quantities, a SELL candidate is scheduled
only when a previous successful BUY quote provides `output_amount_raw`. That amount is a
hypothetical copy lot for a specific BUY event/delay; it is not an inference of source
inventory and does not close all positions automatically.

Attempt keys include the SELL event and BUY entry lineage, making reprocessing idempotent.
All timing remains causal: the SELL quote target is the local `observed_at` of the SELL,
never its later chain history. Historical rows keep `run_key=NULL`; new forward rows may
carry the run manifest key and remain auditable by the existing ID interval.

The economic replay reports `OPEN` for an active run and `RIGHT_CENSORED` for an ended run
when no source SELL is observed. No historical SELL backfill or parameter optimization is
performed.

# Prior liquidity discovery finding frozen before Geometry V1

Source sample: the existing 900s Launch Burst / Sniper V1 capture, reused retrospectively for diagnostic discovery only.

The unit-controlled dominant SOL-quote cohort contained 101/115 baseline admissions and 35/42 Sniper-selected admissions. No threshold search was performed.

Observed association with later `ENTRY_USABLE`:

- real quote reserve change / initial virtual quote reserve: Spearman `0.1183662731` baseline, `0.0679283181` Sniper;
- raw real quote reserve at cutoff: `0.0515310590` baseline, `-0.0113221794` Sniper;
- real / virtual quote reserve ratio: `0.0660565925` baseline, `0.0` Sniper.

Observed association with post-decision provider price impact among rows where provider impact existed:

- reserve change: `-0.2495617681` baseline, `-0.3624551258` Sniper;
- raw real quote reserve: `-0.1686813581` baseline, `-0.2893297023` Sniper;
- real / virtual ratio: `-0.1808294889` baseline, `-0.2893297023` Sniper.

## Frozen interpretation

Simple quote-reserve amount/ratio features did **not** show useful separation of entry availability in this discovery sample. There is a modest descriptive association with later provider price impact, especially inside the small Sniper cohort, but provider impact is an execution outcome and not selector evidence.

Do not retune reserve thresholds on this sample. Geometry V1 is a new diagnostic family: it reconstructs token-side and SOL-side bonding-curve state and fixed mechanical curve probes from event payload bytes. Any future selector rule still requires a separate preregistration and fresh prospective capture.

# Rejection Filter V3 — run notes (2026-10-02)

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY. Notes only; they change no gate.

- Frozen protocol: `docs/rejection-filter-prospective-holdout-v3-usd10-selection-preregistration-2026-10-02.md`
  (frozen at commit e40c1fb).
- SHA-256 (CRLF-normalized): `72d820f718eb7a9ab0f7959508af8ca796893213c3101caedd1af6c22c24a199`, recorded in `rejection_filter_holdout_v3_collect.py`.
- Base run key: `rejection-filter-v3-20261002-01`, cohorts T1..T10, replacements T11..T13 (DEGRADED only).
- Runner: `rejection_filter_holdout_v3_collect.py` (needs `--confirm-live-acquisition`); helper
  `research/run_v3_cohorts.ps1` (`-DryRun`, `-Cohorts 1..3`). Analysis: `rejection_filter_holdout_v3_analyze.py`
  (refuses partial studies).
- Rules: at most 3 cohorts started per UTC day, valid cohorts on >= 3 UTC days, about 25 min per cohort.
- Operational: no concurrent process on the database, Jupiter or Helius RPC; back up the DB; fresh bootstrap (<= 24h);
  disable QuickEdit (the console guard does it); use the `.venv` Python.
- No acquisition had been run at the time of this note.

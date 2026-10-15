# CLAUDE.md — signals_mvp (signal bot v0)

Scope: this folder only. It is self-contained (imports nothing from the rest of the repo) and lives on branch
`signals-mvp`. The repo-wide rules in the root `CLAUDE.md` still apply (read-only/paper, no live money, scientific
discipline). Operator-facing docs are in `README.md` (Portuguese); keep user-visible text in Portuguese.

## Hard rules
- **PAPER / READ ONLY.** Never add private keys, signing, transaction sending or order execution.
- **Secrets:** never log or commit `TELEGRAM_BOT_TOKEN`. `util.redact` + `logging_setup` scrub logs; `TelegramClient`
  must never put a `requests` exception message in its errors (it contains the URL with the token).
- **Fail closed on security:** "sem dado" must never become "ok" (`security.py`). The operator-configurable policy
  (`seguranca.sem_dado_acao`) decides release-with-warning vs discard; the default is release-with-warning because
  GoPlus has no data for ~95% of fresh tokens (measured 2026-10-13).
- **No lookahead:** a signal is decided on the pool snapshot at `decision_ts`; outcomes only use 1-min candles that
  *start after* it; checkpoints use the last *closed* candle; never rewrite `seguranca` with later knowledge
  (`seguranca_tardia` holds the late re-check).
- **Missing data stays explicit** (`None`/blank in CSV, never 0). One evaluation per `(pool, etiqueta)`; the first
  decision is final. Do not re-score or retune on the same sample.
- **CSV formats are a stable contract** (`storage.SINAIS_COLUMNS`, `DESCARTADOS_COLUMNS`, `TRADES_COLUMNS`; a test
  pins the exact header). Extra fields go to `sinais_detalhe.csv` / `features_json`. Changing columns needs an
  explicit operator decision.
- **Every row carries `versao_config` / `versao_meta`** (hashes). Config is only swapped through
  `Engine.set_config`; each signal stores its own frozen plan (`plano_json`).
- Local rate-limit throttling ("budget"/429) is not a property of the token: postpone, don't decide on missing data.
- The alert must always get out: Telegram 400 falls back to simpler variants (`alerts.delivery_variants`).
- Do not touch `benchmarks/sig_fast_v0/`, `artifacts/sig_fast_h2_*`, the Rust kernel or other branches.
  `sobrevivente20` is an operational API-based trigger, **not** the pre-registered H2 trigger.
- v0 does not test an economic hypothesis. Any claim that the score has edge needs a pre-registration
  (`docs/research-hypothesis-registry-v1-2026-10-04.md`) and validation on unseen data.

## Layout and tests
`engine.py` (cycle) · `geckoterminal.py`/`goplus.py` (clients + pure parsers) · `security.py` · `triggers.py` ·
`metrics.py` · `scoring.py` · `narrative.py` · `tracker.py` (outcome simulation) · `storage.py` (SQLite is the source
of truth; CSVs are regenerated atomically) · `telegram.py`/`alerts.py`/`summary.py` · `worker.py`/`supervisor.py`/`cli.py`.

- Offline suite (stdlib only, ~15 s): `python -m unittest discover -s signals_mvp/tests -t .`
  (or `python -m signals_mvp selfcheck`). Parsers are tested against **real API responses** in `tests/fixtures/`;
  when an API shape changes, capture a new real response instead of hand-writing one.
- Real-network smoke (read-only): `python -m signals_mvp teste-rede`.
- Test doubles live in `tests/fakes.py` (fake clock/HTTP/GT/GoPlus/Telegram + a simulated pool "world").

## Measured facts worth remembering (2026-10-13)
- GeckoTerminal public API returns 429 with `retry-after: 0`; the limiter is adaptive (AIMD) for that reason.
- `new_pools` page 1 spans only ~1 min of Solana launches; DEXes `meteora-dbc` report liquidity 0 (unknown, not zero).
- GoPlus Robinhood (chain id 4663) returns an empty shell record; EVM holder lists lag (`holder_count` ~0) for fresh tokens.
- Network ids: `solana`, `bsc`, `robinhood` (GeckoTerminal); DexScreener slug for Robinhood is `robinhood`.
- Unverified: GMGN slug for Robinhood, Axiom link template, Telegram against the real service, Windows runtime.

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

## POS-RUNNER-V0 (`pos_runner/`)
Hypothesis POS-RUNNER-V0. The rules are the operator's (2026-10-16 decisions; unanswered points took the most
conservative option, listed in the pre-registration §5). **Frozen (PRE-REGISTRADO) on 2026-10-16**, config hash
`2a8bef99a917` + the rule code (`detector.py`/`simulate.py`/`costs.py`/`params.py`) at commit `dbbcea1` (SHA256 in the
pre-registration). From that commit on, no parameter/grid/period/baseline/cut/cost change — a change is a new
hypothesis (§4). The examples only calibrate phase DETECTION (Passo 0 v2: no parameter sweep, no trade results). Part
A is the unbiased collection that judges it; run it in commit-sized steps exactly as `docs/pos-runner-v0-preregistration-DRAFT-2026-10-15.md`
§7 orders (seal the holdout and commit it before any discovery call). One detector/simulator/cost model shared by Passo 0,
Part A (`parte_a/`, unbiased backtest) and Part B (`live.py`, inside the bot). Age = days since token CREATION
(on-chain: oldest successful mint signature before the migration, `lineage.creation_time`); unknown creation = no age
= never primary. The pre-registration gate (`params.is_preregistered`) reads ONLY the status line (the first line
starting with "Status:"); the draft text may quote the final status. Part B invariants:
- candles are consumed only when CLOSED (+`LAG_S`) and are frozen in `pr_bars`; a restart replays them (never rewrite);
- USD conversion uses only closed reference hours; a candle without USD waits, never converted by guess;
- a pool is tracked only after on-chain lineage (same key-account enumeration as Part A, +-10 min window) — never by
  paging the pool's own history (hot pools have ~500 tx/s right after graduation);
- GT calls come from a reserved slice of the v0 cycle budget (`BudgetedHttp`); v0 candidates keep priority minus 1 call;
- every ENTRADA decided after tracking started AND after the start of the current continuous run of the `versao_config`
  (`pr_version_start`: same-version restarts keep it, any version switch resets it) is a paper
  A/B signal (alerts gated by recency and `so_primario`); replaying frozen bars never creates retroactive signals;
  open paper of another version becomes `descontinuado`; alert keys carry the version;
- a pool is promoted to the radar only with its token creation date (the lineage thread fetches it; pools verified by
  an older bot without it go back to `verificado` until it is fetched);
- live paper results must never be used to tune the draft parameters.

## Measured facts worth remembering (2026-10-13)
- GeckoTerminal public API returns 429 with `retry-after: 0`; the limiter is adaptive (AIMD) for that reason.
- `new_pools` page 1 spans only ~1 min of Solana launches; DEXes `meteora-dbc` report liquidity 0 (unknown, not zero).
- GoPlus Robinhood (chain id 4663) returns an empty shell record; EVM holder lists lag (`holder_count` ~0) for fresh tokens.
- Network ids: `solana`, `bsc`, `robinhood` (GeckoTerminal); DexScreener slug for Robinhood is `robinhood`.
- Unverified: GMGN slug for Robinhood, Axiom link template, Telegram against the real service, Windows runtime.
- (2026-10-15/16) GT dex ids of graduation pools: `pumpswap`, `raydium` (CPMM pools show as `raydium`),
  `meteora-damm-v2`. The Solana USDT mint is `Es9vMFrz…NkY11McCe8BenwNYB` (the old config value returned 404).
  Public RPC `api.mainnet-beta.solana.com` is the only free endpoint with old history and rate-limits getTransaction.

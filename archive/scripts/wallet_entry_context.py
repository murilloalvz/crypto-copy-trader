import argparse
import json
import sys
import time
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.database import connection, initialize_database, rows
from src.wallet_entry_context import (
    EntrySeed,
    analyze_entry_candles,
    summarize_entry_context,
)


GECKO_BASE_URL = "https://api.geckoterminal.com/api/v2"
RESEARCH_MIN_INTERVAL_SECONDS = 12.0


class ResearchPriceError(RuntimeError):
    pass


class ResearchGeckoClient:
    """Low-rate research client kept separate from exit-engine provider telemetry."""

    def __init__(self, *, timeout: int = 30, interval_seconds: float = RESEARCH_MIN_INTERVAL_SECONDS):
        self.timeout = timeout
        self.interval_seconds = max(0.0, interval_seconds)
        self._last_request_at = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.interval_seconds - elapsed
        if self._last_request_at and wait > 0:
            time.sleep(wait)

    def _get(self, path: str, query: dict | None = None) -> dict:
        url = f"{GECKO_BASE_URL}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "crypto-copy-trader-research/0.1"},
        )
        last_error = None
        for attempt in range(2):
            self._wait()
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self._last_request_at = time.monotonic()
                if not isinstance(payload, dict):
                    raise ResearchPriceError("resposta GeckoTerminal inválida")
                return payload
            except HTTPError as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
                retryable = exc.code == 429 or exc.code in {408, 425} or exc.code >= 500
                if not retryable:
                    raise ResearchPriceError(f"GeckoTerminal HTTP {exc.code}") from exc
                if attempt == 0:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        delay = float(retry_after) if retry_after else self.interval_seconds
                    except (TypeError, ValueError):
                        delay = self.interval_seconds
                    time.sleep(max(self.interval_seconds, min(delay, 30.0)))
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
                if attempt == 0:
                    time.sleep(self.interval_seconds)
        raise ResearchPriceError(f"GeckoTerminal indisponível: {last_error}") from last_error

    @staticmethod
    def _mint_from_relationship(pool: dict, side: str) -> str | None:
        token_id = (
            pool.get("relationships", {})
            .get(f"{side}_token", {})
            .get("data", {})
            .get("id")
        )
        return token_id.removeprefix("solana_") if token_id else None

    def _cached_pool(self, token_mint: str) -> tuple[str, str] | None:
        with connection() as conn:
            row = conn.execute(
                """SELECT pool_address, token_side, updated_at FROM token_pool_cache
                WHERE token_mint=?""",
                (token_mint,),
            ).fetchone()
        if row and int(time.time()) - int(row["updated_at"]) < 86_400:
            return str(row["pool_address"]), str(row["token_side"])
        return None

    def resolve_pool(self, token_mint: str) -> tuple[str, str]:
        cached = self._cached_pool(token_mint)
        if cached:
            return cached
        payload = self._get(f"/networks/solana/tokens/{token_mint}/pools", {"page": 1})
        candidates = []
        for item in payload.get("data") or []:
            if self._mint_from_relationship(item, "base") == token_mint:
                side = "base"
            elif self._mint_from_relationship(item, "quote") == token_mint:
                side = "quote"
            else:
                continue
            attributes = item.get("attributes") or {}
            address = attributes.get("address")
            if not address:
                continue
            reserve = float(attributes.get("reserve_in_usd") or 0)
            volume = float((attributes.get("volume_usd") or {}).get("h24") or 0)
            candidates.append((volume, reserve, str(address), side))
        if not candidates:
            raise ResearchPriceError("nenhum pool atual encontrado")
        volume, reserve, address, side = max(candidates)
        with connection() as conn:
            conn.execute(
                """INSERT INTO token_pool_cache
                (token_mint, pool_address, token_side, reserve_usd, volume_usd_24h, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_mint) DO UPDATE SET
                    pool_address=excluded.pool_address,
                    token_side=excluded.token_side,
                    reserve_usd=excluded.reserve_usd,
                    volume_usd_24h=excluded.volume_usd_24h,
                    updated_at=excluded.updated_at""",
                (token_mint, address, side, reserve, volume, int(time.time())),
            )
        return address, side

    def entry_window(self, token_mint: str, entry_at: int) -> list[dict]:
        pool, side = self.resolve_pool(token_mint)
        entry_minute = entry_at - entry_at % 60
        payload = self._get(
            f"/networks/solana/pools/{pool}/ohlcv/minute",
            {
                "aggregate": 1,
                "before_timestamp": entry_minute + 61 * 60,
                "limit": 125,
                "currency": "usd",
                "token": side,
            },
        )
        raw = payload.get("data", {}).get("attributes", {}).get("ohlcv_list") or []
        candles = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 5:
                continue
            try:
                candles.append(
                    {
                        "timestamp": int(item[0]),
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                    }
                )
            except (TypeError, ValueError):
                continue
        candles.sort(key=lambda item: item["timestamp"])
        return candles


def _first_observed_buys(address: str) -> list[EntrySeed]:
    data = rows(
        """SELECT t.token_mint, t.block_time, t.dex
        FROM transactions t
        JOIN (
            SELECT token_mint, MIN(block_time) AS first_buy_at
            FROM transactions
            WHERE wallet_address=? AND kind='swap' AND status='success'
              AND token_change > 0 AND token_mint IS NOT NULL AND block_time IS NOT NULL
            GROUP BY token_mint
        ) first_buy
          ON first_buy.token_mint=t.token_mint AND first_buy.first_buy_at=t.block_time
        WHERE t.wallet_address=? AND t.kind='swap' AND t.status='success' AND t.token_change > 0
        GROUP BY t.token_mint, t.block_time
        ORDER BY t.block_time""",
        (address, address),
    )
    return [
        EntrySeed(str(item["token_mint"]), int(item["block_time"]), item.get("dex"))
        for item in data
    ]


def _spread_sample(entries: list[EntrySeed], limit: int) -> list[EntrySeed]:
    if len(entries) <= limit:
        return entries
    if limit == 1:
        return [entries[len(entries) // 2]]
    indexes = []
    for position in range(limit):
        index = round(position * (len(entries) - 1) / (limit - 1))
        if index not in indexes:
            indexes.append(index)
    return [entries[index] for index in indexes]


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def _plain_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _short(token: str) -> str:
    return f"{token[:6]}...{token[-6:]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pesquisa contexto de preço antes/depois das primeiras compras observadas da wallet. "
            "Não usa Solana Tracker Data API e não altera wave_v3."
        )
    )
    parser.add_argument("address", help="endereço público Solana já sincronizado no SQLite")
    parser.add_argument(
        "--tokens", type=int, default=12,
        help="quantidade de primeiras compras espalhadas pela janela local (padrão: 12)",
    )
    parser.add_argument(
        "--interval-seconds", type=float, default=RESEARCH_MIN_INTERVAL_SECONDS,
        help="pacing do GeckoTerminal para pesquisa (padrão conservador: 12s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.tokens <= 50:
        print("Erro: --tokens precisa ficar entre 1 e 50.", file=sys.stderr)
        return 2
    if args.interval_seconds < 5:
        print("Erro: --interval-seconds deve ser >= 5 para não pressionar o provider.", file=sys.stderr)
        return 2

    initialize_database()
    all_entries = _first_observed_buys(args.address)
    selected = _spread_sample(all_entries, args.tokens)
    if not selected:
        print("Nenhuma compra on-chain observada para essa wallet no SQLite.")
        return 0

    print("Crypto Copy Trader — Wallet Entry Context v1")
    print("Modo: RESEARCH / READ ONLY — wave_v3 permanece congelada.")
    print("IMPORTANTE: execute esta pesquisa com o monitor parado para não disputar GeckoTerminal.")
    print(
        f"Primeiras compras locais: {len(all_entries)} | amostra espalhada no tempo: {len(selected)}"
    )

    client = ResearchGeckoClient(interval_seconds=args.interval_seconds)
    observations = []
    failures = Counter()
    for index, seed in enumerate(selected, start=1):
        print(f"[entry] {index}/{len(selected)} {_short(seed.token_mint)}", file=sys.stderr)
        try:
            candles = client.entry_window(seed.token_mint, seed.entry_at)
            observation = analyze_entry_candles(seed, candles, max_distance_seconds=120)
        except ResearchPriceError as exc:
            failures[str(exc)] += 1
            print(f"[entry] falha {_short(seed.token_mint)}: {exc}", file=sys.stderr)
            continue
        if observation is None:
            failures["sem candle suficientemente próximo da compra"] += 1
            continue
        observations.append(observation)

    summary = summarize_entry_context(observations, attempted_entries=len(selected))
    print()
    print("COBERTURA")
    print(
        f"Entradas precificadas: {summary.priced_entries}/{summary.attempted_entries} | "
        f"falhas: {summary.failed_entries}"
    )
    if failures:
        for reason, count in failures.most_common():
            print(f"- {reason}: {count}")

    print()
    print("CONTEXTO ANTES DA COMPRA — DESCRITIVO")
    print(
        f"Retorno mediano pré 5m/15m/60m: {_pct(summary.median_pre_5m_return_pct)} / "
        f"{_pct(summary.median_pre_15m_return_pct)} / {_pct(summary.median_pre_60m_return_pct)}"
    )
    print(
        f"Posição mediana no range pré-60m: {_plain_pct(summary.median_pre_60m_range_position_pct)} | "
        f"amplitude mediana pré-60m: {_plain_pct(summary.median_pre_60m_amplitude_pct)}"
    )
    print(
        f"Pré-15m >= +5%: {summary.pre15_up_5_share_pct:.1f}% | "
        f"pré-15m <= -5%: {summary.pre15_down_5_share_pct:.1f}% | "
        f"entrada perto do topo do range pré-60m: {summary.near_pre60_high_share_pct:.1f}%"
    )
    print("Heurísticas de contexto (não são regras de trading):")
    for label, count in summary.context_counts.items():
        print(f"- {label}: {count}")

    print()
    print("MOVIMENTO APÓS A COMPRA OBSERVADA — NÃO É PnL DA WALLET")
    print(
        f"Retorno mediano +5m/+15m/+60m: {_pct(summary.median_post_5m_return_pct)} / "
        f"{_pct(summary.median_post_15m_return_pct)} / {_pct(summary.median_post_60m_return_pct)}"
    )
    print("DEX das primeiras compras precificadas:")
    for dex, count in summary.dex_mix.items():
        print(f"- {dex}: {count}")

    print()
    print("AMOSTRA POR TOKEN")
    for item in observations:
        print(
            f"- {_short(item.token_mint)} | {item.dex or 'unknown'} | "
            f"pré15 {_pct(item.pre_15m_return_pct)} | pré60 {_pct(item.pre_60m_return_pct)} | "
            f"range {_plain_pct(item.pre_60m_range_position_pct)} | "
            f"+60m {_pct(item.post_60m_return_pct)} | {item.context_label}"
        )

    print()
    print("LIMITAÇÕES")
    print("- A primeira compra observada pode não ser a primeira compra histórica da wallet se o backfill local estiver incompleto.")
    print("- O candle de minuto é proxy de mercado, não o preço executado pela wallet.")
    print("- O pool escolhido é o pool atual dominante/cacheado e pode não ser o mesmo pool usado historicamente na entrada.")
    print("- Este estágio não possui liquidez/market cap históricos confiáveis nem autoriza alterar wave_v3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

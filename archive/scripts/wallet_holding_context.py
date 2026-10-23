import argparse
import json
import sys
from collections import Counter
from urllib.error import HTTPError, URLError

from src.database import initialize_database
from src.wallet_entry_context import analyze_entry_candles
from src.wallet_holding_context import (
    analyze_holding_context,
    summarize_holding_context,
)
from wallet_entry_context import (
    RESEARCH_MIN_INTERVAL_SECONDS,
    ResearchGeckoClient,
    ResearchPriceError,
    _first_observed_buys,
    _short,
    _spread_sample,
)


class HoldingResearchGeckoClient(ResearchGeckoClient):
    def holding_window(self, token_mint: str, entry_at: int, *, hours: int = 72) -> list[dict]:
        pool, side = self.resolve_pool(token_mint)
        payload = self._get(
            f"/networks/solana/pools/{pool}/ohlcv/hour",
            {
                "aggregate": 1,
                "before_timestamp": entry_at + (hours + 2) * 3_600,
                "limit": min(100, hours + 6),
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


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pesquisa evolução de preço em 6h/24h/48h/72h após as primeiras compras "
            "observadas de uma wallet. Não usa Solana Tracker Data API."
        )
    )
    parser.add_argument("address", help="endereço público Solana já sincronizado no SQLite")
    parser.add_argument(
        "--tokens", type=int, default=12,
        help="quantidade de primeiras compras espalhadas pela janela local (padrão: 12)",
    )
    parser.add_argument(
        "--interval-seconds", type=float, default=RESEARCH_MIN_INTERVAL_SECONDS,
        help="pacing GeckoTerminal por request (padrão conservador: 12s)",
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

    print("Crypto Copy Trader — Wallet Holding Context v1")
    print("Modo: RESEARCH / READ ONLY — wave_v3 permanece congelada.")
    print("IMPORTANTE: execute com o monitor parado para não disputar GeckoTerminal.")
    print(
        f"Primeiras compras locais: {len(all_entries)} | amostra espalhada no tempo: {len(selected)}"
    )

    client = HoldingResearchGeckoClient(interval_seconds=args.interval_seconds)
    observations = []
    failures = Counter()
    for index, seed in enumerate(selected, start=1):
        print(f"[holding] {index}/{len(selected)} {_short(seed.token_mint)}", file=sys.stderr)
        try:
            minute_candles = client.entry_window(seed.token_mint, seed.entry_at)
            entry = analyze_entry_candles(seed, minute_candles, max_distance_seconds=120)
            if entry is None:
                failures["sem candle de minuto próximo da compra"] += 1
                continue
            hourly = client.holding_window(seed.token_mint, seed.entry_at, hours=72)
            observation = analyze_holding_context(seed, entry.entry_price_usd, hourly)
        except ResearchPriceError as exc:
            failures[str(exc)] += 1
            print(f"[holding] falha {_short(seed.token_mint)}: {exc}", file=sys.stderr)
            continue
        observations.append(observation)

    summary = summarize_holding_context(observations, attempted_entries=len(selected))
    print()
    print("COBERTURA")
    print(
        f"Entradas com análise multi-dia: {summary.priced_entries}/{summary.attempted_entries} | "
        f"falhas: {summary.failed_entries}"
    )
    if failures:
        for reason, count in failures.most_common():
            print(f"- {reason}: {count}")

    print()
    print("MOVIMENTO APÓS A COMPRA — NÃO É PnL DA WALLET")
    print(
        "Retorno mediano +6h/+24h/+48h/+72h: "
        f"{_pct(summary.median_post_6h_return_pct)} / "
        f"{_pct(summary.median_post_24h_return_pct)} / "
        f"{_pct(summary.median_post_48h_return_pct)} / "
        f"{_pct(summary.median_post_72h_return_pct)}"
    )
    print(
        f"24h MFE/MAE medianos: {_pct(summary.median_mfe_24h_pct)} / "
        f"{_pct(summary.median_mae_24h_pct)}"
    )
    print(
        f"72h MFE/MAE medianos: {_pct(summary.median_mfe_72h_pct)} / "
        f"{_pct(summary.median_mae_72h_pct)}"
    )
    print(
        f"Retorno >0 em 24h: {summary.positive_24h_share_pct:.1f}% | "
        f"em 72h: {summary.positive_72h_share_pct:.1f}% | "
        f"retorno <= -30% em 24h: {summary.drawdown_30_24h_share_pct:.1f}%"
    )

    print()
    print("AMOSTRA POR TOKEN")
    for item in observations:
        print(
            f"- {_short(item.token_mint)} | {item.dex or 'unknown'} | "
            f"+6h {_pct(item.post_6h_return_pct)} | +24h {_pct(item.post_24h_return_pct)} | "
            f"+48h {_pct(item.post_48h_return_pct)} | +72h {_pct(item.post_72h_return_pct)} | "
            f"MFE72 {_pct(item.mfe_72h_pct)} | MAE72 {_pct(item.mae_72h_pct)}"
        )

    print()
    print("LIMITAÇÕES")
    print("- A primeira compra observada pode não ser a primeira compra histórica da wallet.")
    print("- O preço de entrada usa candle de minuto; horizontes e MFE/MAE usam candles horários.")
    print("- O candle da hora parcial da entrada é excluído do MFE/MAE para evitar usar movimento pré-compra.")
    print("- O pool atual dominante/cacheado pode não ser o mesmo pool usado historicamente pela wallet.")
    print("- Retornos são movimento do mercado após a compra observada, não PnL realizado da wallet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

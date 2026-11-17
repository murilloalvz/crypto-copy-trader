import argparse
import math
import sys
from collections import Counter

from src.database import initialize_database, rows
from src.wallet_entry_context import EntrySeed, analyze_entry_candles
from src.wallet_exit_context import (
    ExitCycleSeed,
    analyze_exit_context,
    extract_exit_cycle_seeds,
    summarize_exit_context,
)
from wallet_entry_context import (
    RESEARCH_MIN_INTERVAL_SECONDS,
    ResearchGeckoClient,
    ResearchPriceError,
    _short,
)


class ExitResearchGeckoClient(ResearchGeckoClient):
    @staticmethod
    def _candles(payload: dict) -> list[dict]:
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

    def minute_window(self, token_mint: str, timestamp: int) -> list[dict]:
        pool, side = self.resolve_pool(token_mint)
        minute_ts = timestamp - timestamp % 60
        payload = self._get(
            f"/networks/solana/pools/{pool}/ohlcv/minute",
            {
                "aggregate": 1,
                "before_timestamp": minute_ts + 4 * 60,
                "limit": 7,
                "currency": "usd",
                "token": side,
            },
        )
        return self._candles(payload)

    def hourly_path_to_first_sell(
        self,
        token_mint: str,
        entry_at: int,
        first_sell_at: int,
        *,
        max_pages: int = 3,
    ) -> list[dict]:
        pool, side = self.resolve_pool(token_mint)
        first_full_hour = ((entry_at // 3_600) + 1) * 3_600
        before_timestamp = first_sell_at + 3_600
        collected: dict[int, dict] = {}

        for _ in range(max_pages):
            span_hours = max(1, math.ceil((before_timestamp - first_full_hour) / 3_600))
            limit = min(100, max(6, span_hours + 3))
            payload = self._get(
                f"/networks/solana/pools/{pool}/ohlcv/hour",
                {
                    "aggregate": 1,
                    "before_timestamp": before_timestamp,
                    "limit": limit,
                    "currency": "usd",
                    "token": side,
                },
            )
            page = self._candles(payload)
            if not page:
                break
            for candle in page:
                collected[candle["timestamp"]] = candle

            earliest = min(item["timestamp"] for item in page)
            if earliest <= first_full_hour:
                break
            next_before = earliest
            if next_before >= before_timestamp:
                break
            before_timestamp = next_before

        return [collected[key] for key in sorted(collected)]


def _local_swaps(address: str) -> list[dict]:
    return rows(
        """SELECT token_mint, block_time, token_change, dex
        FROM transactions
        WHERE wallet_address=? AND kind='swap' AND status='success'
          AND token_mint IS NOT NULL AND token_change IS NOT NULL AND block_time IS NOT NULL
        ORDER BY block_time""",
        (address,),
    )


def _spread_cycles(cycles: list[ExitCycleSeed], limit: int) -> list[ExitCycleSeed]:
    if len(cycles) <= limit:
        return cycles
    if limit == 1:
        return [cycles[len(cycles) // 2]]
    indexes = []
    for position in range(limit):
        index = round(position * (len(cycles) - 1) / (limit - 1))
        if index not in indexes:
            indexes.append(index)
    return [cycles[index] for index in indexes]


def _nearest_close(candles: list[dict], timestamp: int, *, max_distance_seconds: int = 120) -> float | None:
    minute_ts = timestamp - timestamp % 60
    candidates = [
        item
        for item in candles
        if item.get("timestamp") is not None and item.get("close") is not None
    ]
    if not candidates:
        return None
    selected = min(candidates, key=lambda item: abs(int(item["timestamp"]) - minute_ts))
    if abs(int(selected["timestamp"]) - minute_ts) > max_distance_seconds:
        return None
    price = float(selected["close"])
    return price if price > 0 else None


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def _hours(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 48:
        return f"{value:.1f}h"
    return f"{value / 24:.1f}d"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Alinha primeiras compras observadas, vendas on-chain reais e caminho de preço "
            "para estudar timing de saída. Não usa Solana Tracker Data API."
        )
    )
    parser.add_argument("address", help="endereço público Solana já sincronizado no SQLite")
    parser.add_argument(
        "--tokens", type=int, default=12,
        help="quantidade de ciclos limpos espalhados no tempo (padrão: 12)",
    )
    parser.add_argument(
        "--interval-seconds", type=float, default=RESEARCH_MIN_INTERVAL_SECONDS,
        help="pacing GeckoTerminal por request (padrão conservador: 12s)",
    )
    parser.add_argument(
        "--max-hour-pages", type=int, default=3,
        help="máximo de páginas horárias para reconstruir o caminho até a primeira venda (padrão: 3)",
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
    if not 1 <= args.max_hour_pages <= 6:
        print("Erro: --max-hour-pages precisa ficar entre 1 e 6.", file=sys.stderr)
        return 2

    initialize_database()
    extraction = extract_exit_cycle_seeds(_local_swaps(args.address))
    all_cycles = list(extraction.cycles)
    selected = _spread_cycles(all_cycles, args.tokens)

    print("Crypto Copy Trader — Wallet Exit Context v1")
    print("Modo: RESEARCH / READ ONLY — wave_v3 e exit_engine_v1 permanecem congelados.")
    print("IMPORTANTE: execute com o monitor parado para não disputar GeckoTerminal.")
    print(f"Wallet: {args.address}")
    print(
        f"Tokens locais: {extraction.token_count} | ciclos limpos observados: {len(all_cycles)} | "
        f"amostra espalhada: {len(selected)}"
    )
    print(
        "Exclusões/cobertura local: "
        f"sem compra {extraction.no_observed_buy_token_count} | "
        f"sem venda após compra {extraction.no_sell_after_buy_token_count} | "
        f"estoque pré-existente observado {extraction.excluded_preexisting_inventory_token_count}"
    )

    if not selected:
        print("Nenhum ciclo buy→sell limpo disponível no SQLite.")
        return 0

    client = ExitResearchGeckoClient(interval_seconds=args.interval_seconds)
    observations = []
    failures = Counter()

    for index, seed in enumerate(selected, start=1):
        print(
            f"[exit] {index}/{len(selected)} {_short(seed.token_mint)} | "
            f"sells {seed.sell_count}",
            file=sys.stderr,
        )
        try:
            entry_candles = client.minute_window(seed.token_mint, seed.entry_at)
            entry = analyze_entry_candles(
                EntrySeed(seed.token_mint, seed.entry_at, seed.entry_dex),
                entry_candles,
                max_distance_seconds=120,
            )
            if entry is None:
                failures["sem candle de minuto próximo da compra"] += 1
                continue

            first_sell_candles = client.minute_window(seed.token_mint, seed.first_sell_at)
            first_sell_price = _nearest_close(first_sell_candles, seed.first_sell_at)
            if first_sell_price is None:
                failures["sem candle de minuto próximo da primeira venda"] += 1
                continue

            if seed.last_sell_at == seed.first_sell_at:
                last_sell_price = first_sell_price
            else:
                last_sell_candles = client.minute_window(seed.token_mint, seed.last_sell_at)
                last_sell_price = _nearest_close(last_sell_candles, seed.last_sell_at)
                if last_sell_price is None:
                    failures["sem candle de minuto próximo da última venda"] += 1
                    continue

            hourly = client.hourly_path_to_first_sell(
                seed.token_mint,
                seed.entry_at,
                seed.first_sell_at,
                max_pages=args.max_hour_pages,
            )
            observations.append(
                analyze_exit_context(
                    seed,
                    entry_price_usd=entry.entry_price_usd,
                    first_sell_price_usd=first_sell_price,
                    last_sell_price_usd=last_sell_price,
                    pre_first_sell_hourly_candles=hourly,
                )
            )
        except (ResearchPriceError, ValueError) as exc:
            failures[str(exc)] += 1
            print(f"[exit] falha {_short(seed.token_mint)}: {exc}", file=sys.stderr)

    summary = summarize_exit_context(observations, attempted_cycles=len(selected))

    print()
    print("COBERTURA")
    print(
        f"Ciclos precificados: {summary.priced_cycles}/{summary.attempted_cycles} | "
        f"falhas: {summary.failed_cycles} | caminho completo até 1ª venda: "
        f"{summary.path_complete_share_pct:.1f}%"
    )
    if failures:
        for reason, count in failures.most_common():
            print(f"- {reason}: {count}")

    print()
    print("TIMING E PREÇO NAS VENDAS OBSERVADAS — NÃO É PnL REALIZADO")
    print(
        f"Primeira/última venda (tempo mediano): {_hours(summary.median_first_exit_hours)} / "
        f"{_hours(summary.median_last_exit_hours)}"
    )
    print(
        f"Retorno proxy mediano na 1ª/última venda: {_pct(summary.median_first_sell_return_pct)} / "
        f"{_pct(summary.median_last_sell_return_pct)}"
    )
    print(
        f"1ª venda >0: {summary.positive_first_sell_share_pct:.1f}% | "
        f">=+20%: {summary.first_sell_up_20_share_pct:.1f}% | "
        f"<0: {summary.negative_first_sell_share_pct:.1f}%"
    )
    print(
        f"Ciclos multi-sell: {summary.multi_sell_cycle_share_pct:.1f}% | "
        f"reentrada após 1º ciclo: {summary.reentry_after_cycle_share_pct:.1f}% | "
        f"última vs 1ª venda nos multi-sell (mediana): "
        f"{_pct(summary.median_first_to_last_sell_change_pct)}"
    )

    print()
    print("CAMINHO ANTES DA PRIMEIRA VENDA — SOMENTE JANELAS HORÁRIAS COMPLETAS")
    print(
        f"MFE/MAE medianos antes da 1ª venda: {_pct(summary.median_mfe_before_first_sell_pct)} / "
        f"{_pct(summary.median_mae_before_first_sell_pct)}"
    )
    print(
        "Preço da 1ª venda vs pico pré-saída (mediana): "
        f"{_pct(summary.median_first_sell_vs_pre_exit_peak_pct)} "
        "(negativo = devolveu parte do pico antes de vender)"
    )

    print()
    print("AMOSTRA POR TOKEN")
    for item in observations:
        print(
            f"- {_short(item.token_mint)} | {item.entry_dex or 'unknown'} | sells {item.sell_count} | "
            f"1ª {_hours(item.first_exit_hours)} {_pct(item.first_sell_return_pct)} | "
            f"última {_hours(item.last_exit_hours)} {_pct(item.last_sell_return_pct)} | "
            f"MFEpré {_pct(item.mfe_before_first_sell_pct)} | "
            f"MAEpré {_pct(item.mae_before_first_sell_pct)} | "
            f"pico→1ª {_pct(item.first_sell_vs_pre_exit_peak_pct)} | "
            f"path {'ok' if item.path_complete_before_first_sell else 'parcial'} | "
            f"reentry {'sim' if item.reentry_at is not None else 'não'}"
        )

    print()
    print("LIMITAÇÕES")
    print("- Preços de compra/venda são candles de minuto próximos aos timestamps, não fills exatos da wallet.")
    print("- MFE/MAE pré-saída usam apenas horas completas após a hora da compra e antes da primeira venda.")
    print("- Caminhos longos podem ficar parciais se excederem o limite de páginas horárias solicitado.")
    print("- O pool atual dominante/cacheado pode não ser o pool historicamente usado pela wallet.")
    print("- Reentradas são separadas do primeiro ciclo; este relatório não reconstrói PnL, tamanho ou intenção.")
    print("- Nenhum resultado deste estudo autoriza alterar wave_v3 ou promover uma política de saída.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

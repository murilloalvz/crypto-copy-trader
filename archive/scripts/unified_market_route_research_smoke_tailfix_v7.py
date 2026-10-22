from __future__ import annotations

import unified_market_route_research_smoke_tailfix_v6 as tailfix_v6


_RUN_V6 = tailfix_v6.run_smoke_tailfix_v6


async def run_smoke_tailfix_v7(**kwargs) -> None:
    """Run unchanged V6 scheduling with observation-only remaining-HOL attribution."""

    await _RUN_V6(**kwargs)
    print(
        "\nTAILFIX V7 NOTE: this run adds observation-only attribution for dependency, "
        "ready-capacity, writer-result, hot-asset and proof-based-demotion waits. "
        "It does not change V6 partial-order scheduling or any frozen gate/policy."
    )


def build_parser():
    parser = tailfix_v6.build_parser()
    parser.description = (
        "Systems-only Tailfix v7 diagnostic: V6 partial-order plus remaining PumpSwap HOL attribution"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    import asyncio

    print("Crypto Copy Trader — Route Research Systems Tailfix v7 HOL Diagnostics")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — V6 scheduling unchanged; targeted HOL attribution only."
    )
    asyncio.run(run_smoke_tailfix_v7(**vars(args)))


if __name__ == "__main__":
    main()

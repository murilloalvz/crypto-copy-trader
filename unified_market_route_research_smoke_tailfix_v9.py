from __future__ import annotations

import unified_market_route_research_smoke_tailfix_v8 as tailfix_v8


async def run_smoke_tailfix_v9(**kwargs) -> None:
    """Run V8 with early causal acknowledgement for proven continuation work."""

    run_kwargs = dict(kwargs)
    run_kwargs["pumpswap_demoted_audit_split"] = True
    await tailfix_v8.run_smoke_tailfix_v8(**run_kwargs)


def build_parser():
    parser = tailfix_v8.build_parser()
    parser.description = (
        "Systems-only Tailfix v9: V8 plus early causal release and separate demoted audit lane"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    import asyncio

    print("Crypto Copy Trader — Route Research Systems Tailfix v9")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — V6 partial-order preserved; proven continuation "
        "work leaves the causal ready queue and remains mandatory audit work."
    )
    asyncio.run(run_smoke_tailfix_v9(**vars(args)))


if __name__ == "__main__":
    main()

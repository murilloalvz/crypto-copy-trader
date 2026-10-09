from __future__ import annotations

import src.pumpswap_authoritative_writer_v8 as writer_admission
import src.pumpswap_normalized_persistence_v4 as writer_module
import unified_market_route_research_smoke_tailfix_v7 as tailfix_v7


async def run_smoke_tailfix_v8(**kwargs) -> None:
    """Run V6/V7 semantics with causal admission for the authoritative writer stage."""

    original_stage = writer_module._persist_prepared_batch_db_stage
    writer_module._persist_prepared_batch_db_stage = writer_admission.causal_authoritative_stage(
        original_stage
    )
    try:
        await tailfix_v7.run_smoke_tailfix_v7(**kwargs)
    finally:
        writer_module._persist_prepared_batch_db_stage = original_stage


def build_parser():
    parser = tailfix_v7.build_parser()
    parser.description = (
        "Systems-only Tailfix v8: V6 partial-order plus causal authoritative SQLite admission"
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    import asyncio

    print("Crypto Copy Trader — Route Research Systems Tailfix v8")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — one physical SQLite writer; causal admission and "
        "canonical readback batching only."
    )
    asyncio.run(run_smoke_tailfix_v8(**vars(args)))


if __name__ == "__main__":
    main()

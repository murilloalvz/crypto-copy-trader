from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
import time
from typing import Any, Iterator

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_prospective_route_paper_v2 import live as live_v2
from src.assets import USDC_MINT
from src.jupiter_swap_v2 import JupiterOrderError, JupiterSwapV2Client, jupiter_order_to_causal_quote
from src.solana import SolanaRPCError


HORIZON_VERSION = "launch_burst_momentum_horizon_300_v0"
HORIZON_SECONDS = 300


def _path_for_episode(episode_key: str) -> dict[str, Any] | None:
    for row in reversed(sim._SIM_CONTEXT.get("paths") or []):
        if str(row.get("episode_key") or "") == episode_key:
            return row
    return None


@contextmanager
def patched_300s_route_collection_v0() -> Iterator[None]:
    original = sim._capture_selected_episode_sim

    async def capture_with_300s(
        *, episode_key: str, token_mint: str, snapshot: dict[str, Any],
        contract: dict[str, Any], jupiter_api_key: str, taker_public_key: str,
        rpc_url: str, rpc_fallback_urls: tuple[str, ...],
    ):
        episode = await original(
            episode_key=episode_key,
            token_mint=token_mint,
            snapshot=snapshot,
            contract=contract,
            jupiter_api_key=jupiter_api_key,
            taker_public_key=taker_public_key,
            rpc_url=rpc_url,
            rpc_fallback_urls=rpc_fallback_urls,
        )
        path_row = _path_for_episode(episode_key)
        if not isinstance(path_row, dict):
            return episode
        entry = path_row.get("entry_quote")
        if not isinstance(entry, dict):
            return episode
        amount_raw = entry.get("output_amount_raw")
        observed_at = entry.get("observed_at")
        try:
            amount_raw_i = int(amount_raw)
            entry_at = int(observed_at)
        except (TypeError, ValueError):
            return episode
        if amount_raw_i <= 0 or entry_at <= 0:
            return episode
        if any(int(mark.get("offset_seconds") or 0) == HORIZON_SECONDS for mark in path_row.get("path") or []):
            return episode

        target = entry_at + HORIZON_SECONDS
        if time.time() < target:
            await asyncio.sleep(max(0.0, target - time.time()))
        mark: dict[str, Any] = {
            "offset_seconds": HORIZON_SECONDS,
            "target_at": target,
            "status": "STARTED",
            "quote": None,
            "inference_role": "EXPLORATORY_HISTORICAL_MOMENTUM_ALIGNMENT",
        }
        try:
            decimals = await asyncio.to_thread(
                live_v2._resolve_decimals,
                token_mint,
                rpc_url=rpc_url,
                fallback_urls=rpc_fallback_urls,
            )
            order = await asyncio.to_thread(
                JupiterSwapV2Client(api_key=jupiter_api_key, timeout=7).order,
                input_mint=token_mint,
                output_mint=USDC_MINT,
                amount_raw=amount_raw_i,
                taker=None,
                slippage_bps=int(contract["costs"]["exit_adverse_slippage_bps"]),
            )
            sell = jupiter_order_to_causal_quote(
                order,
                token_mint=token_mint,
                side="sell",
                token_decimals=decimals,
            )
            if sell.executable:
                raise ValueError("route-only 300s SELL unexpectedly executable")
            mark["status"] = "AVAILABLE_ROUTE_ONLY"
            mark["quote"] = asdict(sell)
        except (JupiterOrderError, SolanaRPCError, ValueError, TypeError) as exc:
            mark["status"] = "ERROR:" + sim._redacted_error(exc, jupiter_api_key, rpc_url)

        path_row.setdefault("path", []).append(mark)
        path_row["path"] = sorted(
            path_row["path"],
            key=lambda item: int(item.get("offset_seconds") or 0),
        )
        collection = path_row.setdefault("collection", {})
        collection["momentum_horizon_version"] = HORIZON_VERSION
        collection["path_mark_count"] = len(path_row["path"])
        collection["path_available_count"] = sum(
            item.get("status") == "AVAILABLE_ROUTE_ONLY" for item in path_row["path"]
        )
        return episode

    sim._capture_selected_episode_sim = capture_with_300s
    try:
        yield
    finally:
        sim._capture_selected_episode_sim = original

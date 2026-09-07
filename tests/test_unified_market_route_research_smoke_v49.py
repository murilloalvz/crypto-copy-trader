import asyncio

import unified_market_route_research_smoke_v42 as v42
import unified_market_route_research_smoke_v49 as v49


def test_v49_uses_frozen_base_v42_reference(monkeypatch):
    calls = []

    async def fake_base(**kwargs):
        calls.append(kwargs)

    async def recursive_sentinel(**kwargs):  # pragma: no cover - must never be called
        raise AssertionError("v49 called monkey-patched v42.run_smoke_v42 recursively")

    monkeypatch.setattr(v49, "_BASE_V42_RUN_SMOKE", fake_base)
    monkeypatch.setattr(v42, "run_smoke_v42", recursive_sentinel)

    class FakePrefetcher:
        def snapshot(self):
            return type(
                "Snapshot",
                (),
                {
                    "notifications_seen": 0,
                    "candidate_pools": 0,
                    "scheduled": 0,
                    "coalesced_inflight": 0,
                    "completed_available": 0,
                    "completed_unresolved": 0,
                    "failed": 0,
                    "active": 0,
                },
            )()

        async def drain(self, *, timeout_seconds):
            return None

    monkeypatch.setattr(v49, "PumpSwapIngressPrefetchV49", FakePrefetcher)

    asyncio.run(v49.run_smoke_v49(rpc_timeout_seconds=3, marker="ok"))

    assert calls == [{"rpc_timeout_seconds": 3, "marker": "ok"}]

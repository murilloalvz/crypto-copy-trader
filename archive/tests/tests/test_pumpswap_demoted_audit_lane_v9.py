from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from dataclasses import dataclass
import io
from types import SimpleNamespace
import time
import unittest
from unittest.mock import patch

from src.pumpswap_eager_demoting_scheduler_v42 import EagerDemotingReadyAssetSchedulerV42
import unified_market_latency_smoke_v19 as v19


@dataclass
class _FakeNotification:
    signature: str


class _FakeResolver:
    hydration_budget_skips = 0
    negative_cache_skips = 0
    hydration_failures = 0
    historical_store_hits = 0
    store_hits = 0
    cache_hits = 0
    singleflight_waits = 0
    network_hydration_calls = 0
    hydration_successes = 0

    def __init__(self, **kwargs):
        pass


class _FakeHandle:
    reservation_assets = ("ASSET",)
    normalization_completed_monotonic = 0.0
    writer_enqueued_monotonic = 0.0

    def __init__(self, result):
        self._result = result

    async def wait_result(self):
        return self._result


class PumpSwapDemotedAuditLaneV9Tests(unittest.IsolatedAsyncioTestCase):
    async def test_v9_audit_lane_runs_demoted_payload_without_ready_queue(self):
        finalizer_calls = []

        class ConfiguredScheduler(EagerDemotingReadyAssetSchedulerV42):
            last_instance = None

            def __init__(self):
                super().__init__(
                    should_remain_stateful=lambda payload: payload.sequence == 0
                )
                ConfiguredScheduler.last_instance = self

        async def empty_stream(**kwargs):
            if False:
                yield None

        async def pumpswap_stream(**kwargs):
            yield _FakeNotification("sig-0")
            yield _FakeNotification("sig-1")

        async def fake_begin(notification, **kwargs):
            result = SimpleNamespace(
                newly_persisted_trades=1,
                duplicate_or_replayed_trades=0,
                unresolved_trades=0,
                role_filtered_trades=0,
                newly_persisted_lifecycle=0,
                affected_tokens=("ASSET",),
            )
            return _FakeHandle(result)

        def fake_prepare(notification, *, acquisition_run_key, persist_result):
            token = SimpleNamespace(
                trigger=object(),
                token_as_of=1,
                token_mint="ASSET",
                trigger_chain_time=1,
            )
            return SimpleNamespace(
                signature=notification.signature,
                observed_at=1,
                persist_result=persist_result,
                affected_tokens=("ASSET",),
                tokens=(token,),
                transaction_view_read_seconds=0.0,
                history_read_seconds=0.0,
                db_read_seconds=0.0,
                detect_seconds=0.0,
            )

        def fake_finalize(prepared, *, acquisition_run_key):
            finalizer_calls.append(prepared.signature)
            if prepared.signature == "sig-0":
                time.sleep(0.05)
            return SimpleNamespace(
                affected_tokens=("ASSET",),
                hits=(),
                telemetry=SimpleNamespace(episode_assign_seconds=0.0),
            )

        output = io.StringIO()
        with (
            patch.object(v19, "ReadyAssetScheduler", ConfiguredScheduler),
            patch.object(v19, "BoundedConcurrentResolver", _FakeResolver),
            patch.object(v19, "iter_pump_log_notifications", empty_stream),
            patch.object(v19, "iter_pumpswap_log_notifications", pumpswap_stream),
            patch.object(v19, "begin_pumpswap_notification_normalized_v5", fake_begin),
            patch.object(
                v19,
                "prepare_persisted_pumpswap_notification_for_radar_v5",
                fake_prepare,
            ),
            patch.object(v19, "finalize_prepared_pumpswap_radar_v5", fake_finalize),
            redirect_stdout(output),
        ):
            await v19.run_smoke_v19(
                run_key="test-v9",
                duration_seconds=1,
                commitment="confirmed",
                max_hydrations=1,
                rpc_timeout_seconds=1,
                pump_batch_size=2,
                pump_batch_max_wait_ms=0,
                pumpswap_workers=1,
                pumpswap_prepare_submitters=1,
                pumpswap_prepare_executor_workers=1,
                pumpswap_writer_batch_size=2,
                pumpswap_writer_batch_max_wait_ms=0,
                max_concurrent_resolutions=1,
                queue_size=8,
                offload_sync_radar=True,
                split_pump_radar=False,
                stateful_only_finalize=False,
                pumpswap_reservation_mode="partial_order",
                pumpswap_demoted_audit_split=True,
            )

        self.assertEqual(finalizer_calls, ["sig-0", "sig-1"])
        self.assertEqual(ConfiguredScheduler.last_instance.ready_backlog(), 0)
        text = output.getvalue()
        self.assertIn("demoted_audit_split=True", text)
        self.assertIn("demoted_audit_pending_at_deadline': 0", text)
        self.assertIn("pumpswap_proven_demoted_jobs=1", text)

    async def test_audit_pressure_does_not_overtake_later_stateful_work(self):
        finalizer_calls = []
        continuation_count = 40
        final_stateful_sequence = continuation_count + 1

        class ConfiguredScheduler(EagerDemotingReadyAssetSchedulerV42):
            last_instance = None

            def __init__(self):
                super().__init__(
                    should_remain_stateful=lambda payload: payload.sequence
                    in {0, final_stateful_sequence}
                )
                ConfiguredScheduler.last_instance = self

        async def empty_stream(**kwargs):
            if False:
                yield None

        async def pumpswap_stream(**kwargs):
            for sequence in range(final_stateful_sequence + 1):
                yield _FakeNotification(f"sig-{sequence}")

        async def fake_begin(notification, **kwargs):
            result = SimpleNamespace(
                newly_persisted_trades=1,
                duplicate_or_replayed_trades=0,
                unresolved_trades=0,
                role_filtered_trades=0,
                newly_persisted_lifecycle=0,
                affected_tokens=("ASSET",),
            )
            return _FakeHandle(result)

        def fake_prepare(notification, *, acquisition_run_key, persist_result):
            token = SimpleNamespace(
                trigger=object(),
                token_as_of=1,
                token_mint="ASSET",
                trigger_chain_time=1,
            )
            return SimpleNamespace(
                signature=notification.signature,
                observed_at=1,
                persist_result=persist_result,
                affected_tokens=("ASSET",),
                tokens=(token,),
                transaction_view_read_seconds=0.0,
                history_read_seconds=0.0,
                db_read_seconds=0.0,
                detect_seconds=0.0,
            )

        def fake_finalize(prepared, *, acquisition_run_key):
            finalizer_calls.append(prepared.signature)
            if prepared.signature == "sig-0":
                time.sleep(0.1)
            return SimpleNamespace(
                affected_tokens=("ASSET",),
                hits=(),
                telemetry=SimpleNamespace(episode_assign_seconds=0.0),
            )

        output = io.StringIO()
        with (
            patch.object(v19, "ReadyAssetScheduler", ConfiguredScheduler),
            patch.object(v19, "BoundedConcurrentResolver", _FakeResolver),
            patch.object(v19, "iter_pump_log_notifications", empty_stream),
            patch.object(v19, "iter_pumpswap_log_notifications", pumpswap_stream),
            patch.object(v19, "begin_pumpswap_notification_normalized_v5", fake_begin),
            patch.object(
                v19,
                "prepare_persisted_pumpswap_notification_for_radar_v5",
                fake_prepare,
            ),
            patch.object(v19, "finalize_prepared_pumpswap_radar_v5", fake_finalize),
            redirect_stdout(output),
        ):
            await v19.run_smoke_v19(
                run_key="test-v9-pressure",
                duration_seconds=1,
                commitment="confirmed",
                max_hydrations=1,
                rpc_timeout_seconds=1,
                pump_batch_size=2,
                pump_batch_max_wait_ms=0,
                pumpswap_workers=1,
                pumpswap_prepare_submitters=1,
                pumpswap_prepare_executor_workers=1,
                pumpswap_writer_batch_size=2,
                pumpswap_writer_batch_max_wait_ms=0,
                max_concurrent_resolutions=1,
                queue_size=128,
                offload_sync_radar=True,
                split_pump_radar=False,
                stateful_only_finalize=False,
                pumpswap_reservation_mode="partial_order",
                pumpswap_demoted_audit_split=True,
            )

        continuation_calls = [
            call for call in finalizer_calls if call.startswith("sig-")
            and call not in {"sig-0", f"sig-{final_stateful_sequence}"}
        ]
        self.assertEqual(len(continuation_calls), continuation_count)
        self.assertEqual(finalizer_calls[0], "sig-0")
        self.assertLess(
            finalizer_calls.index(f"sig-{final_stateful_sequence}"),
            finalizer_calls.index("sig-1"),
        )
        self.assertEqual(ConfiguredScheduler.last_instance.ready_backlog(), 0)
        text = output.getvalue()
        self.assertIn("demoted_audit_pending_at_deadline': 0", text)
        self.assertIn(f"pumpswap_proven_demoted_jobs={continuation_count}", text)


if __name__ == "__main__":
    unittest.main()

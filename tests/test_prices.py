import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from src import database
from src.assets import USDC_MINT
from src.database import initialize_database
from src.prices import (
    GeckoTerminalPriceProvider,
    Pool,
    PermanentPriceProviderError,
    ProviderCycleBudgetExhausted,
    TemporaryPriceProviderError,
)


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"data": {}}'


class PriceTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self._settings_patch = patch.object(
            database,
            "settings",
            SimpleNamespace(database_path=Path(self._tempdir.name) / "prices-test.db"),
        )
        self._settings_patch.start()
        initialize_database()
        GeckoTerminalPriceProvider.reset_global_rate_limit_state()

    def tearDown(self):
        self._settings_patch.stop()
        self._tempdir.cleanup()

    def test_stablecoin_price_does_not_require_network(self):
        provider = GeckoTerminalPriceProvider()

        self.assertEqual(provider.price_at(USDC_MINT, 1_700_000_000), 1.0)

    @patch("src.prices.urlopen")
    def test_non_retryable_http_error_stops_immediately(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test", 404, "Not Found", {}, None
        )
        provider = GeckoTerminalPriceProvider(min_interval_seconds=0)

        with self.assertRaises(PermanentPriceProviderError) as raised:
            provider._get("/missing")

        self.assertEqual(raised.exception.code, "http_404")
        self.assertEqual(mocked_urlopen.call_count, 1)

    @patch("src.prices.time.sleep")
    @patch("src.prices.urlopen")
    def test_rate_limit_is_retried_then_classified_temporary(
        self, mocked_urlopen, _mocked_sleep
    ):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test", 429, "Too Many Requests", {}, None
        )
        provider = GeckoTerminalPriceProvider(min_interval_seconds=0)

        with self.assertRaises(TemporaryPriceProviderError):
            provider._get("/limited")

        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch("src.prices.time.sleep")
    @patch("src.prices.urlopen")
    def test_rate_limit_backoff_is_conservative_between_retries(
        self, mocked_urlopen, mocked_sleep
    ):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test", 429, "Too Many Requests", {}, None
        )
        provider = GeckoTerminalPriceProvider(min_interval_seconds=0)

        with self.assertRaises(TemporaryPriceProviderError):
            provider._get("/limited")

        delays = [call.args[0] for call in mocked_sleep.call_args_list]
        self.assertEqual(len(delays), 1)
        self.assertAlmostEqual(delays[0], 12.0, delta=0.1)

    @patch("src.prices.time.sleep")
    @patch("src.prices.urlopen")
    def test_retry_after_header_is_respected(self, mocked_urlopen, mocked_sleep):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test", 429, "Too Many Requests", {"Retry-After": "7"}, None
        )
        provider = GeckoTerminalPriceProvider(
            min_interval_seconds=0,
            rate_limit_interval_seconds=0,
        )

        with self.assertRaises(TemporaryPriceProviderError):
            provider._get("/limited")

        delays = [call.args[0] for call in mocked_sleep.call_args_list]
        self.assertEqual(len(delays), 1)
        self.assertAlmostEqual(delays[0], 7.0, delta=0.1)

    @patch("src.prices.urlopen")
    def test_exhausted_failure_is_shared_within_provider_cycle(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test", 429, "Too Many Requests", {}, None
        )
        provider = GeckoTerminalPriceProvider(min_interval_seconds=0)
        with patch.object(provider, "_resolve_pool") as resolve_pool, patch(
            "src.prices.time.sleep"
        ):
            resolve_pool.return_value = Pool("pool", "base", 1.0, 1.0)
            for _ in range(2):
                with self.assertRaises(TemporaryPriceProviderError):
                    provider.price_at("token", 1_700_000_000, max_distance_seconds=120)

        self.assertEqual(mocked_urlopen.call_count, 2)

    @patch("src.prices.urlopen")
    def test_rate_limit_state_is_shared_between_provider_instances(self, mocked_urlopen):
        clock = FakeClock()
        mocked_urlopen.side_effect = [
            HTTPError("https://example.test", 429, "Too Many Requests", {}, None),
            FakeResponse(),
            FakeResponse(),
        ]
        with patch("src.prices.time.monotonic", side_effect=clock), patch(
            "src.prices.time.sleep", side_effect=clock.sleep
        ):
            first = GeckoTerminalPriceProvider(
                min_interval_seconds=0,
                rate_limit_interval_seconds=12,
                max_cycle_seconds=52,
            )
            first._get("/first")
            second = GeckoTerminalPriceProvider(
                min_interval_seconds=0,
                rate_limit_interval_seconds=12,
                max_cycle_seconds=52,
            )
            second._get("/second")

        self.assertEqual(mocked_urlopen.call_count, 3)
        self.assertEqual(clock.sleeps, [12.0, 12.0])

    @patch("src.prices.urlopen")
    def test_cycle_budget_defers_before_making_late_http_request(self, mocked_urlopen):
        clock = FakeClock()
        GeckoTerminalPriceProvider._global_last_request_at = clock.value
        GeckoTerminalPriceProvider._global_rate_limited_until = clock.value + 60
        with patch("src.prices.time.monotonic", side_effect=clock), patch(
            "src.prices.time.sleep", side_effect=clock.sleep
        ):
            provider = GeckoTerminalPriceProvider(
                min_interval_seconds=0,
                rate_limit_interval_seconds=12,
                max_cycle_seconds=5,
            )
            with self.assertRaises(ProviderCycleBudgetExhausted) as raised:
                provider._get("/too-late")

        self.assertEqual(raised.exception.code, "provider_cycle_budget_exhausted")
        self.assertFalse(raised.exception.counts_toward_retry)
        mocked_urlopen.assert_not_called()

    @patch("src.prices.urlopen", return_value=FakeResponse())
    def test_rate_limited_cycle_serves_five_calls_and_defers_sixth(self, mocked_urlopen):
        clock = FakeClock()
        GeckoTerminalPriceProvider._global_last_request_at = clock.value - 12
        GeckoTerminalPriceProvider._global_rate_limited_until = clock.value + 60
        with patch("src.prices.time.monotonic", side_effect=clock), patch(
            "src.prices.time.sleep", side_effect=clock.sleep
        ):
            provider = GeckoTerminalPriceProvider(
                min_interval_seconds=0,
                rate_limit_interval_seconds=12,
                max_cycle_seconds=52,
            )
            for index in range(5):
                provider._get(f"/ok/{index}")
            with self.assertRaises(ProviderCycleBudgetExhausted):
                provider._get("/deferred")

        self.assertEqual(mocked_urlopen.call_count, 5)
        self.assertEqual(clock.sleeps, [12.0, 12.0, 12.0, 12.0])

    @patch("src.prices.urlopen")
    def test_telemetry_marks_rate_limited_retry_and_wait(self, mocked_urlopen):
        clock = FakeClock()
        mocked_urlopen.side_effect = [
            HTTPError("https://example.test", 429, "Too Many Requests", {}, None),
            FakeResponse(),
        ]
        with patch("src.prices.time.monotonic", side_effect=clock), patch(
            "src.prices.time.sleep", side_effect=clock.sleep
        ):
            provider = GeckoTerminalPriceProvider(
                min_interval_seconds=0,
                rate_limit_interval_seconds=12,
                max_cycle_seconds=52,
            )
            with patch.object(provider, "_record_http_attempt") as telemetry:
                provider._get("/limited")

        self.assertEqual(telemetry.call_count, 2)
        second = telemetry.call_args_list[1].kwargs
        self.assertEqual(second["control_mode"], "rate_limited")
        self.assertEqual(second["wait_ms"], 12_000)

import unittest

from src.pons_curve_state_progress_v64 import (
    PonsCurveStateObservationV64,
    build_pons_curve_progress_snapshot_v64,
)
from src.robinhood_pons_adapter_v62 import PonsLaunchV62


TOKEN = "0x1111111111111111111111111111111111111111"
CURVE = "0x2222222222222222222222222222222222222222"
DEPLOYER = "0x3333333333333333333333333333333333333333"
PAIR = "0x4444444444444444444444444444444444444444"
TX = "0x" + "11" * 32


def launch(**overrides):
    values = dict(
        token_address=TOKEN,
        curve_address=CURVE,
        deployer_address=DEPLOYER,
        pair_token_address=PAIR,
        graduation_threshold_raw=1_000,
        pair_token_decimals=6,
        chain_time=100,
        observed_at=101,
        transaction_hash=TX,
        block_number=10,
        event_index=1,
    )
    values.update(overrides)
    return PonsLaunchV62(**values)


def state(**overrides):
    values = dict(
        token_address=TOKEN,
        graduation_threshold_raw=1_000,
        real_quote_reserve_raw=500,
        sellable_tokens_raw=500,
        ready_to_graduate=False,
        graduated=False,
        block_number=20,
        chain_time=120,
        observed_at=121,
        source_provider="archive_rpc",
    )
    values.update(overrides)
    return PonsCurveStateObservationV64(**values)


class PonsCurveStateProgressV64Tests(unittest.TestCase):
    def test_active_curve_progress_uses_exact_real_quote_reserve(self):
        snapshot = build_pons_curve_progress_snapshot_v64(
            launch=launch(), observations=[state()], as_of=130
        )
        self.assertEqual(snapshot.reserve_progress_pct, 50.0)
        self.assertEqual(snapshot.remaining_quote_to_threshold_raw, 500)
        self.assertEqual(snapshot.remaining_quote_to_threshold_pct, 50.0)
        self.assertTrue(snapshot.curve_tradable)

    def test_late_discovered_historical_state_cannot_leak_backward(self):
        early = state(
            real_quote_reserve_raw=400,
            block_number=20,
            chain_time=120,
            observed_at=121,
        )
        late_discovered = state(
            real_quote_reserve_raw=900,
            block_number=21,
            chain_time=125,
            observed_at=200,
        )
        snapshot = build_pons_curve_progress_snapshot_v64(
            launch=launch(), observations=[early, late_discovered], as_of=150
        )
        self.assertEqual(snapshot.observation_block_number, 20)
        self.assertEqual(snapshot.reserve_progress_pct, 40.0)

    def test_ready_to_graduate_state_is_not_tradable(self):
        snapshot = build_pons_curve_progress_snapshot_v64(
            launch=launch(),
            observations=[
                state(
                    real_quote_reserve_raw=1_000,
                    sellable_tokens_raw=0,
                    ready_to_graduate=True,
                )
            ],
            as_of=130,
        )
        self.assertEqual(snapshot.reserve_progress_pct, 100.0)
        self.assertFalse(snapshot.curve_tradable)
        self.assertIn("CURVE_READY_TO_GRADUATE_TRADING_HALTED", snapshot.data_quality_flags)

    def test_post_graduation_drained_curve_does_not_report_zero_percent_progress(self):
        snapshot = build_pons_curve_progress_snapshot_v64(
            launch=launch(),
            observations=[
                state(
                    real_quote_reserve_raw=0,
                    sellable_tokens_raw=0,
                    ready_to_graduate=False,
                    graduated=True,
                )
            ],
            as_of=130,
        )
        self.assertIsNone(snapshot.reserve_progress_pct)
        self.assertIsNone(snapshot.remaining_quote_to_threshold_pct)
        self.assertFalse(snapshot.curve_tradable)
        self.assertIn(
            "POST_GRADUATION_CURVE_STATE_PROGRESS_NOT_MEANINGFUL",
            snapshot.data_quality_flags,
        )

    def test_missing_state_is_explicit_not_imputed(self):
        snapshot = build_pons_curve_progress_snapshot_v64(
            launch=launch(), observations=[], as_of=130
        )
        self.assertIsNone(snapshot.reserve_progress_pct)
        self.assertIsNone(snapshot.curve_tradable)
        self.assertEqual(snapshot.data_quality_flags, ("NO_CAUSAL_STATE_OBSERVATION",))

    def test_threshold_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "threshold does not match"):
            build_pons_curve_progress_snapshot_v64(
                launch=launch(),
                observations=[state(graduation_threshold_raw=2_000)],
                as_of=130,
            )

    def test_ready_flag_must_match_sellable_tokens_on_active_curve(self):
        with self.assertRaisesRegex(ValueError, "must agree"):
            build_pons_curve_progress_snapshot_v64(
                launch=launch(),
                observations=[state(sellable_tokens_raw=0, ready_to_graduate=False)],
                as_of=130,
            )

    def test_latest_causally_known_state_wins(self):
        snapshot = build_pons_curve_progress_snapshot_v64(
            launch=launch(),
            observations=[
                state(real_quote_reserve_raw=300, block_number=20, chain_time=120, observed_at=121),
                state(real_quote_reserve_raw=700, block_number=25, chain_time=125, observed_at=126),
            ],
            as_of=130,
        )
        self.assertEqual(snapshot.observation_block_number, 25)
        self.assertEqual(snapshot.reserve_progress_pct, 70.0)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import wallet_forward_checkpoint as checkpoint
from src import database
from src.causal_quote_store import record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.opportunity_intelligence import WalletActionObservation
from src.wallet_causal_replay import WalletCausalReplayConfig
from src.wallet_forward_observations import record_wallet_forward_observation
from src.wallet_quote_watch import (
    latest_forward_observation_id,
    load_forward_buys_after,
    record_quote_attempt,
    schedule_buy_quotes,
)


class WalletForwardCheckpointTests(unittest.TestCase):
    def test_id_bounds_exclude_observations_outside_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("W", "OLD", "buy", 90, 100),
                    observation_key="old",
                )
                baseline = latest_forward_observation_id()
                record_wallet_forward_observation(
                    WalletActionObservation("W", "IN1", "buy", 110, 120),
                    observation_key="in-1",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("W", "IN2", "sell", 120, 130),
                    observation_key="in-2",
                )
                end_id = latest_forward_observation_id()
                record_wallet_forward_observation(
                    WalletActionObservation("W", "LATE", "buy", 140, 150),
                    observation_key="late",
                )

                scoped = checkpoint._load_scoped_observations(
                    ["W"], after_id=baseline, through_id=end_id
                )

        self.assertEqual([item.observation_key for item in scoped], ["in-1", "in-2"])

    def test_replay_is_buy_only_and_quote_is_bound_to_exact_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_wallet_forward_observation(
                    WalletActionObservation("W", "T", "buy", 95, 100),
                    observation_key="buy-a",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("W", "T", "sell", 99, 105),
                    observation_key="sell-a",
                )
                record_wallet_forward_observation(
                    WalletActionObservation("W", "T", "buy", 105, 110),
                    observation_key="buy-b",
                )
                observations = checkpoint._load_scoped_observations(["W"])

                buy_b = next(
                    item
                    for item in load_forward_buys_after(0)
                    if item.observation_key == "buy-b"
                )
                probe = schedule_buy_quotes([buy_b], delays_seconds=[0])[0]
                record_causal_quote(
                    CausalQuoteObservation(
                        token_mint="T",
                        side="buy",
                        market_time=110,
                        observed_at=110,
                        price_usd=2.0,
                        source="jupiter-test",
                        executable=False,
                    ),
                    quote_key=probe.quote_key,
                )
                record_quote_attempt(
                    probe,
                    requested_at=110,
                    completed_at=111,
                    status="success",
                    quote_key=probe.quote_key,
                )

                results = checkpoint._replay_event_scoped(
                    observations,
                    config=WalletCausalReplayConfig(
                        decision_delay_seconds=0,
                        require_executable_quote=False,
                    ),
                )

        self.assertEqual(len(results), 2)  # two BUYs; SELL is intentionally excluded
        self.assertEqual([row.side for row in results], ["buy", "buy"])
        by_observed_at = {row.source_observed_at: row for row in results}
        self.assertEqual(by_observed_at[100].status, "missing_quote")
        self.assertEqual(by_observed_at[110].status, "filled")
        self.assertEqual(by_observed_at[110].market_price_usd, 2.0)


if __name__ == "__main__":
    unittest.main()

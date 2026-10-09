import unittest

from src.analytics import calculate_wallet_score


def _performance(
    *, closed: int, return_pct: float = 10, win_rate: float = 60, drawdown: float = 8
) -> dict:
    return {
        "closed_trades": closed,
        "return_pct": return_pct,
        "win_rate_pct": win_rate,
        "max_drawdown_pct": drawdown,
    }


class ScoreTests(unittest.TestCase):
    def test_score_is_hidden_until_five_trades_are_closed(self):
        result = calculate_wallet_score(20, 4.0, _performance(closed=4))

        self.assertIsNone(result["score"])
        self.assertEqual(result["score_status"], "insufficient_data")
        self.assertIn("4/5", result["score_reason"])

    def test_financial_score_is_released_with_minimum_sample(self):
        result = calculate_wallet_score(20, 4.0, _performance(closed=5))

        self.assertEqual(result["score_status"], "ready")
        self.assertLessEqual(result["score"], 100)
        self.assertGreaterEqual(result["score"], 0)
        self.assertEqual(
            set(result["score_components"]),
            {
                "retorno",
                "win_rate",
                "risco",
                "amostra",
                "atividade",
                "frequencia",
            },
        )

    def test_score_components_are_capped_at_one_hundred_points(self):
        result = calculate_wallet_score(
            1_000,
            1_000,
            _performance(closed=1_000, return_pct=10_000, win_rate=100, drawdown=0),
        )

        self.assertEqual(result["score"], 100.0)

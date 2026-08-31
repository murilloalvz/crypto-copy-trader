import json
import unittest
from unittest.mock import patch

from src.jupiter_swap_v2 import (
    JupiterOrderError,
    JupiterSwapV2Client,
    jupiter_order_to_causal_quote,
    parse_jupiter_order,
)


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _payload(*, transaction=None, input_mint="USDC", output_mint="TOKEN") -> dict:
    return {
        "mode": "ultra",
        "inputMint": input_mint,
        "outputMint": output_mint,
        "inAmount": "25000000",
        "outAmount": "5000000000",
        "inUsdValue": 25.0,
        "outUsdValue": 24.8,
        "swapUsdValue": 24.9,
        "slippageBps": 50,
        "priceImpact": -0.1,
        "router": "metis",
        "transaction": transaction,
        "requestId": "request-1",
        "quoteId": "quote-1",
        "lastValidBlockHeight": "1234",
    }


class JupiterSwapV2Tests(unittest.TestCase):
    def test_quote_only_order_is_not_marked_executable(self):
        order = parse_jupiter_order(_payload(transaction=None), observed_at=100)
        quote = jupiter_order_to_causal_quote(
            order,
            token_mint="TOKEN",
            side="buy",
            token_decimals=9,
        )

        self.assertFalse(order.has_assembled_transaction)
        self.assertFalse(quote.executable)
        self.assertEqual(quote.side, "buy")
        self.assertEqual(quote.input_mint, "USDC")
        self.assertEqual(quote.output_mint, "TOKEN")
        self.assertEqual(quote.market_time, 100)
        self.assertAlmostEqual(quote.price_usd, 5.0)

    def test_assembled_transaction_is_candidate_executable_route(self):
        order = parse_jupiter_order(_payload(transaction="base64tx"), observed_at=100)
        quote = jupiter_order_to_causal_quote(
            order,
            token_mint="TOKEN",
            side="buy",
            token_decimals=9,
        )

        self.assertTrue(order.has_assembled_transaction)
        self.assertTrue(quote.executable)
        self.assertEqual(quote.route_id, "quote-1")
        self.assertEqual(quote.source, "jupiter_swap_v2_order:metis")

    def test_sell_price_uses_expected_usd_output_per_token_sold(self):
        payload = _payload(
            transaction="base64tx",
            input_mint="TOKEN",
            output_mint="USDC",
        )
        payload["inAmount"] = "5000000000"
        payload["outAmount"] = "24800000"
        payload["inUsdValue"] = 25.0
        payload["outUsdValue"] = 24.8
        order = parse_jupiter_order(payload, observed_at=100)

        quote = jupiter_order_to_causal_quote(
            order,
            token_mint="TOKEN",
            side="sell",
            token_decimals=9,
        )

        self.assertAlmostEqual(quote.price_usd, 4.96)
        self.assertEqual(quote.input_mint, "TOKEN")
        self.assertEqual(quote.output_mint, "USDC")

    def test_wrong_direction_is_rejected(self):
        order = parse_jupiter_order(_payload(), observed_at=100)
        with self.assertRaises(ValueError):
            jupiter_order_to_causal_quote(
                order,
                token_mint="TOKEN",
                side="sell",
                token_decimals=9,
            )

    def test_missing_usd_value_is_not_invented(self):
        payload = _payload()
        payload["inUsdValue"] = None
        order = parse_jupiter_order(payload, observed_at=100)
        with self.assertRaises(JupiterOrderError):
            jupiter_order_to_causal_quote(
                order,
                token_mint="TOKEN",
                side="buy",
                token_decimals=9,
            )

    def test_client_calls_order_with_api_key_and_without_execute(self):
        payload = _payload(transaction=None)
        client = JupiterSwapV2Client(api_key="secret", timeout=3)

        with patch("src.jupiter_swap_v2.urlopen", return_value=_Response(payload)) as mocked:
            with patch("src.jupiter_swap_v2.time.time", return_value=123.9):
                order = client.order(
                    input_mint="USDC",
                    output_mint="TOKEN",
                    amount_raw=25_000_000,
                )

        request = mocked.call_args.args[0]
        self.assertIn("/order?", request.full_url)
        self.assertIn("inputMint=USDC", request.full_url)
        self.assertIn("outputMint=TOKEN", request.full_url)
        self.assertIn("amount=25000000", request.full_url)
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-api-key"], "secret")
        self.assertEqual(order.observed_at, 123)
        self.assertFalse(order.has_assembled_transaction)

    def test_taker_is_optional_but_when_given_is_sent_for_transaction_assembly(self):
        client = JupiterSwapV2Client(api_key="secret")
        with patch(
            "src.jupiter_swap_v2.urlopen",
            return_value=_Response(_payload(transaction="base64tx")),
        ) as mocked:
            client.order(
                input_mint="USDC",
                output_mint="TOKEN",
                amount_raw=1,
                taker="WalletPublicKey",
            )

        request = mocked.call_args.args[0]
        self.assertIn("taker=WalletPublicKey", request.full_url)

    def test_client_does_not_accept_invalid_amount_or_slippage(self):
        client = JupiterSwapV2Client(api_key="secret")
        with self.assertRaises(ValueError):
            client.order(input_mint="A", output_mint="B", amount_raw=0)
        with self.assertRaises(ValueError):
            client.order(
                input_mint="A",
                output_mint="B",
                amount_raw=1,
                slippage_bps=10_001,
            )

    def test_parse_requires_positive_route_amounts(self):
        payload = _payload()
        payload["outAmount"] = "0"
        with self.assertRaises(JupiterOrderError):
            parse_jupiter_order(payload, observed_at=100)


if __name__ == "__main__":
    unittest.main()

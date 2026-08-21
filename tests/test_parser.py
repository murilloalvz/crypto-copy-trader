import unittest

from src.assets import USDC_MINT, WRAPPED_SOL_MINT
from src.solana import parse_wallet_transaction

WALLET = "Wallet1111111111111111111111111111111111"
JUPITER_V6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RAYDIUM_CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_SWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
MEME = "MemeTokenMint"


def _token_balance(mint: str, amount: float | str) -> dict:
    return {
        "owner": WALLET,
        "mint": mint,
        "uiTokenAmount": {"uiAmountString": str(amount)},
    }


def _transaction(
    *,
    program_id: str | None,
    pre_tokens: list[dict],
    post_tokens: list[dict],
    pre_lamports: int = 2_000_000_000,
    post_lamports: int = 1_499_995_000,
    fee: int = 5_000,
) -> dict:
    instructions = [{"programId": program_id}] if program_id else []
    return {
        "blockTime": 1_700_000_000,
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": WALLET}],
                "instructions": instructions,
            }
        },
        "meta": {
            "err": None,
            "fee": fee,
            "preBalances": [pre_lamports],
            "postBalances": [post_lamports],
            "preTokenBalances": pre_tokens,
            "postTokenBalances": post_tokens,
        },
    }


class ParserTests(unittest.TestCase):
    def test_jupiter_swap_requires_program_evidence_and_balance_flow(self):
        tx = _transaction(
            program_id=JUPITER_V6,
            pre_tokens=[],
            post_tokens=[_token_balance(MEME, 100)],
        )

        result = parse_wallet_transaction(WALLET, "sig", tx)

        self.assertEqual(result["kind"], "swap")
        self.assertEqual(result["dex"], "Jupiter v6")
        self.assertEqual(result["token_mint"], MEME)
        self.assertEqual(result["token_change"], 100.0)
        self.assertEqual(result["fee_sol"], 0.000005)

    def test_balance_deltas_without_supported_dex_are_not_a_swap(self):
        tx = _transaction(
            program_id=None,
            pre_tokens=[],
            post_tokens=[_token_balance(MEME, 100)],
        )

        result = parse_wallet_transaction(WALLET, "internal-transfer", tx)

        self.assertEqual(result["kind"], "token_transfer")
        self.assertIsNone(result["dex"])

    def test_fee_only_sol_delta_does_not_turn_token_transfer_into_swap(self):
        tx = _transaction(
            program_id=None,
            pre_tokens=[_token_balance(MEME, 100)],
            post_tokens=[_token_balance(MEME, 110)],
            post_lamports=1_999_995_000,
        )

        result = parse_wallet_transaction(WALLET, "fee-only", tx)

        self.assertEqual(result["kind"], "token_transfer")
        self.assertEqual(result["token_change"], 10.0)

    def test_parser_prefers_non_quote_token_in_raydium_swap(self):
        tx = _transaction(
            program_id=RAYDIUM_CPMM,
            pre_tokens=[_token_balance(USDC_MINT, 10), _token_balance(MEME, 0)],
            post_tokens=[_token_balance(USDC_MINT, 0), _token_balance(MEME, 1_000)],
            post_lamports=1_999_995_000,
        )

        result = parse_wallet_transaction(WALLET, "sig-token-swap", tx)

        self.assertEqual(result["kind"], "swap")
        self.assertEqual(result["dex"], "Raydium CPMM")
        self.assertEqual(result["token_mint"], MEME)
        self.assertEqual(result["token_change"], 1_000)

    def test_versioned_inner_instruction_finds_loaded_raydium_address(self):
        tx = _transaction(
            program_id=None,
            pre_tokens=[_token_balance(USDC_MINT, 10), _token_balance(MEME, 0)],
            post_tokens=[_token_balance(USDC_MINT, 0), _token_balance(MEME, 1_000)],
            post_lamports=1_999_995_000,
        )
        tx["meta"]["loadedAddresses"] = {
            "writable": [RAYDIUM_CPMM],
            "readonly": [],
        }
        tx["meta"]["innerInstructions"] = [
            {"index": 0, "instructions": [{"programIdIndex": 1}]}
        ]

        result = parse_wallet_transaction(WALLET, "versioned-raydium", tx)

        self.assertEqual(result["kind"], "swap")
        self.assertEqual(result["dex"], "Raydium CPMM")

    def test_pump_program_can_be_detected_from_logs(self):
        tx = _transaction(
            program_id=None,
            pre_tokens=[],
            post_tokens=[_token_balance(MEME, 100)],
        )
        tx["meta"]["logMessages"] = [f"Program {PUMP} invoke [1]"]

        result = parse_wallet_transaction(WALLET, "pump-log", tx)

        self.assertEqual(result["kind"], "swap")
        self.assertEqual(result["dex"], "Pump.fun")

    def test_pumpswap_liquidity_flow_is_not_mislabeled_as_swap(self):
        tx = _transaction(
            program_id=PUMP_SWAP,
            pre_tokens=[_token_balance(USDC_MINT, 100), _token_balance(MEME, 100)],
            post_tokens=[_token_balance(USDC_MINT, 90), _token_balance(MEME, 90)],
            post_lamports=1_999_995_000,
        )

        result = parse_wallet_transaction(WALLET, "liquidity-add", tx)

        self.assertEqual(result["kind"], "dex_activity")
        self.assertEqual(result["dex"], "PumpSwap")

    def test_native_sol_stablecoin_swap_preserves_sol_direction(self):
        tx = _transaction(
            program_id=JUPITER_V6,
            pre_tokens=[_token_balance(USDC_MINT, 100)],
            post_tokens=[_token_balance(USDC_MINT, 50)],
            pre_lamports=1_000_000_000,
            post_lamports=1_999_995_000,
        )

        result = parse_wallet_transaction(WALLET, "buy-sol", tx)

        self.assertEqual(result["kind"], "swap")
        self.assertEqual(result["token_mint"], WRAPPED_SOL_MINT)
        self.assertAlmostEqual(result["token_change"], 1.0)

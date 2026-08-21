from src.solana import parse_wallet_transaction


def test_parse_swap_from_balance_deltas():
    wallet = "Wallet1111111111111111111111111111111111"
    tx = {
        "blockTime": 1_700_000_000,
        "transaction": {"message": {"accountKeys": [{"pubkey": wallet}]}},
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000],
            "postBalances": [1_499_995_000],
            "preTokenBalances": [],
            "postTokenBalances": [{
                "owner": wallet,
                "mint": "TokenMint",
                "uiTokenAmount": {"uiAmount": 100.0},
            }],
        },
    }
    result = parse_wallet_transaction(wallet, "sig", tx)
    assert result["kind"] == "swap"
    assert result["token_change"] == 100.0
    assert result["fee_sol"] == 0.000005


def test_parser_prefers_non_quote_token_in_token_swap():
    wallet = "Wallet1111111111111111111111111111111111"
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    meme = "MemeTokenMint"
    tx = {
        "blockTime": 1_700_000_000,
        "transaction": {"message": {"accountKeys": [{"pubkey": wallet}]}},
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000],
            "postBalances": [1_999_995_000],
            "preTokenBalances": [
                {"owner": wallet, "mint": usdc, "uiTokenAmount": {"uiAmount": 10}},
                {"owner": wallet, "mint": meme, "uiTokenAmount": {"uiAmount": 0}},
            ],
            "postTokenBalances": [
                {"owner": wallet, "mint": usdc, "uiTokenAmount": {"uiAmount": 0}},
                {"owner": wallet, "mint": meme, "uiTokenAmount": {"uiAmount": 1000}},
            ],
        },
    }
    result = parse_wallet_transaction(wallet, "sig-token-swap", tx)
    assert result["kind"] == "swap"
    assert result["token_mint"] == meme
    assert result["token_change"] == 1000


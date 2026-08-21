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


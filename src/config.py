from dataclasses import dataclass
from os import getenv
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _csv_urls(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lstrip("@") for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    rpc_url: str = getenv("SOLANA_RPC_URL", "https://api.mainnet.solana.com")
    rpc_fallback_urls: tuple[str, ...] = _csv_urls(
        getenv("SOLANA_RPC_FALLBACK_URLS", "https://solana-rpc.publicnode.com")
    )
    database_path: Path = Path(getenv("DATABASE_PATH", "data/copytrader.db"))
    max_signatures: int = int(getenv("MAX_SIGNATURES_PER_SYNC", "30"))
    starting_balance_usd: float = float(getenv("STARTING_BALANCE_USD", "1000"))
    copy_size_usd: float = float(getenv("COPY_SIZE_USD", "25"))
    slippage_bps: int = int(getenv("SLIPPAGE_BPS", "100"))
    copy_delay_seconds: int = int(getenv("COPY_DELAY_SECONDS", "15"))
    min_signal_liquidity_usd: float = float(
        getenv("MIN_SIGNAL_LIQUIDITY_USD", "50000")
    )
    min_signal_volume_24h_usd: float = float(
        getenv("MIN_SIGNAL_VOLUME_24H_USD", "10000")
    )
    max_price_retry_attempts: int = int(getenv("MAX_PRICE_RETRY_ATTEMPTS", "3"))
    birdeye_api_key: str = getenv("BIRDEYE_API_KEY", "").strip()
    solana_tracker_api_key: str = getenv("SOLANA_TRACKER_API_KEY", "").strip()
    solana_tracker_timeout_seconds: int = int(
        getenv("SOLANA_TRACKER_TIMEOUT_SECONDS", "12")
    )
    solana_tracker_max_attempts: int = int(
        getenv("SOLANA_TRACKER_MAX_ATTEMPTS", "3")
    )
    x_bearer_token: str = getenv("X_BEARER_TOKEN", "").strip()
    social_tier_a_accounts: tuple[str, ...] = _csv_values(
        getenv("SOCIAL_TIER_A_ACCOUNTS", "")
    )
    social_lookback_minutes: int = int(getenv("SOCIAL_LOOKBACK_MINUTES", "15"))
    social_timeout_seconds: int = int(getenv("SOCIAL_TIMEOUT_SECONDS", "10"))


settings = Settings()

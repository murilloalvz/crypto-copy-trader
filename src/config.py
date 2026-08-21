from dataclasses import dataclass
from os import getenv
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    rpc_url: str = getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    database_path: Path = Path(getenv("DATABASE_PATH", "data/copytrader.db"))
    max_signatures: int = int(getenv("MAX_SIGNATURES_PER_SYNC", "30"))
    starting_balance_usd: float = float(getenv("STARTING_BALANCE_USD", "1000"))
    copy_size_usd: float = float(getenv("COPY_SIZE_USD", "25"))
    slippage_bps: int = int(getenv("SLIPPAGE_BPS", "100"))
    copy_delay_seconds: int = int(getenv("COPY_DELAY_SECONDS", "15"))


settings = Settings()

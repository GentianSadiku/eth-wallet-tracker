import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class Config:
    """Application configuration."""

    # API Keys
    etherscan_api_key: str
    coingecko_api_key: Optional[str] = None
    alchemy_api_key: Optional[str] = None

    # API URLs
    etherscan_base_url: str = "https://api.etherscan.io/api"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"

    # Analysis settings
    max_early_wallets: int = 50
    max_transactions_per_request: int = 10000
    rate_limit_delay: float = 0.2  # seconds between API calls

    # Output settings
    output_format: str = "table"  # table, csv, json
    include_likely_airdrops: bool = True
    min_token_amount: float = 0.0

    @classmethod
    def from_env(cls) -> "Config":
        """Create config from environment variables."""
        etherscan_key = os.getenv("ETHERSCAN_API_KEY")
        if not etherscan_key:
            raise ValueError(
                "ETHERSCAN_API_KEY environment variable is required")

        return cls(
            etherscan_api_key=etherscan_key,
            coingecko_api_key=os.getenv("COINGECKO_API_KEY"),
            alchemy_api_key=os.getenv("ALCHEMY_API_KEY"),
            max_early_wallets=int(os.getenv("MAX_EARLY_WALLETS", "50")),
            max_transactions_per_request=int(
                os.getenv("MAX_TRANSACTIONS_PER_REQUEST", "10000")),
            rate_limit_delay=float(os.getenv("RATE_LIMIT_DELAY", "0.2")),
            output_format=os.getenv("OUTPUT_FORMAT", "table"),
            include_likely_airdrops=os.getenv(
                "INCLUDE_LIKELY_AIRDROPS", "true").lower() == "true",
            min_token_amount=float(os.getenv("MIN_TOKEN_AMOUNT", "0.0")),
        )

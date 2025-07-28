"""
Data models for Ethereum wallet tracking.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from decimal import Decimal


@dataclass
class TokenInfo:
    """Information about an Ethereum token."""
    name: str
    symbol: str
    contract_address: str
    decimals: int
    total_supply: Optional[str] = None


@dataclass
class WalletTransaction:
    """Individual wallet transaction with a token."""
    wallet_address: str
    tx_hash: str
    block_number: int
    timestamp: datetime
    token_amount: Decimal
    token_amount_raw: str
    direction: str  # 'in' or 'out'
    from_address: str
    to_address: str
    gas_used: Optional[int] = None
    gas_price: Optional[str] = None


@dataclass
class WalletAnalysis:
    """Analysis of a wallet's interaction with a token."""
    wallet_address: str
    first_transaction: WalletTransaction
    total_received: Decimal
    total_sent: Decimal
    net_position: Decimal
    transaction_count: int
    estimated_eth_cost: Optional[Decimal] = None
    estimated_usd_value: Optional[Decimal] = None
    is_likely_buyer: bool = False
    is_likely_airdrop: bool = False


@dataclass
class TokenAnalysis:
    """Complete analysis of early token interactions."""
    token_info: TokenInfo
    total_transactions: int
    unique_wallets: int
    earliest_wallets: List[WalletAnalysis]
    analysis_date: datetime

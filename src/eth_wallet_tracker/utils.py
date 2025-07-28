"""
Utility functions for data processing and analysis.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import re
import copy
import logging
from collections import defaultdict

from .models import TokenInfo, WalletTransaction, WalletAnalysis
from .config import Config

# Set up logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def is_valid_ethereum_address(address: str) -> bool:
    """Check if a string is a valid Ethereum address."""
    if not address:
        return False

    # Remove 0x prefix if present
    if address.startswith('0x'):
        address = address[2:]

    # Check if it's 40 hex characters
    return bool(re.match(r'^[0-9a-fA-F]{40}$', address))


def normalize_address(address: str) -> str:
    """Normalize an Ethereum address to lowercase with 0x prefix."""
    if not address:
        return ""

    address = address.lower()
    if not address.startswith('0x'):
        address = '0x' + address

    return address


def wei_to_ether(wei: str) -> Decimal:
    """Convert Wei to Ether."""
    try:
        return Decimal(wei) / Decimal('1000000000000000000')
    except (ValueError, TypeError, ZeroDivisionError) as e:
        logger.warning(f"Error converting wei to ether: {wei}, error: {e}")
        return Decimal('0')


def format_token_amount(amount: Decimal, decimals: int) -> Decimal:
    """Format token amount based on decimals."""
    try:
        if decimals == 0:
            return amount

        divisor = Decimal(10) ** decimals
        return (amount / divisor).quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    except (ValueError, TypeError, ZeroDivisionError) as e:
        logger.warning(
            f"Error formatting token amount: {amount}, decimals: {decimals}, error: {e}")
        return Decimal('0')


def parse_etherscan_transactions(raw_transactions: List[Dict[str, Any]],
                                 token_info: TokenInfo) -> List[WalletTransaction]:
    """Parse raw Etherscan transaction data into WalletTransaction objects."""
    transactions = []

    if not raw_transactions:
        return transactions

    for tx in raw_transactions:
        try:
            # Validate required fields
            required_fields = ['timeStamp', 'value',
                               'hash', 'blockNumber', 'from', 'to']
            if not all(field in tx for field in required_fields):
                logger.warning(
                    f"Skipping transaction with missing fields: {tx}")
                continue

            # Convert timestamp
            timestamp = datetime.fromtimestamp(int(tx['timeStamp']))

            # Convert token amount
            token_amount_raw = tx['value']
            token_amount = format_token_amount(
                Decimal(token_amount_raw), token_info.decimals)

            # Validate addresses
            from_addr = normalize_address(tx['from'])
            to_addr = normalize_address(tx['to'])

            if not is_valid_ethereum_address(from_addr) or not is_valid_ethereum_address(to_addr):
                logger.warning(
                    f"Skipping transaction with invalid addresses: from={from_addr}, to={to_addr}")
                continue

            transaction = WalletTransaction(
                wallet_address=to_addr,  # We'll adjust this based on context
                tx_hash=tx['hash'],
                block_number=int(tx['blockNumber']),
                timestamp=timestamp,
                token_amount=token_amount,
                token_amount_raw=token_amount_raw,
                direction='in',  # We'll adjust this based on context
                from_address=from_addr,
                to_address=to_addr,
                gas_used=int(tx.get('gasUsed', 0)) if tx.get(
                    'gasUsed') else None,
                gas_price=tx.get('gasPrice')
            )

            transactions.append(transaction)

        except (ValueError, KeyError, TypeError, OverflowError) as e:
            logger.warning(
                f"Error parsing transaction {tx.get('hash', 'unknown')}: {e}")
            continue

    logger.info(
        f"Parsed {len(transactions)} valid transactions from {len(raw_transactions)} raw transactions")
    return transactions


def group_transactions_by_wallet(transactions: List[WalletTransaction]) -> Dict[str, List[WalletTransaction]]:
    """
    Group transactions by wallet address.

    CRITICAL FIX: Creates proper copies to avoid data corruption.
    """
    wallet_transactions = defaultdict(list)

    for tx in transactions:
        try:
            # CRITICAL FIX: Create proper copies instead of using the same object reference
            # Add transaction for the recipient (incoming)
            recipient_tx = copy.deepcopy(tx)  # ✅ Create a deep copy
            recipient_tx.wallet_address = tx.to_address
            recipient_tx.direction = 'in'
            wallet_transactions[tx.to_address].append(recipient_tx)

            # If sender is not a common contract (DEX, etc.), add as outgoing
            if not is_likely_contract(tx.from_address):
                # CRITICAL FIX: Create a new object instead of modifying original
                sender_tx = WalletTransaction(  # ✅ Create new object
                    wallet_address=tx.from_address,
                    tx_hash=tx.tx_hash,
                    block_number=tx.block_number,
                    timestamp=tx.timestamp,
                    token_amount=tx.token_amount,
                    token_amount_raw=tx.token_amount_raw,
                    direction='out',
                    from_address=tx.from_address,
                    to_address=tx.to_address,
                    gas_used=tx.gas_used,
                    gas_price=tx.gas_price
                )
                wallet_transactions[tx.from_address].append(sender_tx)
        except Exception as e:
            logger.error(f"Error grouping transaction {tx.tx_hash}: {e}")
            continue

    logger.info(
        f"Grouped transactions into {len(wallet_transactions)} unique wallets")
    return dict(wallet_transactions)


def is_likely_contract(address: str) -> bool:
    """Enhanced heuristic to determine if an address is likely a smart contract."""
    try:
        address = normalize_address(address)

        if not address or not is_valid_ethereum_address(address):
            return False

        # Common special addresses
        special_addresses = [
            '0x0000000000000000000000000000000000000000',  # Null address
            '0x000000000000000000000000000000000000dead',  # Burn address
            '0x0000000000000000000000000000000000000001',  # EVM precompile
            '0x0000000000000000000000000000000000000002',  # EVM precompile
            '0x0000000000000000000000000000000000000003',  # EVM precompile
            '0x0000000000000000000000000000000000000004',  # EVM precompile
            '0x0000000000000000000000000000000000000005',  # EVM precompile
            '0x0000000000000000000000000000000000000006',  # EVM precompile
            '0x0000000000000000000000000000000000000007',  # EVM precompile
            '0x0000000000000000000000000000000000000008',  # EVM precompile
            '0x0000000000000000000000000000000000000009',  # EVM precompile
        ]

        if address in special_addresses:
            return True

        # Known DEX and DeFi contract addresses
        known_contracts = [
            '0x7a250d5630b4cf539739df2c5dacb4c659f2488d',  # Uniswap V2 Router
            '0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45',  # Uniswap V3 Router
            '0xe592427a0aece92de3edee1f18e0157c05861564',  # Uniswap V3 SwapRouter
            '0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad',  # Uniswap Universal Router
            '0x1111111254eeb25477b68fb85ed929f73a960582',  # 1inch V4 Router
            '0x11111254369792b2ca5d084ab5eea397ca8fa48b',  # 1inch V5 Router
            '0xdef1c0ded9bec7f1a1670819833240f027b25eff',  # 0x Exchange Proxy
            '0x881d40237659c251811cec9c364ef91dc08d300c',  # Metamask Swap Router
            '0x6b175474e89094c44da98b954eedeac495271d0f',  # DAI Token
            '0xa0b86a33e6441e3c6cdeaf9bf464c44c78a1f0e9',  # Binance 14
            '0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be',  # Binance 7
            '0xd551234ae421e3bcba99a0da6d736074f22192ff',  # Binance 8
            '0x564286362092d8e7936f0549571a803b203aaced',  # FTX Exchange
            '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',  # WETH
            '0x1e0049783f008a0085193e00003d00cd54003c71',  # OpenSea Seaport
            '0x00000000006c3852cbef3e08e8df289169ede581',  # OpenSea Seaport 1.1
        ]

        if address in known_contracts:
            return True

        # Pattern-based detection
        # Many contracts have patterns like repeated digits or specific endings
        address_no_prefix = address[2:] if address.startswith(
            '0x') else address

        # Check for repeated patterns (often contracts)
        if len(set(address_no_prefix)) <= 4:  # Very few unique characters
            return True

        # Check for addresses ending in many zeros (often contracts)
        if address_no_prefix.endswith('00000'):
            return True

        # Check for addresses starting with many zeros (often contracts)
        if address_no_prefix.startswith('00000'):
            return True

        return False
    except Exception as e:
        logger.warning(f"Error checking if address is contract {address}: {e}")
        return False


def analyze_wallet_transactions(wallet_address: str,
                                transactions: List[WalletTransaction],
                                config: Optional[Config] = None) -> Optional[WalletAnalysis]:
    """Analyze a wallet's transactions to determine investment pattern."""
    try:
        if not transactions:
            return None

        # Sort transactions by block number
        transactions.sort(key=lambda x: x.block_number)
        first_transaction = transactions[0]

        # Calculate totals with error handling
        total_received = Decimal('0')
        total_sent = Decimal('0')

        for tx in transactions:
            try:
                if tx.direction == 'in':
                    total_received += tx.token_amount
                else:
                    total_sent += tx.token_amount
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Error processing transaction amount {tx.tx_hash}: {e}")
                continue

        net_position = total_received - total_sent

        # Apply minimum token amount filter if config is provided
        if config and total_received < Decimal(str(config.min_token_amount)):
            return None

        # Enhanced heuristics for determining if it's a buyer vs airdrop recipient
        is_likely_airdrop = (
            len(transactions) == 1 and
            transactions[0].direction == 'in' and
            is_likely_contract(transactions[0].from_address) and
            is_round_number(total_received)
        )

        # More sophisticated buyer detection
        is_likely_buyer = (
            not is_likely_airdrop and
            total_received > 0 and
            (
                not is_round_number(total_received) or  # Not round numbers
                len(transactions) > 1 or  # Multiple transactions
                (len(transactions) == 1 and not is_likely_contract(
                    transactions[0].from_address))  # From EOA
            )
        )

        return WalletAnalysis(
            wallet_address=wallet_address,
            first_transaction=first_transaction,
            total_received=total_received,
            total_sent=total_sent,
            net_position=net_position,
            transaction_count=len(transactions),
            is_likely_buyer=is_likely_buyer,
            is_likely_airdrop=is_likely_airdrop
        )
    except Exception as e:
        logger.error(f"Error analyzing wallet {wallet_address}: {e}")
        return None


def is_round_number(amount: Decimal) -> bool:
    """Enhanced check if a number is likely a 'round' number (suggesting airdrop)."""
    try:
        if amount <= 0:
            return False

        # Convert to string and check for patterns
        amount_str = str(amount)
        amount_float = float(amount)

        # Check if it's a power of 10 or has many trailing zeros
        if amount_str.endswith('000000') or amount_str.endswith('00000'):
            return True

        # Check if it's a simple multiple of common airdrop amounts
        common_amounts = [
            100, 200, 500, 1000, 2000, 5000, 10000, 20000, 25000,
            50000, 100000, 200000, 500000, 1000000, 2000000, 5000000,
            10000000, 50000000, 100000000, 500000000, 1000000000
        ]

        for common in common_amounts:
            if abs(amount_float - common) < 0.001:  # Very close to round number
                return True

        # Check for numbers that are exact powers of 10
        if amount_float > 0:
            import math
            try:
                log10_val = math.log10(amount_float)
                if abs(log10_val - round(log10_val)) < 0.001:  # Close to power of 10
                    return True
            except (ValueError, OverflowError):
                pass

        # Check for numbers ending in many 9s (like 99999, 999999)
        if amount_str.endswith('9999') or amount_str.endswith('99999'):
            return True

        return False
    except Exception as e:
        logger.warning(f"Error checking if number is round {amount}: {e}")
        return False


def format_number(number: Decimal, decimals: int = 2) -> str:
    """Format a number with thousands separators."""
    try:
        if number == 0:
            return "0"

        # Convert to float for formatting
        num = float(number)

        if num >= 1_000_000_000:
            return f"{num / 1_000_000_000:.{decimals}f}B"
        elif num >= 1_000_000:
            return f"{num / 1_000_000:.{decimals}f}M"
        elif num >= 1_000:
            return f"{num / 1_000:.{decimals}f}K"
        else:
            return f"{num:.{decimals}f}"
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Error formatting number {number}: {e}")
        return str(number)


def estimate_transaction_cost_usd(gas_used: Optional[int], gas_price: Optional[str],
                                  eth_price_usd: float) -> Optional[Decimal]:
    """Estimate the USD cost of a transaction."""
    try:
        if not gas_used or not gas_price or eth_price_usd <= 0:
            return None

        # Convert gas price from wei to ether
        gas_price_ether = wei_to_ether(gas_price)

        # Calculate total cost in ETH
        eth_cost = gas_price_ether * Decimal(gas_used)

        # Convert to USD
        usd_cost = eth_cost * Decimal(str(eth_price_usd))

        return usd_cost
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(
            f"Error estimating transaction cost: gas_used={gas_used}, gas_price={gas_price}, eth_price={eth_price_usd}, error={e}")
        return None

import time
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
import requests
from web3 import Web3

from .config import Config
from .models import TokenInfo, WalletTransaction

# Set up logging
logger = logging.getLogger(__name__)


class EtherscanClient:
    """Client for Etherscan API."""

    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.etherscan_base_url
        self.api_key = config.etherscan_api_key

    def _make_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a request to Etherscan API."""
        params["apikey"] = self.api_key

        response = requests.get(self.base_url, params=params)
        response.raise_for_status()

        data = response.json()
        if data.get("status") != "1":
            raise Exception(
                f"Etherscan API error: {data.get('message', 'Unknown error')}")

        # Rate limiting
        time.sleep(self.config.rate_limit_delay)

        return data

    def get_current_block_number(self) -> int:
        """Get the current block number from Etherscan."""
        params = {
            "module": "proxy",
            "action": "eth_blockNumber"
        }
        try:
            data = self._make_request(params)
            # Convert hex to int
            block_hex = data.get("result", "0x0")
            return int(block_hex, 16)
        except Exception as e:
            logger.warning(f"Failed to get current block number: {e}")
            import time
            estimated_block = 15500000 + int((time.time() - 1663200000) / 12)
            return estimated_block

    def get_token_transfers(self, contract_address: str, start_block: int = 0,
                            end_block: Optional[int] = None, page: int = 1) -> List[Dict[str, Any]]:
        """Get token transfer events for a contract."""
        if end_block is None:
            end_block = self.get_current_block_number()

        params = {
            "module": "account",
            "action": "tokentx",
            "contractaddress": contract_address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": self.config.max_transactions_per_request,
            "sort": "asc"
        }

        data = self._make_request(params)
        return data.get("result", [])

    def get_token_info(self, contract_address: str) -> Dict[str, Any]:
        """Get basic token information from Etherscan token info API."""
        params = {
            "module": "token",
            "action": "tokeninfo",
            "contractaddress": contract_address
        }

        try:
            data = self._make_request(params)
            result = data.get("result", [])

            if result and len(result) > 0:
                token_data = result[0]

                # Calculate decimals from divisor string
                divisor = token_data.get("divisor", "1000000000000000000")
                decimals = len(divisor) - 1 if divisor.startswith("1") else 18

                return {
                    "name": token_data.get("tokenName", "Unknown Token"),
                    "symbol": token_data.get("symbol", "UNKNOWN"),
                    "decimals": decimals,
                    "contract_address": contract_address.lower(),
                    "total_supply": token_data.get("totalSupply", "0")
                }
        except Exception as e:
            logger.warning(
                f"Token info API failed for {contract_address}: {e}")
            # Try alternative approach

        # Fallback: try to get contract source and parse it
        try:
            source_params = {
                "module": "contract",
                "action": "getsourcecode",
                "address": contract_address
            }
            source_data = self._make_request(source_params)
            source_result = source_data.get("result", [])

            if source_result and len(source_result) > 0:
                contract_info = source_result[0]
                contract_name = contract_info.get("ContractName", "")

                # Try to extract token info from contract name or source
                return {
                    "name": contract_name if contract_name else "Unknown Token",
                    "symbol": "UNKNOWN",
                    "decimals": 18,  # Most common default
                    "contract_address": contract_address.lower(),
                    "total_supply": None
                }
        except Exception as e:
            logger.warning(
                f"Contract source API failed for {contract_address}: {e}")

        # Try proxy eth_call as a last resort (Etherscan-only, no external RPC)
        proxy_info = self._get_token_metadata_via_proxy(contract_address)
        if proxy_info:
            return proxy_info

        # Final fallback with minimal info
        return {
            "name": "Unknown Token",
            "symbol": "UNKNOWN",
            "decimals": 18,
            "contract_address": contract_address.lower(),
            "total_supply": None
        }

    def get_eth_transactions(self, address: str, start_block: int = 0,
                             end_block: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get ETH transactions for an address."""
        if end_block is None:
            end_block = self.get_current_block_number()

        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": 1,
            "offset": 1000,
            "sort": "asc"
        }

        data = self._make_request(params)
        return data.get("result", [])

    # ------------------------------------------------------------------
    # Low-level proxy call helpers (Etherscan-only metadata fallback)
    # ------------------------------------------------------------------

    def _proxy_eth_call(self, contract_address: str, data: str) -> Optional[str]:
        """Call a contract function via Etherscan's proxy.eth_call endpoint."""
        params = {
            "module": "proxy",
            "action": "eth_call",
            "to": contract_address,
            "data": data,
            "tag": "latest"
        }
        try:
            result = self._make_request(params).get("result")
            return result
        except Exception as e:
            logger.warning(f"eth_call failed for {contract_address}: {e}")
            return None

    @staticmethod
    def _decode_string(hex_str: str) -> str:
        """Decode a hex-encoded ABI string return value."""
        try:
            if not hex_str or hex_str == "0x":
                return ""

            # Remove 0x prefix and decode bytes
            raw = bytes.fromhex(hex_str[2:])

            # The standard ABI encoding for string is: offset (32), length (32), data (padded)
            if len(raw) >= 64:
                # The length is stored in bytes 32-64
                strlen = int.from_bytes(raw[32:64], byteorder="big")
                data_bytes = raw[64:64+strlen]
            else:
                # Some tokens (old) return fixed 32-byte string padded with zeros
                data_bytes = raw.rstrip(b"\x00")

            return data_bytes.decode("utf-8", "replace")
        except Exception:
            return ""

    def _get_token_metadata_via_proxy(self, contract_address: str) -> Optional[Dict[str, Any]]:
        """Fetch name, symbol, decimals using proxy.eth_call. Returns dict or None."""
        try:
            # Function selectors pre-computed with keccak-256
            SELECTOR_NAME = "0x06fdde03"      # name()
            SELECTOR_SYMBOL = "0x95d89b41"    # symbol()
            SELECTOR_DECIMALS = "0x313ce567"  # decimals()

            name_hex = self._proxy_eth_call(contract_address, SELECTOR_NAME)
            symbol_hex = self._proxy_eth_call(
                contract_address, SELECTOR_SYMBOL)
            decimals_hex = self._proxy_eth_call(
                contract_address, SELECTOR_DECIMALS)

            if name_hex is None and symbol_hex is None and decimals_hex is None:
                return None

            name = self._decode_string(name_hex)
            symbol = self._decode_string(symbol_hex)

            try:
                decimals = int(decimals_hex, 16) if decimals_hex else 18
            except ValueError:
                decimals = 18

            return {
                "name": name or "Unknown Token",
                "symbol": symbol or "UNKNOWN",
                "decimals": decimals,
                "contract_address": contract_address.lower(),
                "total_supply": None,
            }
        except Exception as e:
            logger.warning(
                f"Proxy metadata fetch failed for {contract_address}: {e}")
            return None

    def get_current_eth_price(self) -> float:
        """Get current ETH price in USD using Etherscan stats endpoint."""
        params = {
            "module": "stats",
            "action": "ethprice"
        }
        try:
            data = self._make_request(params)
            result = data.get("result", {})
            return float(result.get("ethusd", 0))
        except Exception as e:
            logger.warning(f"ETH price API failed via Etherscan: {e}")
            # Fallback to a constant price if API fails
            return 2000.0


class CoinGeckoClient:
    """Client for CoinGecko API."""

    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.coingecko_base_url
        self.api_key = config.coingecko_api_key

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to CoinGecko API."""
        url = f"{self.base_url}/{endpoint}"
        headers = {}

        if self.api_key:
            headers["x-cg-pro-api-key"] = self.api_key

        if params is None:
            params = {}

        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

        # Rate limiting
        time.sleep(self.config.rate_limit_delay)

        return response.json()

    def search_token_by_name(self, name: str) -> List[Dict[str, Any]]:
        """Search for tokens by name."""
        try:
            data = self._make_request("search", {"query": name})
            return data.get("coins", [])
        except Exception as e:
            logger.warning(f"Token search failed for '{name}': {e}")
            return []

    def get_token_by_contract_address(self, contract_address: str,
                                      platform: str = "ethereum") -> Optional[Dict[str, Any]]:
        """Get token information by contract address."""
        try:
            endpoint = f"coins/{platform}/contract/{contract_address.lower()}"
            return self._make_request(endpoint)
        except Exception as e:
            logger.warning(
                f"Token info by address failed for {contract_address}: {e}")
            return None

    def get_token_price_history(self, token_id: str, vs_currency: str = "usd",
                                from_timestamp: Optional[int] = None, to_timestamp: Optional[int] = None) -> Dict[str, Any]:
        """Get historical price data for a token."""
        try:
            if from_timestamp is None or to_timestamp is None:
                # Default to last 30 days if no timestamps provided
                import time
                to_timestamp = int(time.time())
                from_timestamp = to_timestamp - \
                    (30 * 24 * 60 * 60)  # 30 days ago

            params = {
                "vs_currency": vs_currency,
                "from": from_timestamp,
                "to": to_timestamp
            }
            endpoint = f"coins/{token_id}/market_chart/range"
            return self._make_request(endpoint, params)
        except Exception as e:
            logger.warning(f"Price history failed for {token_id}: {e}")
            return {"prices": [], "market_caps": [], "total_volumes": []}


class Web3Client:
    """Client for Web3 operations."""

    def __init__(self, config: Optional[Config] = None, provider_url: Optional[str] = None):
        if provider_url is None:
            # Use Alchemy if API key is available, otherwise use public RPC
            if config and config.alchemy_api_key and not str(config.alchemy_api_key).lower().startswith("your_") and config.alchemy_api_key.strip() != "":
                provider_url = f"https://eth-mainnet.g.alchemy.com/v2/{config.alchemy_api_key}"
            else:
                provider_url = "https://eth.llamarpc.com"

        self.w3 = Web3(Web3.HTTPProvider(provider_url))

    def is_contract_address(self, address: str) -> bool:
        """Check if an address is a smart contract."""
        try:
            address = Web3.to_checksum_address(address)
            code = self.w3.eth.get_code(address)
            return len(code) > 0
        except Exception as e:
            logger.warning(f"Contract check failed for {address}: {e}")
            return False

    def get_token_info_from_contract(self, contract_address: str) -> TokenInfo:
        """Get token information directly from the contract."""
        try:
            # Standard ERC20 ABI for name, symbol, decimals
            erc20_abi = [
                {"constant": True, "inputs": [], "name": "name", "outputs": [
                    {"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [
                    {"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [
                    {"name": "", "type": "uint8"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [
                    {"name": "", "type": "uint256"}], "type": "function"}
            ]

            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=erc20_abi
            )

            name = contract.functions.name().call()
            symbol = contract.functions.symbol().call()
            decimals = contract.functions.decimals().call()
            total_supply = str(contract.functions.totalSupply().call())

            return TokenInfo(
                name=name,
                symbol=symbol,
                contract_address=contract_address.lower(),
                decimals=decimals,
                total_supply=total_supply
            )
        except Exception as e:
            logger.warning(f"Contract call failed for {contract_address}: {e}")
            # Fallback to basic info
            return TokenInfo(
                name="Unknown Token",
                symbol="UNKNOWN",
                contract_address=contract_address.lower(),
                decimals=18,
                total_supply=None
            )

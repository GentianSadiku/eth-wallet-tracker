# Ethereum Wallet Tracker

A minimal, lightweight tool to track the earliest wallet interactions with any Ethereum token and discover their investment amounts. This simple project serves as an excellent starting point for on-chain analysis - fork it and extend with features tailored to your specific use case, whether that's whale hunting, identifying early adopters, or building more sophisticated analytics.

## 🚀 Features

- **Token Analysis**: Input token contract addresses to analyze early interactions
- **Early Wallet Discovery**: Find the first 50-100 unique wallets that interacted with a token  
- **Investment Analysis**: Estimate investment amounts and identify likely buyers vs airdrop recipients
- **Multiple Output Formats**: Display results in rich tables, CSV, or JSON
- **Smart Heuristics**: Distinguish between genuine buyers and airdrop recipients
- **Rate Limiting**: Built-in API rate limiting to respect service limits

## 🛠️ Installation

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) package managergit

### Setup

1. Install dependencies:
```bash
uv sync
```

1. Set up your API key:
```bash
uv run eth-tracker setup
```

1. Edit the `.env` file with your Etherscan API key:
   - **Required**: Etherscan API key from https://etherscan.io/apis
   - **Optional**: CoinGecko and Alchemy keys for enhanced features

## 📖 Usage

### Basic Usage

Track early wallets for a token by contract address:
```bash
uv run eth-tracker track "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce"
```

Example: Track ENA (Ethena) token:
```bash
uv run eth-tracker track "0x57e114b691db790c35207b2e685d4a43181e6061"
```

### Advanced Options

```bash
# Limit to top 25 early wallets
uv run eth-tracker track "0x57e114b691db790c35207b2e685d4a43181e6061" --max-wallets 25

# Exclude likely airdrop recipients
uv run eth-tracker track "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce" --exclude-airdrops

# Export to CSV
uv run eth-tracker track "0x57e114b691db790c35207b2e685d4a43181e6061" --format csv --output ena_early_wallets.csv

# Export to JSON
uv run eth-tracker track "0xa0b86a33e6441e3c6cdeaf9bf464c44c78a1f0e9" --format json --output analysis.json
```

### Output Example

```
┏━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Rank ┃ Wallet Address ┃ Amount Received ┃ Transaction Hash ┃      Block ┃ Date             ┃ Type     ┃ Gas Cost (USD) ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│  1   │ 0x688a...a67f  │       4.50B ENA │ 0x14395562...    │ 19,371,662 │ 2024-03-05 22:29 │ 💰 Buyer │        $857.87 │
│  2   │ 0xd4b3...9bc1  │      11.34B ENA │ 0x14395562...    │ 19,371,662 │ 2024-03-05 22:29 │ 💰 Buyer │        $857.87 │
│  3   │ 0x6f0a...b161  │      15.60M ENA │ 0xd740c4dd...    │ 19,532,780 │ 2024-03-28 14:03 │ 💰 Buyer │         $22.91 │
└──────┴────────────────┴─────────────────┴──────────────────┴────────────┴──────────────────┴──────────┴────────────────┘
```

## 🔧 Configuration

Environment variables (in `.env`):

| Variable | Required | Description |
|----------|----------|-------------|
| `ETHERSCAN_API_KEY` | ✅ | Your Etherscan API key |
| `COINGECKO_API_KEY` | ❌ | CoinGecko API key (better rate limits) |
| `ALCHEMY_API_KEY` | ❌ | Alchemy API key (faster Web3 calls) |
| `MAX_EARLY_WALLETS` | ❌ | Number of early wallets to analyze (default: 50) |
| `RATE_LIMIT_DELAY` | ❌ | Delay between API calls in seconds (default: 0.2) |
| `INCLUDE_LIKELY_AIRDROPS` | ❌ | Include airdrop recipients (default: true) |

## 📊 Output Formats

### Table (default)
Rich, colorized table output in the terminal

### CSV Export
```csv
Rank,Wallet_Address,Amount_Received,Token_Symbol,Transaction_Hash,Block_Number,Date,Is_Likely_Buyer,Is_Likely_Airdrop
1,0x688a...a67f,4500000000.0,ENA,0x14395562...,19371662,2024-03-05 22:29:59,true,false
```

### JSON Export
```json
{
  "token_info": {
    "name": "Ethena",
    "symbol": "ENA", 
    "contract_address": "0x57e114b691db790c35207b2e685d4a43181e6061",
    "decimals": 18
  },
  "earliest_wallets": [
    {
      "rank": 1,
      "wallet_address": "0x688a...a67f",
      "amount_received": 4500000000.0,
      "is_likely_buyer": true
    }
  ]
}
```

## 🚧 Limitations

- **API Rate Limits**: Free tier APIs have rate limits
- **Historical Data**: Limited by what Etherscan provides
- **Heuristic Classification**: Wallet classification is based on patterns, not certainty
- **Contract Address Required**: Token name lookup requires additional APIs


## 📜 License

MIT License - feel free to use this for your own analysis and research.

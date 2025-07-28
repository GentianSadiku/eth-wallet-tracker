"""
Main CLI application for Ethereum Wallet Tracker.
"""

from .utils import (
    is_valid_ethereum_address,
    normalize_address,
    parse_etherscan_transactions,
    group_transactions_by_wallet,
    analyze_wallet_transactions,
    format_number,
    estimate_transaction_cost_usd
)
from .models import TokenInfo, TokenAnalysis, WalletAnalysis
import sys
from typing import Optional, List
from datetime import datetime
import csv
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich import print as rprint

from .config import Config
from .api_clients import EtherscanClient, Web3Client

# Logging setup
import logging
logger = logging.getLogger(__name__)


app = typer.Typer(
    name="eth-tracker",
    help="Track earliest wallet interactions with Ethereum tokens and their investment amounts."
)

console = Console()


def load_config() -> Config:
    """Load application configuration."""
    try:
        return Config.from_env()
    except ValueError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        console.print(
            "\n[yellow]Please create a .env file with your API keys:[/yellow]")
        console.print("ETHERSCAN_API_KEY=your_key_here")
        console.print("COINGECKO_API_KEY=your_key_here  # Optional")
        raise typer.Exit(1)


def resolve_token_address(token_input: str, etherscan_client: EtherscanClient,
                          web3_client: Web3Client) -> Optional[TokenInfo]:
    """Resolve token name or address to TokenInfo."""

    if is_valid_ethereum_address(token_input):
        # It's already an address, get token info
        address = normalize_address(token_input)

        # Use Etherscan token info first (CoinGecko disabled)
        try:
            es_info = etherscan_client.get_token_info(address)
            if es_info and es_info.get('symbol') != 'UNKNOWN':
                return TokenInfo(
                    name=es_info.get('name', 'Unknown Token'),
                    symbol=es_info.get('symbol', 'UNKNOWN'),
                    contract_address=address,
                    decimals=es_info.get('decimals', 18)
                )
        except Exception as e:
            logger.warning(f"Etherscan token info failed for {address}: {e}")

        # Fallback to Web3 contract call if Etherscan fails or returns unknown
        return web3_client.get_token_info_from_contract(address)

    else:
        # Without CoinGecko, we cannot resolve by token name
        console.print(
            "[red]Token name lookup requires CoinGecko API which is disabled. Please provide a contract address instead.[/red]")
        return None


def analyze_token_interactions(token_info: TokenInfo, etherscan_client: EtherscanClient,
                               config: Config) -> TokenAnalysis:
    """Analyze early interactions with a token."""

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:

        # Fetch token transfers
        task1 = progress.add_task("Fetching token transfers...", total=None)
        raw_transactions = etherscan_client.get_token_transfers(
            token_info.contract_address)
        progress.update(task1, description="✓ Fetched token transfers")

        if not raw_transactions:
            return TokenAnalysis(
                token_info=token_info,
                total_transactions=0,
                unique_wallets=0,
                earliest_wallets=[],
                analysis_date=datetime.now()
            )

        # Parse transactions
        task2 = progress.add_task("Parsing transactions...", total=None)
        transactions = parse_etherscan_transactions(
            raw_transactions, token_info)
        progress.update(task2, description="✓ Parsed transactions")

        # Group by wallet
        task3 = progress.add_task("Analyzing wallets...", total=None)
        wallet_transactions = group_transactions_by_wallet(transactions)
        progress.update(task3, description="✓ Grouped by wallet")

        # Get ETH price for cost estimation via Etherscan
        task4 = progress.add_task("Getting ETH price...", total=None)
        eth_price_usd = etherscan_client.get_current_eth_price()
        progress.update(task4, description="✓ Fetched ETH price")

        # Analyze each wallet
        task5 = progress.add_task("Computing wallet analysis...", total=None)
        wallet_analyses = []

        for wallet_addr, wallet_txs in wallet_transactions.items():
            if len(wallet_analyses) >= config.max_early_wallets:
                break

            analysis = analyze_wallet_transactions(
                wallet_addr, wallet_txs, config)
            if analysis and analysis.total_received >= config.min_token_amount:

                # Estimate transaction cost in USD
                if (analysis.first_transaction.gas_used and
                    analysis.first_transaction.gas_price and
                        eth_price_usd > 0):
                    analysis.estimated_usd_value = estimate_transaction_cost_usd(
                        analysis.first_transaction.gas_used,
                        analysis.first_transaction.gas_price,
                        eth_price_usd
                    )

                wallet_analyses.append(analysis)

        # Sort by first transaction block number
        wallet_analyses.sort(key=lambda x: x.first_transaction.block_number)
        progress.update(task5, description="✓ Completed wallet analysis")

    return TokenAnalysis(
        token_info=token_info,
        total_transactions=len(transactions),
        unique_wallets=len(wallet_transactions),
        earliest_wallets=wallet_analyses[:config.max_early_wallets],
        analysis_date=datetime.now()
    )


def display_results_table(analysis: TokenAnalysis, config: Config):
    """Display results in a rich table."""

    # Token info panel
    token_panel = Panel(
        f"[bold blue]{analysis.token_info.name}[/bold blue] ([green]{analysis.token_info.symbol}[/green])\n"
        f"Contract: [yellow]{analysis.token_info.contract_address}[/yellow]\n"
        f"Decimals: {analysis.token_info.decimals}",
        title="Token Information",
        expand=False
    )
    console.print(token_panel)

    # Summary stats
    console.print(f"\n[bold]Analysis Summary:[/bold]")
    console.print(
        f"Total Transactions: [green]{analysis.total_transactions:,}[/green]")
    console.print(
        f"Unique Wallets: [green]{analysis.unique_wallets:,}[/green]")
    console.print(
        f"Showing: [green]{len(analysis.earliest_wallets)}[/green] earliest wallets")

    if not analysis.earliest_wallets:
        console.print("[yellow]No wallet interactions found.[/yellow]")
        return

    # Create table - add cost column if we have cost data
    table = Table(
        title=f"\nEarliest {analysis.token_info.symbol} Wallet Interactions")

    table.add_column("Rank", style="cyan", no_wrap=True)
    table.add_column("Wallet Address", style="magenta", no_wrap=True)
    table.add_column("Amount Received", style="green", justify="right")
    table.add_column("Transaction Hash", style="yellow", no_wrap=True)
    table.add_column("Block", style="white", justify="right")
    table.add_column("Date", style="white", no_wrap=True)
    table.add_column("Type", style="blue", no_wrap=True)

    # Add gas cost column if we have cost estimates
    has_cost_data = any(
        w.estimated_usd_value is not None for w in analysis.earliest_wallets)
    if has_cost_data:
        table.add_column("Gas Cost (USD)", style="red", justify="right")

    for i, wallet in enumerate(analysis.earliest_wallets, 1):
        # Truncate addresses for display
        wallet_short = f"{wallet.wallet_address[:6]}...{wallet.wallet_address[-4:]}"
        tx_short = f"{wallet.first_transaction.tx_hash[:10]}..."

        # Format amount
        amount_str = format_number(wallet.total_received)

        # Determine type
        wallet_type = "🎁 Airdrop" if wallet.is_likely_airdrop else "💰 Buyer" if wallet.is_likely_buyer else "❓ Unknown"

        # Format date
        date_str = wallet.first_transaction.timestamp.strftime(
            "%Y-%m-%d %H:%M")

        # Base row data
        row_data = [
            str(i),
            wallet_short,
            f"{amount_str} {analysis.token_info.symbol}",
            tx_short,
            f"{wallet.first_transaction.block_number:,}",
            date_str,
            wallet_type
        ]

        # Add cost data if available
        if has_cost_data:
            cost_str = f"${wallet.estimated_usd_value:.2f}" if wallet.estimated_usd_value else "N/A"
            row_data.append(cost_str)

        table.add_row(*row_data)

    console.print(table)


def export_to_csv(analysis: TokenAnalysis, filepath: str):
    """Export analysis results to CSV."""
    with open(filepath, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)

        # Header
        writer.writerow([
            'Rank', 'Wallet_Address', 'Amount_Received', 'Token_Symbol',
            'Transaction_Hash', 'Block_Number', 'Timestamp', 'Date',
            'Is_Likely_Buyer', 'Is_Likely_Airdrop', 'Transaction_Count',
            'Total_Sent', 'Net_Position', 'Estimated_Gas_Cost_USD'
        ])

        # Data rows
        for i, wallet in enumerate(analysis.earliest_wallets, 1):
            writer.writerow([
                i,
                wallet.wallet_address,
                float(wallet.total_received),
                analysis.token_info.symbol,
                wallet.first_transaction.tx_hash,
                wallet.first_transaction.block_number,
                wallet.first_transaction.timestamp.isoformat(),
                wallet.first_transaction.timestamp.strftime(
                    "%Y-%m-%d %H:%M:%S"),
                wallet.is_likely_buyer,
                wallet.is_likely_airdrop,
                wallet.transaction_count,
                float(wallet.total_sent),
                float(wallet.net_position),
                str(wallet.estimated_usd_value) if wallet.estimated_usd_value else None
            ])


def export_to_json(analysis: TokenAnalysis, filepath: str):
    """Export analysis results to JSON."""
    data = {
        'token_info': {
            'name': analysis.token_info.name,
            'symbol': analysis.token_info.symbol,
            'contract_address': analysis.token_info.contract_address,
            'decimals': analysis.token_info.decimals
        },
        'analysis_summary': {
            'total_transactions': analysis.total_transactions,
            'unique_wallets': analysis.unique_wallets,
            'analysis_date': analysis.analysis_date.isoformat()
        },
        'earliest_wallets': []
    }

    for i, wallet in enumerate(analysis.earliest_wallets, 1):
        wallet_data = {
            'rank': i,
            'wallet_address': wallet.wallet_address,
            'amount_received': float(wallet.total_received),
            'total_sent': float(wallet.total_sent),
            'net_position': float(wallet.net_position),
            'transaction_count': wallet.transaction_count,
            'first_transaction': {
                'hash': wallet.first_transaction.tx_hash,
                'block_number': wallet.first_transaction.block_number,
                'timestamp': wallet.first_transaction.timestamp.isoformat(),
                'from_address': wallet.first_transaction.from_address,
                'to_address': wallet.first_transaction.to_address
            },
            'is_likely_buyer': wallet.is_likely_buyer,
            'is_likely_airdrop': wallet.is_likely_airdrop,
            'estimated_gas_cost_usd': str(wallet.estimated_usd_value) if wallet.estimated_usd_value else None
        }
        data['earliest_wallets'].append(wallet_data)

    with open(filepath, 'w') as jsonfile:
        json.dump(data, jsonfile, indent=2, default=str)


@app.command()
def track(
    token: str = typer.Argument(...,
                                help="Token name (e.g., 'SHIBA') or contract address"),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="Output format: table, csv, json"),
    output_file: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file path"),
    max_wallets: int = typer.Option(
        50, "--max-wallets", "-m", help="Maximum number of early wallets to analyze"),
    include_airdrops: bool = typer.Option(
        True, "--include-airdrops/--exclude-airdrops", help="Include likely airdrop recipients")
):
    """Track earliest wallet interactions with an Ethereum token."""

    # Load configuration
    try:
        config = load_config()
        config.max_early_wallets = max_wallets
        config.output_format = output_format
        config.include_likely_airdrops = include_airdrops
    except Exception as e:
        console.print(f"[red]Failed to load configuration: {e}[/red]")
        return

    # Initialize clients
    console.print("[cyan]Initializing API clients...[/cyan]")
    etherscan_client = EtherscanClient(config)
    web3_client = Web3Client(config)  # Uses Alchemy if key provided

    # Resolve token
    console.print(f"[cyan]Resolving token: {token}[/cyan]")
    token_info = resolve_token_address(token, etherscan_client, web3_client)

    if not token_info:
        console.print(f"[red]Could not resolve token: {token}[/red]")
        console.print(
            "[yellow]Please check the token name or contract address.[/yellow]")
        raise typer.Exit(1)

    # Analyze token interactions
    console.print(
        f"[cyan]Analyzing early interactions for {token_info.name} ({token_info.symbol})...[/cyan]")
    analysis = analyze_token_interactions(
        token_info, etherscan_client, config)

    # Filter out airdrops if requested
    if not config.include_likely_airdrops:
        analysis.earliest_wallets = [
            wallet for wallet in analysis.earliest_wallets
            if not wallet.is_likely_airdrop
        ]

    # Display or export results
    if output_format == "table" or not output_file:
        display_results_table(analysis, config)

    if output_file:
        if output_format == "csv":
            export_to_csv(analysis, output_file)
            console.print(f"[green]Results exported to {output_file}[/green]")
        elif output_format == "json":
            export_to_json(analysis, output_file)
            console.print(f"[green]Results exported to {output_file}[/green]")
        else:
            console.print(
                f"[yellow]Unsupported output format: {output_format}[/yellow]")


@app.command()
def setup():
    """Setup the application by creating a .env file template."""
    env_content = """# Ethereum Wallet Tracker Configuration

# Required: Etherscan API Key (get from https://etherscan.io/apis)
ETHERSCAN_API_KEY=your_etherscan_api_key_here

# Optional: Enhanced features (not required for basic operation)
# COINGECKO_API_KEY=your_coingecko_api_key_here
# ALCHEMY_API_KEY=your_alchemy_api_key_here

# Analysis Settings
MAX_EARLY_WALLETS=50
RATE_LIMIT_DELAY=0.2
INCLUDE_LIKELY_AIRDROPS=true
MIN_TOKEN_AMOUNT=0.0

# Output Settings
OUTPUT_FORMAT=table
"""

    env_path = Path(".env")
    if env_path.exists():
        console.print("[yellow].env file already exists![/yellow]")
        if not typer.confirm("Overwrite existing .env file?"):
            return

    with open(env_path, 'w') as f:
        f.write(env_content)

    console.print(f"[green]Created .env file at {env_path.absolute()}[/green]")
    console.print(
        "\n[yellow]Please edit the .env file and add your API key:[/yellow]")
    console.print("1. Get an Etherscan API key from https://etherscan.io/apis")
    console.print(
        "2. Replace 'your_etherscan_api_key_here' with your real key")
    console.print(
        "3. Optional: Add CoinGecko/Alchemy keys for enhanced features")
    console.print("4. Run: eth-tracker track <contract_address>")


if __name__ == "__main__":
    app()

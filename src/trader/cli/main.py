"""
CLI Commands for Automated Trading System.

Provides command-line interface for system management and operations.
"""

import click
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from ..core.config import get_config
from ..core.logging_config import get_logger
from ..api.client import GrowwClient
from ..risk.manager import RiskManager
from ..risk.kill_switch import KillSwitch
from ..gtt.storage import GTTStorage
from ..data.news_fetcher import NewsFetcher

logger = get_logger(__name__)
console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """
    Automated Trading System CLI.

    Manage your trading system, check status, run backtests, and more.
    """
    pass


@cli.command()
def status():
    """Check system status and configuration."""
    console.print("\n[bold cyan]System Status[/bold cyan]\n")

    try:
        config = get_config()

        # Configuration table
        config_table = Table(title="Configuration", box=box.ROUNDED)
        config_table.add_column("Setting", style="cyan")
        config_table.add_column("Value", style="green")

        config_table.add_row("Trading Mode", "PAPER" if config.is_paper_mode() else "LIVE")
        config_table.add_row("Max Portfolio Value", f"₹{config.get('risk.max_portfolio_value'):,}")
        config_table.add_row("Max Position Size", f"₹{config.get('risk.max_position_size'):,}")
        config_table.add_row("Max Daily Loss", f"₹{config.get('risk.max_daily_loss'):,}")
        config_table.add_row("Max Open Positions", str(config.get('risk.max_open_positions')))

        console.print(config_table)

        # Hard limits table
        limits_table = Table(title="Hard Limits (Non-Overridable)", box=box.ROUNDED)
        limits_table.add_column("Limit", style="yellow")
        limits_table.add_column("Value", style="red")

        limits_table.add_row("Max Single Order", f"₹{config.hard_limits['MAX_SINGLE_ORDER_VALUE']:,}")
        limits_table.add_row("Max Daily Orders", str(config.hard_limits['MAX_DAILY_ORDERS']))
        limits_table.add_row("Max Portfolio", f"₹{config.hard_limits['MAX_PORTFOLIO_VALUE']:,}")
        limits_table.add_row("Max Daily Loss (Hard)", f"₹{config.hard_limits['MAX_DAILY_LOSS_HARD']:,}")

        console.print(limits_table)

        # Status
        if config.is_paper_mode():
            console.print("\n[bold green]✅ PAPER MODE ACTIVE - Safe for testing[/bold green]")
        else:
            console.print("\n[bold red]⚠️  LIVE MODE - Real money at risk![/bold red]")

        console.print()

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")


@cli.command()
@click.option('--format', '-f', type=click.Choice(['table', 'json']), default='table', help='Output format')
def risk_status(format):
    """Check current risk metrics."""

    async def _run():
        try:
            config = get_config()
            groww_client = GrowwClient(config=config)
            await groww_client.initialize()

            risk_manager = RiskManager(groww_client, config=config)
            status = await risk_manager.get_status()

            if format == 'json':
                import json
                console.print(json.dumps(status.model_dump(), indent=2, default=str))
            else:
                # Display as table
                table = Table(title="Risk Status", box=box.ROUNDED)
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")

                table.add_row("Daily P&L", f"₹{status.daily_pnl:.2f}")
                table.add_row("Open Positions", str(status.open_positions))
                table.add_row("Daily Order Count", str(status.daily_order_count))
                table.add_row("Consecutive Losses", str(status.consecutive_losses))

                console.print(table)

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    asyncio.run(_run())


@cli.group()
def gtt():
    """Manage GTT (Good Till Triggered) orders."""
    pass


@gtt.command('list')
@click.option('--status', '-s', help='Filter by status (ACTIVE, TRIGGERED, etc.)')
@click.option('--symbol', help='Filter by symbol')
def gtt_list(status, symbol):
    """List GTT orders."""

    async def _run():
        try:
            data_dir = Path.cwd() / "data"
            storage = GTTStorage(db_path=data_dir / "gtt_orders.db")

            if status and status.upper() == "ACTIVE":
                gtts = await storage.get_active_gtts()
            elif symbol:
                gtts = await storage.get_gtts_by_symbol(symbol)
            else:
                gtts = await storage.get_all_gtts()

            if not gtts:
                console.print("[yellow]No GTT orders found[/yellow]")
                return

            # Display as table
            table = Table(title=f"GTT Orders ({len(gtts)} total)", box=box.ROUNDED)
            table.add_column("ID", style="cyan")
            table.add_column("Symbol", style="green")
            table.add_column("Action", style="yellow")
            table.add_column("Trigger Price", style="magenta")
            table.add_column("Quantity", style="blue")
            table.add_column("Status", style="red")

            for gtt in gtts:
                table.add_row(
                    str(gtt.id),
                    gtt.symbol,
                    gtt.action,
                    f"₹{gtt.trigger_price:.2f}",
                    str(gtt.quantity),
                    gtt.status
                )

            console.print(table)
            await storage.close()

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    asyncio.run(_run())


@gtt.command('stats')
def gtt_stats():
    """Show GTT statistics."""

    async def _run():
        try:
            data_dir = Path.cwd() / "data"
            storage = GTTStorage(db_path=data_dir / "gtt_orders.db")

            stats = await storage.get_statistics()

            # Display stats
            table = Table(title="GTT Statistics", box=box.ROUNDED)
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Total GTTs", str(stats.get('total', 0)))
            table.add_row("Active", str(stats.get('active', 0)))
            table.add_row("Triggered", str(stats.get('triggered', 0)))
            table.add_row("Completed", str(stats.get('completed', 0)))
            table.add_row("Cancelled", str(stats.get('cancelled', 0)))
            table.add_row("Failed", str(stats.get('failed', 0)))
            table.add_row("Success Rate", f"{stats.get('success_rate', 0):.1f}%")

            console.print(table)
            await storage.close()

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    asyncio.run(_run())


@cli.group()
def news():
    """Fetch market news."""
    pass


@news.command('latest')
@click.option('--limit', '-l', default=10, help='Number of articles to fetch')
@click.option('--source', '-s', help='Specific news source')
def news_latest(limit, source):
    """Fetch latest market news."""
    try:
        fetcher = NewsFetcher()

        sources = [source] if source else None
        articles = fetcher.fetch_latest_news(sources=sources, limit=limit)

        if not articles:
            console.print("[yellow]No news articles found[/yellow]")
            return

        for i, article in enumerate(articles, 1):
            console.print(f"\n[bold cyan]{i}. {article.title}[/bold cyan]")
            console.print(f"   [dim]{article.source} • {article.published.strftime('%Y-%m-%d %H:%M')}[/dim]")
            console.print(f"   {article.summary[:200]}...")
            if article.symbols:
                console.print(f"   [green]Symbols: {', '.join(article.symbols)}[/green]")
            console.print(f"   [blue]{article.link}[/blue]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")


@news.command('symbol')
@click.argument('symbol')
@click.option('--limit', '-l', default=5, help='Number of articles to fetch')
def news_symbol(symbol, limit):
    """Fetch news for a specific symbol."""
    try:
        fetcher = NewsFetcher()
        articles = fetcher.fetch_news_for_symbol(symbol.upper(), limit=limit)

        if not articles:
            console.print(f"[yellow]No news found for {symbol}[/yellow]")
            return

        console.print(f"\n[bold green]News for {symbol.upper()}[/bold green]\n")

        for i, article in enumerate(articles, 1):
            console.print(f"\n[bold cyan]{i}. {article.title}[/bold cyan]")
            console.print(f"   [dim]{article.source} • {article.published.strftime('%Y-%m-%d %H:%M')}[/dim]")
            console.print(f"   {article.summary[:200]}...")
            console.print(f"   [blue]{article.link}[/blue]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")


@news.command('summary')
@click.option('--hours', '-h', default=24, help='Hours to look back')
def news_summary(hours):
    """Get news summary."""
    try:
        fetcher = NewsFetcher()
        summary = fetcher.get_news_summary(hours_back=hours)

        console.print(f"\n[bold cyan]News Summary (Last {hours} hours)[/bold cyan]\n")
        console.print(f"Total Articles: [green]{summary['total_articles']}[/green]\n")

        # By source
        console.print("[bold]Articles by Source:[/bold]")
        for source, count in summary['by_source'].items():
            console.print(f"  • {source}: {count}")

        # Top symbols
        if summary['top_symbols']:
            console.print("\n[bold]Most Mentioned Symbols:[/bold]")
            for item in summary['top_symbols'][:5]:
                console.print(f"  • {item['symbol']}: {item['mentions']} mentions")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")


@cli.group()
def kill_switch():
    """Manage kill switch."""
    pass


@kill_switch.command('activate')
@click.option('--reason', '-r', required=True, help='Reason for activation')
@click.option('--message', '-m', help='Additional message')
def kill_switch_activate(reason, message):
    """Activate the kill switch (halt all trading)."""

    async def _run():
        try:
            config = get_config()
            groww_client = GrowwClient(config=config)
            await groww_client.initialize()

            risk_manager = RiskManager(groww_client, config=config)
            ks = KillSwitch(risk_manager, config=config)

            ks.activate(reason=reason, message=message or "Manual activation via CLI")

            console.print("\n[bold red]🚨 KILL SWITCH ACTIVATED[/bold red]")
            console.print(f"Reason: {reason}")
            if message:
                console.print(f"Message: {message}")
            console.print("\n[yellow]All trading has been halted.[/yellow]")
            console.print("[yellow]Use 'trader kill-switch deactivate' to resume after cooldown.[/yellow]\n")

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    asyncio.run(_run())


@kill_switch.command('status')
def kill_switch_status():
    """Check kill switch status."""

    async def _run():
        try:
            config = get_config()
            groww_client = GrowwClient(config=config)
            await groww_client.initialize()

            risk_manager = RiskManager(groww_client, config=config)
            ks = KillSwitch(risk_manager, config=config)

            if ks.is_active():
                console.print("\n[bold red]🚨 KILL SWITCH IS ACTIVE[/bold red]")
                console.print("[yellow]Trading is currently halted.[/yellow]\n")
            else:
                console.print("\n[bold green]✅ Kill switch is inactive[/bold green]")
                console.print("[green]Trading is allowed.[/green]\n")

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    asyncio.run(_run())


if __name__ == "__main__":
    cli()

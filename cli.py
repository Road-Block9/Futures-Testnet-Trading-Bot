"""Command-line interface for Binance Futures Testnet operations."""

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from bot.client import BinanceFuturesClient, BinanceFuturesClientError
from bot.logging_config import configure_logging, safe_log_value
from bot.orders import FuturesOrderService, OrderResult, OrderServiceError
from bot.validators import OrderValidationError, validate_order_input


app = typer.Typer(
    add_completion=False,
    help="Utilities for the Binance Futures Testnet trading bot.",
)
console = Console()
logger = configure_logging()


def _yes_no(value: bool) -> str:
    """Convert a credential-presence flag to safe display text."""
    return "Yes" if value else "No"


@app.command("check-connection")
def check_connection() -> None:
    """Check public and authenticated Binance Futures Testnet access."""
    logger.info("COMMAND_START command=check-connection")
    console.print("[bold]Binance Futures Testnet connection check[/bold]")

    try:
        client = BinanceFuturesClient()
    except BinanceFuturesClientError as exc:
        logger.error(
            "CONNECTION_FAILED stage=configuration error_type=%s reason=%s",
            type(exc).__name__,
            safe_log_value(exc),
        )
        console.print(f"[red]Configuration: Failed - {escape(str(exc))}[/red]")
        console.print("[bold red]Connection check failed.[/bold red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        logger.error(
            "CONNECTION_FAILED stage=configuration error_type=%s",
            type(exc).__name__,
        )
        console.print("[red]Configuration: Failed - unexpected error.[/red]")
        console.print("[bold red]Connection check failed.[/bold red]")
        raise typer.Exit(code=1) from exc

    console.print(f"Futures Testnet base URL: [cyan]{client.base_url}[/cyan]")
    console.print(f"API key configured: {_yes_no(client.api_key_configured)}")
    console.print(f"API secret configured: {_yes_no(client.api_secret_configured)}")

    public_ok = False
    authenticated_ok = False

    try:
        public_ok = client.test_public_connection()
        console.print("Public API connection: [green]Success[/green]")
    except BinanceFuturesClientError as exc:
        logger.error(
            "CONNECTION_FAILED kind=public error_type=%s reason=%s",
            type(exc).__name__,
            safe_log_value(exc),
        )
        console.print(f"Public API connection: [red]Failed - {escape(str(exc))}[/red]")
    except Exception as exc:
        logger.error(
            "CONNECTION_FAILED kind=public error_type=%s",
            type(exc).__name__,
        )
        console.print("Public API connection: [red]Failed - unexpected error.[/red]")

    try:
        authenticated_ok = client.test_authenticated_connection()
        console.print("Authenticated API connection: [green]Success[/green]")
    except BinanceFuturesClientError as exc:
        logger.error(
            "CONNECTION_FAILED kind=authenticated error_type=%s reason=%s",
            type(exc).__name__,
            safe_log_value(exc),
        )
        console.print(
            f"Authenticated API connection: [red]Failed - {escape(str(exc))}[/red]"
        )
    except Exception as exc:
        logger.error(
            "CONNECTION_FAILED kind=authenticated error_type=%s",
            type(exc).__name__,
        )
        console.print(
            "Authenticated API connection: [red]Failed - unexpected error.[/red]"
        )

    if public_ok and authenticated_ok:
        logger.info("COMMAND_SUCCESS command=check-connection")
        console.print("[bold green]Connection check succeeded.[/bold green]")
        return

    logger.error("COMMAND_FAILED command=check-connection")
    console.print("[bold red]Connection check failed.[/bold red]")
    raise typer.Exit(code=1)


@app.command("place-order")
def place_order(
    symbol: str = typer.Option(..., "--symbol", help="Uppercase Futures symbol."),
    side: str = typer.Option(..., "--side", help="BUY or SELL."),
    order_type: str = typer.Option(
        ..., "--order-type", help="MARKET or LIMIT."
    ),
    quantity: str = typer.Option(
        ..., "--quantity", help="Positive decimal quantity."
    ),
    price: str | None = typer.Option(
        None, "--price", help="Positive decimal price; required only for LIMIT."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Submit without the confirmation prompt."
    ),
) -> None:
    """Validate and submit a MARKET or LIMIT Futures Testnet order."""
    logger.info("COMMAND_START command=place-order")
    try:
        validated = validate_order_input(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )
    except OrderValidationError as exc:
        logger.warning(
            "ORDER_FAILED stage=cli_validation error_type=%s reason=%s",
            type(exc).__name__,
            safe_log_value(exc),
        )
        console.print(f"[bold red]Invalid order: {escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from exc

    console.print(
        "[bold yellow]TESTNET ONLY — this order must never use real funds.[/bold yellow]"
    )
    summary = Table(title="Order request summary", show_header=False)
    summary.add_column("Field", style="bold")
    summary.add_column("Value")
    summary.add_row("Environment", "Binance Futures Testnet")
    summary.add_row("Symbol", validated.symbol)
    summary.add_row("Side", validated.side)
    summary.add_row("Order type", validated.order_type)
    summary.add_row("Quantity", format(validated.quantity, "f"))
    if validated.price is not None:
        summary.add_row("Price", format(validated.price, "f"))
    console.print(summary)

    if not yes and not typer.confirm("Submit this TESTNET order?", default=False):
        logger.warning(
            "ORDER_CANCELLED symbol=%s type=%s",
            safe_log_value(validated.symbol),
            safe_log_value(validated.order_type),
        )
        console.print("[yellow]Order submission cancelled.[/yellow]")
        raise typer.Exit(code=1)

    try:
        client = BinanceFuturesClient()
        service = FuturesOrderService(client)
        result = service.place_order(
            symbol=validated.symbol,
            side=validated.side,
            order_type=validated.order_type,
            quantity=validated.quantity,
            price=validated.price,
        )
    except (OrderValidationError, BinanceFuturesClientError, OrderServiceError) as exc:
        logger.error(
            "ORDER_FAILED stage=cli_submission error_type=%s reason=%s",
            type(exc).__name__,
            safe_log_value(exc),
        )
        console.print(f"[bold red]Order failed: {escape(str(exc))}[/bold red]")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        logger.error(
            "ORDER_FAILED stage=cli_submission error_type=%s",
            type(exc).__name__,
        )
        console.print("[bold red]Order failed due to an unexpected error.[/bold red]")
        raise typer.Exit(code=1) from exc

    _print_order_result(result)
    logger.info(
        "COMMAND_SUCCESS command=place-order orderId=%s type=%s",
        safe_log_value(result.order_id),
        safe_log_value(result.order_type),
    )
    console.print(
        "[bold green]Futures Testnet order submitted successfully.[/bold green]"
    )


def _print_order_result(result: OrderResult) -> None:
    """Print order response fields safely, including zero and missing values."""
    response = Table(title="Order response", show_header=False)
    response.add_column("Field", style="bold")
    response.add_column("Value")
    response.add_row("orderId", _display_value(result.order_id))
    response.add_row("symbol", _display_value(result.symbol))
    response.add_row("side", _display_value(result.side))
    response.add_row("type", _display_value(result.order_type))
    response.add_row("status", _display_value(result.status))
    response.add_row("original quantity", _display_value(result.original_quantity))
    response.add_row("executedQty", _display_value(result.executed_quantity))
    response.add_row("price", _display_value(result.price))
    response.add_row("avgPrice", _display_value(result.average_price))
    console.print(response)


def _display_value(value: str) -> str:
    """Display empty response values without hiding valid numeric zeroes."""
    return value if value not in {"", None} else "N/A"


if __name__ == "__main__":
    app()

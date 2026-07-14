# Futures Testnet Trading Bot

## Overview

This is a Python 3 application with a Typer CLI and Streamlit dashboard for placing validated MARKET and LIMIT orders on the Binance USDT-M Futures Testnet. It is configured only for the Testnet and never uses real funds.

## Features

- public and authenticated Binance Futures Testnet connection checks
- MARKET and LIMIT orders with BUY and SELL support
- Decimal-based input validation
- live symbol-filter validation for quantity, price, precision, and minimum notional where calculable
- confirmation before submission, with an optional automation flag
- professional request summaries and response tables
- layered client, order-service, validation, logging, and CLI modules
- append-only, sanitised file logging for requests, responses, successes, and failures
- clear exceptions and non-zero CLI exit codes on failure
- a dark Streamlit dashboard with account summaries and read-only order data
- optional password protection for deployed dashboard access
- secure Streamlit Community Cloud secrets support

## Project Structure

```text
trading_bot/
|-- bot/
|   |-- __init__.py
|   |-- client.py
|   |-- dashboard.py
|   |-- orders.py
|   |-- validators.py
|   `-- logging_config.py
|-- logs/
|   |-- .gitkeep
|   `-- trading_bot.log
|-- cli.py
|-- app.py
|-- .streamlit/
|   |-- config.toml
|   `-- secrets.toml.example
|-- .env.example
|-- .gitignore
|-- requirements.txt
`-- README.md
```

## Prerequisites

- Python 3
- an internet connection
- a Binance Futures Testnet account
- API credentials generated only for Binance Futures Testnet

Do not use Binance production credentials, production endpoints, or real funds.

## Setup

Run all commands from the `trading_bot` project root.

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

Add only your Futures Testnet credentials to `.env`. Keep the required base URL unchanged:

```env
BINANCE_API_KEY=<your-testnet-api-key>
BINANCE_API_SECRET=<your-testnet-api-secret>
BINANCE_BASE_URL=https://testnet.binancefuture.com
```

The application rejects any other base URL. Never commit or share `.env`.

## CLI Commands

Show all commands:

```powershell
python cli.py --help
```

Check public and authenticated connectivity without placing an order:

```powershell
python cli.py check-connection
```

Launch the Streamlit trading dashboard:

```powershell
python -m streamlit run app.py
```

The dashboard uses the same Futures Testnet client, validation, order service,
safe exceptions, and append-only logging as the CLI. It requires an explicit
confirmation and a successful connection check before enabling order submission.

## Streamlit Community Cloud Deployment

The project is deployment-ready, but deployment is intentionally manual.

1. Push the project to a private or appropriately secured GitHub repository. Never
   add `.env` or `.streamlit/secrets.toml` to Git.
2. In Streamlit Community Cloud, create an app from the repository and select
   `app.py` as the entry point.
3. Open the app's **Settings > Secrets** section.
4. Copy the structure from `.streamlit/secrets.toml.example` and replace the
   placeholders with Binance **Futures Testnet** credentials:

```toml
BINANCE_API_KEY = "your-testnet-api-key"
BINANCE_API_SECRET = "your-testnet-api-secret"
BINANCE_BASE_URL = "https://testnet.binancefuture.com"
APP_PASSWORD = "choose-a-strong-dashboard-password"
```

`APP_PASSWORD` is optional. When configured, the dashboard requires a session-based
login before any trading or authenticated account controls are available. Use a
unique strong password and do not reuse a Binance credential.

On Streamlit, credential values are read from `st.secrets`. Locally, the same client
falls back to environment variables loaded from `.env`. The application never
prints or intentionally logs credential values.

If credentials are missing, the dashboard still loads and shows setup instructions,
but trading and authenticated account controls remain disabled. No `packages.txt`
is required because the project has no operating-system package dependency.

Place a MARKET BUY order:

```powershell
python cli.py place-order --symbol BTCUSDT --side BUY --order-type MARKET --quantity 0.002
```

Place a LIMIT SELL order:

```powershell
python cli.py place-order --symbol BTCUSDT --side SELL --order-type LIMIT --quantity 0.002 --price 130000
```

### Order Options

| Option | Meaning |
|---|---|
| `--symbol` | Required uppercase Futures symbol, such as `BTCUSDT`. |
| `--side` | Required order side: `BUY` or `SELL`. |
| `--order-type` | Required order type: `MARKET` or `LIMIT`. |
| `--quantity` | Required positive decimal quantity. |
| `--price` | Required for LIMIT orders and rejected for MARKET orders. |
| `--yes` | Skips the interactive confirmation prompt. |

Before submission, the CLI shows a Testnet warning and order request summary, then asks:

```text
Submit this TESTNET order? [y/N]
```

The default is No. Review the summary before entering `y`. Use `--yes` only for controlled Testnet automation:

```powershell
python cli.py place-order --symbol BTCUSDT --side BUY --order-type MARKET --quantity 0.002 --yes
```

## Validation and Order Behavior

Local validation rejects unsupported symbols, sides, order types, non-positive values, missing LIMIT prices, and MARKET prices. The application then fetches current Futures Testnet exchange information and validates symbol status, quantity range and step size, price range and tick size, and minimum notional for LIMIT orders where it can be calculated.

MARKET orders request a `RESULT` response so Binance can return the final fill details. LIMIT orders use `timeInForce=GTC`; an accepted LIMIT order may remain in `NEW` status with `executedQty=0` until its price is reached. That is a successful placement.

## Response Output

The response table includes:

- `orderId`
- symbol, side, and type
- status
- original quantity
- `executedQty`
- price
- `avgPrice`

Missing or empty fields display as `N/A` instead of crashing. Depending on the Binance API response and order state, `avgPrice` may be empty or unavailable.

## Reusable Python API

The CLI remains available, while these helpers are also used by the Streamlit
dashboard and can be called by other Python code without invoking Typer:

- `bot.client.create_binance_client()` creates the locked Futures Testnet client.
- `bot.client.check_binance_connection()` returns a structured
  `ConnectionCheckResult`.
- `bot.validators.validate_symbol()` performs local symbol-format validation.
- `bot.client.validate_futures_symbol()` validates a symbol against current Futures
  Testnet exchange information and returns its metadata.
- `bot.orders.place_futures_order()` validates and places a MARKET or LIMIT order,
  returning an `OrderResult` object.

These helpers use the same validation, safe exceptions, and file logging as the CLI.
The dashboard requires explicit user confirmation before calling the
order-placement helper.

## Error Handling

The CLI reports missing credentials, invalid credentials or permissions, unsupported symbols, filter and precision failures, insufficient Testnet balance, API rejection, network or timeout failures, and unexpected responses. Expected failures do not show stack traces, and commands return a non-zero exit status.

## File Logging

Logs are written in UTF-8 append mode to:

```text
logs/trading_bot.log
```

Entries include timestamps, levels, logger names, connection outcomes, sanitised order requests, allow-listed response fields, and `ORDER_SUCCESS` or `ORDER_FAILED` markers. Append mode preserves prior order evidence.

On Streamlit Community Cloud the filesystem is ephemeral, so log entries may not
survive an app restart. If the host filesystem is unavailable, the application
falls back safely instead of failing at startup.

The log intentionally excludes API secrets, full API keys, signatures, sensitive headers, raw environment variables, and unfiltered API responses. Runtime `.log` files are ignored by Git and must not be added to commits.

Local verification may include entries such as:

```text
ORDER_SUCCESS type=MARKET ... status=FILLED ...
ORDER_SUCCESS type=LIMIT ...
```

## Security Practices

- use Futures Testnet credentials only
- keep the exact base URL `https://testnet.binancefuture.com`
- keep `.env` local and ignored by Git
- keep `.streamlit/secrets.toml` local and ignored by Git
- configure deployed credentials only through Streamlit Community Cloud Secrets
- use the optional `APP_PASSWORD` to restrict deployed dashboard access
- never print or log secrets, full keys, signatures, or sensitive headers
- review order summaries before confirmation
- review logs before including them in a submission

## Assumptions

- commands are run from the `trading_bot` project root
- Python and the dependencies in `requirements.txt` are available in the active environment
- the Testnet account has sufficient test funds and appropriate API permissions
- Binance symbol filters and API availability can change, so current values are fetched at runtime
- minimum notional for a MARKET order is ultimately enforced by Binance because no fixed execution price exists before submission

## Troubleshooting

- **Missing credentials:** Ensure both credential fields are set in `.env` using Futures Testnet values.
- **Invalid credentials:** Confirm the credentials belong to Futures Testnet and have suitable permissions.
- **Network failure:** Check connectivity, firewall, proxy, DNS, and Testnet availability.
- **Quantity precision:** Use a quantity within the current range and exactly aligned to its step size.
- **Price precision:** Use a LIMIT price within the current range and exactly aligned to its tick size.
- **Minimum notional:** Increase quantity or select a valid LIMIT price so quantity times price meets the current minimum.
- **Insufficient margin:** Add test funds to the Futures Testnet account; never use real funds.

> **Warning:** This project is for Binance USDT-M Futures Testnet only. It never uses real funds.

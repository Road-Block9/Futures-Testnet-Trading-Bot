# Binance Futures Testnet Trading Bot

## Overview

This is a Python 3 command-line application for placing validated MARKET and LIMIT orders on the Binance USDT-M Futures Testnet. It is configured only for the Testnet and never uses real funds.

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

## Project Structure

```text
trading_bot/
|-- bot/
|   |-- __init__.py
|   |-- client.py
|   |-- orders.py
|   |-- validators.py
|   `-- logging_config.py
|-- logs/
|   |-- .gitkeep
|   `-- trading_bot.log
|-- cli.py
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

## Error Handling

The CLI reports missing credentials, invalid credentials or permissions, unsupported symbols, filter and precision failures, insufficient Testnet balance, API rejection, network or timeout failures, and unexpected responses. Expected failures do not show stack traces, and commands return a non-zero exit status.

## File Logging

Logs are written in UTF-8 append mode to:

```text
logs/trading_bot.log
```

Entries include timestamps, levels, logger names, connection outcomes, sanitised order requests, allow-listed response fields, and `ORDER_SUCCESS` or `ORDER_FAILED` markers. Append mode preserves prior order evidence.

The log intentionally excludes API secrets, full API keys, signatures, sensitive headers, raw environment variables, and unfiltered API responses. Review the file before submission. The Git ignore rules allow `logs/trading_bot.log` to be included deliberately while ignoring unrelated log files.

The assignment evidence should include at least:

```text
ORDER_SUCCESS type=MARKET ... status=FILLED ...
ORDER_SUCCESS type=LIMIT ...
```

## Security Practices

- use Futures Testnet credentials only
- keep the exact base URL `https://testnet.binancefuture.com`
- keep `.env` local and ignored by Git
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

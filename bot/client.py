"""Configuration and connectivity checks for Binance Futures Testnet."""

from __future__ import annotations

import os
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from dotenv import load_dotenv

from bot.logging_config import safe_log_value
from bot.validators import validate_symbol


EXPECTED_TESTNET_URL = "https://testnet.binancefuture.com"
_Result = TypeVar("_Result")
logger = logging.getLogger("trading_bot.client")


class BinanceFuturesClientError(Exception):
    """Base exception for safe client errors shown by the CLI."""


class BinanceConfigurationError(BinanceFuturesClientError):
    """Raised when the Futures Testnet configuration is invalid."""


class MissingCredentialsError(BinanceConfigurationError):
    """Raised when an authenticated check lacks API credentials."""


class BinanceAuthenticationError(BinanceFuturesClientError):
    """Raised when Binance rejects the configured API credentials."""


class BinanceServiceError(BinanceFuturesClientError):
    """Raised when Binance returns an API error unrelated to credentials."""


class BinanceNetworkError(BinanceFuturesClientError):
    """Raised when Binance cannot be reached over the network."""


class BinanceUnexpectedError(BinanceFuturesClientError):
    """Raised when an unexpected client failure occurs."""


class BinanceSymbolNotFoundError(BinanceServiceError):
    """Raised when Futures exchange information lacks a requested symbol."""


@dataclass(frozen=True)
class ConnectionStatus:
    """Result of one connection check without exposing implementation details."""

    ok: bool
    error_message: str | None = None
    error_type: str | None = None
    unexpected: bool = False


@dataclass(frozen=True)
class ConnectionCheckResult:
    """Structured result from public and authenticated connection checks."""

    base_url: str
    api_key_configured: bool
    api_secret_configured: bool
    public: ConnectionStatus
    authenticated: ConnectionStatus

    @property
    def success(self) -> bool:
        """Return whether both connection checks succeeded."""
        return self.public.ok and self.authenticated.ok


class BinanceFuturesClient:
    """Small synchronous wrapper for safe USDT-M Futures Testnet checks."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Load configuration and prepare a non-pinging testnet client."""
        env_path = Path(__file__).resolve().parents[1] / ".env"
        load_dotenv(dotenv_path=env_path, override=False)

        self._api_key = (
            api_key if api_key is not None else os.getenv("BINANCE_API_KEY", "")
        ).strip()
        self._api_secret = (
            api_secret
            if api_secret is not None
            else os.getenv("BINANCE_API_SECRET", "")
        ).strip()
        configured_base_url = (
            base_url
            if base_url is not None
            else os.getenv("BINANCE_BASE_URL", EXPECTED_TESTNET_URL)
        )
        self._base_url = configured_base_url.strip().rstrip("/")

        self._validate_base_url()
        self._client = self._create_client()

    @property
    def base_url(self) -> str:
        """Return the non-sensitive configured Futures Testnet base URL."""
        return self._base_url

    @property
    def api_key_configured(self) -> bool:
        """Report whether an API key is present without exposing its value."""
        return bool(self._api_key)

    @property
    def api_secret_configured(self) -> bool:
        """Report whether an API secret is present without exposing its value."""
        return bool(self._api_secret)

    def test_public_connection(self) -> bool:
        """Call the harmless USDT-M Futures ping endpoint."""
        logger.info("CONNECTION_CHECK kind=public base_url=%s", self._base_url)
        self._call(
            self._client.futures_ping,
            authenticated=False,
            operation_name="futures_ping",
        )
        logger.info("CONNECTION_SUCCESS kind=public")
        return True

    def test_authenticated_connection(self) -> bool:
        """Call a read-only signed Futures account endpoint."""
        self._validate_credentials()
        logger.info(
            "CONNECTION_CHECK kind=authenticated api_key_configured=%s "
            "api_secret_configured=%s",
            self.api_key_configured,
            self.api_secret_configured,
        )
        self._call(
            self._client.futures_account,
            authenticated=True,
            operation_name="futures_account",
        )
        logger.info("CONNECTION_SUCCESS kind=authenticated")
        return True

    def get_futures_exchange_info(self) -> dict[str, Any]:
        """Return public USDT-M Futures Testnet exchange information."""
        response = self._call(
            self._client.futures_exchange_info,
            authenticated=False,
            operation_name="futures_exchange_info",
        )
        if not isinstance(response, dict):
            raise BinanceServiceError(
                "Binance returned unexpected Futures exchange information."
            )
        symbols = response.get("symbols")
        symbol_count = len(symbols) if isinstance(symbols, list) else 0
        logger.debug("API_RESPONSE operation=futures_exchange_info symbols=%s", symbol_count)
        return response

    def get_futures_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Return exchange information for one exact Futures symbol."""
        exchange_info = self.get_futures_exchange_info()
        symbols = exchange_info.get("symbols", [])
        if isinstance(symbols, list):
            for item in symbols:
                if isinstance(item, dict) and item.get("symbol") == symbol:
                    logger.debug(
                        "SYMBOL_INFO_FOUND symbol=%s",
                        safe_log_value(symbol),
                    )
                    return item
        logger.warning("SYMBOL_NOT_FOUND symbol=%s", safe_log_value(symbol))
        raise BinanceSymbolNotFoundError(
            f"Symbol {symbol} was not found on Binance Futures Testnet."
        )

    def get_futures_mark_price(self, symbol: str) -> str:
        """Return the current public Futures Testnet mark price for a symbol."""
        response = self._call(
            lambda: self._client.futures_mark_price(symbol=symbol),
            authenticated=False,
            operation_name="futures_mark_price",
        )
        if not isinstance(response, dict) or response.get("markPrice") in {None, ""}:
            raise BinanceServiceError(
                "Binance returned an unexpected Futures mark-price response."
            )
        logger.debug("MARK_PRICE_FOUND symbol=%s", safe_log_value(symbol))
        return str(response["markPrice"])

    def get_futures_account_snapshot(self) -> dict[str, Any]:
        """Return a read-only authenticated Futures Testnet account snapshot."""
        self._validate_credentials()
        response = self._call(
            self._client.futures_account,
            authenticated=True,
            operation_name="futures_account",
        )
        if not isinstance(response, dict):
            raise BinanceServiceError(
                "Binance returned an unexpected Futures account response."
            )
        return response

    def get_futures_open_orders(
        self, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Return current open orders, optionally limited to one symbol."""
        self._validate_credentials()
        validated_symbol = validate_symbol(symbol) if symbol is not None else None
        response = self._call(
            (
                lambda: self._client.futures_get_open_orders(symbol=validated_symbol)
                if validated_symbol is not None
                else self._client.futures_get_open_orders()
            ),
            authenticated=True,
            operation_name="futures_get_open_orders",
        )
        if not isinstance(response, list):
            raise BinanceServiceError(
                "Binance returned an unexpected open-orders response."
            )
        return [item for item in response if isinstance(item, dict)]

    def get_futures_recent_orders(
        self, symbol: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent orders for one Futures Testnet symbol."""
        self._validate_credentials()
        response = self._call(
            lambda: self._client.futures_get_all_orders(symbol=symbol, limit=limit),
            authenticated=True,
            operation_name="futures_get_all_orders",
        )
        if not isinstance(response, list):
            raise BinanceServiceError(
                "Binance returned an unexpected recent-orders response."
            )
        return [item for item in response if isinstance(item, dict)]

    def place_futures_order(self, **params: str) -> dict[str, Any]:
        """Submit a validated Futures order using python-binance."""
        self._validate_credentials()
        logger.info(
            "API_REQUEST operation=futures_create_order symbol=%s type=%s",
            safe_log_value(params.get("symbol", "")),
            safe_log_value(params.get("type", "")),
        )
        response = self._call(
            lambda: self._client.futures_create_order(**params),
            authenticated=True,
            operation_name="futures_create_order",
        )
        if not isinstance(response, dict):
            raise BinanceServiceError("Binance returned an unexpected order response.")
        return response

    def _validate_base_url(self) -> None:
        if self._base_url != EXPECTED_TESTNET_URL:
            logger.error("CONFIGURATION_FAILED reason=invalid_testnet_base_url")
            raise BinanceConfigurationError(
                "BINANCE_BASE_URL must be the Binance Futures Testnet URL: "
                f"{EXPECTED_TESTNET_URL}"
            )

    def _validate_credentials(self) -> None:
        missing = []
        if not self._api_key:
            missing.append("BINANCE_API_KEY")
        if not self._api_secret:
            missing.append("BINANCE_API_SECRET")
        if missing:
            logger.error(
                "AUTHENTICATION_FAILED reason=missing_credentials "
                "api_key_configured=%s api_secret_configured=%s",
                self.api_key_configured,
                self.api_secret_configured,
            )
            raise MissingCredentialsError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )

    def _create_client(self) -> Client:
        try:
            client = Client(
                api_key=self._api_key or None,
                api_secret=self._api_secret or None,
                testnet=True,
                ping=False,
                requests_params={"timeout": 10},
            )
            # python-binance builds USDT-M Futures URLs from this testnet base.
            client.FUTURES_TESTNET_URL = f"{self._base_url}/fapi"
            logger.debug("CLIENT_INITIALIZED environment=testnet base_url=%s", self._base_url)
            return client
        except Exception as exc:
            logger.error(
                "CLIENT_INITIALIZATION_FAILED error_type=%s",
                type(exc).__name__,
            )
            raise BinanceUnexpectedError(
                "Unable to initialize the Binance Futures Testnet client."
            ) from exc

    def _call(
        self,
        operation: Callable[[], _Result],
        *,
        authenticated: bool,
        operation_name: str,
    ) -> _Result:
        try:
            return operation()
        except BinanceAPIException as exc:
            code = getattr(exc, "code", None)
            status_code = getattr(exc, "status_code", None)
            logger.error(
                "API_ERROR operation=%s authenticated=%s code=%s status_code=%s",
                safe_log_value(operation_name),
                authenticated,
                code,
                status_code,
            )
            if authenticated and (
                code in {-1022, -2014, -2015} or status_code in {401, 403}
            ):
                raise BinanceAuthenticationError(
                    "Binance rejected the testnet API credentials or permissions."
                ) from exc

            safe_messages = {
                -1013: "The order failed a Binance symbol filter.",
                -1102: "A required order parameter is missing or invalid.",
                -1111: "The quantity or price has too much precision.",
                -2010: "Binance rejected the order request.",
                -2019: "The Futures Testnet account has insufficient margin balance.",
                -4004: "The order quantity is below the allowed minimum.",
                -4164: "The order does not meet the minimum notional value.",
            }
            if code in safe_messages:
                raise BinanceServiceError(safe_messages[code]) from exc

            code_text = f" (code {code})" if code is not None else ""
            raise BinanceServiceError(
                f"Binance Futures Testnet returned an API error{code_text}."
            ) from exc
        except (requests.exceptions.RequestException, BinanceRequestException) as exc:
            logger.error(
                "NETWORK_ERROR operation=%s error_type=%s",
                safe_log_value(operation_name),
                type(exc).__name__,
            )
            raise BinanceNetworkError(
                "Could not reach Binance Futures Testnet; check the network and retry."
            ) from exc
        except Exception as exc:
            logger.error(
                "UNEXPECTED_API_ERROR operation=%s error_type=%s",
                safe_log_value(operation_name),
                type(exc).__name__,
            )
            raise BinanceUnexpectedError(
                "An unexpected error occurred during the Binance Futures request."
            ) from exc


def create_binance_client(
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    base_url: str | None = None,
) -> BinanceFuturesClient:
    """Create a Testnet client using explicit values or local environment config."""
    return BinanceFuturesClient(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
    )


def check_binance_connection(
    client: BinanceFuturesClient | None = None,
) -> ConnectionCheckResult:
    """Run public and authenticated checks and return structured status data."""
    active_client = client or create_binance_client()
    return ConnectionCheckResult(
        base_url=active_client.base_url,
        api_key_configured=active_client.api_key_configured,
        api_secret_configured=active_client.api_secret_configured,
        public=_connection_status(
            active_client.test_public_connection,
            "Public connection check failed due to an unexpected error.",
        ),
        authenticated=_connection_status(
            active_client.test_authenticated_connection,
            "Authenticated connection check failed due to an unexpected error.",
        ),
    )


def validate_futures_symbol(
    symbol: str,
    client: BinanceFuturesClient | None = None,
) -> dict[str, Any]:
    """Validate local symbol syntax and return its Testnet exchange metadata."""
    validated_symbol = validate_symbol(symbol)
    active_client = client or create_binance_client()
    return active_client.get_futures_symbol_info(validated_symbol)


def get_futures_market_price(
    symbol: str,
    client: BinanceFuturesClient | None = None,
) -> str:
    """Validate a symbol and return its current public Testnet mark price."""
    validated_symbol = validate_symbol(symbol)
    active_client = client or create_binance_client()
    return active_client.get_futures_mark_price(validated_symbol)


def _connection_status(
    check: Callable[[], bool], unexpected_message: str
) -> ConnectionStatus:
    try:
        return ConnectionStatus(ok=check())
    except BinanceFuturesClientError as exc:
        return ConnectionStatus(
            ok=False,
            error_message=str(exc),
            error_type=type(exc).__name__,
        )
    except Exception as exc:
        return ConnectionStatus(
            ok=False,
            error_message=unexpected_message,
            error_type=type(exc).__name__,
            unexpected=True,
        )

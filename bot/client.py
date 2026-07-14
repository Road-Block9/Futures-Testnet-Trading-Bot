"""Configuration and connectivity checks for Binance Futures Testnet."""

from __future__ import annotations

import os
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from dotenv import load_dotenv

from bot.logging_config import safe_log_value


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


class BinanceFuturesClient:
    """Small synchronous wrapper for safe USDT-M Futures Testnet checks."""

    def __init__(self) -> None:
        """Load configuration and prepare a non-pinging testnet client."""
        env_path = Path(__file__).resolve().parents[1] / ".env"
        load_dotenv(dotenv_path=env_path, override=False)

        self._api_key = os.getenv("BINANCE_API_KEY", "").strip()
        self._api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
        self._base_url = os.getenv(
            "BINANCE_BASE_URL", EXPECTED_TESTNET_URL
        ).strip().rstrip("/")

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

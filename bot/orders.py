"""Validated MARKET and LIMIT order service for Futures Testnet."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from bot.client import (
    BinanceFuturesClient,
    BinanceFuturesClientError,
    BinanceSymbolNotFoundError,
)
from bot.logging_config import safe_log_value
from bot.validators import (
    OrderValidationError,
    ValidatedOrderInput,
    format_decimal,
    validate_exchange_rules,
    validate_order_input,
)


logger = logging.getLogger("trading_bot.orders")


class OrderServiceError(Exception):
    """Raised when Binance returns an unusable order response."""


@dataclass(frozen=True)
class OrderResult:
    """Stable subset of fields returned after an accepted order request."""

    order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    original_quantity: str
    executed_quantity: str
    price: str
    average_price: str


class FuturesOrderService:
    """Validate and submit MARKET or LIMIT orders through the client layer."""

    def __init__(self, client: BinanceFuturesClient) -> None:
        self._client = client

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str | Decimal,
        price: str | Decimal | None = None,
    ) -> OrderResult:
        """Validate, build, and submit one Futures Testnet order."""
        try:
            order = validate_order_input(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
            )
            symbol_info = self._client.get_futures_symbol_info(order.symbol)
            validate_exchange_rules(order, symbol_info)
            payload = self._build_payload(order)
            self._log_order_request(payload)
            response = self._client.place_futures_order(**payload)
            result = self._build_result(response, order)
            self._log_order_success(result)
            return result
        except OrderValidationError as exc:
            logger.warning(
                "ORDER_FAILED stage=validation error_type=%s reason=%s",
                type(exc).__name__,
                safe_log_value(exc),
            )
            raise
        except BinanceSymbolNotFoundError as exc:
            logger.warning(
                "ORDER_FAILED stage=symbol_validation error_type=%s reason=%s",
                type(exc).__name__,
                safe_log_value(exc),
            )
            raise
        except BinanceFuturesClientError as exc:
            logger.error(
                "ORDER_FAILED stage=api error_type=%s reason=%s",
                type(exc).__name__,
                safe_log_value(exc),
            )
            raise
        except OrderServiceError as exc:
            logger.warning(
                "ORDER_FAILED stage=response error_type=%s reason=%s",
                type(exc).__name__,
                safe_log_value(exc),
            )
            raise
        except Exception as exc:
            logger.error(
                "ORDER_FAILED stage=unexpected error_type=%s",
                type(exc).__name__,
            )
            raise

    def _log_order_request(self, payload: Mapping[str, str]) -> None:
        details = [
            "ORDER_REQUEST",
            "environment=Binance_Futures_Testnet",
            f"base_url={safe_log_value(self._client.base_url)}",
            f"symbol={safe_log_value(payload.get('symbol', ''))}",
            f"side={safe_log_value(payload.get('side', ''))}",
            f"type={safe_log_value(payload.get('type', ''))}",
            f"quantity={safe_log_value(payload.get('quantity', ''))}",
        ]
        if payload.get("type") == "LIMIT":
            details.extend(
                [
                    f"price={safe_log_value(payload.get('price', ''))}",
                    f"timeInForce={safe_log_value(payload.get('timeInForce', ''))}",
                ]
            )
        logger.info(" ".join(details))

    @staticmethod
    def _log_order_success(result: OrderResult) -> None:
        logger.info(
            "ORDER_SUCCESS type=%s orderId=%s symbol=%s side=%s status=%s "
            "origQty=%s executedQty=%s price=%s avgPrice=%s",
            safe_log_value(result.order_type),
            safe_log_value(result.order_id),
            safe_log_value(result.symbol),
            safe_log_value(result.side),
            safe_log_value(result.status),
            safe_log_value(result.original_quantity),
            safe_log_value(result.executed_quantity),
            safe_log_value(result.price),
            safe_log_value(result.average_price),
        )

    @staticmethod
    def _build_payload(order: ValidatedOrderInput) -> dict[str, str]:
        payload = {
            "symbol": order.symbol,
            "side": order.side,
            "type": order.order_type,
            "quantity": format_decimal(order.quantity),
        }
        if order.order_type == "MARKET":
            payload["newOrderRespType"] = "RESULT"
        elif order.order_type == "LIMIT" and order.price is not None:
            payload.update(
                price=format_decimal(order.price),
                timeInForce="GTC",
            )
        return payload

    @staticmethod
    def _build_result(
        response: Mapping[str, Any], order: ValidatedOrderInput
    ) -> OrderResult:
        if not isinstance(response, Mapping):
            raise OrderServiceError("Binance returned an unexpected order response.")

        requested_price = format_decimal(order.price) if order.price is not None else "0"
        result = OrderResult(
            order_id=_safe_text(response.get("orderId")),
            symbol=_safe_text(response.get("symbol"), order.symbol),
            side=_safe_text(response.get("side"), order.side),
            order_type=_safe_text(response.get("type"), order.order_type),
            status=_safe_text(response.get("status")),
            original_quantity=_safe_text(
                response.get("origQty"), format_decimal(order.quantity)
            ),
            executed_quantity=_safe_text(response.get("executedQty"), "0"),
            price=_safe_text(response.get("price"), requested_price),
            average_price=_safe_text(response.get("avgPrice")),
        )
        missing_fields = [
            name
            for name, value in {
                "orderId": result.order_id,
                "symbol": result.symbol,
                "type": result.order_type,
                "status": result.status,
            }.items()
            if value == ""
        ]
        if missing_fields:
            logger.warning(
                "ORDER_RESPONSE_UNUSUAL type=%s missing_fields=%s",
                safe_log_value(result.order_type or order.order_type),
                safe_log_value(",".join(missing_fields)),
            )
        return result


def _safe_text(value: Any, fallback: str = "") -> str:
    """Convert optional response fields without treating numeric zero as absent."""
    if value is None or value == "":
        return fallback
    return str(value)

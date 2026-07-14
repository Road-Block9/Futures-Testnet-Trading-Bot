"""Decimal-based local and Binance Futures order validation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


SUPPORTED_SIDES = {"BUY", "SELL"}
SUPPORTED_ORDER_TYPES = {"MARKET", "LIMIT"}


class OrderValidationError(ValueError):
    """Base exception for invalid order input or exchange filters."""


class InvalidSymbolError(OrderValidationError):
    """Raised when a symbol is empty, malformed, or unsupported."""


class InvalidOrderValueError(OrderValidationError):
    """Raised when an order field has an unsupported value."""


class ExchangeFilterError(OrderValidationError):
    """Raised when an order violates a Binance symbol filter."""


@dataclass(frozen=True)
class ValidatedOrderInput:
    """Locally validated order values represented without float rounding."""

    symbol: str
    side: str
    order_type: str
    quantity: Decimal
    price: Decimal | None


def validate_symbol(symbol: str) -> str:
    """Validate that a symbol is a non-empty uppercase string."""
    value = symbol.strip()
    if not value:
        raise InvalidSymbolError("Symbol must not be empty.")
    if value != value.upper():
        raise InvalidSymbolError(
            f"Symbol '{value}' must be uppercase (for example, BTCUSDT)."
        )
    if not value.isalnum():
        raise InvalidSymbolError("Symbol may contain only letters and numbers.")
    return value


def validate_side(side: str) -> str:
    """Validate the Binance order side."""
    value = side.strip()
    if value not in SUPPORTED_SIDES:
        raise InvalidOrderValueError("Side must be BUY or SELL.")
    return value


def validate_order_type(order_type: str) -> str:
    """Validate the supported order type."""
    value = order_type.strip()
    if value not in SUPPORTED_ORDER_TYPES:
        raise InvalidOrderValueError("Order type must be MARKET or LIMIT.")
    return value


def validate_decimal(value: str | Decimal, field_name: str) -> Decimal:
    """Parse a positive finite decimal value."""
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise InvalidOrderValueError(
            f"{field_name.capitalize()} must be a valid decimal number."
        ) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise InvalidOrderValueError(
            f"{field_name.capitalize()} must be greater than zero."
        )
    return parsed


def validate_order_input(
    *,
    symbol: str,
    side: str,
    order_type: str,
    quantity: str | Decimal,
    price: str | Decimal | None = None,
) -> ValidatedOrderInput:
    """Validate order fields before consulting Binance exchange rules."""
    validated_type = validate_order_type(order_type)
    validated_price: Decimal | None = None
    if validated_type == "LIMIT":
        if price is None or str(price).strip() == "":
            raise InvalidOrderValueError("Price is required for LIMIT orders.")
        validated_price = validate_decimal(price, "price")
    elif price is not None and str(price).strip() != "":
        raise InvalidOrderValueError("Price must not be provided for MARKET orders.")

    return ValidatedOrderInput(
        symbol=validate_symbol(symbol),
        side=validate_side(side),
        order_type=validated_type,
        quantity=validate_decimal(quantity, "quantity"),
        price=validated_price,
    )


def validate_exchange_rules(
    order: ValidatedOrderInput, symbol_info: Mapping[str, Any]
) -> None:
    """Reject values that violate the selected symbol's Binance filters."""
    if symbol_info.get("status") not in {None, "TRADING"}:
        raise InvalidSymbolError(
            f"Symbol {order.symbol} is not currently available for trading."
        )

    raw_filters = symbol_info.get("filters", [])
    if not isinstance(raw_filters, list):
        raise ExchangeFilterError("Binance returned invalid symbol filter data.")
    filters = {
        item.get("filterType"): item
        for item in raw_filters
        if isinstance(item, Mapping) and item.get("filterType")
    }

    quantity_filter_name = (
        "MARKET_LOT_SIZE"
        if order.order_type == "MARKET" and "MARKET_LOT_SIZE" in filters
        else "LOT_SIZE"
    )
    quantity_filter = filters.get(quantity_filter_name)
    if quantity_filter:
        _validate_range_and_increment(
            value=order.quantity,
            minimum=_filter_decimal(quantity_filter, "minQty"),
            maximum=_filter_decimal(quantity_filter, "maxQty"),
            increment=_filter_decimal(quantity_filter, "stepSize"),
            field_name="Quantity",
            increment_name="step size",
        )

    if order.order_type == "LIMIT" and order.price is not None:
        price_filter = filters.get("PRICE_FILTER")
        if price_filter:
            _validate_range_and_increment(
                value=order.price,
                minimum=_filter_decimal(price_filter, "minPrice"),
                maximum=_filter_decimal(price_filter, "maxPrice"),
                increment=_filter_decimal(price_filter, "tickSize"),
                field_name="Price",
                increment_name="tick size",
            )

        notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
        if notional_filter:
            minimum_notional = _filter_decimal(notional_filter, "notional")
            if minimum_notional is None:
                minimum_notional = _filter_decimal(notional_filter, "minNotional")
            if minimum_notional and order.quantity * order.price < minimum_notional:
                raise ExchangeFilterError(
                    "Order notional "
                    f"{format_decimal(order.quantity * order.price)} is below the "
                    f"minimum {format_decimal(minimum_notional)} for {order.symbol}."
                )


def format_decimal(value: Decimal) -> str:
    """Format a Decimal for Binance without exponent notation."""
    return format(value, "f")


def _filter_decimal(
    exchange_filter: Mapping[str, Any], field_name: str
) -> Decimal | None:
    raw_value = exchange_filter.get(field_name)
    if raw_value in {None, ""}:
        return None
    try:
        value = Decimal(str(raw_value))
    except InvalidOperation as exc:
        raise ExchangeFilterError(
            f"Binance returned an invalid {field_name} filter value."
        ) from exc
    return value if value > 0 else None


def _validate_range_and_increment(
    *,
    value: Decimal,
    minimum: Decimal | None,
    maximum: Decimal | None,
    increment: Decimal | None,
    field_name: str,
    increment_name: str,
) -> None:
    if minimum is not None and value < minimum:
        raise ExchangeFilterError(
            f"{field_name} {format_decimal(value)} is below the minimum "
            f"{format_decimal(minimum)}."
        )
    if maximum is not None and value > maximum:
        raise ExchangeFilterError(
            f"{field_name} {format_decimal(value)} exceeds the maximum "
            f"{format_decimal(maximum)}."
        )
    if increment is not None and value % increment != 0:
        raise ExchangeFilterError(
            f"{field_name} {format_decimal(value)} does not match the accepted "
            f"{increment_name} {format_decimal(increment)}."
        )

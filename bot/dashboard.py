"""Read-only structured data services for the Streamlit dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from bot.client import BinanceFuturesClient
from bot.validators import validate_symbol


@dataclass(frozen=True)
class AccountSummary:
    """Allow-listed account values displayed in dashboard summary cards."""

    available_usdt_balance: str
    open_position_count: int


@dataclass(frozen=True)
class OpenOrderRecord:
    """Allow-listed fields for one current open order."""

    order_id: str
    symbol: str
    side: str
    order_type: str
    original_quantity: str
    executed_quantity: str
    price: str
    status: str
    creation_time: str
    update_time: str


@dataclass(frozen=True)
class PositionRecord:
    """Allow-listed fields for one non-zero Futures position."""

    symbol: str
    position_amount: str
    entry_price: str
    mark_price: str
    unrealized_profit_loss: str
    leverage: str


@dataclass(frozen=True)
class RecentOrderRecord:
    """Allow-listed fields for one recent Futures order."""

    order_id: str
    symbol: str
    side: str
    order_type: str
    original_quantity: str
    executed_quantity: str
    price: str
    status: str
    creation_time: str


class FuturesDashboardService:
    """Load and normalize read-only Futures Testnet dashboard data."""

    def __init__(self, client: BinanceFuturesClient) -> None:
        self._client = client

    def get_account_summary(self) -> AccountSummary:
        snapshot = self._client.get_futures_account_snapshot()
        assets = snapshot.get("assets", [])
        positions = snapshot.get("positions", [])

        available_balance = "0"
        if isinstance(assets, list):
            for asset in assets:
                if isinstance(asset, Mapping) and asset.get("asset") == "USDT":
                    available_balance = _text(
                        asset.get("availableBalance"),
                        _text(asset.get("walletBalance"), "0"),
                    )
                    break

        open_position_count = 0
        if isinstance(positions, list):
            open_position_count = sum(
                1
                for position in positions
                if isinstance(position, Mapping)
                and _is_non_zero(position.get("positionAmt"))
            )
        return AccountSummary(available_balance, open_position_count)

    def get_positions(self) -> list[PositionRecord]:
        snapshot = self._client.get_futures_account_snapshot()
        positions = snapshot.get("positions", [])
        if not isinstance(positions, list):
            return []
        return [
            PositionRecord(
                symbol=_text(item.get("symbol")),
                position_amount=_text(item.get("positionAmt"), "0"),
                entry_price=_text(item.get("entryPrice"), "0"),
                mark_price=_text(item.get("markPrice"), "0"),
                unrealized_profit_loss=_text(
                    item.get("unrealizedProfit"),
                    _text(item.get("unRealizedProfit"), "0"),
                ),
                leverage=_text(item.get("leverage"), "N/A"),
            )
            for item in positions
            if isinstance(item, Mapping) and _is_non_zero(item.get("positionAmt"))
        ]

    def get_open_orders(self, symbol: str | None = None) -> list[OpenOrderRecord]:
        validated_symbol = validate_symbol(symbol) if symbol is not None else None
        return [
            OpenOrderRecord(
                order_id=_text(item.get("orderId")),
                symbol=_text(item.get("symbol")),
                side=_text(item.get("side")),
                order_type=_text(item.get("type")),
                original_quantity=_text(item.get("origQty"), "0"),
                executed_quantity=_text(item.get("executedQty"), "0"),
                price=_text(item.get("price"), "0"),
                status=_text(item.get("status")),
                creation_time=_utc_time(item.get("time")),
                update_time=_utc_time(item.get("updateTime", item.get("time"))),
            )
            for item in self._client.get_futures_open_orders(validated_symbol)
        ]

    def get_recent_orders(
        self, symbol: str, *, limit: int = 50
    ) -> list[RecentOrderRecord]:
        validated_symbol = validate_symbol(symbol)
        return [
            RecentOrderRecord(
                order_id=_text(item.get("orderId")),
                symbol=_text(item.get("symbol"), validated_symbol),
                side=_text(item.get("side")),
                order_type=_text(item.get("type")),
                original_quantity=_text(item.get("origQty"), "0"),
                executed_quantity=_text(item.get("executedQty"), "0"),
                price=_text(item.get("price"), "0"),
                status=_text(item.get("status")),
                creation_time=_utc_time(item.get("time")),
            )
            for item in self._client.get_futures_recent_orders(
                validated_symbol, limit=limit
            )
        ]


def _text(value: Any, fallback: str = "") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _is_non_zero(value: Any) -> bool:
    try:
        return Decimal(str(value or "0")) != 0
    except InvalidOperation:
        return False


def _utc_time(value: Any) -> str:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return "N/A"
    return datetime.fromtimestamp(
        milliseconds / 1000, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

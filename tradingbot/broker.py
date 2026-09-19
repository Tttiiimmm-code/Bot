"""Dünner Wrapper um die Alpaca-API (Konto, Marktdaten, Orders)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import Adjustment
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from tradingbot.config import Config

logger = logging.getLogger(__name__)

# Freie Alpaca-Datenpläne haben eine ~15-Minuten-Verzögerung; ein `end` ohne
# Sicherheitsabstand zu "jetzt" liefert sonst 0 Zeilen zurück.
_DATA_DELAY = timedelta(minutes=20)
# Puffer an Kalendertagen pro angefragtem Handelstag (Wochenenden/Feiertage).
_CALENDAR_DAYS_PER_TRADING_DAY = 1.6


@dataclass
class Position:
    qty: float
    avg_entry_price: float


class Broker:
    def __init__(self, config: Config):
        self.config = config
        self.trading_client = TradingClient(
            config.api_key, config.secret_key, paper=config.paper
        )
        self.data_client = StockHistoricalDataClient(config.api_key, config.secret_key)

    def get_recent_closes(self, limit: int) -> pd.Series:
        """Holt die letzten `limit` Tages-Schlusskurse für das konfigurierte Symbol."""
        end = datetime.now(timezone.utc) - _DATA_DELAY
        start = end - timedelta(days=int(limit * _CALENDAR_DAYS_PER_TRADING_DAY) + 5)

        request = StockBarsRequest(
            symbol_or_symbols=self.config.symbol,
            timeframe=TimeFrame.Day,
            start=start,
            end=end,
            # Ohne Split-/Dividenden-Adjustierung erzeugt z.B. ein Aktiensplit
            # einen künstlichen Kurssprung, der die Strategie verfälscht.
            adjustment=Adjustment.ALL,
        )
        bars = self.data_client.get_stock_bars(request).df
        if bars.empty:
            return pd.Series(dtype=float)

        symbol_bars = bars.xs(self.config.symbol, level="symbol")
        return symbol_bars["close"].tail(limit)

    def get_position(self) -> Position | None:
        try:
            position = self.trading_client.get_open_position(self.config.symbol)
            return Position(qty=float(position.qty), avg_entry_price=float(position.avg_entry_price))
        except Exception:
            return None

    def get_position_qty(self) -> float:
        position = self.get_position()
        return position.qty if position else 0.0

    def submit_market_order(self, side: OrderSide, qty: float):
        order_request = MarketOrderRequest(
            symbol=self.config.symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = self.trading_client.submit_order(order_request)
        logger.info("Order platziert: %s %s %s (id=%s)", side, qty, self.config.symbol, order.id)
        return order

    def buy(self, qty: float):
        return self.submit_market_order(OrderSide.BUY, qty)

    def sell(self, qty: float):
        return self.submit_market_order(OrderSide.SELL, qty)

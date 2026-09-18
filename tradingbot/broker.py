"""Dünner Wrapper um die Alpaca-API (Konto, Marktdaten, Orders)."""

from __future__ import annotations

import logging

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from tradingbot.config import Config

logger = logging.getLogger(__name__)


class Broker:
    def __init__(self, config: Config):
        self.config = config
        self.trading_client = TradingClient(
            config.api_key, config.secret_key, paper=config.paper
        )
        self.data_client = StockHistoricalDataClient(config.api_key, config.secret_key)

    def get_recent_closes(self, limit: int) -> pd.Series:
        """Holt die letzten `limit` Tages-Schlusskurse für das konfigurierte Symbol."""
        request = StockBarsRequest(
            symbol_or_symbols=self.config.symbol,
            timeframe=TimeFrame.Day,
            limit=limit,
        )
        bars = self.data_client.get_stock_bars(request).df
        if bars.empty:
            return pd.Series(dtype=float)

        symbol_bars = bars.xs(self.config.symbol, level="symbol")
        return symbol_bars["close"]

    def get_position_qty(self) -> float:
        try:
            position = self.trading_client.get_open_position(self.config.symbol)
            return float(position.qty)
        except Exception:
            return 0.0

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

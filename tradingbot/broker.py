"""Dünner Wrapper um die Alpaca-API (Konto, Marktdaten, Orders)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

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
        """Gibt die offene Position zurück, oder None, wenn keine existiert.

        Nur ein 404 ("keine Position offen") wird als None interpretiert.
        Jeder andere Fehler (Netzwerk, Auth, Rate-Limit, ...) wird
        weitergereicht -- sonst könnte z.B. ein API-Ausfall fälschlich als
        "keine Position" interpretiert werden und einen aktiven Stop-Loss
        unbemerkt außer Kraft setzen.
        """
        try:
            position = self.trading_client.get_open_position(self.config.symbol)
        except APIError as e:
            if e.status_code == 404:
                return None
            raise
        qty = float(position.qty)
        avg_entry_price = float(position.avg_entry_price)
        # Lieber laut scheitern (Zyklus wird oben geloggt übersprungen) als
        # mit kaputten Positionsdaten weiterzumachen: NaN würde den
        # Stop-Loss-Vergleich in bot.py unbemerkt immer False werden lassen,
        # und ein avg_entry_price <= 0 würde die Stop-Schwelle auf <= 0
        # setzen (nie erreichbar durch einen echten Kurs) -- in beiden
        # Fällen wäre der Stop-Loss lautlos wirkungslos.
        if not (math.isfinite(qty) and math.isfinite(avg_entry_price) and avg_entry_price > 0):
            raise ValueError(
                f"Ungültige Positionsdaten von Alpaca erhalten für {self.config.symbol}: "
                f"qty={qty}, avg_entry_price={avg_entry_price}"
            )
        return Position(qty=qty, avg_entry_price=avg_entry_price)

    def get_position_qty(self) -> float:
        position = self.get_position()
        return position.qty if position else 0.0

    def get_account_equity(self) -> float:
        """Gesamtwert des Portfolios (Cash + offene Positionen) -- Basis für
        die Risikoberechnung bei risikobasierten Positionsgrößen
        (RISK_PER_TRADE_PCT): "Risiko pro Trade" bezieht sich standardmäßig
        auf das Gesamtkapital, nicht nur auf freies Cash."""
        account = self.trading_client.get_account()
        equity = float(account.equity)
        if not (math.isfinite(equity) and equity > 0):
            raise ValueError(f"Ungültiger Equity-Wert von Alpaca erhalten: {equity}")
        return equity

    def get_available_cash(self) -> float:
        """Tatsächlich freies, nicht bereits investiertes Kapital --
        Obergrenze für risikobasierte Positionsgrößen. Auf einem Konto mit
        anderen offenen Positionen kann das deutlich unter dem
        Gesamt-Equity liegen; die berechnete Ordergröße darf das nie
        überschreiten (kein Hebel). Ein negativer Wert (Margin-Konto im
        Soll) wird auf 0 gedeckelt statt eine negative Notional-Größe zu
        erzeugen."""
        account = self.trading_client.get_account()
        cash = float(account.cash)
        if not math.isfinite(cash):
            raise ValueError(f"Ungültiger Cash-Wert von Alpaca erhalten: {cash}")
        return max(cash, 0.0)

    def has_open_buy_order(self) -> bool:
        """Prüft, ob für das Symbol bereits eine unausgeführte Kauf-Order
        offen ist -- verhindert, dass der Bot eine zweite Kauf-Order
        auslöst, bevor die erste gefüllt wurde."""
        return self._has_open_order(OrderSide.BUY)

    def has_open_sell_order(self) -> bool:
        """Wie `has_open_buy_order`, aber für Verkaufs-Orders (inkl.
        Stop-Loss-Ausstiege)."""
        return self._has_open_order(OrderSide.SELL)

    def _has_open_order(self, side: OrderSide) -> bool:
        """Nach Richtung gefiltert, damit eine offene Kauf-Order einen
        dringenden Stop-Loss-Verkauf nicht blockiert (und umgekehrt) --
        sonst könnte eine einzelne unausgeführte Order in eine Richtung den
        Stop-Loss für den Rest des Handelstags außer Kraft setzen."""
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[self.config.symbol], side=side)
        open_orders = self.trading_client.get_orders(filter=request)
        return len(open_orders) > 0

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

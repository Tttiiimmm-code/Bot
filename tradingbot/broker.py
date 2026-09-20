"""Dünner Wrapper um die Alpaca-API (Konto, Marktdaten, Orders)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

import pandas as pd
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment, DataFeed
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


def _filter_regular_session(bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Extrahiert aus einer Multi-Symbol-Minuten-Bars-Antwort (wie von
    StockHistoricalDataClient.get_stock_bars(...).df zurückgegeben) die
    OHLCV-Bars EINES Symbols, gefiltert auf reguläre US-Handelszeiten
    (9:30-16:00 ET) -- Vor-/Nachbörslich fließt sonst mit untypisch
    geringem Volumen in Muster-/Volumenvergleiche ein. Geteilte Grundlage
    für Broker.get_minute_bars UND den Live-Bot
    (tradingbot/momentum_live.py), damit beide garantiert dieselbe
    Definition von "regulärer Handelstag" verwenden -- eine künftige
    Änderung (z.B. Frühschluss-Behandlung) muss so nur an einer Stelle
    gemacht werden."""
    if bars.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    symbol_bars = bars.xs(symbol, level="symbol")
    ny_index = symbol_bars.index.tz_convert("America/New_York")
    session_mask = (ny_index.time >= time(9, 30)) & (ny_index.time < time(16, 0))
    regular_session = symbol_bars.loc[session_mask].copy()
    regular_session.index = ny_index[session_mask]
    return regular_session[["open", "high", "low", "close", "volume"]]


@dataclass
class Position:
    qty: float
    avg_entry_price: float


@dataclass
class AccountInfo:
    equity: float
    available_cash: float


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

    def get_minute_bars(self, calendar_days: int, feed: DataFeed | None = None) -> pd.DataFrame:
        """Holt Minuten-OHLCV-Bars der letzten `calendar_days` Kalendertage
        für das konfigurierte Symbol, gefiltert auf reguläre US-
        Handelszeiten (9:30-16:00 ET) -- Vor-/Nachbörslich fließt sonst mit
        untypisch geringem Volumen in Muster-/Volumenvergleiche ein.

        Nur für historische Analyse gedacht (z.B. Backtests intraday-
        basierter Strategien). Für Live-Entscheidungen ungeeignet: Alpacas
        kostenloser Datenplan liefert Minutendaten mit dem üblichen
        Verzögerungs-Sicherheitsabstand (_DATA_DELAY), was für eine
        Strategie, die auf die exakt erste Kerze nach einem Pullback
        abzielt, keine belastbare Basis ist.

        `feed`: None (Standard) fragt Alpacas Standard-/SIP-Feed ab -- den
        vollen Marktüberblick, aber nur für Daten älter als _DATA_DELAY.
        `feed=DataFeed.IEX` fragt stattdessen den (ohne Zusatzabo)
        einzigen ECHTZEIT-fähigen Feed ab, braucht dafür KEINEN
        Verzögerungs-Sicherheitsabstand. Relevant, um einen Backtest exakt
        nachzustellen, was tradingbot/momentum_live.py (das live IMMER
        IEX nutzt) tatsächlich sehen würde -- IEX deckt nur einen
        Bruchteil (~2-3%) des gesamten Marktvolumens ab, ein auf SIP
        beruhender Backtest testet also ein ANDERES, vollständigeres Bild
        des Marktes, als der Live-Bot je zu sehen bekommt.
        """
        delay = timedelta(0) if feed == DataFeed.IEX else _DATA_DELAY
        end = datetime.now(timezone.utc) - delay
        start = end - timedelta(days=calendar_days)

        request = StockBarsRequest(
            symbol_or_symbols=self.config.symbol,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            adjustment=Adjustment.ALL,
            feed=feed,
        )
        bars = self.data_client.get_stock_bars(request).df
        return _filter_regular_session(bars, self.config.symbol)

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

    def get_account_info(self) -> AccountInfo:
        """Gesamt-Equity und tatsächlich freies Cash -- Basis für
        risikobasierte Positionsgrößen (RISK_PER_TRADE_PCT). Ein einziger
        Alpaca-Aufruf statt zwei separater, da beide Werte in derselben
        Account-Antwort enthalten sind.

        - `equity`: Cash + offene Positionen. "Risiko pro Trade" bezieht
          sich standardmäßig auf dieses Gesamtkapital, nicht nur auf freies
          Cash.
        - `available_cash`: tatsächlich freies, nicht bereits investiertes
          Kapital -- Obergrenze für die berechnete Ordergröße (kein Hebel).
          Auf einem Konto mit anderen offenen Positionen kann das deutlich
          unter dem Gesamt-Equity liegen. Ein negativer Wert (Margin-Konto
          im Soll) wird auf 0 gedeckelt statt eine negative Notional-Größe
          zu erzeugen.
        """
        account = self.trading_client.get_account()
        equity = float(account.equity)
        cash = float(account.cash)
        if not (math.isfinite(equity) and equity > 0):
            raise ValueError(f"Ungültiger Equity-Wert von Alpaca erhalten: {equity}")
        if not math.isfinite(cash):
            raise ValueError(f"Ungültiger Cash-Wert von Alpaca erhalten: {cash}")
        return AccountInfo(equity=equity, available_cash=max(cash, 0.0))

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
